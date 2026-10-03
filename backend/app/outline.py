"""Slides -> outline of key points.

Two ways to build it:
  1. Fallback (instant, no AI): the first lines of each content slide.
  2. Gemma (slow, runs in the background): Gemma picks the key lines per slide.

The fallback is shown straight away and replaced when Gemma finishes, so the
app works even if Ollama is off.

Both skip "structural" slides (Outline, References, Thank you...) and share
the points fairly across the whole deck, so the last slides are never cut off.
"""
import asyncio
import logging
import re
import time

import numpy as np

from . import config, coverage, llm, prompts, store
from .pdf import WORD_RE, STOPWORDS, is_distinctive, split_sentences

log = logging.getLogger("nkuzi.outline")

_tasks: dict[str, asyncio.Task] = {}  # running Gemma jobs, by session id

THIN_SLIDE_WORDS = 12  # fewer body words than this = nearly empty slide
SENTENCE_TITLE_WORDS = 8  # a "title" this long is really a sentence of content
LIST_SLIDE_WORDS_PER_LINE = 5  # lines this short on average = a list of terms
LONG_LINE_WORDS = 15  # slide lines longer than this are worth shortening
MAX_POINT_CHARS = 200
SUMMARY_CHARS = 140  # length limit of a "Title: item, item, item" point
STOP_AFTER_FAILURES = 3  # give up on Gemma after this many slides fail in a row

# Slides that organise the lecture but hold nothing to explain. Compared with
# the title after removing everything except letters ("Thank You!" -> "thankyou").
STRUCTURAL_TITLES = {
    "outline", "introduction", "objectives", "learningobjectives", "overview",
    "contents", "tableofcontents", "questions", "anyquestions", "thankyou", "thanks",
}
STRUCTURAL_STARTS = ("thankyou", "learningobjectives")
LEAD_IN_WORDS = {"involves", "involve", "include", "includes", "including", "following"}
REFERENCE_STARTS = ("reference", "bibliography")  # these run on to the end of the deck


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
    """Safety net: keep at most `limit` points, spread across slides, in slide order.

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
            # Not enough room for this whole round: take evenly spaced ones,
            # so the end of the deck is represented as well as the start.
            keep += [group[int(i * len(group) / room)] for i in range(room)]
            break
    return [points[pos] for pos in sorted(keep)]


def _slide_body(slide: dict) -> list[str]:
    return slide["text"].split("\n")[1:]  # line 0 is the title


def _word_count(lines: list[str]) -> int:
    return len(" ".join(lines).split())


def _has_sentence_title(slide: dict) -> bool:
    """Some slides have no real title; their first line is a sentence of content."""
    return len(slide["title"].split()) >= SENTENCE_TITLE_WORDS


def _lines(slide: dict) -> list[str]:
    """The lines an outline point may come from.

    Normally the slide's body lines. A sentence-like title counts as a line
    too. If the slide is nearly empty (e.g. a picture) but has speaker notes,
    the notes' sentences are added.
    """
    lines = _slide_body(slide)
    if _has_sentence_title(slide):
        lines = [slide["title"]] + lines
    notes = slide.get("notes", "")
    if notes and _word_count(lines) < THIN_SLIDE_WORDS:
        lines = lines + split_sentences(notes)
    return lines


# ---------- which slides are worth explaining ----------

def _title_key(slide: dict) -> str:
    return re.sub(r"[^a-z]", "", slide["title"].lower())


def is_structural(slide: dict) -> bool:
    key = _title_key(slide)
    return key in STRUCTURAL_TITLES or key.startswith(STRUCTURAL_STARTS)


def _is_title_slide(slide: dict) -> bool:
    """The opening slide: a short title with a name/date under it, or nothing."""
    return not _has_sentence_title(slide) and _word_count(_slide_body(slide)) < THIN_SLIDE_WORDS


def find_topic(slides: list[dict]) -> str | None:
    """The lecture's topic, taken from the title slide (if the deck has one)."""
    if slides and _is_title_slide(slides[0]):
        return slides[0]["title"]
    return None


def content_slides(slides: list[dict]) -> list[dict]:
    """The slides that get outline points. Skips the title slide, structural
    slides (Outline, Objectives, Thank you...), title-only slides, and
    everything from the References slide onwards."""
    result = []
    for position, slide in enumerate(slides):
        if _title_key(slide).startswith(REFERENCE_STARTS):
            break
        if is_structural(slide) or not _lines(slide):
            continue
        if position == 0 and _is_title_slide(slide):
            continue
        result.append(slide)
    return result


def _is_list_slide(slide: dict) -> bool:
    """A slide that is a list of short terms ("CXR", "Spirometry", "ABG")."""
    lines = _lines(slide)
    return _word_count(lines) / len(lines) <= LIST_SLIDE_WORDS_PER_LINE


def _summary_point(slide: dict) -> str:
    """One point for a list slide: "Investigations: CXR, Spirometry, ABG …"."""
    text = slide["title"].rstrip(": ") + ": "
    lines = _lines(slide)
    # Skip a lead-in such as "Pathogenesis involves:" that only repeats the title.
    title_words = set(_content_words(slide["title"])) | LEAD_IN_WORDS
    if len(lines) > 1 and lines[0].endswith(":") and set(_content_words(lines[0])) <= title_words:
        lines = lines[1:]
    items = [line.rstrip(":;,. ") for line in lines]
    for i, item in enumerate(items):
        addition = item if i == 0 else ", " + item
        if i > 0 and len(text) + len(addition) > SUMMARY_CHARS:
            return text + " …"
        text += addition
    return text


def _capacity(slide: dict) -> int:
    """The most points this slide can give."""
    if _is_list_slide(slide):
        return 1
    return min(config.OUTLINE_POINTS_PER_SLIDE, len(_lines(slide)))


def plan_budget(content: list[dict]) -> dict[int, int]:
    """How many points each content slide gets: {slide number: count}.

    Small deck: up to OUTLINE_POINTS_PER_SLIDE each. Big deck: about 1 each,
    so every slide (including treatment at the end) is represented. Any
    points left over go to the slides with the most text.
    """
    if not content:
        return {}
    limit = config.MAX_OUTLINE_POINTS
    base = max(1, min(config.OUTLINE_POINTS_PER_SLIDE, limit // len(content)))
    budget = {s["index"]: min(base, _capacity(s)) for s in content}

    spare = limit - sum(budget.values())
    by_richness = sorted(
        enumerate(content), key=lambda pair: (-_word_count(_lines(pair[1])), -pair[0])  # ties: later slides first
    )
    while spare > 0:
        gave = False
        for _, slide in by_richness:
            if spare > 0 and budget[slide["index"]] < _capacity(slide):
                budget[slide["index"]] += 1
                spare -= 1
                gave = True
        if not gave:
            break
    return budget


# ---------- 1. fallback outline (no AI) ----------

def _slide_fallback(slide: dict, count: int) -> list[dict]:
    """Points for one slide without Gemma: its first `count` proper lines."""
    if _is_list_slide(slide):
        return [make_point(_summary_point(slide), slide["index"])]
    lines = _lines(slide)
    proper = [line for line in lines if len(line.split()) >= 3] or lines
    return [make_point(line, slide["index"]) for line in proper[:count]]


def fallback_outline(slides: list[dict]) -> list[dict]:
    content = content_slides(slides)
    if not content:
        # Nothing but titles: better a list of titles than an empty outline.
        points = [make_point(s["title"], s["index"]) for s in slides if not is_structural(s)]
        return number_points(cap_points(points, config.MAX_OUTLINE_POINTS))
    budget = plan_budget(content)
    points = [p for slide in content for p in _slide_fallback(slide, budget[slide["index"]])]
    return number_points(cap_points(points, config.MAX_OUTLINE_POINTS))


# ---------- 2. Gemma outline (background) ----------

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
      2. if that line is short, it keeps every key term (drug names, acronyms,
         long words) of the line. A long line (over 15 words) has to lose
         words to be shortened, so there rule 1 is enough.
    Returns (line number or None, trusted?).
    """
    words = _content_words(text)
    if not words:
        return None, False
    title_words = _content_words(slide["title"])
    lines = _lines(slide)
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
    if len(lines[best_line].split()) > LONG_LINE_WORDS:
        return best_line, True
    key_terms = [w.lower() for w in WORD_RE.findall(lines[best_line]) if is_distinctive(w, first_in_line=True)]
    kept_all = all(any(_same_word(term, w) for w in words) for term in key_terms)
    return best_line, kept_all


def _plain(text: str) -> str:
    """Lower-case words only, to tell "copied the line" from "reworded it"."""
    return " ".join(w.lower() for w in WORD_RE.findall(text))


def new_stats() -> dict:
    """How Gemma's points did against the verification check (for honest reporting)."""
    return {"slides_asked": 0, "failed": 0, "reworded": 0, "copied": 0, "fell_back": 0, "dropped": 0, "seconds": 0.0}


def _needs_gemma(slide: dict, count: int) -> bool:
    """Gemma is only asked when there is a choice to make or a line to shorten."""
    if _is_list_slide(slide):
        return False
    lines = _lines(slide)
    return len(lines) > count or any(len(line.split()) > LONG_LINE_WORDS for line in lines)


async def _ask_gemma(slide: dict, count: int, stats: dict) -> list[str]:
    """One Gemma call for one slide. Returns up to `count` key points, verified in code."""
    lines = _lines(slide)
    count = min(count, len(lines))

    body = "\n".join(lines)
    words = body.split(" ")
    if len(words) > config.OUTLINE_SLIDE_WORDS:  # keep the prompt inside num_ctx
        body = " ".join(words[: config.OUTLINE_SLIDE_WORDS])
    # Speaker notes help Gemma judge what matters, but points must come from the lines above.
    notes = slide.get("notes", "")
    if notes and split_sentences(notes)[0] not in lines:
        body += prompts.OUTLINE_NOTES.format(notes=" ".join(notes.split(" ")[: config.OUTLINE_NOTES_WORDS]))
    prompt = prompts.OUTLINE_PROMPT.format(title=slide["title"], body=body, count=count)
    # A JSON schema makes Ollama return exactly `count` strings.
    schema = {
        "type": "object",
        "properties": {
            "points": {"type": "array", "items": {"type": "string"}, "minItems": count, "maxItems": count}
        },
        "required": ["points"],
    }
    started = time.perf_counter()
    stats["slides_asked"] += 1
    try:
        data = await llm.generate_json(prompt, prompts.OUTLINE_SYSTEM, max_tokens=60 * count, schema=schema)
    finally:
        stats["seconds"] = round(stats["seconds"] + time.perf_counter() - started, 1)

    points, used_lines = [], set()
    items = data.get("points")
    for text in items if isinstance(items, list) else []:
        if not isinstance(text, str):
            continue
        line_number, trusted = _ground(text, slide)
        if line_number is None or line_number in used_lines:
            stats["dropped"] += 1
            continue  # not from this slide, or the same line twice
        used_lines.add(line_number)
        if _plain(text) == _plain(lines[line_number]):
            stats["copied"] += 1  # Gemma picked the line and left it as it was
            points.append((line_number, lines[line_number]))
        elif trusted:
            stats["reworded"] += 1
            points.append((line_number, text.strip()))
        else:
            # Gemma chose this line but changed its meaning: use the slide's own words.
            stats["fell_back"] += 1
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
        log.warning("Gemma outline skipped: %s", ready["message"])
        _finish(session, "fallback_only", ready["message"])
        return

    content = content_slides(slides)
    budget = plan_budget(content)
    todo = [slide for slide in content if _needs_gemma(slide, budget[slide["index"]])]
    outline["progress"] = {"done": 0, "total": len(todo)}
    stats = outline["stats"] = new_stats()
    store.save(session)

    from_gemma: dict[int, list[str]] = {}
    reason = ""  # why the last failure happened, in words the UI can show
    in_a_row = 0
    for slide in todo:
        try:
            texts = await _ask_gemma(slide, budget[slide["index"]], stats)
            if texts:
                from_gemma[slide["index"]] = texts
            in_a_row = 0
        except Exception as e:
            stats["failed"] += 1
            in_a_row += 1
            if isinstance(e, llm.LLMError):
                reason = str(e)
                log.warning("Gemma failed on slide %d: [%s] %s", slide["index"], e.reason, e)
                # These won't fix themselves by trying the next slide.
                hopeless = e.reason in ("not_running", "model_missing", "out_of_memory")
            else:
                reason = f"{type(e).__name__}: {e}"
                log.exception("Unexpected error on slide %d", slide["index"])
                hopeless = False
            if hopeless or in_a_row >= STOP_AFTER_FAILURES:
                log.warning("Stopping the Gemma outline early; the remaining slides use their own lines.")
                break
        outline["progress"]["done"] += 1
        store.save(session)

    if todo and not from_gemma:
        _finish(session, "fallback_only", reason or "Gemma returned no usable points.")
        return

    # Slides Gemma wasn't asked about (or failed on) use their own lines.
    points = []
    for slide in content:
        if slide["index"] in from_gemma:
            points += [make_point(text, slide["index"]) for text in from_gemma[slide["index"]]]
        else:
            points += _slide_fallback(slide, budget[slide["index"]])

    points = await asyncio.to_thread(_dedupe, points)
    outline["points"] = number_points(cap_points(points, config.MAX_OUTLINE_POINTS))
    outline["source"] = "gemma" if from_gemma else "slides"
    message = ""
    if stats["failed"]:
        message = f"Gemma couldn't finish {stats['failed']} of {len(todo)} slides: {reason} Those use your slides' own wording."
    _finish(session, "ready", message)
    log.info(
        "Gemma outline: %d points from %d content slides (%d in the file) in %.0f s. Verification: %s",
        len(outline["points"]), len(content), len(slides), time.perf_counter() - started, stats,
    )
    await asyncio.to_thread(coverage.cache_point_embeddings, session)


async def _run(session: dict):
    try:
        await _generate(session)
    except asyncio.CancelledError:
        raise  # the user took over the outline; whoever cancelled sets the status
    except Exception as e:
        log.exception("Outline generation stopped unexpectedly")
        _finish(session, "fallback_only", f"Gemma stopped unexpectedly ({type(e).__name__}: {e}).")
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
