"""Run chat retrieval and optional generation on labeled conversation regressions.

The fixture inserts prepared chunks; it does not evaluate document ingestion.

python benchmarks/rag.py             # local hybrid retrieval, no model API calls
python benchmarks/rag.py --keyword   # lightweight deterministic CI gate
python benchmarks/rag.py --answers --model MODEL  # generation + claim judge (API usage)
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ['NOTEBOOK_DATA_DIR'] = str(ROOT / 'test-results' / f'rag-{time.time_ns()}')
os.environ['NOTEBOOK_MODEL_DIR'] = str(ROOT / '.data' / 'models')

from rag_cases import CASES, TOPICS, seed  # noqa: E402
from local_notebook import chat, providers, storage as db  # noqa: E402
from local_notebook.evaluation import AnswerJudgment, JUDGE_SYSTEM, audit_judgment, require_retrieval_mode, retrieval_metrics  # noqa: E402
from local_notebook.ingestion import jobs  # noqa: E402
from local_notebook.retrieval.search import coverage, retrieve  # noqa: E402
from local_notebook.retrieval.workflow import ResearchWorkflow  # noqa: E402


async def run(args):
    if args.answers and (not args.judge_model or args.judge_model == args.model) and not args.allow_self_judge:
        raise SystemExit('Use --judge-model with a different model, or explicitly opt into --allow-self-judge. Self-judged results are not independent validation.')
    if args.provider == 'Gemini':
        from local_notebook.config import GEMINI_MODELS
        if args.model not in GEMINI_MODELS or (args.judge_model and args.judge_model not in GEMINI_MODELS):
            raise SystemExit('Gemini evaluations support only: ' + ', '.join(GEMINI_MODELS))
        # This is an isolated evaluation process; never change the user's .env file.
        os.environ['GEMINI_MAIN_MODEL'] = args.model
    db.initialize()
    db.save_settings({'semantic': not args.keyword, 'rerank': not args.keyword,
                      'provider': args.provider, 'model': args.model, 'fast_model': args.model,
                      'endpoint': args.endpoint})
    if args.answers and not providers.configured():
        raise SystemExit('Answer evaluation needs a configured model key. Set GEMINI_API_KEY or NOTEBOOK_API_KEY; never pass keys as arguments.')
    started = time.perf_counter()
    last_request = 0.0

    async def complete(system, prompt, **kwargs):
        nonlocal last_request
        for attempt in range(3):
            await asyncio.sleep(max(0, args.request_interval - (time.perf_counter() - last_request)))
            last_request = time.perf_counter()
            try:
                return await providers.complete(system, prompt, **kwargs)
            except Exception as exc:
                code = getattr(exc, 'code', None)
                if code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise
                delay = 60 if code == 429 else 5
                print(f'Provider returned {code}; preserving progress and retrying in {delay}s.', flush=True)
                await asyncio.sleep(delay)

    book, count = seed(db, jobs, semantic=not args.keyword)
    # Warm local models before measuring query latencies.
    await asyncio.to_thread(retrieve, book, 'FastAPI')
    cases = []
    for case in CASES:
        evidence = await ResearchWorkflow(timeout=180).run(notebook_id=book, query=case['question'], history=case['history'])
        require_retrieval_mode(evidence, semantic=not args.keyword, rerank=not args.keyword)
        found = [p['locator'] for p in evidence.passages]
        sample = {**case, 'retrieved': found, 'diagnostics': evidence.diagnostics,
                  'latency_ms': evidence.elapsed_ms, **retrieval_metrics(found, case['relevant']),
                  'scope_pass': all(p['notebook_id'] == book and 'PRIVATE CANARY' not in p['text'] for p in evidence.passages),
                  'route_pass': evidence.diagnostics.get('route') == 'targeted',
                  'top_score': evidence.passages[0].get('relevance_score') if evidence.passages else None}
        if args.answers:
            generation_started = time.perf_counter()
            answer = await complete(chat.SYSTEM, chat.prompt(book, case['question'], evidence, history=case['history']))
            sample['answer_origin'] = 'model'
            sample['evidence'] = evidence.passages
            sample['generation_seconds'] = round(time.perf_counter() - generation_started, 2)
            judge_prompt = (f"QUESTION: {case['question']}\nREFERENCE: {case['reference']}\n"
                            f"ANSWER: {answer}\nEVIDENCE:\n{chat.evidence_text(evidence)}")
            if args.provider == 'Gemini':
                os.environ['GEMINI_MAIN_MODEL'] = args.judge_model or args.model
            db.save_settings({'model': args.judge_model or args.model, 'thinking_level': 'low'})
            try:
                judgment = AnswerJudgment.model_validate_json(await complete(JUDGE_SYSTEM, judge_prompt, json_mode=True, max_output_tokens=8192))
            finally:
                if args.provider == 'Gemini':
                    os.environ['GEMINI_MAIN_MODEL'] = args.model
                db.save_settings({'model': args.model, 'thinking_level': 'minimal'})
            sample['answer'] = answer
            sample['answer_evaluation'] = audit_judgment(judgment, answer, evidence)
        cases.append(sample)
        checkpoint = (ROOT / args.output).with_suffix('.partial.json')
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(json.dumps({'model': args.model, 'judge_model': args.judge_model or args.model,
                                          'complete': False, 'cases': cases}, indent=2), encoding='utf-8')
        print(json.dumps({k: sample[k] for k in ['id', 'recall_at_8', 'abstained', 'route_pass', 'latency_ms']}), flush=True)
    overview = chat.fit_evidence(coverage(book))
    overview_sources = len({p['source_id'] for p in overview.passages})
    summary = {key: round(statistics.mean(c[key] for c in cases if c[key] is not None), 4)
               for key in ['recall_at_8', 'mrr_at_8', 'ndcg_at_8']}
    negatives = [c for c in cases if not c['relevant']]
    summary.update(abstention_accuracy=sum(c['abstained'] for c in negatives) / len(negatives),
                   unanswerable_queries=len(negatives), rejected_unanswerable_queries=sum(c['abstained'] for c in negatives),
                   scope_pass=all(c['scope_pass'] for c in cases), route_pass=all(c['route_pass'] for c in cases),
                   overview_sources=overview_sources, p50_ms=statistics.median(c['latency_ms'] for c in cases),
                   p95_ms=sorted(c['latency_ms'] for c in cases)[math.ceil(.95 * len(cases)) - 1])
    # CI keyword mode checks routing, isolation, negative queries, and an aggregate
    # recall floor. It does not stand in for the semantic/reranker run.
    passed = (summary['scope_pass'] and summary['route_pass'] and overview_sources == 2
              and summary['recall_at_8'] >= .9 and summary['abstention_accuracy'] == 1
              and all(c['recall_at_8'] > 0 for c in cases if c['relevant']))
    if args.answers:
        judged = [c['answer_evaluation'] for c in cases]
        summary['answer_correctness'] = sum(j['correct'] for j in judged) / len(judged)
        summary['model_abstention_accuracy'] = sum(c['answer_evaluation']['abstains'] and c['answer_evaluation']['correct'] for c in negatives) / len(negatives)
        summary['judge_reviews_needed'] = sum(j['needs_review'] for j in judged)
        values = [j['supported_claim_fraction'] for j in judged if j['supported_claim_fraction'] is not None]
        summary['supported_claim_fraction'] = statistics.mean(values) if values else None
        summary['answer_completeness'] = statistics.mean(j['completeness'] for j in judged)
        citation_values = [j['citation_validity'] for j in judged if j['citation_validity'] is not None]
        summary['citation_validity'] = statistics.mean(citation_values) if citation_values else None
        passed = (passed and not summary['judge_reviews_needed'] and summary['answer_correctness'] >= .9
                  and (summary['supported_claim_fraction'] or 0) >= .9
                  and summary['answer_completeness'] >= .8
                  and summary['model_abstention_accuracy'] == 1
                  and all(not j['invalid_citations'] for j in judged)
                  and all(c['answer_evaluation']['citation_count'] > 0 for c in cases if c['relevant']))
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'passages': count, 'queries': len(cases),
              'mode': 'Keyword' if args.keyword else 'Hybrid + reranker', 'answers_evaluated': args.answers,
              'model': args.model if args.answers else None, 'judge_model': (args.judge_model or args.model) if args.answers else None,
              'self_judged': args.answers and (args.judge_model or args.model) == args.model,
              'model_abstention_evaluated': args.answers,
              'fixture_composition': {'topic_passages': len(TOPICS), 'repetitive_archive_distractors': count - len(TOPICS), 'ingestion_evaluated': False},
              'passed': passed, 'summary': summary, 'cases': cases,
              'fixture_sha256': hashlib.sha256(json.dumps([TOPICS, CASES], sort_keys=True).encode()).hexdigest(),
              'duration_s': round(time.perf_counter() - started, 2),
              'protocol': 'Chat retrieval workflow over 8 topic passages and 240 repetitive archive distractors across two sources, plus out-of-scope canaries. Prepared chunks bypass parsing and chunking. Warm retrieval-only latency, one pass. With --answers, the generator is called even with empty evidence; refusals are model-generated. No private documents.',
              'limitations': 'Developer-authored regression fixture, not held-out real-user or diverse long-document accuracy. No ingestion evaluation. Retrieval rejection and model abstention are separate metrics. Claim support is a macro-average over answers with judged claims, not the fraction of all factual claims. Quote verification cannot prove entailment or that the judge enumerated every claim. Single-pass latency is not a stable performance estimate. Self-judging is not independent validation.',
              'metric_reference': 'https://www.sbert.net/docs/package_reference/sentence_transformer/evaluation.html'}
    path = ROOT / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'passed': passed, 'summary': summary, 'report': str(path)}), flush=True)
    await providers.close_clients()
    if not passed:
        raise SystemExit('RAG evaluation gates failed; see per-case results.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keyword', action='store_true')
    parser.add_argument('--answers', action='store_true')
    parser.add_argument('--provider', default='Gemini', choices=['Gemini', 'Local / compatible'])
    parser.add_argument('--model', default='gemini-3.5-flash-lite')
    parser.add_argument('--judge-model', help='Use a separate model for answer judgments (recommended).')
    parser.add_argument('--allow-self-judge', action='store_true', help='Explicitly allow non-independent model judgments.')
    parser.add_argument('--request-interval', type=float, default=6, help='Minimum seconds between evaluation API calls.')
    parser.add_argument('--endpoint', default='http://127.0.0.1:11434/v1')
    parser.add_argument('--output', default='test-results/rag-evaluation.json', help='Report path; publish to app assets explicitly after review.')
    asyncio.run(run(parser.parse_args()))
