"""Reuse local embeddings across retries and duplicate content without storing text twice."""
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

from ..config import EMBED_MODEL, EMBED_REVISION, EMBED_DIM, IMAGE_SOFT_TOKENS


def embed_cached(directory: Path, texts: list, model=None, *, model_factory=None) -> list[np.ndarray]:
    from ..ingestion.media import image_cache_identity
    contract = f"{EMBED_MODEL}:{EMBED_REVISION}:{EMBED_DIM}:Document:normalized:media-v1"
    keys = [hashlib.sha256((contract + (f':image-{IMAGE_SOFT_TOKENS}' if isinstance(text, dict) else '') + "\0" + json.dumps(
        image_cache_identity(text) if isinstance(text, dict) else text, sort_keys=True)).encode()).hexdigest()
            for text in texts]
    with sqlite3.connect(directory / "embedding-cache.db", timeout=30) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE IF NOT EXISTS embeddings (digest TEXT PRIMARY KEY, vector BLOB)")
        cached = {}
        for start in range(0, len(keys), 500):
            batch = keys[start:start + 500]
            placeholders = ",".join("?" for _ in batch)
            cached.update(connection.execute(
                f"SELECT digest,vector FROM embeddings WHERE digest IN ({placeholders})", batch))
        missing = {key: text for key, text in zip(keys, texts) if key not in cached}
        if missing:
            if model is None:
                model = model_factory()
            # Similar lengths share a batch, avoiding padding short passages to the longest one.
            ordered = sorted(missing, key=lambda key: len(missing[key])) if len(missing) > 16 else list(missing)
            batch_size = 8
            vectors = model.embed([missing[key] for key in ordered], batch_size=batch_size)
            fresh = [(key, np.asarray(vector, dtype="<f4").tobytes()) for key, vector in zip(ordered, vectors)]
            if len(fresh) != len(missing):
                raise ValueError("The embedding model returned an incomplete batch. Retry this source.")
            connection.executemany("INSERT OR REPLACE INTO embeddings VALUES (?,?)", fresh)
            cached.update(fresh)
        return [np.frombuffer(cached[key], dtype="<f4") for key in keys]
