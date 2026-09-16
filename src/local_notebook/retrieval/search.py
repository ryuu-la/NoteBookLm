import re
import time
from dataclasses import dataclass

from .. import storage as db
from . import vectors


@dataclass
class Evidence:
    passages: list[dict]
    mode: str
    elapsed_ms: int
    warning: str = ""


def selected_sources(notebook_id: str) -> list[dict]:
    return db.rows("SELECT * FROM sources WHERE notebook_id=? AND selected=1 AND status='ready'",
                   (notebook_id,))


def retrieve(notebook_id: str, query: str, limit=8, *, candidate_limit=None) -> Evidence:
    started = time.perf_counter()
    sources = selected_sources(notebook_id)
    identifiers = [source["id"] for source in sources]
    if not identifiers:
        return Evidence([], "No indexed sources", 0)
    placeholders = ",".join("?" for _ in identifiers)
    tokens = re.findall(r"\w+", query, re.UNICODE)[:24]
    fts_query = " OR ".join('"' + token + '"' for token in tokens)
    lexical = []
    if fts_query:
        lexical = db.rows(f"""SELECT c.id FROM chunk_fts f JOIN chunks c ON c.rowid=f.rowid
            WHERE chunk_fts MATCH ? AND c.notebook_id=? AND c.source_id IN ({placeholders})
            ORDER BY bm25(chunk_fts) LIMIT 40""", (fts_query, notebook_id, *identifiers))
    rankings = [[row["id"] for row in lexical]]
    mode, warning = "Keyword search", ""
    if db.settings()["semantic"]:
        try:
            rankings.append(vectors.search(query, notebook_id, identifiers))
            mode = "Hybrid retrieval"
        except Exception:
            warning = "Semantic search is unavailable. Results use the local keyword index."
    scores = {}
    for ranking in rankings:
        for rank, identifier in enumerate(ranking):
            scores[identifier] = scores.get(identifier, 0) + 1 / (60 + rank + 1)
    candidates = candidate_limit if candidate_limit is not None else db.settings()["rerank_candidates"]
    ranked_ids = sorted(scores, key=scores.get, reverse=True)[:max(limit, candidates)]
    slots = ",".join("?" for _ in ranked_ids)
    rows = db.rows(f"""SELECT c.*, s.name, s.url FROM chunks c JOIN sources s ON s.id=c.source_id
        WHERE c.id IN ({slots}) AND s.status='ready' AND s.selected=1 AND c.notebook_id=?""",
                   (*ranked_ids, notebook_id)) if ranked_ids else []
    by_id = {row["id"]: row for row in rows}
    passages = [by_id[identifier] for identifier in ranked_ids if identifier in by_id]
    if db.settings()["rerank"]:
        try:
            passages = vectors.rerank(query, passages)
            mode += " + reranker"
        except Exception:
            warning += " Reranker unavailable; using fused retrieval scores."
    kept, budget = [], 0
    for passage in passages:
        if budget + len(passage["text"]) > 24000:
            continue
        kept.append(passage)
        budget += len(passage["text"])
        if len(kept) == limit:
            break
    return Evidence(kept, mode, round((time.perf_counter() - started) * 1000), warning.strip())


def coverage(notebook_id: str, max_chunks=80) -> Evidence:
    started = time.perf_counter()
    sources = selected_sources(notebook_id)
    result, total = [], 0
    quota = max(1, max_chunks // max(1, len(sources)))
    for source in sources[:max_chunks]:
        count = db.one("SELECT COUNT(*) AS n FROM chunks WHERE source_id=?", (source["id"],))["n"]
        total += count
        if count > quota:
            indices = sorted({round((i + .5) * count / quota) - 1 for i in range(quota)})
            slots = ",".join("?" for _ in indices)
            chunks = db.rows(f"SELECT * FROM chunks WHERE source_id=? AND ordinal IN ({slots}) ORDER BY ordinal",
                             (source["id"], *indices))
        else:
            chunks = db.rows("SELECT * FROM chunks WHERE source_id=? ORDER BY ordinal", (source["id"],))
        result.extend({**chunk, "name": source["name"], "url": source["url"]} for chunk in chunks)
    warning = "" if total <= len(result) and len(sources) <= max_chunks else (
        "Overview samples sections across selected sources; it does not cover every passage.")
    return Evidence(result, "Source overview", round((time.perf_counter() - started) * 1000), warning)
