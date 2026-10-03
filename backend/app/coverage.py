"""Embeddings with fastembed (ONNX, CPU).

M0: only loads the embedder. Coverage ticking arrives in M3.
"""
import logging
import time

import numpy as np

from . import config

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
