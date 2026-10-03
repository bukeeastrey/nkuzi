"""Slides -> outline of key points.

Two ways to build it:
  1. Fallback (instant, no AI): slide titles + the first bullet lines.
  2. Gemma (slow, runs in the background): proper key points per slide.

The fallback is shown straight away and replaced when Gemma finishes, so the
app works even if Ollama is off.
"""
import asyncio
import logging
import time

import numpy as np

from . import config, coverage, llm, prompts, store
from .pdf import WORD_RE, STOPWORDS, is_distinctive

log = logging.getLogger("nkuzi.outline")

_tasks: dict[str, asyncio.Task] = {}  # running Gemma jobs, by session id

THIN_SLIDE_WORDS = 12  # fewer body words than this = title slide; it only gets a title point
MAX_POINT_CHARS = 200


# ---------- small helpers ----------

def point_keywords(text: str, limit: int = 4) -> list[str]:
    """2-4 key terms from a point, used later to help tick it off."""
    words = []
    for word in WORD_RE.findall(text):
        if len(word) >= 4 and word.lower() not in STOPWORDS and word.lower() not in [w.lower() for w in words]:
            words.append(word)
    # Distinctive terms (drug names, acronyms) first, then the longest words.
    words.sort(key=lambda w: (not is_distinctive(w, first_in_line=True), -len(w)))
    return words[:limit]


def make_point(text: str, slide: int | None) -> dict:
    text = " ".join(text.split())[:MAX_POINT_CHARS]
    return {"id": "", "text": text, "slide": slide, "keywords": point_keywords(text)}


def number_points(points: list[dict]) -> list[dict]:
    """Give every point an id: p1, p2, ..."""
    for i, point in enumerate(points, start=1):
        point["id"] = f"p{i}"
    return points


def cap_points(points: list[dict], limit: int) -> list[dict]:
    """Keep at most `limit` points, spread fairly across slides, in slide order.

    Every slide keeps its 1st point before any slide keeps its 2nd, and so on.
    """
    if len(points) <= limit:
        return points
    seen_on_slide = {}
    ranked = []  # (rank within its slide, position in the list)
    for position, point in enumerate(points):
        rank = seen_on_slide.get(point["slide"], 0)
        seen_on_slide[point["slide"]] = rank + 1
        ranked.append((rank, position))

    keep = []
    for rank in sorted({r for r, _ in ranked}):
        group = [pos for r, pos in ranked if r == rank]
        room = limit - len(keep)
        if len(group) <= room:
            keep += group
        else:
            # Not enough room for this whole round: take evenly spaced ones.
            keep += [group[int(i * len(group) / room)] for i in range(room)]
            break
    return [points[pos] for pos in sorted(keep)]


def _body_lines(slide: dict) -> list[str]:
    return slide["text"].split("\n")[1:]  # line 0 is the title


# ---------- 1. fallback outline (no AI) ----------

def _slide_fallback(slide: dict) -> list[dict]:
    """Title + up to 2 top bullet lines of one slide."""
    points = [make_point(slide["title"], slide["index"])]
    if _is_thin(slide):
        return points
    bullets = [line for line in _body_lines(slide) if len(line.split()) >= 3]
    points += [make_point(line, slide["index"]) for line in bullets[:2]]
    return points


def fallback_outline(slides: list[dict]) -> list[dict]:
    points = [p for slide in slides for p in _slide_fallback(slide)]
    return number_points(cap_points(points, config.MAX_OUTLINE_POINTS))


# ---------- 2. Gemma outline (background) ----------

def _is_thin(slide: dict) -> bool:
    """Title slides and the like: too little text to be worth a Gemma call."""
    return len(" ".join(_body_lines(slide)).split()) < THIN_SLIDE_WORDS


def _content_words(text: str) -> list[str]:
    """The words that carry meaning: 4+ letters, plus acronyms like "MI" and "AV"."""
    words = WORD_RE.findall(text)
    return [w.lower() for w in words if (len(w) >= 4 or w.isupper()) and w.lower() not in STOPWORDS]


def _same_word(a: str, b: str) -> bool:
    """True for the same word in another form: "lowers" / "lowering", "stop" / "stopping"."""
    return a == b or a.startswith(b[:5]) or b.startswith(a[:5])


def _ground(text: str, slide: dict) -> tuple[int | None, bool]:
    """Which slide line does this point come from, and is it faithful to it?

    A small model sometimes glues two lines into a false statement
    ("Bradycardia is contraindicated in asthma"), or drops the word that
    mattered. So a point is only trusted if:
      1. EVERY content word in it comes from one single line of the slide, and
      2. it keeps every key term (drug names, acronyms, long words) of that line.
    Returns (line number or None, trusted?).
    """
    words = _content_words(text)
    if not words:
        return None, False
    title_words = _content_words(slide["title"])
    lines = _body_lines(slide)
    best_line, best_share = None, 0.0
    for number, line in enumerate(lines):
        line_words = _content_words(line)
        if not any(_same_word(w, lw) for w in words for lw in line_words):
            continue  # nothing in common with this line
        # Words from the slide title are fine too.
        allowed = line_words + title_words
        share = sum(any(_same_word(w, aw) for aw in allowed) for w in words) / len(words)
        if share > best_share:
            best_line, best_share = number, share
    if best_line is None or best_share < 1.0:
        return best_line, False
    key_terms = [w.lower() for w in WORD_RE.findall(lines[best_line]) if is_distinctive(w, first_in_line=True)]
    kept_all = all(any(_same_word(term, w) for w in words) for term in key_terms)
    return best_line, kept_all


async def _ask_gemma(slide: dict) -> list[str]:
    """One Gemma call for one slide. Returns its key points (verified in code)."""
    lines = _body_lines(slide)
    count = min(config.OUTLINE_POINTS_PER_SLIDE, len(lines))
    # Nothing to choose and nothing to shorten: the slide's own lines are the points.
    if len(lines) <= count and all(len(line.split()) <= 15 for line in lines):
        return lines

    body = "\n".join(lines)
    words = body.split(" ")
    if len(words) > config.OUTLINE_SLIDE_WORDS:  # keep the prompt inside num_ctx
        body = " ".join(words[: config.OUTLINE_SLIDE_WORDS])
    prompt = prompts.OUTLINE_PROMPT.format(title=slide["title"], body=body, count=count)
    # A JSON schema makes Ollama return exactly `count` strings.
    schema = {
        "type": "object",
        "properties": {
            "points": {"type": "array", "items": {"type": "string"}, "minItems": count, "maxItems": count}
        },
        "required": ["points"],
    }
    data = await llm.generate_json(prompt, prompts.OUTLINE_SYSTEM, max_tokens=60 * count, schema=schema)

    points, used_lines = [], set()
    items = data.get("points")
    for text in items if isinstance(items, list) else []:
        if not isinstance(text, str):
            continue
        line_number, trusted = _ground(text, slide)
        if line_number is None or line_number in used_lines:
            continue  # not from this slide, or the same line twice
        used_lines.add(line_number)
        if trusted:
            points.append((line_number, text.strip()))
        else:
            # Gemma chose this line but changed its meaning: use the slide's own words.
            log.info("Slide %d: kept the slide's wording instead of %r", slide["index"], text)
            points.append((line_number, lines[line_number]))
    return [text for _, text in sorted(points)]  # back in slide order


def _dedupe(points: list[dict]) -> list[dict]:
    """Drop points that say nearly the same thing as an earlier point."""
    if len(points) < 2:
        return points
    vectors = coverage.embed([p["text"] for p in points])
    keep = []  # positions we keep
    for i in range(len(points)):
        if not keep or float(np.max(vectors[keep] @ vectors[i])) <= config.OUTLINE_DEDUPE_SIM:
            keep.append(i)
    return [points[i] for i in keep]


def _finish(session: dict, status: str, message: str = ""):
    session["outline"].update(status=status, message=message)
    store.save(session)


async def _generate(session: dict):
    outline = session["outline"]
    slides = session["slides"]
    started = time.perf_counter()

    ready = await llm.is_ready()
    if not ready["model_present"]:
        _finish(session, "fallback_only", ready["message"])
        return

    todo = [slide for slide in slides if not _is_thin(slide)]
    outline["progress"] = {"done": 0, "total": len(todo)}
    store.save(session)

    from_gemma: dict[int, list[str]] = {}
    problem = ""
    for slide in todo:
        try:
            texts = await _ask_gemma(slide)
            if texts:
                from_gemma[slide["index"]] = texts
        except llm.LLMError as e:
            problem = str(e)
            log.warning("Outline failed for slide %d: %s", slide["index"], e)
            if not (await llm.is_ready())["model_present"]:
                break  # Ollama went away; no point trying the rest
        outline["progress"]["done"] += 1
        store.save(session)

    if not from_gemma:
        _finish(session, "fallback_only", problem or "Gemma found no points. Using the outline built from your slides.")
        return

    # Slides Gemma gave nothing for keep their fallback points.
    points = []
    for slide in slides:
        if slide["index"] in from_gemma:
            points += [make_point(text, slide["index"]) for text in from_gemma[slide["index"]]]
        else:
            points += _slide_fallback(slide)

    points = await asyncio.to_thread(_dedupe, points)
    outline["points"] = number_points(cap_points(points, config.MAX_OUTLINE_POINTS))
    outline["source"] = "gemma"
    _finish(session, "ready")
    log.info(
        "Gemma outline: %d points from %d slides in %.0f s",
        len(outline["points"]), len(slides), time.perf_counter() - started,
    )
    await asyncio.to_thread(coverage.cache_point_embeddings, session)


async def _run(session: dict):
    try:
        await _generate(session)
    except asyncio.CancelledError:
        raise  # the user took over the outline; whoever cancelled sets the status
    except Exception:
        log.exception("Outline generation crashed")
        _finish(session, "fallback_only", "Gemma hit a problem. Using the outline built from your slides.")
    finally:
        _tasks.pop(session["id"], None)


def start_generation(session: dict):
    """Kick off the Gemma outline in the background and return immediately."""
    _tasks[session["id"]] = asyncio.create_task(_run(session))


def is_running(session_id: str) -> bool:
    return session_id in _tasks


def cancel(session_id: str):
    task = _tasks.pop(session_id, None)
    if task:
        task.cancel()


# ---------- user edits ----------

def clean_user_points(raw_points: list[dict], session: dict) -> list[dict]:
    """Tidy an outline edited in the UI: drop blanks, fix slide numbers and ids."""
    slide_numbers = {slide["index"] for slide in session["slides"]}
    points, used_ids = [], set()
    for raw in raw_points:
        if not raw["text"].strip():
            continue
        point = make_point(raw["text"], raw["slide"] if raw["slide"] in slide_numbers else None)
        # Keep existing ids so ticks stay attached to the same point.
        if raw.get("id") and raw["id"] not in used_ids:
            point["id"] = raw["id"]
            used_ids.add(raw["id"])
        points.append(point)

    next_number = 1
    for point in points:  # new points get the next free id
        if not point["id"]:
            while f"p{next_number}" in used_ids:
                next_number += 1
            point["id"] = f"p{next_number}"
            used_ids.add(point["id"])
    return points
