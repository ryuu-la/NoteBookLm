"""Measure token batching on local source text without changing the user's index."""
import json
import time
from pathlib import Path

import numpy as np

from local_notebook import storage as db
from local_notebook.ingestion.chunking import make_splitter
from local_notebook.retrieval.vectors import GemmaEmbedding


def check():
    # Let the user's current import finish rather than compete for its CPU.
    deadline = time.monotonic() + 900
    while db.one("SELECT id FROM sources WHERE status IN ('queued','parsing','indexing') LIMIT 1"):
        if time.monotonic() > deadline:
            raise TimeoutError('Wait for active imports before benchmarking')
        print('Waiting for the active import to finish before benchmarking.', flush=True)
        time.sleep(15)
    rows = db.rows('''SELECT text FROM chunks WHERE source_id=(
        SELECT source_id FROM chunks GROUP BY source_id ORDER BY count(*) DESC LIMIT 1)
        AND image='' ORDER BY length(text),ordinal''')
    if not rows:
        raise ValueError('Import a text source before running this benchmark')
    splitter = make_splitter(True)
    lengths = [splitter.token_count(row['text']) for row in rows]
    def padded(values):
        return sum(max(values[i:i + 8]) * len(values[i:i + 8]) for i in range(0, len(values), 8))
    sample = np.linspace(0, len(rows) - 1, min(64, len(rows)), dtype=int).tolist()
    texts = [rows[i]['text'] for i in sample]
    orders = {'characters': sorted(range(len(texts)), key=lambda i: len(texts[i])),
              'tokens': sorted(range(len(texts)), key=lambda i: splitter.token_count(texts[i]))}
    model = GemmaEmbedding()
    model.encode(texts[:8], prompt_name='Document', batch_size=8)
    timings, outputs = {}, {}
    # Reverse the second run's order so neither method always gets a warmer CPU.
    for mode in ('characters', 'tokens', 'tokens', 'characters'):
        order = orders[mode]
        start = time.perf_counter()
        encoded = model.encode([texts[i] for i in order], prompt_name='Document', batch_size=8)
        elapsed = time.perf_counter() - start
        timings.setdefault(mode, []).append(elapsed)
        aligned = np.empty_like(encoded)
        for position, original in enumerate(order):
            aligned[original] = encoded[position]
        outputs[mode] = aligned
        print(json.dumps({'mode': mode, 'seconds': elapsed}), flush=True)
    result = {'source_sections': len(rows), 'sample_sections': len(texts),
              'padded_tokens_before': padded(lengths), 'padded_tokens_after': padded(sorted(lengths)),
              'timings_seconds': timings,
              'speedup': float(np.mean(timings['characters']) / np.mean(timings['tokens'])),
              'minimum_cosine': float(np.sum(outputs['characters'] * outputs['tokens'], axis=1).min()),
              'maximum_absolute_difference': float(np.abs(outputs['characters'] - outputs['tokens']).max())}
    path = Path('test-results/indexing-token-batching.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)
    assert result['minimum_cosine'] > .99999


if __name__ == '__main__':
    check()
