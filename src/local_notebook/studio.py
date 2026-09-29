import json
import re
import time

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
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=280)
    citations: list[int] = Field(default_factory=list)
    children: list["MindNode"] = Field(default_factory=list, max_length=10)

    @model_validator(mode='before')
    @classmethod
    def normalize_node(cls, value):
        # Some models abbreviate leaves as "Topic [4]". Preserve those explicit
        # references, then run the same structural and evidence checks as usual.
        if isinstance(value, str):
            value = {'name': value}
        if isinstance(value, dict) and isinstance(value.get('name'), str):
            value = dict(value)
            label = value['name']
            refs = [int(n) for group in re.findall(r'\[(\d+(?:\s*,\s*\d+)*)\]', label)
                    for n in group.split(',')]
            if refs:
                value['name'] = re.sub(r'\[\d+(?:\s*,\s*\d+)*\]', '', label).strip()
                existing = value.get('citations', [])
                if isinstance(existing, list):
                    value['citations'] = list(dict.fromkeys([*existing, *refs]))
        return value


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


async def generate(notebook_id: str, kind: str, evidence: Evidence, instruction: str, *, on_progress=None, persist=True):
    if not evidence.passages:
        raise ValueError("Select at least one indexed source first.")
    if not providers.configured():
        raise ValueError("Connect Gemini or a local model in Settings to create study materials.")
    evidence = fit_evidence(evidence, max_chars=18000 if kind == "quiz" else 30000)
    if not evidence.passages:
        raise ValueError("Source passages exceed the context budget. Reindex with smaller passages.")
    context = evidence_text(evidence)
    fast = db.settings()["studio_fast"]
    base = f"User preferences: {instruction}\nCoverage limitation: {evidence.warning}\n\nSOURCE EVIDENCE:\n{context}"
    started, first, last_update, received = time.perf_counter(), None, 0, ""

    def chunk(part):
        nonlocal first, last_update, received
        received += part
        now = time.perf_counter()
        if first is None:
            first = now - started
        if on_progress and (not last_update or now - last_update >= .1):
            # Preview only complete string fields; never expose raw, unfinished JSON.
            field = "question" if kind == "quiz" else "name"
            labels = [json.loads(match[1]) for match in re.finditer(
                rf'"{field}"\s*:\s*("(?:[^"\\]|\\.)*")', received)] if kind != "report" else []
            on_progress({"stage": "streaming", "characters": len(received), "items": labels,
                         "preview": received[-1800:] if kind == "report" else "",
                         "first_token_s": first, "elapsed_s": now - started})
            last_update = now

    if kind == "quiz":
        request = ('Create a source-grounded quiz. Return ONLY JSON with this structure: '
                   '{"title":"Quiz title","questions":[{"question":"Question text","options":["Option A","Option B","Option C","Option D"],'
                   '"answer":0,"explanation":"A brief source-grounded explanation.","citations":[1]}]}. '
                   'The answer is a zero-based option index. Make 5 questions unless instructed otherwise (maximum 20). '
                   'Every question needs evidence citations. Keep explanations to one or two sentences.')
        result = Quiz.model_validate(parse_json(await providers.complete(SYSTEM, request + "\n" + base, json_mode=True, fast=fast, on_chunk=chunk)))
        for question in result.questions:
            if any(number < 1 or number > len(evidence.passages) for number in question.citations):
                raise ValueError("Quiz contains an invalid source reference. Please regenerate.")
        result.coverage = evidence.warning
        title, content = result.title, result.model_dump_json()
    elif kind == "mindmap":
        request = ('Create an in-depth, source-grounded mind map tailored to the requested topic. '
                   'Organize 4–7 distinct main branches with 3–5 levels and 40–65 total nodes when the evidence supports it. '
                   'For narrow evidence use a smaller map; never pad or invent detail. Maximum 80 nodes and 10 children per node. '
                   'Cover definitions, mechanisms, subtypes, relationships, practical examples, and limitations where supported. '
                   'Use distinct short labels (2–6 words, at most 100 characters), not paragraphs. '
                   'Put a useful one-sentence explanation in description (at most 280 characters). Cite every leaf. '
                   'Return ONLY JSON: {"title":"Map title","root":{"name":"Central topic","description":"Explanation",'
                   '"citations":[],"children":[{"name":"Branch","description":"Explanation","citations":[1],"children":[]}]}}. '
                   'Children recursively use the same node structure. Every child MUST be an object, never a string. '
                   'Put reference numbers in citations arrays, not in names.')
        result = MindMap.model_validate(parse_json(await providers.complete(SYSTEM, request + "\n" + base, json_mode=True, fast=fast, on_chunk=chunk, max_output_tokens=8192)))
        validate_map(result.root, len(evidence.passages))
        def count_nodes(node):
            return 1 + sum(count_nodes(child) for child in node.children)
        if count_nodes(result.root) > 80:
            raise ValueError("Mind map exceeded 80 topics. Focus on a narrower topic and try again.")
        result.coverage = evidence.warning
        title, content = result.title, result.model_dump_json()
    else:
        content = await providers.complete(SYSTEM, "Write a well-structured Markdown study report with citations.\n" + base, fast=fast, on_chunk=chunk)
        content = validate_citations(content, evidence)
        title = next((line.lstrip("# ") for line in content.splitlines() if line.strip()), "Study report")[:100]
    if evidence.warning and kind == "report":
        content = f"> {evidence.warning}\n\n" + content
    citations = [{**passage, "number": number} for number, passage in enumerate(evidence.passages, 1)]
    if not persist:
        return {**json.loads(content), 'citations': citations} if kind in {'mindmap', 'quiz'} else {'title': title, 'content': content, 'citations': citations}
    identifier = db.save_artifact(notebook_id, kind, title, content, citations)
    if on_progress:
        on_progress({"stage": "complete", "first_token_s": first, "elapsed_s": time.perf_counter() - started,
                     "prompt_characters": len(request + base) if kind in {"quiz", "mindmap"} else len(base),
                     "characters": len(received)})
    return identifier
