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
        path = Path(__file__).resolve().parents[1] / "assets/retrieval-benchmark.json"
        if not path.exists():
            ui.label("No benchmark results yet. Run python benchmarks/retrieval.py from the project folder.")
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        results = data["results"]
        names = [row["name"] for row in results]
        with ui.row().classes("w-full gap-4"):
            for value, label in [(data["queries"], "LABELED QUESTIONS"), (data["passages"], "PUBLIC PASSAGES"),
                                 ("BGE + MiniLM", "LOCAL CPU MODELS")]:
                with ui.card().classes("panel p-5 flex-1 min-w-48"):
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
