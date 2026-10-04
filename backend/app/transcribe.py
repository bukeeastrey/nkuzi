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
MAX_COMPRESSION_RATIO = 2.4  # text that compresses this well is a loop, not speech
MIN_AVG_LOGPROB = -1.0  # below this, Whisper was guessing
MAX_NEW_TOKENS = 120  # Whisper may write at most this much per chunk
MAX_REPEATS = 3  # a word/phrase repeated more often than this in a row is collapsed
MAX_PHRASE_WORDS = 6  # longest repeated phrase we look for

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
        # Two guards against loops ("see, see, see..." a hundred times), which
        # are also what made some chunks take over a minute:
        no_repeat_ngram_size=3,  # never repeat the same three tokens in a row
        max_new_tokens=MAX_NEW_TOKENS,  # 8 s of speech is 20-30 words
        vad_filter=True,  # skips silence, so quiet chunks cost almost nothing
        initial_prompt=hint or None,
        condition_on_previous_text=False,
    )
    # `segments` is lazy: the real work happens while we loop over it.
    parts = []
    for segment in segments:
        if _is_hallucination(segment):
            log.info("Dropped a doubtful segment: %r", segment.text[:60])
            continue
        parts.append(segment.text.strip())
    return collapse_repeats(" ".join(part for part in parts if part))


def _is_hallucination(segment) -> bool:
    """Whisper's own warning signs that it made the text up."""
    return (
        segment.no_speech_prob >= NO_SPEECH_LIMIT  # probably not speech at all
        or segment.compression_ratio > MAX_COMPRESSION_RATIO  # very repetitive text ("see, see, see...")
        or segment.avg_logprob < MIN_AVG_LOGPROB  # the model was guessing
    )


def _plain_word(word: str) -> str:
    return word.lower().strip(".,;:!?\"'")


def collapse_repeats(text: str) -> str:
    """Safety net for loops: a word or phrase said more than MAX_REPEATS times
    in a row is kept once. "see, see, see, see, see" -> "see"."""
    words = text.split()
    for size in range(1, MAX_PHRASE_WORDS + 1):  # 1 = single words, 2 = two-word phrases...
        kept, i = [], 0
        while i < len(words):
            phrase = [_plain_word(w) for w in words[i : i + size]]
            repeats = 1
            while len(phrase) == size and [_plain_word(w) for w in words[i + repeats * size : i + (repeats + 1) * size]] == phrase:
                repeats += 1
            if repeats > MAX_REPEATS:
                kept += words[i : i + size]  # keep it once
                i += repeats * size
            else:
                kept.append(words[i])
                i += 1
        words = kept
    return " ".join(words)
