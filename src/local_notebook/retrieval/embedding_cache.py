"""Reuse local embeddings across retries and duplicate content without storing text twice."""
import hashlib
import sqlite3
from pathlib import Path

import numpy as np

from ..config import EMBED_MODEL


def embed_cached(directory: Path, texts: list[str], model) -> list[np.ndarray]:
    keys = [hashlib.sha256((EMBED_MODEL + "\0" + text).encode()).hexdigest() for text in texts]
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
            # Similar lengths share a batch, avoiding padding short passages to the longest one.
            ordered = sorted(missing, key=lambda key: len(missing[key])) if len(missing) > 16 else list(missing)
            # Short passages gain throughput at 32; retain 16 for long chunks
            # to bound ONNX padding/activation memory and keep cancellation quick.
            batch_size = 32 if max(map(len, missing.values())) <= 1200 else 16
            vectors = model.embed([missing[key] for key in ordered], batch_size=batch_size)
            fresh = [(key, np.asarray(vector, dtype="<f4").tobytes()) for key, vector in zip(ordered, vectors)]
            if len(fresh) != len(missing):
                raise ValueError("The embedding model returned an incomplete batch. Retry this source.")
            connection.executemany("INSERT OR REPLACE INTO embeddings VALUES (?,?)", fresh)
            cached.update(fresh)
        return [np.frombuffer(cached[key], dtype="<f4") for key in keys]
