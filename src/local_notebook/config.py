import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("NOTEBOOK_DATA_DIR", ROOT / ".data")).resolve()
STYLES = Path(__file__).parent / "ui" / "styles"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
MODEL_CACHE = Path(os.environ.get("NOTEBOOK_MODEL_DIR", DATA / "models"))
MAX_UPLOAD = 150 * 1024 * 1024


def prepare() -> None:
    for directory in (DATA, DATA / "originals", DATA / "vectors", DATA / "models", DATA / "exports"):
        directory.mkdir(parents=True, exist_ok=True)
