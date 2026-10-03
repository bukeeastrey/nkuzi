"""Embeddings (fastembed, ONNX, CPU) and ticking off outline points.

This is the fast path: after every chunk of speech we compare what was
said with each open outline point. No Gemma involved, so it never waits.
"""
import logging
import time

import numpy as np
from rapidfuzz import fuzz

from . import config
from .pdf import split_sentences

log = logging.getLogger("nkuzi.coverage")

_embedder = None  # loaded once, shared by every request


def load_embedder():
    """Load the embedding model once. The first run downloads it (~130 MB)."""
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding  # slow import, so do it here

        started = time.perf_counter()
        cache_dir = str(config.MODEL_CACHE_DIR / "fastembed")
        try:
            # Use the copy on disk without touching the network (works offline).
            _embedder = TextEmbedding(config.EMBED_MODEL, cache_dir=cache_dir, local_files_only=True)
        except Exception:
            log.info("Embedder %s not on disk yet, downloading…", config.EMBED_MODEL)
            _embedder = TextEmbedding(config.EMBED_MODEL, cache_dir=cache_dir)
        log.info("Embedder %s loaded in %.1f s", config.EMBED_MODEL, time.perf_counter() - started)
    return _embedder


def is_loaded() -> bool:
    return _embedder is not None


# Point embeddings live in memory only: {session id: {point id: vector}}.
_point_vectors: dict[str, dict[str, np.ndarray]] = {}


def cache_point_embeddings(session: dict):
    """Embed every outline point (text + keywords). Call when the outline changes."""
    points = session["outline"]["points"]
    texts = [p["text"] + " " + " ".join(p["keywords"]) for p in points]
    vectors = embed(texts) if texts else []
    _point_vectors[session["id"]] = {p["id"]: v for p, v in zip(points, vectors)}


def embed(texts: list[str]) -> np.ndarray:
    """Texts -> one unit-length vector per row, so dot product = cosine similarity."""
    vectors = np.array(list(load_embedder().embed(texts)), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-9)


# ---------- ticking off points (the fast path: no Gemma involved) ----------

KEYWORD_FUZZ = 80  # 0-100: how close a heard word must be to a key term to count
#
# session["covered"] holds one entry per point that has been ticked or touched:
#   {point id: {"covered": bool, "manual": bool, "at": seconds, "snippet": str, "score": float}}
# A point with no entry is still open. A manual entry is never changed by the
# automatic matching: the explainer's click always wins.

def point_vectors(session: dict) -> dict[str, np.ndarray]:
    """Embeddings of the outline points (recomputed if missing, e.g. after a backend restart)."""
    vectors = _point_vectors.get(session["id"])
    if vectors is None or set(vectors) != {p["id"] for p in session["outline"]["points"]}:
        cache_point_embeddings(session)
    return _point_vectors[session["id"]]


def covered_ids(session: dict) -> list[str]:
    """Ids of the covered points, in outline order."""
    covered = session["covered"]
    return [p["id"] for p in session["outline"]["points"] if covered.get(p["id"], {}).get("covered")]


def missed_points(session: dict) -> list[dict]:
    done = set(covered_ids(session))
    return [p for p in session["outline"]["points"] if p["id"] not in done]


def _keywords_heard(point: dict, heard_lower: str) -> bool:
    """Were most of the point's key terms said (allowing small spelling slips)?"""
    keywords = point["keywords"]
    if not keywords:
        return False
    found = 0
    for keyword in keywords:
        word = keyword.lower()
        # Whisper often misspells long medical terms ("bradycardia" -> "braticardia"),
        # so long terms only need to match roughly.
        if word in heard_lower or (len(word) >= 6 and fuzz.partial_ratio(word, heard_lower) >= KEYWORD_FUZZ):
            found += 1
    return found / len(keywords) >= config.COVER_KEYWORD_SHARE


def update(session: dict) -> list[str]:
    """Call after new speech was added to the transcript. Returns newly covered point ids."""
    points = session["outline"]["points"]
    open_points = [p for p in points if p["id"] not in session["covered"]]
    recent = session["transcript"][-2:]
    if not open_points or not recent:
        return []

    # The last two chunks together, so a point that straddles a chunk boundary is caught.
    window = " ".join(line["text"] for line in recent)
    candidates = [s for s in split_sentences(window) if len(s.split()) >= 3]
    if window not in candidates:
        candidates.append(window)
    heard = embed(candidates)
    heard_lower = window.lower()
    vectors = point_vectors(session)

    newly, scores = [], []
    for point in open_points:
        similarities = heard @ vectors[point["id"]]  # cosine similarity with each candidate
        best = int(np.argmax(similarities))
        bonus = config.COVER_KEYWORD_BONUS if _keywords_heard(point, heard_lower) else 0.0
        score = float(similarities[best]) + bonus
        scores.append((score, bonus, point))
        if score >= config.COVER_THRESHOLD:
            session["covered"][point["id"]] = {
                "covered": True,
                "manual": False,
                "at": recent[-1]["at"],
                "snippet": candidates[best][:200],
                "score": round(score, 3),
            }
            newly.append(point["id"])

    # The three best scores, to help tune COVER_THRESHOLD.
    scores.sort(key=lambda item: -item[0])
    summary = " | ".join(
        f"{'TICK ' if s >= config.COVER_THRESHOLD else ''}{s:.2f}{' (+kw)' if b else ''} {p['text'][:40]!r}"
        for s, b, p in scores[:3]
    )
    log.info("coverage (threshold %.2f): %s", config.COVER_THRESHOLD, summary)
    return newly


def toggle(session: dict, point_id: str) -> bool:
    """Manual tick / untick from the UI. Returns the point's new state."""
    now_covered = not session["covered"].get(point_id, {}).get("covered", False)
    session["covered"][point_id] = {
        "covered": now_covered,
        "manual": True,
        "at": session.get("audio_seconds", 0.0),
        "snippet": "",
    }
    return now_covered


def forget_removed_points(session: dict):
    """After the outline was edited: drop ticks that belong to deleted points."""
    ids = {p["id"] for p in session["outline"]["points"]}
    session["covered"] = {pid: entry for pid, entry in session["covered"].items() if pid in ids}
