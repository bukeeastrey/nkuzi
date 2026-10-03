"""Compares Whisper models on recorded microphone chunks: transcript and time per chunk.

Record first with SAVE_AUDIO_CHUNKS on (chunks land in data\\debug_audio\\<session>\\),
then, with the backend stopped, from the backend folder:

    python scripts\\compare_whisper.py data\\debug_audio\\<folder> [more folders] --deck slides.pptx

--deck gives Whisper the same slide-vocabulary hint the app uses.
"""
import argparse
import sys
import time
import wave
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import config, pdf, slides, transcribe  # noqa: E402


def read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as f:
        return f.readframes(f.getnframes())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folders", nargs="+", type=Path)
    parser.add_argument("--deck", type=Path)
    parser.add_argument("--models", default="tiny.en,base.en,distil-small.en")
    args = parser.parse_args()

    vocab = ""
    if args.deck:
        deck, _ = slides.extract(args.deck.name, args.deck.read_bytes())
        vocab = pdf.build_vocab(deck)
    try:
        loaded = httpx.get(f"{config.OLLAMA_URL}/api/ps", timeout=5).json().get("models", [])
        print("Ollama has loaded:", ", ".join(m["name"] for m in loaded) or "none")
    except httpx.HTTPError:
        print("Ollama is not running")

    recordings = {folder: [read_wav(p) for p in sorted(folder.glob("chunk_*.wav"))] for folder in args.folders}
    for name in args.models.split(","):
        # Swap the model the app's own transcribe code uses, so settings are identical.
        config.WHISPER_MODEL = name
        transcribe._model = None
        started = time.perf_counter()
        transcribe.load_model()
        print(f"\n################ {name} (loaded in {time.perf_counter() - started:.1f} s) ################")
        for folder, chunks in recordings.items():
            print(f"--- {folder.name}")
            times, previous = [], ""
            for i, pcm in enumerate(chunks):
                started = time.perf_counter()
                text = transcribe.transcribe_chunk(pcm, vocab, previous)
                times.append(time.perf_counter() - started)
                previous = text or previous
                print(f"  [{i:02d}] {times[-1]:4.1f} s  {text}")
            if times:
                print(f"  time per chunk: average {sum(times) / len(times):.1f} s, slowest {max(times):.1f} s")


if __name__ == "__main__":
    main()
