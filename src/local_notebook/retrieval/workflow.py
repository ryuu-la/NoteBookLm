import asyncio
import re

from llama_index.core.workflow import StartEvent, StopEvent, Workflow, step

from .search import coverage, retrieve


class ResearchWorkflow(Workflow):
    """Keep evidence retrieval outside the UI loop using a typed LlamaIndex workflow."""

    @step
    async def retrieve_evidence(self, event: StartEvent) -> StopEvent:
        overview = re.search(r"(?:key|main|central) (?:ideas|themes)|summari[sz]e (?:these|the|all)|source overview",
                             event.query, re.IGNORECASE)
        evidence = await asyncio.to_thread(coverage, event.notebook_id, 12) if overview else await asyncio.to_thread(
            retrieve, event.notebook_id, event.query)
        return StopEvent(result=evidence)
