"""Pydantic schemas: the shapes of the JSON the API sends and receives."""
from pydantic import BaseModel


class PointIn(BaseModel):
    """One outline point as sent by the UI. New points have no id yet."""
    id: str | None = None
    text: str
    slide: int | None = None


class OutlineUpdate(BaseModel):
    points: list[PointIn]


class Problem(BaseModel):
    """Something that is broken, and how to fix it. Shown as a banner."""
    title: str
    fix: str


class Health(BaseModel):
    app_name: str
    model_name: str
    ollama_ok: bool
    model_present: bool
    whisper_loaded: bool
    embedder_loaded: bool
    problems: list[Problem]
