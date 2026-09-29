import asyncio
import re

from llama_index.core.workflow import StartEvent, StopEvent, Workflow, step

from .search import coverage, retrieve


def is_overview(question: str) -> bool:
    """Route only the current request, never text inherited from earlier turns."""
    return bool(re.search(
        r"^(?:what are |give me |show me )?(?:the )?(?:key|main|central) (?:ideas|themes)(?: in| of| across)? (?:these|the|all|my) (?:sources|documents|notes)"
        r"|^(?:please )?summari[sz]e (?:these|all|my|the selected) (?:sources|documents|notes)"
        r"|^(?:give me (?:a |an )?)?source overview[?.!]*$",
        question.strip(), re.IGNORECASE))


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

        query = contextual_query(event.query, event.get('history', []))
        evidence = await asyncio.to_thread(coverage, event.notebook_id, 80) if is_overview(event.query) else await asyncio.to_thread(
            retrieve, event.notebook_id, query)
        evidence = fit_evidence(evidence)
        return StopEvent(result=evidence)
