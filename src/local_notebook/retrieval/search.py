import re
import time
from dataclasses import dataclass, field

from .. import storage as db
from ..config import TEXT_ONLY
from . import vectors

# A conservative retrieval heuristic, evaluated with answerable and negative cases.
# Similarity is not a probability that a passage answers the question.
MIN_TEXT_SCORE = .65
MIN_IMAGE_SCORE = .62


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
                 "follow up example examples sources source notes document documents "
                 "compare contrast differ difference differences versus vs between".split())


def query_terms(query: str) -> list[str]:
    return list(dict.fromkeys(token for token in re.findall(r"\w+", query.casefold())
                             if token not in STOP_WORDS))[:24]


def comparison_parts(query: str) -> list[str]:
    match = re.match(r'^(?:compare|contrast) (.+?) (?:with|versus|vs\.?|and) (.+?)[?.!]*$', query.strip(), re.I)
    if not match:
        match = re.match(r'^how does (.+?) differ from (.+?)[?.!]*$', query.strip(), re.I)
    return list(match.groups()) if match else []


def selected_sources(notebook_id: str) -> list[dict]:
    return db.rows("SELECT * FROM sources WHERE notebook_id=? AND selected=1 AND status IN ('ready','indexing')",
                   (notebook_id,))


def retrieve(notebook_id: str, query: str, limit=8) -> Evidence:
    started = time.perf_counter()
    with db.connect() as conn:
        sources = [dict(r) for r in conn.execute(
            "SELECT * FROM sources WHERE notebook_id=? AND selected=1 AND status IN ('ready','indexing')",
            (notebook_id,)).fetchall()]
        identifiers = [source["id"] for source in sources]
        if not identifiers:
            return Evidence([], "No indexed sources", 0)
        placeholders = ",".join("?" for _ in identifiers)
        tokens = query_terms(query)
        # A user may type a compound name with spaces ("Fast API", "Py Torch").
        # Search the original terms plus adjacent compounds without an API rewrite.
        compounds = [a + b for a, b in zip(tokens, tokens[1:])]
        matched_compounds = set()
        if compounds:
            # Check chunk_fts directly without joining chunks so SQLite never scans chunks first.
            compound_fts = " OR ".join('"' + c + '"' for c in compounds)
            has_any = conn.execute(
                "SELECT 1 FROM chunk_fts WHERE chunk_fts MATCH ? LIMIT 1",
                (compound_fts,)).fetchone()
            if has_any:
                for a, b, compound in zip(tokens, tokens[1:], compounds):
                    if conn.execute(
                        f"""SELECT 1 FROM chunk_fts f JOIN chunks c ON c.rowid=f.rowid
                        WHERE chunk_fts MATCH ? AND c.notebook_id=? AND c.source_id IN ({placeholders})
                        ORDER BY bm25(chunk_fts) LIMIT 1""",
                        ('"' + compound + '"', notebook_id, *identifiers)).fetchone():
                        matched_compounds.add(compound)
                        query = re.sub(r'\b' + re.escape(a) + r'\s+' + re.escape(b) + r'\b', compound, query, flags=re.I)
        exact_tokens = []
        i = 0
        while i < len(tokens):
            if i + 1 < len(tokens) and (tokens[i] + tokens[i + 1]) in matched_compounds:
                exact_tokens.append(tokens[i] + tokens[i + 1])
                i += 2
            else:
                exact_tokens.append(tokens[i])
                i += 1
        fts_query = " OR ".join('"' + token + '"' for token in [*tokens, *sorted(matched_compounds)])
        lexical = []
        if fts_query:
            lexical = [dict(r) for r in conn.execute(f"""SELECT c.id FROM chunk_fts f JOIN chunks c ON c.rowid=f.rowid
                WHERE chunk_fts MATCH ? AND c.notebook_id=? AND c.source_id IN ({placeholders})
                ORDER BY bm25(chunk_fts) LIMIT 80""", (fts_query, notebook_id, *identifiers)).fetchall()]
        rankings = [[row["id"] for row in lexical]]
        if len(exact_tokens) > 1:
            exact_query = " AND ".join('"' + token + '"' for token in exact_tokens)
            exact = [dict(r) for r in conn.execute(f"""SELECT c.id FROM chunk_fts f JOIN chunks c ON c.rowid=f.rowid
                WHERE chunk_fts MATCH ? AND c.notebook_id=? AND c.source_id IN ({placeholders})
                ORDER BY bm25(chunk_fts) LIMIT 40""", (exact_query, notebook_id, *identifiers)).fetchall()]
            if exact:
                # Prioritize passages matching the whole topic over incidental one-word hits.
                rankings[0] = list(dict.fromkeys([row['id'] for row in exact] + rankings[0]))
        aspects = comparison_parts(query)
        for aspect in aspects:
            aspect_tokens = query_terms(aspect)
            if aspect_tokens:
                aspect_fts = " OR ".join('"' + t + '"' for t in aspect_tokens)
                aspect_rows = [dict(r) for r in conn.execute(f"""SELECT c.id FROM chunk_fts f JOIN chunks c ON c.rowid=f.rowid
                    WHERE chunk_fts MATCH ? AND c.notebook_id=? AND c.source_id IN ({placeholders})
                    ORDER BY bm25(chunk_fts) LIMIT 20""", (aspect_fts, notebook_id, *identifiers)).fetchall()]
                if aspect_rows:
                    rankings.append([row["id"] for row in aspect_rows])
        mode, warning = "Keyword search", ""
        semantic_scores = {}
        if db.settings()["semantic"]:
            try:
                semantic_rankings = []
                for search_query in [query, *aspects]:
                    matches = vectors.search(search_query, notebook_id, identifiers)
                    for match in matches:
                        identifier = match['id']
                        semantic_scores[identifier] = max(semantic_scores.get(identifier, -1), match['semantic_score'])
                    semantic_rankings.append([match['id'] for match in matches
                                              if match['semantic_score'] >= MIN_IMAGE_SCORE])
                rankings.extend(semantic_rankings)
                mode = "Hybrid retrieval"
            except Exception:
                warning = "Semantic search is unavailable. Results use the local keyword index."
        scores = {}
        for ranking in rankings:
            for rank, identifier in enumerate(ranking):
                scores[identifier] = scores.get(identifier, 0) + 1 / (60 + rank + 1)
        ranked_ids = sorted(scores, key=scores.get, reverse=True)[:max(limit, 40)]
        slots = ",".join("?" for _ in ranked_ids)
        rows = [dict(r) for r in conn.execute(f"""SELECT c.*, s.name, s.url FROM chunks c JOIN sources s ON s.id=c.source_id
            WHERE c.id IN ({slots}) AND s.status IN ('ready','indexing') AND s.selected=1 AND c.notebook_id=?
            AND (?=0 OR c.image='')""",
                       (*ranked_ids, notebook_id, int(TEXT_ONLY))).fetchall()] if ranked_ids else []
        total = conn.execute(f"SELECT COUNT(*) n FROM chunks WHERE notebook_id=? AND source_id IN ({placeholders})",
                             (notebook_id, *identifiers)).fetchone()['n']
    by_id = {row["id"]: row for row in rows}
    passages = [{**by_id[identifier], 'fusion_score': scores[identifier],
                 'semantic_score': semantic_scores.get(identifier)}
                for identifier in ranked_ids if identifier in by_id]
    lexical_ids = set(rankings[0])
    passages = [p for p in passages if p['id'] in lexical_ids
                or (p['semantic_score'] is not None and p['semantic_score'] >= (
                    MIN_IMAGE_SCORE if p.get('image') else MIN_TEXT_SCORE))]
    best_score = max(semantic_scores.values(), default=None)
    candidate_count = len(passages)
    kept, budget, seen = [], 0, set()
    for passage in passages:
        fingerprint = passage.get('image') or " ".join(passage['text'].casefold().split())
        if fingerprint in seen:
            continue
        if budget + len(passage["text"]) > 24000:
            continue
        kept.append(passage)
        seen.add(fingerprint)
        budget += len(passage["text"])
        if len(kept) == limit:
            break
    if any(s['status'] == 'indexing' for s in sources):
        warning = (warning + ' Text is searchable; semantic indexing is still in progress.').strip()
    return Evidence(kept, mode, round((time.perf_counter() - started) * 1000), warning.strip(),
                    {'route': 'targeted', 'query': query, 'aspects': aspects, 'indexed_passages': total,
                     'selected_sources': len(sources), 'candidate_count': candidate_count,
                     'retrieved_passages': len(kept),
                     'best_semantic_score': best_score})


def coverage(notebook_id: str, max_chunks=80) -> Evidence:
    started = time.perf_counter()
    sources = selected_sources(notebook_id)
    # Read actual chunk IDs, not assumed contiguous ordinals. Round-robin source
    # allocation prevents a large first document from consuming the whole budget.
    groups = [db.rows("SELECT id FROM chunks WHERE source_id=? AND (?=0 OR image='') ORDER BY ordinal",
                      (s['id'], int(TEXT_ONLY))) for s in sources]
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
    chosen = []
    for offset in range(max(quotas, default=0)):
        for group in selected:
            if offset < len(group):
                identifier, source = group[offset]
                chosen.append((identifier, source))
    # One query instead of opening a SQLite connection for every sampled passage.
    identifiers = [identifier for identifier, _ in chosen]
    slots = ','.join('?' for _ in identifiers)
    chunks = {row['id']: row for row in db.rows(f'SELECT * FROM chunks WHERE id IN ({slots})', identifiers)} if identifiers else {}
    result = [{**chunks[identifier], 'name': source['name'], 'url': source['url']}
              for identifier, source in chosen if identifier in chunks]
    warning = '' if total <= len(result) else f"Overview evidence: {len(result)} of {total} indexed passages, distributed across selected sources."
    if any(s['status'] == 'indexing' for s in sources):
        warning = (warning + ' Text is searchable; semantic indexing is still in progress.').strip()
    return Evidence(result, "Source overview", round((time.perf_counter() - started) * 1000), warning,
                    {'route': 'overview', 'indexed_passages': total, 'selected_sources': len(sources),
                     'retrieved_passages': len(result)})
