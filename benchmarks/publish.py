"""Synchronize the documented retrieval table with the raw report; --check is read-only."""
import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = '<!-- retrieval-results:start -->'
END = '<!-- retrieval-results:end -->'
SCALE_START = '<!-- scale-results:start -->'
SCALE_END = '<!-- scale-results:end -->'


def validate(data):
    """Recompute scores and timings, refusing to publish inconsistent summaries."""
    for result in data['results']:
        cases = result['cases']
        expected = data['queries'] * data.get('repeats', 1)
        if len(cases) != expected:
            raise ValueError('Unexpected sample count: ' + result['name'])
        scores = []
        for case in cases:
            relevant = set(case['relevant'])
            hits = [int(key in relevant) for key in list(dict.fromkeys(case['retrieved']))[:8]]
            score = (sum(hits) / len(relevant),
                     next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0),
                     sum(hit / math.log2(i + 2) for i, hit in enumerate(hits)) /
                     sum(1 / math.log2(i + 2) for i in range(min(8, len(relevant)))))
            scores.append(score)
            for key, value in zip(('recall_at_8', 'mrr_at_8', 'ndcg_at_8'), score):
                if not math.isclose(case[key], value, abs_tol=1e-9):
                    raise ValueError('Incorrect per-case metric: ' + key)
        for i, key in enumerate(('recall_at_8', 'mrr_at_8', 'ndcg_at_8')):
            if round(statistics.mean(score[i] for score in scores), 4) != result[key]:
                raise ValueError('Incorrect aggregate metric: ' + key)
        latencies = sorted(case['latency_ms'] for case in cases)
        if result['p50_ms'] != round(statistics.median(latencies), 1) or result['p95_ms'] != latencies[math.ceil(.95 * len(latencies)) - 1]:
            raise ValueError('Incorrect latency quantiles: ' + result['name'])


def table(data):
    lines = [START, f"Measured {data['created_at'][:10]} · {data['queries']} questions · "
             f"{data['passages']} authored passages · {data.get('repeats', 1)} repetition(s) per configuration.", '',
             '| Configuration | Recall@8 | MRR@8 | nDCG@8 | Median | p95 |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for r in data['results']:
        lines.append(f"| {r['name']} | {r['recall_at_8']:.4f} | {r['mrr_at_8']:.4f} | {r['ndcg_at_8']:.4f} | {r['p50_ms']:g} ms | {r['p95_ms']:g} ms |")
    lines.extend(['', 'Generated from [raw query results](../src/local_notebook/assets/retrieval-benchmark.json). '
                  'Latencies cover warm retrieval only, excluding answer generation.', END])
    return '\n'.join(lines)


def scale_table(data):
    probes = data['probes']
    expected_mode = 'Hybrid retrieval' if data['mode'] == 'hybrid' else 'Keyword search'
    for probe in probes:
        if (not 1 <= probe['page'] <= data['pages'] or probe['mode'] != expected_mode
                or probe['hit'] != (f"Page {probe['page']}" in probe['retrieved'][:8])):
            raise ValueError('Incorrect scale probe evidence or mode')
    if (data['probe_count'] != len(probes) or len({p['page'] for p in probes}) != len(probes)
            or data['chunks'] != data['pages'] or data['passed'] != all(p['hit'] for p in probes)
            or data['exact_record_recall_at_8'] != sum(p['hit'] for p in probes) / len(probes)
            or data['retrieval_ms'] != [p['latency_ms'] for p in probes]):
        raise ValueError('Inconsistent scale probes')
    return '\n'.join([
        SCALE_START, f"Measured {data['created_at'][:10]} · single run · {data['mode']} · reranker disabled.", '',
        '| Measurement | Observed |', '| --- | ---: |',
        f"| Synthetic PDF pages | {data['pages']:,} |",
        f"| Indexed passages | {data['chunks']:,} |",
        f"| Ingestion including local embeddings | {data['ingestion_seconds']:g} s |",
        f"| Average ingestion throughput | {data['pages_per_second']:g} pages/s |",
        f"| Cached reindexing | {data['cached_reindex_seconds']:g} s |",
        f"| Peak process RSS across ingestion, reindex and probes | {data['peak_process_rss_mb']:g} MB |",
        '| Retrieval latency | ' + ', '.join(str(p['latency_ms']) for p in probes) + ' ms |',
        f"| Requested page found in top eight | {sum(p['hit'] for p in probes)} / {len(probes)} |",
        '', 'Generated from [raw scale measurements](benchmark-result.json).', SCALE_END])


def sync_section(path, start, end, section, *, check):
    text = path.read_text(encoding='utf-8')
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    updated = before + section + after
    if check:
        if updated != text:
            raise SystemExit(f'Stale {path.name}: run python benchmarks/publish.py')
    else:
        path.write_text(updated, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    raw = (ROOT / 'src/local_notebook/assets/retrieval-benchmark.json').read_bytes()
    data = json.loads(raw)
    validate(data)
    sync_section(ROOT / 'docs/RETRIEVAL_BENCHMARK.md', START, END, table(data), check=args.check)
    scale = json.loads((ROOT / 'docs/benchmark-result.json').read_text(encoding='utf-8'))
    sync_section(ROOT / 'docs/VERIFICATION.md', SCALE_START, SCALE_END, scale_table(scale), check=args.check)
    digest = hashlib.sha256(raw).hexdigest()
    if digest not in (ROOT / 'docs/images/retrieval-benchmark.svg').read_text(encoding='utf-8'):
        raise SystemExit('Stale retrieval chart: run python benchmarks/plot.py')
    if digest.encode() not in (ROOT / 'docs/images/retrieval-benchmark.png').read_bytes():
        raise SystemExit('Stale retrieval PNG: run python benchmarks/plot.py')
    print('Retrieval scores, scale probes, tables and chart provenance verified.')


if __name__ == '__main__':
    main()
