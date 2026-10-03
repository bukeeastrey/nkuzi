"""FastAPI app: routes, CORS, and loading the local models at startup."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config, coverage, llm, transcribe
from .models import Health

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # don't log every Ollama ping
log = logging.getLogger("nkuzi")

# What the health strip shows while a model is loading, or if loading failed.
load_messages = {
    "whisper": "Loading speech model… (the first run downloads about 75 MB)",
    "embedder": "Loading embeddings… (the first run downloads about 130 MB)",
}


async def _load(name: str, loader, ready_message: str):
    """Load one model in a worker thread so the server stays responsive."""
    try:
        await asyncio.to_thread(loader)
        load_messages[name] = ready_message
    except Exception as e:
        log.exception("Could not load %s", name)
        load_messages[name] = (
            f"Could not load: {e}. If this is the first run, connect to the "
            "internet once so the model can download, then restart the backend."
        )


async def _load_models():
    # One after the other: two downloads at once is rough on slow data.
    await _load("whisper", transcribe.load_model, f"Whisper {config.WHISPER_MODEL} is ready.")
    await _load("embedder", coverage.load_embedder, f"{config.EMBED_MODEL} is ready.")

    status = await llm.is_ready()
    log.info("Ollama: %s", status["message"])
    if not status["model_present"]:
        log.warning("%s still works without Gemma: fallback outline, 'Check me' disabled.", config.APP_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Start loading in the background; /health reports progress meanwhile.
    task = asyncio.create_task(_load_models())
    yield
    task.cancel()


app = FastAPI(title=config.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=Health)
async def health():
    ollama = await llm.is_ready()
    return Health(
        app_name=config.APP_NAME,
        model_name=config.OLLAMA_MODEL,
        ollama_ok=ollama["ok"],
        model_present=ollama["model_present"],
        ollama_message=ollama["message"],
        whisper_loaded=transcribe.is_loaded(),
        whisper_message=load_messages["whisper"],
        embedder_loaded=coverage.is_loaded(),
        embedder_message=load_messages["embedder"],
    )
