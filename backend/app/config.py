"""All settings live here. Every one can be overridden by an environment
variable of the same name, e.g. in PowerShell:

    $env:WHISPER_MODEL = "base.en"; .\\run.ps1
"""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent  # .../nkuzi/backend


def _env(name: str, default):
    """Read an env var and convert it to the same type as the default."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    if isinstance(default, Path):
        return Path(raw)
    return type(default)(raw)  # int("4096"), float("0.62"), str(...)


# The app name lives here (backend) and in frontend/src/config.js. Nowhere else.
APP_NAME = _env("APP_NAME", "Nkuzi")

# --- Gemma via Ollama ---
OLLAMA_URL = _env("OLLAMA_URL", "http://localhost:11434")
# Gemma 3 1B: small enough to sit comfortably in 8 GB RAM next to Whisper.
# Larger options if RAM allows: "gemma4:e2b-it-qat" or "gemma4:e2b".
OLLAMA_MODEL = _env("OLLAMA_MODEL", "gemma3:1b")
OLLAMA_NUM_CTX = _env("OLLAMA_NUM_CTX", 4096)  # never above 8192 on this laptop
OLLAMA_KEEP_ALIVE = _env("OLLAMA_KEEP_ALIVE", "10m")
OLLAMA_TIMEOUT_S = _env("OLLAMA_TIMEOUT_S", 300)  # CPU is slow; be generous

# --- Speech to text (faster-whisper, CPU only) ---
WHISPER_MODEL = _env("WHISPER_MODEL", "tiny.en")  # or "base.en"
WHISPER_THREADS = _env("WHISPER_THREADS", 4)

# --- Embeddings (fastembed, ONNX, CPU only) ---
EMBED_MODEL = _env("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

# --- Live session tuning ---
CHUNK_SECONDS = _env("CHUNK_SECONDS", 8)  # must match frontend/src/config.js
COVER_THRESHOLD = _env("COVER_THRESHOLD", 0.62)
COVER_KEYWORD_BONUS = _env("COVER_KEYWORD_BONUS", 0.08)
MAX_OUTLINE_POINTS = _env("MAX_OUTLINE_POINTS", 25)
CHECK_WINDOW_SECONDS = _env("CHECK_WINDOW_SECONDS", 90)

# --- Folders ---
DATA_DIR = _env("DATA_DIR", BACKEND_DIR / "data" / "sessions")
# Downloaded Whisper + embedding models are kept here so they survive reboots
# and the app works offline after the first run.
MODEL_CACHE_DIR = _env("MODEL_CACHE_DIR", BACKEND_DIR / "model_cache")

FRONTEND_ORIGIN = _env("FRONTEND_ORIGIN", "http://localhost:5173")
