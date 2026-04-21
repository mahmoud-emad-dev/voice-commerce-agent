from __future__ import annotations

import asyncio
import threading

import numpy as np
import structlog
from sentence_transformers import SentenceTransformer

from voice_commerce.config.settings import settings


log = structlog.get_logger(__name__)

# Keep vector size available at import time so Qdrant can initialize cheaply.
VECTOR_DIM: int = settings.embedding_dimension

_MODEL: SentenceTransformer | None = None
_MODEL_LOAD_ERROR: str | None = None
_MODEL_LOCK = threading.Lock()


def _load_model_once() -> SentenceTransformer:
    """Load the embedding model exactly once per process."""
    global _MODEL, _MODEL_LOAD_ERROR

    if _MODEL is not None:
        return _MODEL

    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL

        log.info("embedder_loading_model", model=settings.embedding_model)
        try:
            model = SentenceTransformer(settings.embedding_model)
        except Exception as exc:
            _MODEL_LOAD_ERROR = str(exc)
            log.exception(
                "embedder_model_load_failed",
                model=settings.embedding_model,
                error=str(exc),
            )
            raise

        actual_dim = model.get_sentence_embedding_dimension()
        if actual_dim and actual_dim != VECTOR_DIM:
            log.warning(
                "embedder_dimension_mismatch",
                configured_dim=VECTOR_DIM,
                actual_dim=actual_dim,
                model=settings.embedding_model,
            )

        _MODEL = model
        _MODEL_LOAD_ERROR = None
        log.info(
            "embedder_model_loaded",
            model=settings.embedding_model,
            dim=actual_dim or VECTOR_DIM,
        )
        return _MODEL


def is_ready() -> bool:
    """True after the sentence-transformer model has been loaded."""
    return _MODEL is not None


def last_error() -> str | None:
    """Return the last model load error, if any."""
    return _MODEL_LOAD_ERROR


async def warmup() -> None:
    """Load the embedding model in a worker thread during startup."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _load_model_once)
    log.info("embedder_ready", model=settings.embedding_model, dim=VECTOR_DIM)


def embed(text: str) -> list[float]:
    """
    Convert one text string into an embedding vector.

    Used for: embedding a user's search query at search time.
    """
    if not text or not text.strip():
        return [0.0] * VECTOR_DIM

    model = _load_model_once()
    vector: np.ndarray = model.encode(text, convert_to_numpy=True)
    return vector.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Convert many text strings into embedding vectors in one batch call.
    """
    if not texts:
        return []

    model = _load_model_once()
    log.debug("embedder_batch_start", count=len(texts))
    vectors: np.ndarray = model.encode(
        texts,
        convert_to_numpy=True,
        show_progress_bar=False,
        batch_size=64,
    )
    log.debug("embedder_batch_end", count=len(vectors), dim=vectors.shape[1])
    return vectors.tolist()
