from threading import RLock
from functools import lru_cache

import lancedb
import pyarrow as pa

from ..config import DATA, EMBED_MODEL, MODEL_CACHE, EMBED_THREADS

_lock = RLock()
_model = None
_reranker = None
_tables = {}


def embedding_model():
    global _model
    with _lock:
        if _model is None:
            from fastembed import TextEmbedding
            _model = TextEmbedding(EMBED_MODEL, cache_dir=str(MODEL_CACHE), threads=EMBED_THREADS)
        return _model


def table():
    path = str(DATA / "vectors")
    with _lock:
        if path not in _tables:
            connection = lancedb.connect(path)
            schema = pa.schema([pa.field("id", pa.string()), pa.field("source_id", pa.string()),
                                pa.field("notebook_id", pa.string()), pa.field("vector", pa.list_(pa.float32(), 384))])
            _tables[path] = connection.create_table("bge_small_v1", schema=schema, exist_ok=True)
        return _tables[path]


def insert(chunks: list[dict]) -> None:
    from .embedding_cache import embed_cached
    embeddings = embed_cached(DATA, [row["text"] for row in chunks], embedding_model())
    values = [{"id": row["id"], "source_id": row["source_id"], "notebook_id": row["notebook_id"],
               "vector": vector.tolist()} for row, vector in zip(chunks, embeddings)]
    if values:
        table().merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(values)


@lru_cache(maxsize=128)
def query_vector(query: str) -> tuple:
    return tuple(next(embedding_model().query_embed(query)).tolist())


def remove(source_id: str) -> None:
    if not source_id.isalnum():
        raise ValueError("Invalid source identifier")
    with _lock:
        table().delete(f"source_id = '{source_id}'")


def search(query: str, notebook_id: str, source_ids: list[str], limit=40) -> list[str]:
    if not source_ids:
        return []
    if not all(identifier.isalnum() for identifier in [notebook_id, *source_ids]):
        raise ValueError("Invalid search scope")
    vector = list(query_vector(query))
    scope = ",".join(f"'{identifier}'" for identifier in source_ids)
    result = table().search(vector).where(
        f"notebook_id = '{notebook_id}' AND source_id IN ({scope})", prefilter=True
    ).limit(limit).select(["id", "_distance"]).to_list()
    return [row["id"] for row in result]


def rerank(query: str, passages: list[dict]) -> list[dict]:
    global _reranker
    if not passages:
        return passages
    with _lock:
        if _reranker is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            _reranker = TextCrossEncoder("Xenova/ms-marco-MiniLM-L-6-v2",
                                        cache_dir=str(MODEL_CACHE), threads=2)
    scores = list(_reranker.rerank(query, [passage["text"] for passage in passages], batch_size=8))
    return [{**passage, 'relevance_score': float(score)}
            for score, passage in sorted(zip(scores, passages), key=lambda pair: pair[0], reverse=True)]
