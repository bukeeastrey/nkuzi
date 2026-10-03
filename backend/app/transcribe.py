"""Speech to text with faster-whisper (CPU, int8).

M0: only loads the model. Live chunk transcription arrives in M2.
"""
import logging
import time

from . import config

log = logging.getLogger("nkuzi.transcribe")

_model = None  # loaded once, shared by every request


def load_model():
    """Load Whisper once. The first run downloads it (~75 MB for tiny.en)."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # slow import, so do it here

        started = time.perf_counter()
        options = dict(
            device="cpu",
            compute_type="int8",
            cpu_threads=config.WHISPER_THREADS,
            download_root=str(config.MODEL_CACHE_DIR / "whisper"),
        )
        try:
            # Use the copy on disk without touching the network (works offline).
            _model = WhisperModel(config.WHISPER_MODEL, local_files_only=True, **options)
        except Exception:
            log.info("Whisper %s not on disk yet, downloading…", config.WHISPER_MODEL)
            _model = WhisperModel(config.WHISPER_MODEL, **options)
        log.info("Whisper %s loaded in %.1f s", config.WHISPER_MODEL, time.perf_counter() - started)
    return _model


def is_loaded() -> bool:
    return _model is not None
