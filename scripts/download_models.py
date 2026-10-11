from local_notebook.config import prepare
from local_notebook.retrieval.vectors import embedding_model

prepare()
model = embedding_model()
print("Embedding dimensions:", len(model.embed(["Local Notebook model check"])[0]))
print("EmbeddingGemma 2 ready for local text retrieval (vision and audio disabled).")
