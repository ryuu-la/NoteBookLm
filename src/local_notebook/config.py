import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def load_environment(path: Path = ROOT / ".env") -> None:
    # The project file is authoritative, including a deliberately blank key.
    # An inherited credential from an old setup must not shadow this file.
    load_dotenv(path, override=True)


load_environment()
GEMINI_MODELS = ("gemini-3.5-flash-lite", "gemini-3.8-flash")
RUNINFRA_MODELS = {
    'glm-5-3-flash': 'GLM 5.3 Flash',
    'Qwen/Qwen3.8-27B': 'Qwen 3.8 27B',
    'deepseek-ai/DeepSeek-V4.1-Flash': 'DeepSeek V4.1 Flash',
}


def gemini_models() -> dict[str, str]:
    models = {"fast_model": os.getenv("GEMINI_FAST_MODEL", GEMINI_MODELS[0]).strip(),
              "model": os.getenv("GEMINI_MAIN_MODEL", GEMINI_MODELS[1]).strip()}
    if any(value not in GEMINI_MODELS for value in models.values()):
        raise ValueError("Set GEMINI_FAST_MODEL / GEMINI_MAIN_MODEL in .env to " + " or ".join(GEMINI_MODELS) + ".")
    return models


DATA = Path(os.environ.get("NOTEBOOK_DATA_DIR", ROOT / ".data")).resolve()
STYLES = Path(__file__).parent / "ui" / "styles"
EMBED_MODEL = "google/embeddinggemma-2"
EMBED_REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"
EMBED_DIM = 768
IMAGE_SOFT_TOKENS = 280  # The checkpoint's native image budget.
TEXT_ONLY = True
INDEX_VERSION = 4
MODEL_CACHE = Path(os.environ.get("NOTEBOOK_MODEL_DIR", DATA / "models"))
EMBED_THREADS = max(1, min(8, int(os.environ.get("NOTEBOOK_EMBED_THREADS", min(6, max(1, (os.cpu_count() or 2) // 2))))))
MAX_UPLOAD = 150 * 1024 * 1024


def prepare() -> None:
    for directory in (DATA, DATA / "originals", DATA / "vectors", DATA / "models", DATA / "exports"):
        directory.mkdir(parents=True, exist_ok=True)
