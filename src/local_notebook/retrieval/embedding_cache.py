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
            vectors = model.embed(list(missing.values()), batch_size=16)
            fresh = [(key, np.asarray(vector, dtype="<f4").tobytes()) for key, vector in zip(missing, vectors)]
            connection.executemany("INSERT OR REPLACE INTO embeddings VALUES (?,?)", fresh)
            cached.update(fresh)
        return [np.frombuffer(cached[key], dtype="<f4") for key in keys]
