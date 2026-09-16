from local_notebook.config import prepare
from local_notebook.retrieval.vectors import embedding_model, rerank

prepare()
model = embedding_model()
print("Embedding dimensions:", len(next(model.embed(["Local Notebook model check"]))))
print("Reranker check:", len(rerank("learning", [{"text": "Retrieval practice helps learning."}])))
