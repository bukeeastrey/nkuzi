"""Compares Gemma models on this laptop: outline speed, RAM, stability, and
how often the model's own wording survives our verification check.
Also a small contradiction test, as a preview of "Check me".

Stop the backend first (RAM is tight), then from the backend folder:

    python scripts\\compare_models.py gemma3:1b gemma4:e2b-it-qat
"""
import asyncio
import ctypes
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
from rapidfuzz import fuzz

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="nkuzi_compare_")  # keep test sessions out of real data

from app import config, coverage, llm, outline, slides, store, transcribe  # noqa: E402

SAMPLE = BACKEND_DIR / "samples" / "beta_blockers.pptx"

CHECK_SYSTEM = "You check a student's spoken explanation against their lecture slide. Judge only from the slide."
CHECK_PROMPT = """Slide:
{slide}

The student said: "{said}"

Copy the slide line this is about, then say whether the student contradicts it."""
CHECK_SCHEMA = {
    "type": "object",
    "properties": {"slide_quote": {"type": "string"}, "contradicts": {"type": "boolean"}},
    "required": ["slide_quote", "contradicts"],
}
# (slide title, what the student said, does it contradict the slide?)
CHECK_CASES = [
    ("Classification", "Atenolol is a non-selective beta blocker.", True),
    ("Classification", "Propranolol is a non-selective beta blocker.", False),
    ("Adverse effects and contraindications", "Non-selective beta blockers are safe to use in patients with asthma.", True),
    ("Adverse effects and contraindications", "You should never stop a beta blocker suddenly, because of rebound tachycardia.", False),
]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def ram_used_gb() -> float:
    """RAM in use on the whole laptop, in GB (Windows API)."""
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return (status.ullTotalPhys - status.ullAvailPhys) / 1024**3


class RamWatcher:
    """Samples laptop RAM twice a second in a background thread and keeps the peak."""

    def __enter__(self):
        self.peak = ram_used_gb()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return self

    def _watch(self):
        while not self._stop.wait(0.5):
            self.peak = max(self.peak, ram_used_gb())

    def __exit__(self, *args):
        self._stop.set()
        self._thread.join()


def unload_all_models():
    """Ask Ollama to drop every loaded model, so each test starts from the same RAM."""
    loaded = httpx.get(f"{config.OLLAMA_URL}/api/ps", timeout=10).json().get("models", [])
    for model in loaded:
        httpx.post(f"{config.OLLAMA_URL}/api/generate", json={"model": model["name"], "keep_alive": 0}, timeout=60)
    time.sleep(5)


async def test_model(model: str, deck: list[dict]) -> dict:
    print(f"\n================ {model} ================")
    config.OLLAMA_MODEL = model
    result = {"model": model, "errors": []}

    ready = await llm.is_ready()
    if not ready["model_present"]:
        print(ready["message"])
        result["errors"].append(ready["message"])
        return result

    unload_all_models()
    result["ram_before_gb"] = round(ram_used_gb(), 2)

    with RamWatcher() as ram:
        # 1. Load the model (first call).
        started = time.perf_counter()
        try:
            await llm.generate_json('Reply with this JSON: {"ok": true}', "You reply with JSON only.", max_tokens=20)
        except llm.LLMError as e:
            result["errors"].append(f"load: {e}")
            print("Could not load:", e)
            return result
        result["load_seconds"] = round(time.perf_counter() - started, 1)
        print(f"Loaded in {result['load_seconds']} s")

        # 2. Outline for the sample deck (same code path as the app).
        session = store.new_session("compare", "", deck, "", "Slide")
        session["outline"]["points"] = outline.fallback_outline(deck)
        started = time.perf_counter()
        await outline._run(session)
        result["outline_seconds"] = round(time.perf_counter() - started, 1)
        o = session["outline"]
        result["outline_status"] = o["status"]
        result["stats"] = o.get("stats", {})
        result["points"] = [f"s{p['slide']}: {p['text']}" for p in o["points"]]
        if o["status"] != "ready":
            result["errors"].append(f"outline: {o['message']}")
        asked = result["stats"].get("slides_asked", 0)
        result["seconds_per_slide"] = round(result["stats"].get("seconds", 0) / asked, 1) if asked else None
        print(f"Outline: {o['status']} in {result['outline_seconds']} s, {result['seconds_per_slide']} s per slide")
        print("Verification:", result["stats"])
        for point in result["points"]:
            print("   ", point)

        # 3. Contradiction test.
        by_title = {slide["title"]: slide for slide in deck}
        result["checks"] = []
        for title, said, expected in CHECK_CASES:
            slide = by_title[title]
            started = time.perf_counter()
            try:
                answer = await llm.generate_json(
                    CHECK_PROMPT.format(slide=slide["text"], said=said), CHECK_SYSTEM, max_tokens=80, schema=CHECK_SCHEMA
                )
            except llm.LLMError as e:
                result["errors"].append(f"check: {e}")
                continue
            quote = str(answer.get("slide_quote", ""))
            check = {
                "said": said,
                "expected": expected,
                "answer": answer.get("contradicts"),
                "correct": answer.get("contradicts") == expected,
                "quote": quote,
                # Same rule "Check me" will use: the quote must really be on the slide.
                "quote_on_slide": fuzz.partial_ratio(quote.lower(), slide["text"].lower()) >= 85 if quote else False,
                "seconds": round(time.perf_counter() - started, 1),
            }
            result["checks"].append(check)
            print(f"Check ({check['seconds']} s): {'RIGHT' if check['correct'] else 'WRONG'} | said {said!r} "
                  f"| contradicts={check['answer']} | quote={quote!r} (on slide: {check['quote_on_slide']})")

    loaded = httpx.get(f"{config.OLLAMA_URL}/api/ps", timeout=10).json().get("models", [])
    result["ollama_model_gb"] = round(sum(m.get("size", 0) for m in loaded) / 1024**3, 2)
    result["ram_peak_gb"] = round(ram.peak, 2)
    result["still_running"] = (await llm.is_ready())["ok"]
    print(f"RAM: {result['ram_before_gb']} GB before, {result['ram_peak_gb']} GB peak "
          f"(Ollama reports the model at {result['ollama_model_gb']} GB). Errors: {result['errors'] or 'none'}")
    return result


async def main():
    models = sys.argv[1:] or ["gemma3:1b", "gemma4:e2b-it-qat"]
    deck, _ = slides.extract(SAMPLE.name, SAMPLE.read_bytes())
    # Load what the real backend keeps in RAM, so the numbers are honest.
    transcribe.load_model()
    coverage.load_embedder()
    print(f"Laptop RAM in use with Whisper + embedder loaded: {ram_used_gb():.2f} GB")

    results = [await test_model(model, deck) for model in models]
    unload_all_models()
    out = BACKEND_DIR / "data" / "model_comparison.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    asyncio.run(main())
