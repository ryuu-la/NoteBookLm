import re
import time
from dataclasses import dataclass, field

from .. import storage as db
from . import vectors


@dataclass
class Evidence:
    passages: list[dict]
    mode: str
    elapsed_ms: int
    warning: str = ""
    diagnostics: dict = field(default_factory=dict)


STOP_WORDS = set("a an the is are was were be been to of in on for from with and or by as at "
                 "what why how when where which who do does did can could would should will "
                 "i me my you your we our it its they them their this that these those "
                 "tell explain show give about more anything else please further details detail "
                 "follow up example examples sources source notes document documents".split())


def query_terms(query: str) -> list[str]:
    return list(dict.fromkeys(token for token in re.findall(r"\w+", query.casefold())
                             if token not in STOP_WORDS))[:24]


def comparison_parts(query: str) -> list[str]:
    match = re.match(r'^(?:compare|contrast) (.+?) (?:with|versus|vs\.?|and) (.+?)[?.!]*$', query.strip(), re.I)
    if not match:
        match = re.match(r'^how does (.+?) differ from (.+?)[?.!]*$', query.strip(), re.I)
    return list(match.groups()) if match else []


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
    tokens = query_terms(query)
    # A user may type a compound name with spaces ("Fast API", "Py Torch").
    # Search the original terms plus adjacent compounds without an API rewrite.
    compounds = [a + b for a, b in zip(tokens, tokens[1:])]
    for a, b, compound in zip(tokens, tokens[1:], compounds):
        exists = db.one(f"""SELECT c.id FROM chunk_fts f JOIN chunks c ON c.rowid=f.rowid
            WHERE chunk_fts MATCH ? AND c.notebook_id=? AND c.source_id IN ({placeholders}) LIMIT 1""",
                        ('"' + compound + '"', notebook_id, *identifiers))
        if exists:
            query = re.sub(r'\b' + re.escape(a) + r'\s+' + re.escape(b) + r'\b', compound, query, flags=re.I)
    fts_query = " OR ".join('"' + token + '"' for token in [*tokens, *compounds])
    lexical = []
    if fts_query:
        lexical = db.rows(f"""SELECT c.id FROM chunk_fts f JOIN chunks c ON c.rowid=f.rowid
            WHERE chunk_fts MATCH ? AND c.notebook_id=? AND c.source_id IN ({placeholders})
            ORDER BY bm25(chunk_fts) LIMIT 40""", (fts_query, notebook_id, *identifiers))
    rankings = [[row["id"] for row in lexical]]
    if len(tokens) > 1:
        exact_query = " AND ".join('"' + token + '"' for token in tokens)
        exact = db.rows(f"""SELECT c.id FROM chunk_fts f JOIN chunks c ON c.rowid=f.rowid
            WHERE chunk_fts MATCH ? AND c.notebook_id=? AND c.source_id IN ({placeholders})
            ORDER BY bm25(chunk_fts) LIMIT 40""", (exact_query, notebook_id, *identifiers))
        # Prioritize passages matching the whole topic over incidental one-word hits.
        rankings[0] = list(dict.fromkeys([row['id'] for row in exact] + rankings[0]))
    mode, warning = "Keyword search", ""
    aspects = comparison_parts(query)
    if db.settings()["semantic"]:
        try:
            rankings.append(vectors.search(query, notebook_id, identifiers))
            for aspect in aspects:
                rankings.append(vectors.search(aspect, notebook_id, identifiers))
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
    best_score = max((p.get('relevance_score', 0) for p in passages), default=None)
    candidate_count = len(passages)
    # Reject a query only when even its strongest candidate is very weak.
    # Filtering each passage by a logit would discard useful comparison evidence.
    if best_score is not None and best_score < -8:
        passages = []
    kept, budget, seen = [], 0, set()
    for passage in passages:
        fingerprint = " ".join(passage['text'].casefold().split())
        if fingerprint in seen:
            continue
        if budget + len(passage["text"]) > 24000:
            continue
        kept.append(passage)
        seen.add(fingerprint)
        budget += len(passage["text"])
        if len(kept) == limit:
            break
    total = db.one(f"SELECT COUNT(*) n FROM chunks WHERE notebook_id=? AND source_id IN ({placeholders})",
                   (notebook_id, *identifiers))['n']
    return Evidence(kept, mode, round((time.perf_counter() - started) * 1000), warning.strip(),
                    {'route': 'targeted', 'query': query, 'aspects': aspects, 'indexed_passages': total,
                     'selected_sources': len(sources), 'candidate_count': candidate_count,
                     'retrieved_passages': len(kept),
                     'best_relevance_score': best_score})


def coverage(notebook_id: str, max_chunks=80) -> Evidence:
    started = time.perf_counter()
    sources = selected_sources(notebook_id)
    # Read actual chunk IDs, not assumed contiguous ordinals. Round-robin source
    # allocation prevents a large first document from consuming the whole budget.
    groups = [db.rows('SELECT id FROM chunks WHERE source_id=? ORDER BY ordinal', (s['id'],)) for s in sources]
    total = sum(map(len, groups))
    quotas = [0] * len(groups)
    remaining = min(max_chunks, total)
    while remaining:
        for i, group in enumerate(groups):
            if remaining and quotas[i] < len(group):
                quotas[i] += 1
                remaining -= 1
    selected = []
    for source, group, quota in zip(sources, groups, quotas):
        # Start/end and evenly spaced sections, including all chunks when they fit.
        indices = [round(i * (len(group) - 1) / max(1, quota - 1)) for i in range(quota)]
        selected.append([(group[i]['id'], source) for i in indices])
    result = []
    for offset in range(max(quotas, default=0)):
        for group in selected:
            if offset < len(group):
                identifier, source = group[offset]
                chunk = db.one('SELECT * FROM chunks WHERE id=?', (identifier,))
                result.append({**chunk, 'name': source['name'], 'url': source['url']})
    warning = '' if total <= len(result) else f"Overview evidence: {len(result)} of {total} indexed passages, distributed across selected sources."
    return Evidence(result, "Source overview", round((time.perf_counter() - started) * 1000), warning,
                    {'route': 'overview', 'indexed_passages': total, 'selected_sources': len(sources),
                     'retrieved_passages': len(result)})
