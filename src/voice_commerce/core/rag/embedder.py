# core/rag/embedder_p6.py
# ──────────────────────────────────────────────────────────────────────────────
# Loads the sentence-transformer model once and exposes two functions:
#   embed(text)        → one 384-float vector for a single query string
#   embed_batch(texts) → list of 384-float vectors for many strings at once
#
# WHAT AN EMBEDDING IS:
#   A vector is a list of floats (384 numbers) that encodes the *meaning* of
#   a piece of text in a high-dimensional space. Texts with similar meanings
#   produce vectors that point in similar directions — measured by cosine similarity.
#
#   "running shoes"     → [0.12, -0.34,  0.89, ...]   ← 384 numbers
#   "jogging footwear"  → [0.11, -0.33,  0.87, ...]   ← very close direction
#   "winter jacket"     → [0.54,  0.21, -0.43, ...]   ← different direction
#
#   Cosine similarity between "running shoes" and "jogging footwear" ≈ 0.92
#   Cosine similarity between "running shoes" and "winter jacket"    ≈ 0.31
#
#   This is how "I need shoes for my morning jog" finds "Nike Air Zoom (running shoe)"
#   even though the words "jog" and "running" are different — their meanings are close.
#
# WHY LOAD THE MODEL AT MODULE IMPORT TIME (not lazily per request):
#   Loading a sentence-transformer model takes 2-4 seconds (reading ~470 MB from disk,
#   initialising PyTorch layers). If we loaded it on the first search request, that
#   user would wait 4 extra seconds with no audio — terrible experience.
#   Loading at import time means the delay happens at server startup, which is
#   expected and acceptable. Every subsequent request is fast (~1 ms per query embed).
#
# WHY embed_batch (not just calling embed() in a loop):
#   Transformer models process inputs as matrices. Feeding 100 texts as one batch
#   lets the model vectorise them all in parallel — roughly 10x faster than 100
#   separate calls. We use this during catalog sync at startup.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations


import structlog
import numpy as np
from sentence_transformers import SentenceTransformer

from voice_commerce.config.settings import settings



log = structlog.get_logger()
log.info("embedder_loading_model", model=settings.embedding_model)

# 1. Load the model immediately on startup
_MODEL = SentenceTransformer(settings.embedding_model)
log.info("embedder_model_loaded", model=settings.embedding_model, dim=_MODEL.get_sentence_embedding_dimension())

# 2. Dynamically extract the math dimension (e.g., 384) so Qdrant knows how big to make the database
_dim = _MODEL.get_sentence_embedding_dimension()
if _dim is None:
    log.warning("embedder_dim_missing_in_config", fallback="calculating_dynamically")
    # If the model's config is broken, force it to reveal its size by embedding a dummy word!
    _dummy_vector = _MODEL.encode("test", convert_to_numpy=True)
    _dim = len(_dummy_vector)
VECTOR_DIM: int = _dim
log.info("embedder_ready", model=settings.embedding_model, dim=VECTOR_DIM)

# # or ues 
# VECTOR_DIM: int = _MODEL.get_sentence_embedding_dimension() or 0
# or use 
# VECTOR_DIM: int = _MODEL.get_sentence_embedding_dimension() or len(_MODEL.encode("test", convert_to_numpy=True))


def embed(text: str) -> list[float]:
    """
    Convert one text string into a 384-float embedding vector.
 
    Used for: embedding a user's search query at search time.
    The resulting vector is compared against all stored product vectors
    to find the most semantically similar products.
 
    Returns a Python list[float] (not numpy array) because qdrant-client
    expects plain Python floats, and json.dumps() can serialise lists but
    not numpy arrays without a custom encoder.
    """
    if not text or not text.strip():
        # Fallback for empty strings so the database doesn't crash
        # Zero vector for empty queries — Qdrant will return low-confidence results.
        # The caller (rag_service) checks for empty queries before calling embed().
        return [0.0] * VECTOR_DIM    
    
    # encode() creates the math. convert_to_numpy=True ensures it's an array we can .tolist()
    vector: np.ndarray = _MODEL.encode(text, convert_to_numpy=True)
    return vector.tolist()



def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Convert many text strings into embedding vectors in one batch call.
 
    Used for: embedding the entire product catalog at startup (catalog sync).
    Batching is ~10x faster than calling embed() in a loop because the model
    processes all texts as a single matrix operation.
 
    Args:
        texts: List of strings to embed. Order is preserved.
 
    Returns:
        List of vectors in the same order as the input texts.
        len(result) == len(texts), each inner list has VECTOR_DIM floats.
    """
    if not texts :
        return []

    log.debug("embedder_batch_start", count=len(texts))

    vectors: np.ndarray = _MODEL.encode(texts, convert_to_numpy=True, show_progress_bar=False ,batch_size=64)
    log.debug("embedder_batch_end", count=len(vectors), dim=vectors.shape[1])
    return vectors.tolist()
    
