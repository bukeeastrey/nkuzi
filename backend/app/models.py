"""Pydantic schemas: the shapes of the JSON the API sends and receives."""
from pydantic import BaseModel


class Health(BaseModel):
    app_name: str
    model_name: str
    # Ollama + Gemma
    ollama_ok: bool
    model_present: bool
    ollama_message: str
    # Speech model (faster-whisper)
    whisper_loaded: bool
    whisper_message: str
    # Embedding model (fastembed)
    embedder_loaded: bool
    embedder_message: str
