import asyncio
import re

from llama_index.core.workflow import StartEvent, StopEvent, Workflow, step

from .search import coverage, retrieve


def is_overview(question: str) -> bool:
    """Route only the current request, never text inherited from earlier turns."""
    if generic_study_request(question):
        return True
    return bool(re.search(
        r"^(?:what|wat) (?:is|are) (?:this|that|the|these|my) (?:pdf|file|document|source|book|notebook)s? (?:about|on)[\s?.!]*$"
        r"|^(?:what are |give me |show me )?(?:the )?(?:key|main|central) (?:ideas|themes)(?: in| of| across)? (?:these|the|all|my) (?:sources|documents|notes)"
        r"|^(?:please )?summari[sz]e (?:these|all|my|the selected) (?:sources|documents|notes)"
        r"|^(?:give me (?:a |an )?)?source overview[?.!]*$",
        question.strip(), re.IGNORECASE))


def generic_study_request(question: str) -> bool:
    """Recognize source-wide study requests without mistaking a named topic for one."""
    from .search import query_terms
    if not re.search(r'guide|plan|curriculum|summar|overview|mind\s*map|learn|study', question, re.I):
        return False
    filler = set('can could would you u me us create make build prepare write provide proper good detailed '
                 'comprehensive complete learning study guide plan curriculum summary summarize summarise overview '
                 'mind map mindmap graph chart expand into week weeks day days month months here this these '
                 'the selected uploaded attached given available material materials notebook book books source '
                 'sources document documents text notes everything all it please based using from on for in '
                 'and also organize organise step steps by'.split())
    return not [t for t in query_terms(question) if t not in filler and not t.isdigit()]


def contextual_query(question: str, history: list[dict]) -> str:
    """Carry a topic forward for referential turns; explicit new topics stand alone."""
    from .search import query_terms

    referential = re.search(r"\b(it|its|they|them|their|that|those|this|these)\b", question, re.I)
    if query_terms(question) and not referential:
        return question
    for item in reversed(history):
        if item['role'] == 'user' and not is_overview(item['text']) and query_terms(item['text']):
            return item['text'][-800:] + "\nFollow-up: " + question
    # A user can refer to an idea introduced only in the preceding answer.
    previous = next((item['text'] for item in reversed(history) if item['role'] == 'assistant'), '')
    return question + ("\nPrevious answer: " + previous[:800] if previous else '')


class ResearchWorkflow(Workflow):
    """Keep evidence retrieval outside the UI loop using a typed LlamaIndex workflow."""

    @step
    async def retrieve_evidence(self, event: StartEvent) -> StopEvent:
        from ..chat import fit_evidence

        evidence = await source_evidence(event.notebook_id, event.query, event.get('history', []))
        evidence = fit_evidence(evidence)
        return StopEvent(result=evidence)


async def source_evidence(notebook_id, question, history=()):
    """Direct async entry point; no workflow event dispatch or planner call."""
    from ..chat import fit_evidence
    if is_overview(question):
        result = await asyncio.to_thread(coverage, notebook_id, 80)
    else:
        result = await asyncio.to_thread(retrieve, notebook_id, contextual_query(question, list(history)))
    return fit_evidence(result)
