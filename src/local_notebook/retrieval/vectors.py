"""One local EmbeddingGemma 2 model for text and image retrieval."""
from functools import lru_cache
import logging
import os
import platform
from threading import Condition, RLock

import lancedb
import numpy as np
import pyarrow as pa

from ..config import DATA, EMBED_MODEL, EMBED_REVISION, EMBED_DIM, MODEL_CACHE, EMBED_THREADS, IMAGE_SOFT_TOKENS, TEXT_ONLY

_model_lock = RLock()
_table_lock = RLock()
_inference = Condition()
_encoding = False
_waiting_queries = 0
_model = None
_tables = {}


class GemmaEmbedding:
    def __init__(self):
        import torch

        torch.set_num_threads(EMBED_THREADS)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported() else torch.float32
        snapshot = MODEL_CACHE / ('models--' + EMBED_MODEL.replace('/', '--')) / 'snapshots' / EMBED_REVISION
        if (device == 'cpu' and TEXT_ONLY and platform.machine().lower() in {'amd64', 'x86_64'}
                and os.getenv('NOTEBOOK_EMBED_BACKEND', 'openvino') == 'openvino'
                and (snapshot / 'modules.json').exists()):
            from .cpu_encoder import CpuEncoder
            self.model = CpuEncoder(snapshot)
            self.tokenizer = self.model.tokenizer.backend_tokenizer
            logging.getLogger(__name__).info('EmbeddingGemma 2: OpenVINO CPU, float32, text only')
            return
        from sentence_transformers import SentenceTransformer
        model_path = str(snapshot) if (snapshot / 'modules.json').exists() else EMBED_MODEL
        self.model = SentenceTransformer(
            model_path, revision=EMBED_REVISION, cache_folder=str(MODEL_CACHE), device=device,
            config_kwargs={"audio_config": None, **({'vision_config': None} if TEXT_ONLY else {})},
            model_kwargs={"torch_dtype": dtype})
        self.model.max_seq_length = 8192
        self.tokenizer = self.model.tokenizer.backend_tokenizer

    def encode(self, inputs, *, prompt_name=None, batch_size=8):
        global _encoding, _waiting_queries
        priority = prompt_name == 'SearchQuery'
        # Yield between small batches so a question can overtake background work.
        output = []
        for start in range(0, len(inputs), batch_size):
            batch = inputs[start:start + batch_size]
            with _inference:
                if priority:
                    _waiting_queries += 1
                try:
                    while _encoding or (not priority and _waiting_queries):
                        _inference.wait()
                    _encoding = True
                finally:
                    if priority:
                        _waiting_queries -= 1
            try:
                values = self.model.encode(batch, prompt_name=prompt_name, batch_size=batch_size,
                                       normalize_embeddings=True, convert_to_numpy=True,
                                       show_progress_bar=False,
                                       **({'processing_kwargs': {'image': {'max_soft_tokens': IMAGE_SOFT_TOKENS}}}
                                          if any(isinstance(item, dict) for item in batch) else {}))
                output.extend(values)
            finally:
                with _inference:
                    _encoding = False
                    _inference.notify_all()
        values = np.asarray(output, dtype=np.float32).reshape(-1, EMBED_DIM)
        if (len(values) != len(inputs) or not np.isfinite(values).all()
                or not np.allclose(np.linalg.norm(values, axis=1), 1, atol=.001)):
            raise ValueError("EmbeddingGemma returned invalid embeddings. Use float32 or bfloat16 inference.")
        return values

    def embed(self, inputs, batch_size=8):
        from ..ingestion.media import open_image

        # Text is batched separately; images stay bounded to one decoded asset at a time.
        output = [None] * len(inputs)
        text_positions = [i for i, item in enumerate(inputs) if isinstance(item, str)]
        if text_positions:
            values = self.encode([inputs[i] for i in text_positions], prompt_name="Document", batch_size=batch_size)
            for i, value in zip(text_positions, values):
                output[i] = value
        for i, item in enumerate(inputs):
            if isinstance(item, dict):
                with open_image(item) as picture:
                    output[i] = self.encode([{"image": picture}], batch_size=1)[0]
        return output

    def query_embed(self, query):
        return self.encode([query], prompt_name="SearchQuery", batch_size=1)


def embedding_model():
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            _model = GemmaEmbedding()
        return _model


def table():
    path = str(DATA / "vectors")
    with _table_lock:
        if path not in _tables:
            connection = lancedb.connect(path)
            schema = pa.schema([pa.field("id", pa.string()), pa.field("source_id", pa.string()),
                                pa.field("notebook_id", pa.string()),
                                pa.field("vector", pa.list_(pa.float32(), EMBED_DIM))])
            _tables[path] = connection.create_table("embeddinggemma2_v1", schema=schema, exist_ok=True)
        return _tables[path]


def insert(chunks: list[dict]) -> None:
    import json
    from .embedding_cache import embed_cached

    inputs = [json.loads(row["image"]) if row.get("image") else row["text"] for row in chunks]
    embeddings = embed_cached(DATA, inputs, model_factory=embedding_model)
    values = [{"id": row["id"], "source_id": row["source_id"], "notebook_id": row["notebook_id"],
               "vector": vector.tolist()} for row, vector in zip(chunks, embeddings)]
    if values:
        table().merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(values)


@lru_cache(maxsize=128)
def query_vector(query: str) -> tuple:
    return tuple(next(iter(embedding_model().query_embed(query))).tolist())


def remove(source_id: str) -> None:
    if not source_id.isalnum():
        raise ValueError("Invalid source identifier")
    with _table_lock:
        table().delete(f"source_id = '{source_id}'")


def search(query: str, notebook_id: str, source_ids: list[str], limit=40) -> list[dict]:
    if not source_ids:
        return []
    if not all(identifier.isalnum() for identifier in [notebook_id, *source_ids]):
        raise ValueError("Invalid search scope")
    scope = ",".join(f"'{identifier}'" for identifier in source_ids)
    result = table().search(list(query_vector(query))).distance_type("cosine").where(
        f"notebook_id = '{notebook_id}' AND source_id IN ({scope})", prefilter=True
    ).limit(limit).select(["id", "_distance"]).to_list()
    return [{"id": row["id"], "semantic_score": 1 - float(row["_distance"])} for row in result]
