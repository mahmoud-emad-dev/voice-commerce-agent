"""
RAG Service: Orchestrates WooCommerce → Qdrant catalog sync and semantic search.

SYNC (startup, ~5–60s):
    1. Fetch all products from WooCommerce
    2. Build rich text for each product
    3. Embed all texts in batch
    4. Upsert to Qdrant by product ID

SEARCH (per query, ~20–100ms):
    1. Embed query
    2. Retrieve similar products from Qdrant
    3. Return results with filters

SINGLETON PATTERN:
    One RagService per process. The embedding model (~300 MB) and Qdrant client
    are expensive to create. get_rag_service() returns the module-level singleton.
    All concurrent voice sessions share one instance. Phase 12 (multi-tenancy)
    creates one RagService per tenant by collection_name.
"""


from __future__ import annotations
from typing import Any
import re
import time 

import structlog
import asyncio

from voice_commerce.core.rag import embedder
from voice_commerce.core.rag.vector_store import VectorStore
from voice_commerce.core.rag.retriever import Retriever
from voice_commerce.models.product import Product
from voice_commerce.services.woocommerce_client import get_client


log = structlog.get_logger()

# ── Module-level singleton ────────────────────────────────────────────────────
_service_instance: "RagService | None" = None

def get_rag_service() -> "RagService":
    """
    Return the global RagService singleton, creating it if needed.
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = RagService()
    return _service_instance

# ── The Rich Text Builder ────────────────────────────────────────────────────
def _build_rich_text(product: Product) -> str:
    """
    Turns a WooCommerce product into a dense semantic paragraph for the AI.
    """
    cats = ", ".join(cat.name for cat in product.categories) if product.categories else ""
    tags = ", ".join(tag.name for tag in product.tags) if product.tags else ""   
# <p>Great shoe!</p><br><b>Buy now</b>
    clean_description = re.sub(r"<[^>]+>", " ", product.description).strip()
    return f"Name: {product.name}. Category: {cats}. Tags: {tags}. Price: ${product.price}. Description: {clean_description}"

# ── Service class ─────────────────────────────────────────────────────────────
class RagService:
    """
    High-level RAG service: sync WooCommerce catalog → Qdrant, search by query.
    """

    def __init__(self) -> None:
        self.v_store = VectorStore()
        self.retriever = Retriever(self.v_store)
        self._sync_complete = False
        self._products_indexed = 0


    # ── Catalog sync ──────────────────────────────────────────────────────────
    async def sync_catalog(self) -> int:
        """
        Fetch all products from WooCommerce, embed them, upsert to Qdrant.
        Runs entirely in the background (non-blocking).
        """
        log.info("rag_sync_starting")
        t0 = time.perf_counter()

        # 1. Fetch all products from WooCommerce
        log.info("rag_sync_fetching_products")
        try:
            wc_client = get_client()
            all_products = await wc_client.list_all_products()
        except Exception as e:
            log.exception("rag_sync_woocommerce_error", error=str(e))
            return 0

        if not all_products:
            log.warning("rag_sync_no_products")
            return 0

        log.info("rag_sync_building_texts", count=len(all_products))


        # 2. Build embedding texts
        texts = [_build_rich_text(p) for p in all_products]

        # 3. Embed ALL texts in a background thread (Prevents server freezing!)
        try:
            loop = asyncio.get_running_loop()
            vectors = await loop.run_in_executor(
                None, 
                lambda: embedder.embed_batch(texts) 
            )
        except Exception as e:
            log.error("rag_sync_embed_error", error=str(e))
            return 0
        log.info("rag_sync_embedding_done", count=len(vectors))

        # 4. Upsert to Qdrant (We removed Claude's manual dicts, we just pass lists!)
        try:
            indexed_products = self.v_store.upsert(all_products, vectors)
        except Exception as e:
            log.error("rag_sync_upsert_error", error=str(e))
            return 0

        elapsed = time.perf_counter() - t0
        self._sync_complete = True
        self._products_indexed = indexed_products

        log.info(
            "rag_catalog_sync_complete",
            indexed=indexed_products,
            seconds=round(elapsed, 2),
        )
        return indexed_products



    # ── Search ────────────────────────────────────────────────────────────────
    async def search_products(
        self,
        query: str,
        limit: int = 5,
        max_price: float | None = None,
    ) -> list[Product]:
        """
        Semantic product search. Runs on every user voice command.
        Embed query and find most similar products using Qdrant.
        """

        # Fallback if someone speaks before the server finishes booting
        if not self._sync_complete:
            log.warning("rag_search_collection_not_ready_yet")
            return []
        
        # Run CPU-bound embedding in thread pool so it doesn't interrupt audio streams
        loop = asyncio.get_running_loop()
        try:
            search_results = await loop.run_in_executor(None, lambda: self.retriever.retrieve(query, limit, max_price))
        except Exception as e:
            log.exception("rag_search_error", query=query[:80], error=str(e))
            return []

        return search_results
    
    # ── Stats ─────────────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        """True when catalog has been synced at least once."""
        return self._sync_complete
    
    
    def stats(self) -> dict[str, Any]:
        """Return current sync status and indexed product count."""
        return {
            "sync_complete": self._sync_complete,
            "products_indexed": self._products_indexed,
            "qdrant_count": self.v_store.count,
        }