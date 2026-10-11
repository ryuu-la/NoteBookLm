"""Exercise real image ingestion and text-to-image retrieval without OCR or an API.

Uses simple authored diagrams, not a claim of general visual-document accuracy.
"""
import json
import argparse
import os
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reuse-data', type=Path, help='Reuse an isolated test-results directory and its embedding cache')
args = parser.parse_args()
RUN = (args.reuse_data or (ROOT / 'test-results' / f'multimodal-{time.time_ns()}')).resolve()
if not RUN.is_relative_to(ROOT / 'test-results'):
    parser.error('Visual benchmarks must use an isolated test-results directory')
os.environ['NOTEBOOK_DATA_DIR'] = str(RUN)
os.environ['NOTEBOOK_MODEL_DIR'] = str(ROOT / '.data' / 'models')

from local_notebook import storage as db  # noqa: E402
from local_notebook.config import EMBED_MODEL, EMBED_REVISION, EMBED_DIM  # noqa: E402
from local_notebook.evaluation import require_retrieval_mode  # noqa: E402
from local_notebook.ingestion import jobs  # noqa: E402
from local_notebook.ingestion.media import answer_images  # noqa: E402
from local_notebook.retrieval.search import retrieve  # noqa: E402


def diagram(title, labels):
    image = Image.new('RGB', (1000, 500), 'white')
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype('arial.ttf', 28)
    except OSError:
        font = ImageFont.load_default(size=28)
    draw.text((35, 30), title, fill='black', font=font)
    colors = ['#d8eaff', '#dcf5e4', '#fff1cc']
    for i, label in enumerate(labels):
        left = 35 + i * 330
        draw.rounded_rectangle((left, 180, left + 270, 330), radius=15, fill=colors[i], outline='black', width=3)
        draw.multiline_text((left + 15, 215), label, fill='black', font=font, spacing=8)
        if i < len(labels) - 1:
            draw.line((left + 275, 255, left + 320, 255), fill='black', width=4)
            draw.polygon([(left + 320, 255), (left + 307, 245), (left + 307, 265)], fill='black')
    buffer = BytesIO()
    image.save(buffer, 'PNG')
    image.close()
    return buffer.getvalue()


def main():
    db.initialize()
    db.save_settings({'semantic': True})
    book = db.create_notebook('Authored visual retrieval fixture')
    examples = [
        ('Solar power storage', ['Solar panels', 'Battery\nstorage', 'Home\nelectricity'],
         'Find the diagram showing solar panels charging a battery to power a home.'),
        ('Water treatment process', ['Dirty water', 'Filter and\npurify', 'Clean drinking\nwater'],
         'Which diagram shows filtering dirty water into drinking water?'),
        ('Software deployment pipeline', ['Source code', 'Build and\nrun tests', 'Deploy to\nserver'],
         'Find the software pipeline from source code through tests to deployment.'),
        ('Plant life cycle', ['Seed', 'Seedling', 'Flowering\nplant'],
         'Show the stages of a plant growing from a seed into a flowering plant.'),
    ]
    cases = []
    for i, (title, labels, question) in enumerate(examples):
        # Neutral filenames ensure retrieval must use pixels, not title metadata.
        source = jobs.add_file(book, f'figure-{i}.png', diagram(title, labels))
        jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (source,)))
        print(f'Indexed visual fixture {i + 1}/{len(examples)}', flush=True)
        cases.append({'question': question, 'expected_source': source})
    for case in cases:
        evidence = retrieve(book, case['question'])
        require_retrieval_mode(evidence, semantic=True)
        found = [p['source_id'] for p in evidence.passages]
        case.update(retrieved_sources=found, hit_at_1=found[:1] == [case['expected_source']],
                    hit_at_3=case['expected_source'] in found[:3],
                    scores=[p.get('semantic_score') for p in evidence.passages],
                    attachment_count=len(answer_images(evidence.passages)), latency_ms=evidence.elapsed_ms)
    result = {'created_at': datetime.now(timezone.utc).isoformat(), 'embedding_model': EMBED_MODEL,
              'revision': EMBED_REVISION, 'dimensions': EMBED_DIM, 'cases': cases,
              'hit_at_1': sum(c['hit_at_1'] for c in cases) / len(cases),
              'hit_at_3': sum(c['hit_at_3'] for c in cases) / len(cases),
              'limitations': 'Four simple authored raster diagrams. Native image ingestion, no OCR, no answer-generation API. Not held-out real-world document evaluation.'}
    (RUN / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)
    if not all(c['hit_at_1'] and c['attachment_count'] for c in cases):
        raise SystemExit('Visual retrieval gate failed; inspect test-results before claiming accuracy.')


if __name__ == '__main__':
    main()
