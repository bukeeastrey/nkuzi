"""Thin client for Ollama (Gemma). Only talks to localhost."""
import json
import logging
import time

import httpx

from . import config

log = logging.getLogger("nkuzi.llm")


class LLMError(Exception):
    """Raised with a friendly message the UI can show as-is."""


async def is_ready() -> dict:
    """Is Ollama running, and is our model pulled? -> {ok, model_present, message}"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{config.OLLAMA_URL}/api/tags")
            resp.raise_for_status()
    except Exception:
        return {
            "ok": False,
            "model_present": False,
            "message": "Ollama isn't running. Open the Ollama app.",
        }

    names = [m.get("name", "") for m in resp.json().get("models", [])]
    wanted = config.OLLAMA_MODEL
    # "gemma3" and "gemma3:latest" are the same model to Ollama.
    present = wanted in names or f"{wanted}:latest" in names
    if not present:
        return {
            "ok": True,
            "model_present": False,
            "message": f"Model not downloaded yet. Run: ollama pull {wanted}",
        }
    return {"ok": True, "model_present": True, "message": f"{wanted} is ready."}


async def generate_json(prompt: str, system: str, max_tokens: int) -> dict:
    """Ask Gemma for a JSON object. Retries once if the JSON is broken."""
    last_error = None
    for attempt in (1, 2):
        # Second attempt: remind the model what we want.
        text = prompt if attempt == 1 else prompt + "\n\nReturn valid JSON only."
        raw = await _generate(text, system, max_tokens)
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
            last_error = "JSON was not an object"
        except json.JSONDecodeError as e:
            last_error = str(e)
        log.warning("Gemma returned invalid JSON (attempt %d): %s", attempt, last_error)
    raise LLMError("Gemma returned an answer we couldn't read. Please try again.")


async def _generate(prompt: str, system: str, max_tokens: int) -> str:
    """One call to Ollama's /api/generate. Returns the raw response text."""
    body = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "system": system,
        "format": "json",
        "stream": False,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": 0.2,
            "num_ctx": config.OLLAMA_NUM_CTX,
            "num_predict": max_tokens,
        },
    }
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT_S) as client:
            resp = await client.post(f"{config.OLLAMA_URL}/api/generate", json=body)
    except httpx.TimeoutException:
        raise LLMError(f"Gemma took longer than {config.OLLAMA_TIMEOUT_S} s and was stopped.")
    except httpx.HTTPError:
        raise LLMError("Ollama isn't running. Open the Ollama app.")

    if resp.status_code == 404:
        raise LLMError(f"Model not downloaded yet. Run: ollama pull {config.OLLAMA_MODEL}")
    if resp.status_code != 200:
        raise LLMError(f"Ollama error {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    # Log speed for every call so we can report honest numbers in the write-up.
    elapsed = time.perf_counter() - started
    tokens = data.get("eval_count", 0)
    eval_s = data.get("eval_duration", 0) / 1e9  # Ollama reports nanoseconds
    speed = tokens / eval_s if eval_s else 0
    log.info("Gemma call: %.1f s total, %d tokens out, %.1f tokens/s", elapsed, tokens, speed)
    return data.get("response", "")
