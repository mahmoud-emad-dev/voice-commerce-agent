# src/voice_commerce/core/rag/retriever.py
# =============================================================================
# PURPOSE:
#   Retrieval abstraction layer between rag_service and the vector store.
#
# WHY THIS LAYER EXISTS:
#   Without retriever.py, rag_service.py calls VectorStore directly.
#   With retriever.py, the flow is:
#       rag_service.py → Retriever.retrieve() → VectorStore.search_products()
#                                             → payload normalisation (via Pydantic)
#
#   This abstraction pays off when you want to:
#     1. Add BM25 keyword search alongside vector search (hybrid retrieval)
#     2. Add a cross-encoder re-ranker after the initial retrieval
#     3. Apply query expansion ("shoes" → ["shoes", "sneakers", "trainers"])
#     4. Swap Qdrant for pgvector without touching rag_service_p7.py
#     5. Test retrieval logic in isolation without needing a real vector store
# Future phases (not needed yet):
#   • hybrid_retrieve() — BM25 + vector, merged with Reciprocal Rank Fusion
#   • rerank()          — cross-encoder pass over top-k candidates
#   • expand_query()    — WordNet / LLM-based query expansion
# =============================================================================


from __future__ import annotations
from typing import Any

import structlog

from voice_commerce.core.rag import embedder
from voice_commerce.core.rag.vector_store import VectorStore
from voice_commerce.models.product import Product


log = structlog.get_logger()

class Retriever:
    """
    Retrieval layer: embed query → search Qdrant → normalise payloads using Pydantic.

    Usage in rag_service.py:
        retriever = Retriever(vector_store=self._store)
        results = retriever.retrieve(
            query="warm jacket for hiking",
            limit=5,
            max_price=200.0,
        )
        # results: list of normalised product dicts ready for Gemini
    """
    def __init__(self, vector_store: VectorStore) -> None:
        self._store = vector_store

    def retrieve(
        self,
        query: str,
        limit: int = 5,
        max_price: float | None = None,
        ) -> list[Product]:
        """
        Embed the query and search Qdrant for the most similar products.

        Args:
            query:        natural-language string in any language
            limit:        max results to return
            max_price:    optional price ceiling, applied natively in Qdrant

        Returns:
            list of normalised product dicts.
            Each dict perfectly matches the format of Product.to_tool_summary().
        """
        if not query.strip():
            log.warning("retriever_empty_query")
            return []

        # 1. Embed the user's spoken query
        log.debug("retriever_embedding_query", query=query[:80])
        try:
            query_vector = embedder.embed(query)
        except Exception as e:
            log.error("retriever_embed_error", error=str(e))
            return []

        # 2. Search Qdrant (Returns perfectly hydrated Pydantic models!) 
        try:
            retrieved_products = self._store.search_products(query_vector, limit, max_price)
        except Exception as e:
            log.exception("retriever_search_failed", query=query[:80], error=str(e))
            return []
        
        log.info(
            "retriever_results",
            query=query[:60],
            count=len(retrieved_products),
        )
        return retrieved_products