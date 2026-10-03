"""Thin client for Ollama (Gemma). Only talks to localhost."""
import asyncio
import json
import logging
import time

import httpx

from . import config

log = logging.getLogger("nkuzi.llm")

RETRY_WAIT_S = 8  # how long to wait before the one retry when Ollama is busy


class LLMError(Exception):
    """Raised with a friendly message the UI can show as-is.

    `reason` is a short code so callers can react:
    not_running | model_missing | out_of_memory | timeout | busy | invalid_json | other
    """

    def __init__(self, message: str, reason: str = "other"):
        super().__init__(message)
        self.reason = reason


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


async def generate_json(prompt: str, system: str, max_tokens: int, schema: dict | None = None) -> dict:
    """Ask Gemma for a JSON object. Retries once if the JSON is broken.

    Pass a JSON schema to make Ollama stick to an exact shape.
    """
    last_error = None
    for attempt in (1, 2):
        # Second attempt: remind the model what we want.
        text = prompt if attempt == 1 else prompt + "\n\nReturn valid JSON only."
        raw = await _generate_with_retry(text, system, max_tokens, schema)
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
            last_error = "JSON was not an object"
        except json.JSONDecodeError as e:
            last_error = str(e)
        log.warning("Gemma returned invalid JSON (attempt %d): %s | answer began: %r", attempt, last_error, raw[:120])
    raise LLMError("Gemma's answer wasn't valid JSON, twice in a row.", "invalid_json")


async def _generate_with_retry(prompt: str, system: str, max_tokens: int, schema: dict | None) -> str:
    """If Ollama is busy (another request, or still loading the model), wait and try once more."""
    try:
        return await _generate(prompt, system, max_tokens, schema)
    except LLMError as e:
        if e.reason != "busy":
            raise
        log.warning("Ollama is busy (%s). Waiting %d s, then trying once more.", e, RETRY_WAIT_S)
        await asyncio.sleep(RETRY_WAIT_S)
        return await _generate(prompt, system, max_tokens, schema)


def _explain_ollama_error(status: int, text: str) -> LLMError:
    """Turn an Ollama error reply into a clear reason."""
    try:
        detail = str(json.loads(text).get("error", text))
    except (json.JSONDecodeError, AttributeError):
        detail = text
    detail = detail.strip()[:200]
    lower = detail.lower()
    model = config.OLLAMA_MODEL

    if status == 404 or "not found" in lower:
        return LLMError(f"Model not found. Run: ollama pull {model}", "model_missing")
    if "memory" in lower:
        return LLMError(f"Not enough free memory to run {model}. Close other apps, or switch to a smaller model.", "out_of_memory")
    if status == 503 or "busy" in lower or "try again" in lower:
        return LLMError("Ollama is busy with another request.", "busy")
    if "timed out" in lower or "timeout" in lower:
        return LLMError(f"Ollama timed out loading {model} (the laptop is probably low on memory).", "timeout")
    return LLMError(f"Ollama error {status}: {detail}", "other")


async def _generate(prompt: str, system: str, max_tokens: int, schema: dict | None) -> str:
    """One call to Ollama's /api/generate. Returns the raw response text."""
    body = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "system": system,
        "format": schema or "json",
        "stream": False,
        # Gemma 4 can "think" before answering. That would eat our small token
        # budget and leave the answer empty, so we turn it off.
        "think": False,
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
        raise LLMError(
            f"Gemma took longer than {config.OLLAMA_TIMEOUT_S} s (the laptop is probably low on memory).", "timeout"
        )
    except httpx.ConnectError:
        raise LLMError("Ollama isn't running. Open the Ollama app.", "not_running")
    except httpx.HTTPError as e:
        # The connection dropped half-way: Ollama restarted or unloaded the model.
        raise LLMError(f"Ollama dropped the connection ({type(e).__name__}).", "busy")

    if resp.status_code != 200:
        raise _explain_ollama_error(resp.status_code, resp.text)

    try:
        data = resp.json()
    except json.JSONDecodeError:
        raise LLMError("Ollama sent back a reply we couldn't read.", "other")
    # Log speed for every call so we can report honest numbers in the write-up.
    elapsed = time.perf_counter() - started
    tokens = data.get("eval_count", 0)
    eval_s = data.get("eval_duration", 0) / 1e9  # Ollama reports nanoseconds
    speed = tokens / eval_s if eval_s else 0
    log.info("Gemma call: %.1f s total, %d tokens out, %.1f tokens/s", elapsed, tokens, speed)
    return data.get("response", "")
