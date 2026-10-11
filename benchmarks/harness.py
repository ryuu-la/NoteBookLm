"""Local harness latency, isolated from user data and external model/network time."""
import asyncio
import json
import os
from pathlib import Path
import statistics
import tempfile
import time


def main():
    with tempfile.TemporaryDirectory(prefix='folio-harness-') as directory:
        os.environ['NOTEBOOK_DATA_DIR'] = directory
        from local_notebook import providers, research, storage as db
        from local_notebook.ingestion import jobs
        from local_notebook.retrieval.workflow import source_evidence
        db.initialize()
        db.save_settings({'semantic': False})
        notebook = db.create_notebook('FastAPI')
        sid = jobs.add_file(notebook, 'Mastering FastAPI.txt', b'Fixture')
        topics = ['Routing', 'Dependency injection', 'Validation', 'Async requests', 'Testing', 'Deployment']
        jobs.flush([{'id': db.uid(), 'source_id': sid, 'notebook_id': notebook, 'ordinal': i,
                     'locator': f'Section {i + 1}', 'text': f'FastAPI {topics[i % len(topics)]}: source-backed instruction {i}. ' * 5}
                    for i in range(142)], False)
        db.execute("UPDATE sources SET status='ready' WHERE id=?", (sid,))
        async def measure():
            timings = []
            question = 'can u create a proper learning guide here'
            assert not research.use_web(question, 'web', has_sources=True)
            for _ in range(7):
                started = time.perf_counter()
                result = await source_evidence(notebook, question)
                timings.append((time.perf_counter() - started) * 1000)
                assert result.passages
            async def forbidden(*args, **kwargs):
                raise AssertionError('Quick search must not call a model')
            async def discover(*args):
                await asyncio.sleep(.03)
                return [{'url': f'https://site{i}.example/page'} for i in range(4)]
            async def read(url):
                await asyncio.sleep(.03)
                return {'url': url, 'title': 'Reference', 'text': 'FastAPI documentation. ' * 20}
            providers.complete = forbidden
            research.discovery.discover = discover
            research.read_page = read
            start = time.perf_counter()
            web = await research.research(notebook, 'Search FastAPI', [], depth='quick')
            return {'source_guide': {'median_ms': round(statistics.median(timings), 2),
                                     'max_ms': round(max(timings), 2), 'runs': len(timings),
                                     'indexed_passages': 142, 'returned_passages': len(result.passages),
                                     'planner_calls': 0, 'web_calls': 0},
                    'quick_web_fixture': {'elapsed_ms': round((time.perf_counter() - start) * 1000, 2),
                                          'fixture_search_delay_ms': 30, 'fixture_page_delay_ms': 30,
                                          'pages_read': web.diagnostics['pages_read'], 'planner_calls': 0},
                    'scope': 'Local source retrieval and simulated web I/O only; excludes real provider and internet latency.'}
        report = asyncio.run(measure())
        target = Path(__file__).resolve().parents[1] / 'test-results' / 'harness-latency.json'
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
