""""Check me": compare what the explainer just said with the slides.

This is the slow path (Gemma), so it only runs when asked, as a background
job. The rule that matters most: NEVER show a correction that isn't grounded
in the slides. Gemma proposes issues; code keeps only those whose slide quote
really is on the slide and whose "said" really is in the transcript.
"""
import asyncio
import logging
import time
import uuid

import numpy as np
from rapidfuzz import fuzz

from . import config, coverage, llm, outline, prompts, store

log = logging.getLogger("nkuzi.check")

TOP_SLIDES = 3  # how many slides Gemma is shown
MAX_ISSUES = 3  # per check
QUOTE_MATCH = 85  # 0-100: how exactly the quote must appear on the slide
SAID_MATCH = 70  # 0-100: how closely "said" must match the transcript
SAME_TEXT = 90  # said and quote this alike = agreement, not a contradiction
CONTEXT_WORDS = 4  # words shown around the matched speech in "What Nkuzi heard"
SLIDE_WORDS = 150  # each slide is cut to this many words in the prompt
NO_ISSUES_MESSAGE = "No contradictions with your slides found."

# Set while no check is running. Audio chunks wait for it (see wait_until_idle).
_idle = asyncio.Event()
_idle.set()

_jobs: dict[str, dict] = {}  # job id -> {session_id, status, issues, message}
_running: dict[str, str] = {}  # session id -> job id of the check in progress
_slide_vectors: dict[str, tuple[list[dict], np.ndarray]] = {}  # session id -> (slides, embeddings)


def recent_speech(session: dict) -> list[dict]:
    """Transcript lines from the last CHECK_WINDOW_SECONDS of listening."""
    cutoff = session.get("audio_seconds", 0.0) - config.CHECK_WINDOW_SECONDS
    return [line for line in session["transcript"] if line["at"] >= cutoff]


def _relevant_slides(session: dict, text: str) -> list[dict]:
    """The slides most similar to what was said (embeddings, no Gemma)."""
    if session["id"] not in _slide_vectors:
        slides = outline.content_slides(session["slides"]) or session["slides"]
        _slide_vectors[session["id"]] = (slides, coverage.embed([s["text"] for s in slides]))
    slides, vectors = _slide_vectors[session["id"]]
    scores = vectors @ coverage.embed([text])[0]
    best = np.argsort(-scores)[:TOP_SLIDES]
    return [slides[i] for i in sorted(best)]  # back in slide order


def _heard_span(said: str, window: str) -> tuple[str, float]:
    """The stretch of the transcript that matches Gemma's "said", in the
    transcript's own words, with a few words of context on each side.
    Returns (text, match score 0-100)."""
    match = fuzz.partial_ratio_alignment(said.lower(), window.lower())
    if match is None:
        return "", 0.0
    # Widen to whole words, plus a little context so it reads naturally.
    before = window[: match.dest_start].split(" ")
    after = window[match.dest_end :].split(" ")
    middle = window[match.dest_start : match.dest_end]
    text = " ".join(before[-(CONTEXT_WORDS + 1) :]) + middle + " ".join(after[: CONTEXT_WORDS + 1])
    return text.strip(), match.score


def verify_issue(raw: dict, slides: list[dict], window: str) -> dict | None:
    """Keep an issue only if it is grounded. Returns the cleaned issue, or None.

    1. slide_quote must really be on one of the slides Gemma saw.
    2. said must really be something in the transcript.
    3. said and the quote must not be the same statement.
    """
    said = str(raw.get("said", "")).strip()
    quote = str(raw.get("slide_quote", "")).strip()
    fix = str(raw.get("fix", "")).strip()
    if len(said.split()) < 2 or len(quote.split()) < 2:
        return None

    # 1. Find the quote. Prefer the slide Gemma named; accept another shown slide.
    ordered = sorted(slides, key=lambda s: s["index"] != raw.get("slide"))
    home = next((s for s in ordered if fuzz.partial_ratio(quote.lower(), s["text"].lower()) >= QUOTE_MATCH), None)
    if home is None:
        log.info("Dropped issue: quote %r is not on the slides", quote)
        return None

    # 2. Find what was actually heard.
    heard, score = _heard_span(said, window)
    if score < SAID_MATCH:
        log.info("Dropped issue: %r was not said", said)
        return None

    # 3. Same statement on both sides is agreement.
    if fuzz.token_set_ratio(said.lower(), quote.lower()) >= SAME_TEXT:
        log.info("Dropped issue: %r agrees with the slide", said)
        return None

    return {
        "id": uuid.uuid4().hex[:8],
        "said": said,  # Gemma's short version of the claim
        "heard": heard or said,  # the transcript's own words, shown as "What Nkuzi heard"
        "slide": home["index"],
        "slide_quote": quote,
        "fix": fix,
        "dismissed": False,  # set when the explainer says "That's not what I said"
    }


async def _confirm(issue: dict, slide: dict) -> bool:
    """Second opinion on one issue: a small yes/no question, which Gemma answers
    far more reliably than the open "find contradictions" question."""
    schema = {
        "type": "object",
        "properties": {"contradicts": {"type": "boolean"}},
        "required": ["contradicts"],
    }
    # We ask about Gemma's short version of the claim (already checked to be in
    # the transcript). The raw transcript often runs several sentences together.
    prompt = prompts.CONFIRM_PROMPT.format(quote=issue["slide_quote"], title=slide["title"], said=issue["said"])
    answer = await llm.generate_json(prompt, prompts.CHECK_SYSTEM, max_tokens=20, schema=schema)
    return answer.get("contradicts") is True


async def run_check(session: dict) -> dict:
    """One "Check me". Returns {issues, message}. New issues are stored on the session."""
    started = time.perf_counter()
    lines = recent_speech(session)
    # Whisper ends a chunk that stops mid-sentence with "..."; drop those when joining.
    window = " ".join(line["text"].rstrip(". ") if line["text"].endswith("...") else line["text"] for line in lines)
    if len(window.split()) < 5:
        return {"issues": [], "message": "Nothing to check yet. Explain a little first, then press Check me."}

    slides = await asyncio.to_thread(_relevant_slides, session, window)
    slides_text = "\n\n".join(
        f"[Slide {s['index']}] " + " ".join(s["text"].split(" ")[:SLIDE_WORDS]) for s in slides
    )
    schema = {
        "type": "object",
        "properties": {
            "issues": {
                "type": "array",
                "maxItems": MAX_ISSUES,
                "items": {
                    "type": "object",
                    "properties": {
                        "said": {"type": "string"},
                        "slide": {"type": "integer"},
                        "slide_quote": {"type": "string"},
                        "fix": {"type": "string"},
                    },
                    "required": ["said", "slide", "slide_quote", "fix"],
                },
            }
        },
        "required": ["issues"],
    }
    prompt = prompts.CHECK_PROMPT.format(slides=slides_text, said=window)
    data = await llm.generate_json(prompt, prompts.CHECK_SYSTEM, max_tokens=90 * MAX_ISSUES, schema=schema)

    proposed = data.get("issues")
    proposed = [raw for raw in proposed if isinstance(raw, dict)] if isinstance(proposed, list) else []
    by_number = {s["index"]: s for s in slides}
    known = {(i["slide"], i["heard"]) for i in session["issues"]}  # found by an earlier check

    issues = []
    for raw in proposed:
        issue = verify_issue(raw, slides, window)
        if issue is None or (issue["slide"], issue["heard"]) in known:
            continue
        if not await _confirm(issue, by_number[issue["slide"]]):
            log.info("Dropped issue: on a second look, %r does not contradict %r", issue["said"], issue["slide_quote"])
            continue
        issue["at"] = lines[-1]["at"]
        issues.append(issue)
        known.add((issue["slide"], issue["heard"]))

    session["issues"] += issues
    store.save(session)
    log.info(
        "Check me: %d s of speech against slides %s -> Gemma proposed %d, kept %d, in %.0f s",
        config.CHECK_WINDOW_SECONDS, [s["index"] for s in slides], len(proposed), len(issues),
        time.perf_counter() - started,
    )
    return {"issues": issues, "message": "" if issues else NO_ISSUES_MESSAGE}


# ---------- background jobs (the UI polls these) ----------

async def wait_until_idle():
    """Called before each audio chunk is transcribed.

    Measured on the i5-4310U: Whisper next to a generating Gemma takes 20-30 s
    per 8 s chunk, and slows Gemma down too. So while a check runs, chunks
    wait (the browser keeps recording and queues them) and are transcribed
    as soon as it finishes, at the usual 1-2 s each. Never waits longer than
    CHECK_HOLD_SECONDS.
    """
    if not config.CHECK_PAUSES_TRANSCRIPTION or _idle.is_set():
        return
    try:
        await asyncio.wait_for(_idle.wait(), timeout=config.CHECK_HOLD_SECONDS)
    except asyncio.TimeoutError:
        pass  # the check is taking very long: carry on and share the CPU


async def _run_job(job_id: str, session: dict):
    job = _jobs[job_id]
    _idle.clear()
    try:
        result = await run_check(session)
        job.update(status="done", **result)
    except llm.LLMError as e:
        log.warning("Check me failed: [%s] %s", e.reason, e)
        job.update(status="error", message=str(e))
    except Exception as e:
        log.exception("Check me stopped unexpectedly")
        job.update(status="error", message=f"Check me stopped unexpectedly ({type(e).__name__}: {e}).")
    finally:
        _running.pop(session["id"], None)
        if not _running:
            _idle.set()


def start_job(session: dict) -> str:
    """Start a check in the background and return its job id.
    If one is already running for this session, return that one instead."""
    if session["id"] in _running:
        return _running[session["id"]]
    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {"session_id": session["id"], "status": "running", "issues": [], "message": ""}
    _running[session["id"]] = job_id
    job = _jobs[job_id]
    job["task"] = asyncio.create_task(_run_job(job_id, session))  # keep a reference so it isn't garbage-collected
    return job_id


def get_job(session_id: str, job_id: str) -> dict | None:
    job = _jobs.get(job_id)
    if job is None or job["session_id"] != session_id:
        return None
    return {"status": job["status"], "issues": job["issues"], "message": job["message"]}


def dismiss(session: dict, issue_id: str) -> bool:
    """"That's not what I said": hide the issue and keep it out of the recap."""
    for issue in session["issues"]:
        if issue["id"] == issue_id:
            issue["dismissed"] = True
            return True
    return False
