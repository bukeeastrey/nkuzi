"""FastAPI app: routes, CORS, and loading the local models at startup."""
import asyncio
import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import config, coverage, llm, outline, pdf, store, transcribe
from .models import Health, OutlineUpdate

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


# ---------- sessions + outline ----------

def _get_session(session_id: str) -> dict:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, "That session doesn't exist any more.")
    return session


def _outline_response(session: dict) -> dict:
    o = session["outline"]
    return {
        "status": o["status"],
        "source": o["source"],
        "progress": o["progress"],
        "message": o["message"],
        "points": o["points"],
    }


@app.post("/api/sessions")
async def create_session(
    pdf_file: UploadFile = File(..., alias="pdf"),
    title: str = Form(""),
    explainer: str = Form(""),
):
    data = await pdf_file.read()
    if len(data) > config.MAX_PDF_MB * 1024 * 1024:
        raise HTTPException(400, f"That PDF is larger than {config.MAX_PDF_MB} MB. Export a smaller copy and try again.")
    try:
        slides = await asyncio.to_thread(pdf.extract_slides, data)
    except pdf.PdfError as e:
        raise HTTPException(400, str(e))

    # No title typed? Use the file name.
    title = title.strip() or Path(pdf_file.filename or "Untitled").stem
    session = store.new_session(title, explainer.strip(), slides, pdf.build_vocab(slides))

    # Instant outline from the slide text; Gemma improves it in the background.
    session["outline"]["points"] = outline.fallback_outline(slides)
    store.save(session)
    outline.start_generation(session)

    warning = ""
    if len(slides) > config.LARGE_DECK_SLIDES:
        warning = (
            f"This is a big deck ({len(slides)} slides). The outline is capped at "
            f"{config.MAX_OUTLINE_POINTS} points and Gemma will take a while."
        )
    return {
        "session_id": session["id"],
        "title": session["title"],
        "slides_count": len(slides),
        "outline": session["outline"]["points"],
        "outline_status": "generating",
        "warning": warning,
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    return _get_session(session_id)


@app.get("/api/sessions/{session_id}/outline")
async def get_outline(session_id: str):
    session = _get_session(session_id)
    o = session["outline"]
    # "generating" on disk but nothing running = the backend restarted mid-way.
    if o["status"] == "generating" and not outline.is_running(session_id):
        o.update(status="fallback_only", message="Gemma was interrupted. Using the outline built from your slides.")
        store.save(session)
    return _outline_response(session)


@app.put("/api/sessions/{session_id}/outline")
async def put_outline(session_id: str, update: OutlineUpdate):
    session = _get_session(session_id)
    points = outline.clean_user_points([p.model_dump() for p in update.points], session)
    if not points:
        raise HTTPException(400, "The outline needs at least one point.")
    # The explainer's version wins: stop Gemma if it is still working.
    outline.cancel(session_id)
    session["outline"].update(status="ready", source="edited", message="", points=points)
    store.save(session)
    await asyncio.to_thread(coverage.cache_point_embeddings, session)
    return _outline_response(session)
