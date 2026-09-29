import json
from pathlib import Path

from nicegui import ui

from .common import header, theme


def benchmark_page():
    theme()
    header("Retrieval benchmarks")
    with ui.column().classes("w-full max-w-6xl mx-auto p-8 gap-6"):
        ui.link("Back to your notebooks", "/").classes("breadcrumb")
        ui.label("Evidence before claims.").classes("text-4xl")
        ui.label("Measured retrieval quality and latency on a reproducible, public fixture.").classes("muted")
        rag_path = Path(__file__).resolve().parents[1] / 'assets/rag-evaluation.json'
        if rag_path.exists():
            rag = json.loads(rag_path.read_text(encoding='utf-8'))
            summary = rag['summary']
            ui.label('Conversation RAG evaluation').classes('text-2xl')
            ui.label('Evaluation gates passed' if rag['passed'] else 'Evaluation gates failed — judgments need review').classes('text-sm muted')
            ui.label(f"{rag['queries']} regression questions · {rag['passages']} indexed passages · {rag['mode']} · {rag['created_at'][:10]}").classes('muted')
            ui.label('Fixture: 8 topic passages + 240 repetitive archive distractors. Prepared chunks; parsing and chunking are not evaluated.').classes('muted')
            negatives = [c for c in rag['cases'] if not c['relevant']]
            with ui.element('div').classes('w-full gap-4').style('display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr))'):
                metrics = [(f"{summary['recall_at_8']:.0%}", 'EVIDENCE RECALL@8'),
                           (f"{sum(c['abstained'] for c in negatives)}/{len(negatives)}", 'UNANSWERABLE QUERIES REJECTED BY RETRIEVAL'),
                           ('Passed' if summary['scope_pass'] and summary['route_pass'] else 'Failed', 'SCOPE AND ROUTING'),
                           (f"{summary['p95_ms']} ms", 'P95 RETRIEVAL')]
                for value, label in metrics:
                    with ui.card().classes('panel p-5'):
                        ui.label(value).classes('text-2xl')
                        ui.label(label).classes('eyebrow mt-2')
            ui.label('Answer generation evaluated' if rag['answers_evaluated'] else
                     'Generated-answer quality has not been measured in this run. These scores measure retrieval and routing.').classes('muted')
            if rag['answers_evaluated']:
                support = summary['supported_claim_fraction']
                support_label = f'{support:.1%}' if support is not None else 'not scored'
                ui.label(f"Raw model verdicts: {summary['answer_correctness']:.1%} correct · "
                         f"{support_label} mean quote-audited claim support").classes('text-lg')
                ui.label(f"Generator: {rag['model']} · Judge: {rag.get('judge_model', rag['model'])} · "
                         f"{summary.get('judge_reviews_needed', 0)} judgments flagged for review").classes('muted')
                if rag['model'] == rag.get('judge_model', rag['model']):
                    ui.label('Generator and judge use the same model. These judgments are not independent accuracy measurements.').classes('muted')
                if not rag.get('model_abstention_evaluated', False):
                    ui.label('Model refusal behavior was not evaluated: empty-evidence answers in this historical run were fixed refusal text.').classes('muted')
                else:
                    ui.label(f"Model-judged refusal accuracy: {summary['model_abstention_accuracy']:.1%}").classes('muted')
                with ui.expansion('Answers and raw judge verdicts', icon='fact_check').classes('w-full panel p-4'):
                    for case in rag['cases']:
                        judgment = case['answer_evaluation']
                        with ui.expansion(case['question']).classes('w-full'):
                            ui.label(case['answer']).classes('whitespace-pre-wrap')
                            ui.label(f"Raw correct verdict: {judgment['correct']} · Review flagged: {judgment.get('needs_review', False)}")
                            ui.label(judgment['reason']).classes('muted whitespace-pre-wrap')
                            for reason in judgment.get('review_reasons', []):
                                ui.label(reason).classes('muted')
            with ui.expansion('Cases, evidence, and evaluation limits', icon='science').classes('w-full panel p-4'):
                ui.label(rag['protocol'])
                ui.label(rag['limitations']).classes('muted')
                ui.table(columns=[{'name': key, 'label': label, 'field': key, 'align': 'left'}
                                  for key, label in [('question', 'Question'), ('category', 'Case'), ('score', 'Recall@8'), ('found', 'Retrieved evidence')]],
                         rows=[{'question': c['question'], 'category': c['category'],
                                'score': f"{c['recall_at_8']:.0%}" if c['recall_at_8'] is not None else ('Abstained' if c['abstained'] else 'False match'),
                                'found': ', '.join(c['retrieved']) or 'No evidence'} for c in rag['cases']]).classes('w-full')
            ui.button('Download conversation RAG evaluation', icon='download',
                      on_click=lambda: ui.download.content(rag_path.read_bytes(), 'rag-evaluation.json')).props('outline')
        path = Path(__file__).resolve().parents[1] / "assets/retrieval-benchmark.json"
        if not path.exists():
            ui.label("No benchmark results yet. Run python benchmarks/retrieval.py from the project folder.")
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        results = data["results"]
        names = [row["name"] for row in results]
        with ui.element('div').classes('w-full gap-4').style('display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr))'):
            for value, label in [(data["queries"], "LABELED QUESTIONS"), (data["passages"], "PUBLIC PASSAGES"),
                                 ("BGE + MiniLM", "LOCAL CPU MODELS")]:
                with ui.card().classes("panel p-5"):
                    ui.label(str(value)).classes("text-2xl")
                    ui.label(label).classes("eyebrow mt-2")
        base = {"backgroundColor": "transparent", "animation": False, "textStyle": {"color": "#bac6df"},
                "tooltip": {"trigger": "axis"}, "legend": {"textStyle": {"color": "#bac6df"}, "top": 8},
                "grid": {"left": 60, "right": 24, "bottom": 85},
                "xAxis": {"type": "category", "data": names,
                          "axisLabel": {"interval": 0, "rotate": 15, "color": "#bac6df"}}}
        axis = {"type": "value", "axisLabel": {"color": "#bac6df"},
                "splitLine": {"lineStyle": {"color": "#343c4c"}}}
        ui.label("Quality · higher is better").classes("text-xl")
        ui.echart({**base, "color": ["#abc4ff", "#b4a4f5", "#8bcbb1"],
                   "yAxis": {**axis, "max": 100, "name": "%"},
                   "series": [{"name": label, "type": "bar", "data": [round(row[key] * 100, 2) for row in results]}
                              for label, key in [("Recall@8", "recall_at_8"), ("MRR@8", "mrr_at_8"), ("nDCG@8", "ndcg_at_8")]]}).classes("w-full h-80")
        ui.label("Latency · lower is better").classes("text-xl")
        ui.echart({**base, "color": ["#abc4ff", "#e6b881"], "yAxis": {**axis, "name": "ms"},
                   "series": [{"name": label, "type": "bar", "data": [row[key] for row in results]}
                              for label, key in [("Median", "p50_ms"), ("p95", "p95_ms")]]}).classes("w-full h-80")
        ui.label("Recall measures how much labeled evidence appears in the top 8. MRR rewards an early first match. nDCG rewards placing all relevant passages near the top.").classes("muted")
        with ui.expansion("Methodology and limits", icon="science", value=True).classes("w-full panel p-4"):
            ui.label(data["protocol"]).classes("leading-relaxed")
            ui.label(data["limitations"]).classes("muted leading-relaxed")
            ui.label(f"Measured {data['created_at'][:10]} · Python {data['python']} · {data['platform']}").classes("text-xs muted mt-3")
        ui.button("Download results and query judgments", icon="download",
                  on_click=lambda: ui.download.content(path.read_bytes(), "retrieval-benchmark.json")).props("outline").classes("max-w-full")
