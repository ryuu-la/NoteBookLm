"""Render the measured result as standalone PNG and SVG figures."""
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / "test-results/matplotlib"))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def main():
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/local_notebook/assets/retrieval-benchmark.json").read_bytes()
    data = json.loads(source)
    provenance = {'Description': 'Source SHA256: ' + hashlib.sha256(source).hexdigest()}
    results = data["results"]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "text.color": "#e5e9f4",
                         "axes.labelcolor": "#c0c9df", "xtick.color": "#b7c3de", "ytick.color": "#b7c3de"})
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), facecolor="#151820")
    labels = [r['name'].replace(' reranked', '\nreranked') for r in results]
    positions = np.arange(len(results))
    for ax in axes:
        ax.set_facecolor("#202530")
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color("#414a60")
        ax.set_xticks(positions, labels)
        ax.set_axisbelow(True)
        ax.grid(axis="y", color="#364053", alpha=.6)
    for offset, key, label, color in [(-.25, "recall_at_8", "Recall@8", "#abc4ff"),
                                     (0, "mrr_at_8", "MRR@8", "#b4a4f5"),
                                     (.25, "ndcg_at_8", "nDCG@8", "#8bcbb1")]:
        bars = axes[0].bar(positions + offset, [r[key] * 100 for r in results], width=.24, label=label, color=color)
        axes[0].bar_label(bars, fmt="%.1f", fontsize=8, padding=3)
    axes[0].set_ylim(0, 112)
    axes[0].set_ylabel("Retrieval score (%) · higher is better")
    axes[0].legend(loc="lower left", facecolor="#202530", labelcolor="#e5e9f4", edgecolor="none")
    for offset, key, label, color in [(-.17, "p50_ms", "Median", "#abc4ff"), (.17, "p95_ms", "p95", "#e6b881")]:
        bars = axes[1].bar(positions + offset, [r[key] for r in results], width=.32, label=label, color=color)
        axes[1].bar_label(bars, labels=[f"{r[key]:g} ms" for r in results], fontsize=9, padding=4)
    axes[1].set_ylabel("Warm retrieval latency (ms) · lower is better")
    axes[1].set_ylim(0, max(r["p95_ms"] for r in results) * 1.22)
    axes[1].legend(loc="upper left", facecolor="#202530", labelcolor="#e5e9f4", edgecolor="none")
    fig.suptitle("Folio  /  Retrieval quality & speed", x=.06, ha="left", fontsize=22, fontweight="bold")
    fig.text(.06, .875, f"{data['queries']} questions · {data['passages']} authored passages · {data.get('repeats', 1)} repetition(s) · {data['created_at'][:10]} · CPU", color="#aebbd5")
    fig.text(.06, .045, "Developer-authored fixture; not proof of perfect answers. Warm models, uncached queries, no generation latency.\n40 vs 16 candidates is an ablation on the same optimized engine. See JSON for every query and ranking.", fontsize=9, color="#aebbd5")
    fig.subplots_adjust(left=.06, right=.98, bottom=.23, top=.8, wspace=.22)
    directory = root / "docs/images"
    directory.mkdir(exist_ok=True)
    fig.savefig(directory / "retrieval-benchmark.png", dpi=160, facecolor=fig.get_facecolor(), metadata=provenance)
    fig.savefig(directory / "retrieval-benchmark.svg", facecolor=fig.get_facecolor(), metadata=provenance)
    svg = directory / "retrieval-benchmark.svg"
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
