"""Sessions are plain dicts, saved as one JSON file each. No database."""
import json
import re
import uuid
from datetime import datetime

from . import config

_sessions: dict[str, dict] = {}  # sessions already loaded, by id

ID_RE = re.compile(r"^[a-f0-9]{12}$")  # also stops odd ids reaching the file system


def _path(session_id: str):
    return config.DATA_DIR / f"{session_id}.json"


def new_session(title: str, explainer: str, slides: list[dict], vocab: str) -> dict:
    session = {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "explainer": explainer,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "slides": slides,
        "vocab": vocab,
        "outline": {
            "status": "generating",  # generating | ready | fallback_only
            "source": "slides",  # slides (fallback) | gemma | edited
            "progress": {"done": 0, "total": 0},
            "message": "",
            "points": [],
        },
        # Filled in by later milestones:
        "transcript": [],
        "covered": {},
        "issues": [],
        "started_at": None,
        "ended_at": None,
    }
    _sessions[session["id"]] = session
    save(session)
    return session


def save(session: dict):
    """Write the session to disk. Call after every state change."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(session["id"])
    # Write to a temp file first, so a power cut can't leave half a file.
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(session, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(path)


def get(session_id: str) -> dict | None:
    """From memory if loaded, otherwise from disk (e.g. after a backend restart)."""
    if session_id in _sessions:
        return _sessions[session_id]
    if not ID_RE.match(session_id) or not _path(session_id).exists():
        return None
    session = json.loads(_path(session_id).read_text(encoding="utf-8"))
    _sessions[session_id] = session
    return session
