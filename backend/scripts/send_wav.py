"""Plays a .wav into a running backend as if it came from the microphone,
and prints what Nkuzi heard, how long each chunk took, and which points it ticked.

Use it to test live transcription without a browser. From the backend folder:

    python scripts\\send_wav.py                       (uses the sample deck + samples\\sample.wav)
    python scripts\\send_wav.py my_slides.pptx my_talk.wav
    python scripts\\send_wav.py samples\\beta_blockers.pptx samples\\sample_mistakes.wav --check

--check presses "Check me" at the end and prints the corrections
(sample_mistakes.wav contains two deliberate mistakes).
The .wav must be 16 kHz, mono, 16-bit.
"""
import sys
import time
import wave
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import config  # noqa: E402

API = "http://localhost:8000/api"


def read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as f:
        if (f.getframerate(), f.getnchannels(), f.getsampwidth()) != (16000, 1, 2):
            sys.exit(f"{path.name} must be 16 kHz, mono, 16-bit.")
        return f.readframes(f.getnframes())


def loaded_models() -> str:
    """Which models Ollama has in RAM right now (they compete with Whisper for memory)."""
    try:
        models = httpx.get(f"{config.OLLAMA_URL}/api/ps", timeout=5).json().get("models", [])
        return ", ".join(f"{m['name']} ({m.get('size', 0) / 1024**3:.1f} GB)" for m in models) or "none"
    except httpx.HTTPError:
        return "Ollama not running"


def check_me(client: httpx.Client, session_id: str):
    """Press "Check me" and wait for the result."""
    started = time.perf_counter()
    reply = client.post(f"{API}/sessions/{session_id}/check")
    if reply.status_code != 200:
        print("\nCheck me:", reply.json().get("detail"))
        return
    job_id = reply.json()["job_id"]
    while True:
        job = client.get(f"{API}/sessions/{session_id}/check/{job_id}").json()
        if job["status"] != "running":
            break
        time.sleep(2)
    summary = job["message"] or f"{len(job['issues'])} correction(s)"
    print(f"\nCheck me ({job['status']}, {time.perf_counter() - started:.0f} s): {summary}")
    for issue in job["issues"]:
        print(f"    heard:   {issue['heard']!r}")
        print(f"    slide {issue['slide']}: {issue['slide_quote']!r}")
        print(f"    fix:     {issue['fix']}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run_check = "--check" in sys.argv
    deck = Path(args[0]) if len(args) > 0 else BACKEND_DIR / "samples" / "beta_blockers.pptx"
    wav = Path(args[1]) if len(args) > 1 else BACKEND_DIR / "samples" / "sample.wav"
    pcm = read_wav(wav)
    client = httpx.Client(timeout=300)

    created = client.post(f"{API}/sessions", files={"pdf": (deck.name, deck.read_bytes())})
    if created.status_code != 200:
        sys.exit(f"Could not create the session: {created.text}")
    session_id = created.json()["session_id"]
    session = client.get(f"{API}/sessions/{session_id}").json()
    # Saving the outline stops the background Gemma job, like pressing "Start listening" does.
    points = [{"id": p["id"], "text": p["text"], "slide": p["slide"]} for p in session["outline"]["points"]]
    client.put(f"{API}/sessions/{session_id}/outline", json={"points": points})
    client.post(f"{API}/sessions/{session_id}/start")
    by_id = {p["id"]: p["text"] for p in points}
    print(f"Session {session_id}: {session['title']!r}, {len(points)} points. Ollama has loaded: {loaded_models()}\n")

    chunk_bytes = config.CHUNK_SECONDS * 16000 * 2
    timings = []
    for seq, start in enumerate(range(0, len(pcm), chunk_bytes)):
        chunk = pcm[start : start + chunk_bytes]
        started = time.perf_counter()
        result = client.post(
            f"{API}/sessions/{session_id}/audio",
            params={"seq": seq},
            content=chunk,
            headers={"Content-Type": "application/octet-stream"},
        ).json()
        total = time.perf_counter() - started
        timings.append(result["whisper_seconds"])
        print(f"chunk {seq}: {len(chunk) / 32000:.0f} s audio, Whisper {result['whisper_seconds']:.1f} s, round trip {total:.1f} s")
        print(f"    heard: {result['text']!r}")
        for point_id in result.get("newly_covered", []):
            print(f"    TICK   {point_id}: {by_id.get(point_id, '?')}")

    print(f"\nWhisper per {config.CHUNK_SECONDS} s chunk: average {sum(timings) / len(timings):.1f} s, slowest {max(timings):.1f} s")
    print(f"Ollama has loaded: {loaded_models()}")
    if max(timings) > config.CHUNK_SECONDS:
        print("WARNING: at least one chunk took longer than it lasts. Live transcription would fall behind.")
    if "covered_count" in result:
        print(f"Covered {result['covered_count']} of {result['total']} points.")
    if run_check:
        check_me(client, session_id)
    print(f"Open it in the browser: http://localhost:5173/#/session/{session_id}")


if __name__ == "__main__":
    main()
