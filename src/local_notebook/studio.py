import json
import re

from pydantic import BaseModel, Field, model_validator

from . import providers, storage as db
from .chat import SYSTEM, evidence_text, fit_evidence, validate_citations
from .retrieval.search import Evidence


class Question(BaseModel):
    question: str
    options: list[str] = Field(min_length=2, max_length=6)
    answer: int = Field(ge=0)
    explanation: str
    citations: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_answer(self):
        if self.answer >= len(self.options):
            raise ValueError("Quiz answer index is out of range")
        return self


class Quiz(BaseModel):
    title: str
    questions: list[Question] = Field(min_length=1, max_length=20)
    coverage: str = ""


class MindNode(BaseModel):
    name: str
    citations: list[int] = Field(default_factory=list)
    children: list["MindNode"] = Field(default_factory=list, max_length=10)


class MindMap(BaseModel):
    title: str
    root: MindNode
    coverage: str = ""


def parse_json(text: str) -> dict:
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(clean)


def validate_map(node: MindNode, maximum: int, depth=0) -> None:
    if depth > 5:
        raise ValueError("Mind map exceeded the supported depth")
    if any(number < 1 or number > maximum for number in node.citations):
        raise ValueError("Mind map contains an invalid source reference")
    if not node.children and not node.citations:
        raise ValueError("Mind map leaf needs supporting evidence")
    for child in node.children:
        validate_map(child, maximum, depth + 1)


async def generate(notebook_id: str, kind: str, evidence: Evidence, instruction: str) -> str:
    if not evidence.passages:
        raise ValueError("Select at least one indexed source first.")
    if not providers.configured():
        raise ValueError("Connect Gemini or a local model in Settings to create study materials.")
    evidence = fit_evidence(evidence)
    if not evidence.passages:
        raise ValueError("Source passages exceed the context budget. Reindex with smaller passages.")
    context = evidence_text(evidence)
    fast = db.settings()["studio_fast"]
    base = f"User preferences: {instruction}\nCoverage limitation: {evidence.warning}\n\nSOURCE EVIDENCE:\n{context}"
    if kind == "quiz":
        request = "Create a source-grounded quiz. Return JSON matching this schema: " + json.dumps(Quiz.model_json_schema())
        result = Quiz.model_validate(parse_json(await providers.complete(SYSTEM, request + "\n" + base, json_mode=True, fast=fast)))
        for question in result.questions:
            if any(number < 1 or number > len(evidence.passages) for number in question.citations):
                raise ValueError("Quiz contains an invalid source reference. Please regenerate.")
        result.coverage = evidence.warning
        title, content = result.title, result.model_dump_json()
    elif kind == "mindmap":
        request = "Create a concise mind map with at most 4 levels and 35 nodes. Cite every leaf. Return JSON: "
        request += json.dumps(MindMap.model_json_schema())
        result = MindMap.model_validate(parse_json(await providers.complete(SYSTEM, request + "\n" + base, json_mode=True, fast=fast)))
        validate_map(result.root, len(evidence.passages))
        result.coverage = evidence.warning
        title, content = result.title, result.model_dump_json()
    else:
        content = await providers.complete(SYSTEM, "Write a well-structured Markdown study report with citations.\n" + base, fast=fast)
        content = validate_citations(content, evidence)
        title = next((line.lstrip("# ") for line in content.splitlines() if line.strip()), "Study report")[:100]
    if evidence.warning and kind == "report":
        content = f"> {evidence.warning}\n\n" + content
    citations = [{**passage, "number": number} for number, passage in enumerate(evidence.passages, 1)]
    return db.save_artifact(notebook_id, kind, title, content, citations)
