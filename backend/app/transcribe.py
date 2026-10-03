"""Speech to text with faster-whisper (CPU, int8). This is the fast path:
it runs for every audio chunk and never waits for Gemma."""
import logging
import time

import numpy as np

from . import config

log = logging.getLogger("nkuzi.transcribe")

SAMPLE_RATE = 16000
MIN_SAMPLES = SAMPLE_RATE // 2  # ignore chunks shorter than half a second
NO_SPEECH_LIMIT = 0.6  # Whisper's own "this was not speech" score; above this we drop the text

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


def pcm_to_float(pcm_int16: bytes) -> np.ndarray:
    """Raw 16-bit samples from the browser -> float32 in [-1, 1], as Whisper expects."""
    usable = len(pcm_int16) - (len(pcm_int16) % 2)  # a sample is 2 bytes
    return np.frombuffer(pcm_int16[:usable], dtype=np.int16).astype(np.float32) / 32768.0


def transcribe_chunk(pcm_int16: bytes, vocab: str, prev_text: str) -> str:
    """One chunk of microphone audio -> text ("" for silence or noise).

    vocab:     the slide deck's key terms. Given to Whisper as a hint so it
               spells medical words the way the slides do. This matters a lot.
    prev_text: what was said just before, so a sentence can continue across chunks.
    """
    audio = pcm_to_float(pcm_int16)
    if audio.size < MIN_SAMPLES:
        return ""
    hint = (vocab + " " + prev_text[-200:]).strip()
    segments, _ = load_model().transcribe(
        audio,
        language="en",
        beam_size=1,
        # One pass only. By default Whisper retries an unclear chunk up to five
        # more times, which made some 8 s chunks take 8-13 s on this laptop.
        temperature=0.0,
        vad_filter=True,  # skips silence, so quiet chunks cost almost nothing
        initial_prompt=hint or None,
        condition_on_previous_text=False,
    )
    # `segments` is lazy: the real work happens while we loop over it.
    parts = [s.text.strip() for s in segments if s.no_speech_prob < NO_SPEECH_LIMIT]
    return " ".join(part for part in parts if part)
