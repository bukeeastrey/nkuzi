"""FastAPI app: routes, CORS, and loading the local models at startup."""
import asyncio
import logging
from contextlib import asynccontextmanager

import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import config, coverage, llm, outline, pdf, slides as slide_files, store, transcribe
from .models import Health, OutlineUpdate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # don't log every Ollama ping
log = logging.getLogger("nkuzi")

# Models that failed to load: {"whisper": "why", ...}. Empty when all is well.
load_errors: dict[str, str] = {}


async def _load(name: str, loader):
    """Load one model in a worker thread so the server stays responsive."""
    try:
        await asyncio.to_thread(loader)
        load_errors.pop(name, None)
    except Exception as e:
        log.exception("Could not load %s", name)
        load_errors[name] = str(e)


async def _load_models():
    # One after the other: two downloads at once is rough on slow data.
    await _load("whisper", transcribe.load_model)
    await _load("embedder", coverage.load_embedder)

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


FIRST_RUN_FIX = "If this is the first run, connect to the internet once so it can download, then restart the backend."


@app.get("/api/health", response_model=Health)
async def health():
    ollama = await llm.is_ready()

    # Everything that is broken right now, each with what to do about it.
    # The UI shows these as banners, and shows nothing when the list is empty.
    problems = []
    if not ollama["ok"]:
        problems.append({
            "title": "Ollama isn't running.",
            "fix": "Open the Ollama app. Until then you get a simpler outline and \"Check me\" is off.",
        })
    elif not ollama["model_present"]:
        problems.append({
            "title": f"The Gemma model ({config.OLLAMA_MODEL}) isn't downloaded yet.",
            "fix": f"Run this in a terminal: ollama pull {config.OLLAMA_MODEL}",
        })
    if "whisper" in load_errors:
        problems.append({"title": "The speech model couldn't load.", "fix": FIRST_RUN_FIX})
    if "embedder" in load_errors:
        problems.append({"title": "The embeddings model couldn't load.", "fix": FIRST_RUN_FIX})

    return Health(
        app_name=config.APP_NAME,
        model_name=config.OLLAMA_MODEL,
        ollama_ok=ollama["ok"],
        model_present=ollama["model_present"],
        whisper_loaded=transcribe.is_loaded(),
        embedder_loaded=coverage.is_loaded(),
        problems=problems,
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
    # The form field is still called "pdf", but .pptx and .docx are welcome too.
    upload: UploadFile = File(..., alias="pdf"),
    title: str = Form(""),
    explainer: str = Form(""),
):
    data = await upload.read()
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"That file is larger than {config.MAX_UPLOAD_MB} MB. Export a smaller copy and try again.")
    try:
        slides, unit = await asyncio.to_thread(slide_files.extract, upload.filename, data)
    except pdf.SlidesError as e:
        raise HTTPException(400, str(e))

    # No topic typed? Use the deck's title slide, or else the file name.
    title = title.strip() or outline.find_topic(slides) or Path(upload.filename or "Untitled").stem
    session = store.new_session(title, explainer.strip(), slides, pdf.build_vocab(slides), unit)

    # Instant outline from the slide text; Gemma improves it in the background.
    session["outline"]["points"] = outline.fallback_outline(slides)
    store.save(session)
    outline.start_generation(session)

    warning = ""
    if len(slides) > config.LARGE_DECK_SLIDES:
        warning = (
            f"This is a big file ({len(slides)} {unit.lower()}s). The outline is capped at "
            f"{config.MAX_OUTLINE_POINTS} points and Gemma will take a while."
        )
    return {"session_id": session["id"], "warning": warning}


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


# ---------- live session: audio in, text out (the fast path, no Gemma) ----------

# One chunk at a time for the whole app: this CPU has two cores, and two
# Whisper runs side by side would both be slower than real time.
_audio_lock = asyncio.Lock()
MAX_CHUNK_BYTES = 2 * 1024 * 1024  # 8 s of audio is 256 KB; anything huge is a mistake


@app.post("/api/sessions/{session_id}/start")
async def start_session(session_id: str):
    session = _get_session(session_id)
    if not session["started_at"]:
        session["started_at"] = datetime.now().isoformat(timespec="seconds")
        store.save(session)
    return {"started_at": session["started_at"]}


@app.post("/api/sessions/{session_id}/audio")
async def post_audio(session_id: str, request: Request, seq: int = 0):
    """Body: raw 16 kHz mono Int16 PCM. Returns the text heard in this chunk."""
    session = _get_session(session_id)
    pcm = await request.body()
    if len(pcm) > MAX_CHUNK_BYTES:
        raise HTTPException(400, "That audio chunk is too large.")
    audio_seconds = len(pcm) / 2 / transcribe.SAMPLE_RATE

    async with _audio_lock:
        if not session["started_at"]:
            session["started_at"] = datetime.now().isoformat(timespec="seconds")
        transcript = session["transcript"]
        previous = transcript[-1]["text"] if transcript else ""

        started = time.perf_counter()
        # Whisper blocks, so it runs in a worker thread and the server stays responsive.
        text = await asyncio.to_thread(transcribe.transcribe_chunk, pcm, session["vocab"], previous)
        whisper_seconds = time.perf_counter() - started

        at = session.get("audio_seconds", 0.0)  # where this chunk starts in the session
        session["audio_seconds"] = round(at + audio_seconds, 2)
        if text:
            transcript.append({"seq": seq, "at": round(at, 1), "text": text})
        store.save(session)

    # Per-chunk timing: Whisper must stay faster than the chunk is long.
    log.info("chunk %d: %.1f s of audio -> Whisper %.1f s | %r", seq, audio_seconds, whisper_seconds, text[:80])
    return {
        "seq": seq,
        "text": text,
        "at": round(at, 1),
        "whisper_seconds": round(whisper_seconds, 2),
        "audio_seconds": session["audio_seconds"],
    }
