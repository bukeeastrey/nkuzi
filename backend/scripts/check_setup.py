"""Checks that everything Nkuzi needs is installed, and prints how fast it runs.

Run from the backend folder, with the venv active:

    python scripts\\check_setup.py
"""
import asyncio
import sys
import time
import wave
from pathlib import Path

import numpy as np

# Let this script import the "app" package when run from anywhere.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import config, coverage, llm, transcribe  # noqa: E402

SAMPLE_WAV = BACKEND_DIR / "samples" / "sample.wav"
results = []  # (name, ok, detail)


def report(name: str, ok: bool, detail: str):
    results.append((name, ok, detail))
    print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")


def read_wav(path: Path) -> np.ndarray:
    """Read a 16 kHz mono 16-bit wav into float32 in [-1, 1]."""
    with wave.open(str(path), "rb") as f:
        if (f.getframerate(), f.getnchannels(), f.getsampwidth()) != (16000, 1, 2):
            raise ValueError("sample.wav must be 16 kHz, mono, 16-bit")
        pcm = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def check_whisper():
    try:
        started = time.perf_counter()
        model = transcribe.load_model()
        report("Whisper load", True, f"{config.WHISPER_MODEL} in {time.perf_counter() - started:.1f} s")
    except Exception as e:
        report("Whisper load", False, f"{e} (the first run needs internet to download the model)")
        return

    if SAMPLE_WAV.exists():
        audio, label, vad = read_wav(SAMPLE_WAV), "sample.wav", True
    else:
        # No recording yet: time one chunk of noise. This measures speed only.
        rng = np.random.default_rng(0)
        audio = (rng.standard_normal(16000 * config.CHUNK_SECONDS) * 0.05).astype(np.float32)
        label, vad = f"{config.CHUNK_SECONDS} s of test noise (no samples\\sample.wav yet)", False

    started = time.perf_counter()
    segments, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=vad)
    text = " ".join(s.text.strip() for s in segments)  # segments is lazy; this runs it
    took = time.perf_counter() - started
    seconds = len(audio) / 16000
    report("Whisper transcribe", True, f"{seconds:.0f} s of audio in {took:.1f} s ({label})")
    if SAMPLE_WAV.exists():
        print(f"       heard: {text[:200]!r}")
    if took > config.CHUNK_SECONDS:
        print("       WARNING: slower than one chunk. Live transcription would fall behind.")


def check_embedder():
    try:
        started = time.perf_counter()
        coverage.load_embedder()
        report("Embedder load", True, f"{config.EMBED_MODEL} in {time.perf_counter() - started:.1f} s")
        started = time.perf_counter()
        vectors = coverage.embed(
            ["Beta blockers slow the heart rate.", "Propranolol reduces heart rate.", "The liver makes bile."]
        )
        took = time.perf_counter() - started
        related, unrelated = float(vectors[0] @ vectors[1]), float(vectors[0] @ vectors[2])
        report(
            "Embedder run",
            related > unrelated,
            f"3 sentences in {took * 1000:.0f} ms (related {related:.2f} vs unrelated {unrelated:.2f})",
        )
    except Exception as e:
        report("Embedder", False, f"{e} (the first run needs internet to download the model)")


async def check_gemma():
    status = await llm.is_ready()
    report("Ollama running", status["ok"], status["message"] if not status["ok"] else config.OLLAMA_URL)
    if not status["ok"]:
        return
    report("Gemma model", status["model_present"], status["message"])
    if not status["model_present"]:
        return
    try:
        started = time.perf_counter()
        answer = await llm.generate_json(
            'Reply with this JSON: {"ok": true}', "You reply with JSON only.", max_tokens=20
        )
        first = time.perf_counter() - started
        # The first call includes loading the model into RAM; time a second one.
        started = time.perf_counter()
        await llm.generate_json(
            'Give one key fact about beta blockers as JSON: {"fact": "..."}',
            "You reply with JSON only.",
            max_tokens=60,
        )
        second = time.perf_counter() - started
        report("Gemma JSON prompt", True, f"{answer} | first call {first:.1f} s (with load), second {second:.1f} s")
    except llm.LLMError as e:
        report("Gemma JSON prompt", False, str(e))


def main():
    print(f"{config.APP_NAME} setup check\n")
    check_whisper()
    check_embedder()
    asyncio.run(check_gemma())

    failed = [name for name, ok, _ in results if not ok]
    print()
    if failed:
        print("Needs fixing: " + ", ".join(failed))
        sys.exit(1)
    print("All good. Start the backend with .\\run.ps1")


if __name__ == "__main__":
    main()
