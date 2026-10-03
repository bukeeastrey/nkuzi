"""The recap at the end of a session: what was covered, what was missed,
and the corrections. Built with plain code (no Gemma), so it is instant.
"""
from datetime import datetime

from . import config, coverage

WHATSAPP_LIMIT = 1500  # characters; long lists are cut with "+N more"
POINT_CHARS = 90  # points are shortened to this in the WhatsApp text


def _short(text: str, limit: int = POINT_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _minutes(seconds: float) -> str:
    minutes = round(seconds / 60)
    return "under a minute" if minutes < 1 else f"{minutes} min"


def _list(lines: list[str], limit: int) -> list[str]:
    """At most `limit` bullet lines, then "+N more"."""
    shown = [f"• {line}" for line in lines[:limit]]
    if len(lines) > limit:
        shown.append(f"+{len(lines) - limit} more")
    return shown


def whatsapp_text(recap: dict, unit: str) -> str:
    """The recap as a WhatsApp message (*bold*, _italic_), kept under WHATSAPP_LIMIT."""
    covered = [_short(p["text"]) for p in recap["covered"]]
    missed = [_short(p["text"]) + (f" ({unit.lower()} {p['slide']})" if p["slide"] else "") for p in recap["missed"]]
    corrections = [
        f"{unit} {issue['slide']}: {_short(issue['fix'] or issue['slide_quote'], 120)}" for issue in recap["corrections"]
    ]

    def build(covered_limit: int, missed_limit: int) -> str:
        who = " · ".join(part for part in [recap["explainer"], recap["date"], _minutes(recap["duration_seconds"])] if part)
        lines = [f"*{config.APP_NAME} recap: {recap['title']}*", f"_{who}_", ""]
        lines.append(f"✅ *Covered {len(covered)} of {recap['total']}*")
        lines += _list(covered, covered_limit)
        if missed:
            lines += ["", f"❌ *Missed {len(missed)}*"] + _list(missed, missed_limit)
        if corrections:
            lines += ["", f"⚠️ *Corrections {len(corrections)}*"] + _list(corrections, 4)
        lines += ["", f"_Made with {config.APP_NAME}, running offline on Gemma_"]
        return "\n".join(lines)

    # Missed points and corrections matter most, so the covered list shrinks first.
    covered_limit, missed_limit = 8, 10
    text = build(covered_limit, missed_limit)
    while len(text) > WHATSAPP_LIMIT and (covered_limit > 0 or missed_limit > 3):
        if covered_limit > 0:
            covered_limit -= 1
        else:
            missed_limit -= 1
        text = build(covered_limit, missed_limit)
    return text


def build_recap(session: dict) -> dict:
    points = session["outline"]["points"]
    done = set(coverage.covered_ids(session))
    recap = {
        "session_id": session["id"],
        "title": session["title"],
        "explainer": session["explainer"],
        "date": datetime.fromisoformat(session["created_at"]).strftime("%d %b %Y"),
        "duration_seconds": session.get("audio_seconds", 0.0),
        "unit": session.get("unit", "Slide"),
        "total": len(points),
        "covered": [p for p in points if p["id"] in done],
        "missed": [p for p in points if p["id"] not in done],
        # A dismissed correction ("That's not what I said") never reaches the recap.
        "corrections": [issue for issue in session["issues"] if not issue.get("dismissed")],
        "transcript_lines": len(session["transcript"]),
        "ended_at": session["ended_at"],
    }
    recap["whatsapp_text"] = whatsapp_text(recap, recap["unit"])
    return recap


def transcript_text(session: dict) -> str:
    """The full transcript as plain text, for the download."""
    lines = [f"{config.APP_NAME} transcript: {session['title']}"]
    if session["explainer"]:
        lines.append(f"Explained by {session['explainer']}")
    lines += [datetime.fromisoformat(session["created_at"]).strftime("%d %b %Y"), ""]
    for line in session["transcript"]:
        at = int(line["at"])
        lines.append(f"[{at // 60}:{at % 60:02d}] {line['text']}")
    if not session["transcript"]:
        lines.append("(Nothing was recorded.)")
    return "\n".join(lines) + "\n"
