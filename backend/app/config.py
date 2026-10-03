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
# Gemma 4 E2B (QAT build): the smallest Gemma 4. On this laptop it judged
# contradictions correctly 4 times out of 4, where gemma3:1b could not.
# It needs about 3.6 GB of RAM, so close other apps before a session.
# Fallback if RAM is too tight: "gemma3:1b" (0.8 GB; outline only, "Check me" unreliable).
OLLAMA_MODEL = _env("OLLAMA_MODEL", "gemma4:e2b-it-qat")
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
MAX_OUTLINE_POINTS = _env("MAX_OUTLINE_POINTS", 40)
CHECK_WINDOW_SECONDS = _env("CHECK_WINDOW_SECONDS", 90)

# --- Outline building (Gemma, slow path) ---
# Gemma reads one slide per call, which keeps the prompt tiny for gemma3:1b.
OUTLINE_SLIDE_WORDS = _env("OUTLINE_SLIDE_WORDS", 400)  # longer slides are cut to this
OUTLINE_NOTES_WORDS = _env("OUTLINE_NOTES_WORDS", 120)  # speaker notes are cut to this
OUTLINE_POINTS_PER_SLIDE = _env("OUTLINE_POINTS_PER_SLIDE", 3)
OUTLINE_DEDUPE_SIM = _env("OUTLINE_DEDUPE_SIM", 0.9)  # above this, two points are "the same"

# --- Uploads ---
MAX_UPLOAD_MB = _env("MAX_UPLOAD_MB", 50)
LARGE_DECK_SLIDES = _env("LARGE_DECK_SLIDES", 60)  # warn above this many slides

CHECK_WINDOW_SECONDS = _env("CHECK_WINDOW_SECONDS", 90)

# --- Folders ---
DATA_DIR = _env("DATA_DIR", BACKEND_DIR / "data" / "sessions")
# Downloaded Whisper + embedding models are kept here so they survive reboots
# and the app works offline after the first run.
MODEL_CACHE_DIR = _env("MODEL_CACHE_DIR", BACKEND_DIR / "model_cache")

FRONTEND_ORIGIN = _env("FRONTEND_ORIGIN", "http://localhost:5173")
