

from __future__ import annotations 

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import ( 
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    Range,
    SearchParams,
    ScoredPoint,
)

from voice_commerce.config.settings import settings
from voice_commerce.core.rag.embedder import VECTOR_DIM
from voice_commerce.models.product import Product

log = structlog.get_logger(__name__)

class VectorStore:
    """
    In-memory Qdrant vector store for product embeddings.
    One instance created at startup in main.py lifespan, stored on app.state.
    """
    def __init__(self) -> None:
        # ":memory:" creates an in-process Qdrant — no network, no files.
        self._client = QdrantClient(":memory:")
        self._collection = settings.qdrant_collection
        self._ensure_collection()
        log.info("vector_store_ready", collection=self._collection, dim=VECTOR_DIM)

    def _ensure_collection(self) -> None:
        """
        Create the Qdrant collection if it doesn't already exist.
 
        VectorParams specifies two things:
          size=VECTOR_DIM:      every stored vector must have exactly this many floats.
                                Must match the embedding model's output dimension.
          distance=Distance.COSINE: how similarity is measured between vectors.
 
        WHY COSINE DISTANCE (not Euclidean or dot product):
          Cosine similarity measures the ANGLE between two vectors, ignoring magnitude.
          Text embeddings can have different magnitudes depending on text length —
          a short product name and a long description may produce vectors of very
          different magnitudes even if they describe the same thing.
          Cosine similarity is magnitude-independent, making it more reliable for
          comparing texts of varying lengths. It is the standard for text embeddings.
        """
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=VECTOR_DIM , distance=Distance.COSINE),
            )
            log.info("vector_store_collection_created",
                     collection=self._collection, dim=VECTOR_DIM)

    def upsert(self, products: list[Product], vectors: list[list[float]]) -> int:
        """
        Store or update product vectors in Qdrant.
 
        "Upsert" = insert if new, update if already exists (same product ID).
        This makes catalog sync idempotent — running it twice doesn't
        create duplicate entries; it just overwrites with fresh data.
 
        PAYLOAD — what is stored alongside each vector:
          We store enough product fields in the payload so that a search
          result can be returned to Gemini without a second WooCommerce call.
          The payload is essentially a cache of the product's display data.
 
          We do NOT store every WooCommerce field — only what search_products()
          needs to build its result string. This keeps Qdrant memory lean.
 
        Args:
            products: list of parsed product dicts from _parse_product()
            vectors:  corresponding embedding vectors, same order and length
        """
        if not products or not vectors:
            return 0
        
        assert len(products) == len(vectors), "products and vectors must have equal length"

        points = []
        for product, vector in zip(products, vectors):
            points.append(
                PointStruct(
                    id=product.id, # WooCommerce integer ID
                    vector=vector,
                    # We store the ENTIRE Pydantic model as a dictionary cache
                    payload=product.model_dump(),
                    # payload={              # stored alongside vector, returned in search results
                    # "id":          product.id,
                    # "name":        product.name,
                    # "price":       product.price,
                    # "stock":       product.stock_quantity,
                    # "description": product.description,
                    # "categories":  product.categories,
                    # "tags":        product.tags,
                    # "sku":         product.sku,
                    # "permalink":   product.permalink,
                    # },
                )
            )
        self._client.upsert(collection_name=self._collection, points=points, wait=True)
        log.info("vector_store_upserted", count=len(points))
        return len(points)



    def search_products(
        self,
        query_vector: list[float],
        limit: int = 5,
        offset: int = 0,
        max_price: float | None = None,
    ) -> list[Product]:
        """
        Find the top-k most similar product vectors to the query vector.
 
        Returns a list of payload dicts (product data) sorted by similarity,
        most similar first. The similarity score is not included — Gemini
        doesn't need to know how confident the search was.
 
        QDRANT FILTER WITH max_price:
          Qdrant can combine vector similarity search with payload field filters.
          Filter(must=[FieldCondition(key="price", range=Range(lte=max_price))])
          means: "from all products whose price ≤ max_price, find the most
          similar vectors to the query."
          This is much more efficient than: search everything → filter in Python.
          Qdrant applies the filter before the similarity search, not after.
 
        score_threshold=0.45:
          Cosine similarity ranges from -1 (opposite) to 1 (identical).
          0.3 is a loose minimum — below this, the match is too weak to be
          a meaningful result. Prevents returning "winter jacket" for "running
          shoes" just because it's the closest thing in an empty catalog.
          Raise to 0.4-0.5 if you get too many irrelevant results.
          Lower to 0.2 if you get too few results on edge-case queries.
        """
        query_filter = None
        # ── DATABASE-LEVEL FILTERING ─────────────────────────────────────────
        if max_price is not None:
            query_filter = Filter(
                must=[
                    FieldCondition(key="price", range=Range(lte=max_price))
                ]
            )
        
        results = self._client.query_points(
            collection_name=self._collection,
            query=query_vector,
            limit=limit,
            offset=max(0, offset),
            query_filter=query_filter,
            score_threshold=0.45,
        ).points
        log.debug("vector_store_search", results=len(results))
        # Re-hydrate the results back into our beautiful Pydantic objects
        return [Product(**hit.payload) for hit in results if hit.payload]
    
    @property
    def count(self) -> int:
        """Number of product vectors currently stored."""
        info = self._client.get_collection(self._collection)
        return info.points_count or 0



