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
from typing import Any, TypedDict, TypeAlias
import time
from collections import Counter

import structlog
import asyncio

from voice_commerce.core.rag import embedder
from voice_commerce.core.rag.vector_store import VectorStore
from voice_commerce.core.rag.retriever import Retriever
from voice_commerce.models.product import Product

# from voice_commerce.services.woocommerce_client import get_client
from voice_commerce.services.csv_client import get_client

log = structlog.get_logger()


class CategoryPathParts(TypedDict):
    full_path: str
    main_category: str
    sub_category: str
    leaf_category: str


class CategoryProductSnapshot(TypedDict):
    id: int
    name: str
    price: float
    stock_status: str
    main_category: str
    sub_category: str
    leaf_category: str
    full_path: str


class CategorySummaryEntry(TypedDict):
    count: int
    example_names: list[str]
    min_price: float
    max_price: float
    subcategories: list[str]
    parent_groups: list[str]


CategorySummary: TypeAlias = dict[str, CategorySummaryEntry]
ProductsByCategory: TypeAlias = dict[str, list[CategoryProductSnapshot]]
CategoryLookup: TypeAlias = dict[str, str]

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
        self._product_lookup: dict[int, Product] = {}
        self._category_summary: CategorySummary = {}
        self._products_by_category: ProductsByCategory = {}
        self._category_lookup: CategoryLookup = {}

    @staticmethod
    def _normalize_category_key(value: str) -> str:
        """Normalize category strings for case-insensitive matching."""
        return " ".join(str(value or "").strip().lower().split())

    @staticmethod
    def _parse_category_path(raw_name: str) -> CategoryPathParts:
        """
        Parse category hierarchy into full/main/sub/leaf names.
        Supports single-level and hierarchical paths (e.g. "Men > Shoes > Running").
        """
        clean_name = str(raw_name or "").strip()
        if not clean_name:
            return {
                "full_path": "Uncategorized",
                "main_category": "Uncategorized",
                "sub_category": "Uncategorized",
                "leaf_category": "Uncategorized",
            }

        segments = [part.strip() for part in clean_name.split(">") if part.strip()]
        if not segments:
            segments = ["Uncategorized"]

        main_category = segments[0]
        sub_category = segments[1] if len(segments) > 1 else main_category
        leaf_category = segments[-1]
        return {
            "full_path": " > ".join(segments),
            "main_category": main_category,
            "sub_category": sub_category,
            "leaf_category": leaf_category,
        }

    @classmethod
    def _build_product_snapshot(
        cls, product: Product, parsed_path: CategoryPathParts
    ) -> CategoryProductSnapshot:
        """Build the slim deterministic snapshot used for grouped category retrieval."""
        return {
            "id": product.id,
            "name": product.name,
            "price": float(product.price),
            "stock_status": product.stock_status,
            "main_category": parsed_path["main_category"],
            "sub_category": parsed_path["sub_category"],
            "leaf_category": parsed_path["leaf_category"],
            "full_path": parsed_path["full_path"],
        }

    @staticmethod
    def _copy_product_snapshot(item: CategoryProductSnapshot) -> CategoryProductSnapshot:
        """Return a typed shallow copy of a category product snapshot."""
        return {
            "id": item["id"],
            "name": item["name"],
            "price": item["price"],
            "stock_status": item["stock_status"],
            "main_category": item["main_category"],
            "sub_category": item["sub_category"],
            "leaf_category": item["leaf_category"],
            "full_path": item["full_path"],
        }

    @staticmethod
    def _copy_category_summary_entry(data: CategorySummaryEntry) -> CategorySummaryEntry:
        """Return a typed shallow copy of a category summary entry."""
        return {
            "count": data["count"],
            "example_names": list(data["example_names"]),
            "min_price": data["min_price"],
            "max_price": data["max_price"],
            "subcategories": list(data["subcategories"]),
            "parent_groups": list(data["parent_groups"]),
        }

    def _build_category_indexes(
        self, products: list[Product]
    ) -> tuple[CategorySummary, ProductsByCategory, CategoryLookup]:
        """
        Build category summary and grouped product snapshots from loaded products.
        Grouping key is the leaf category because UX/tooling uses product-type filters
        like Bags, Jackets, Pants, Watches (not high-level containers like Clothing).
        """
        log.debug("rag_category_index_build_start", product_count=len(products))
        grouped: ProductsByCategory = {}

        for product in products:
            if product.categories:
                raw_paths = [cat.name for cat in product.categories if cat.name]
            else:
                raw_paths = ["Uncategorized"]

            # Avoid duplicate category path processing for the same product
            for raw_path in set(raw_paths):
                parsed = self._parse_category_path(raw_path)
                leaf_category = parsed["leaf_category"]
                grouped.setdefault(leaf_category, []).append(
                    self._build_product_snapshot(product, parsed)
                )

        summary: CategorySummary = {}
        for category, items in grouped.items():
            items_sorted = sorted(
                items,
                key=lambda item: (
                    item["stock_status"] != "instock",
                    item["price"],
                    item["name"].lower(),
                    item["id"],
                ),
            )
            subcategory_counts = Counter(
                item["sub_category"] for item in items_sorted if item["sub_category"]
            )
            parent_groups = Counter(
                item["main_category"] for item in items_sorted if item["main_category"]
            )
            summary[category] = {
                "count": len(items_sorted),
                "example_names": [item["name"] for item in items_sorted[:2]],
                "min_price": min(item["price"] for item in items_sorted),
                "max_price": max(item["price"] for item in items_sorted),
                "subcategories": [name for name, _ in subcategory_counts.most_common(3)],
                "parent_groups": [name for name, _ in parent_groups.most_common(2)],
            }
            grouped[category] = items_sorted

        log.info(
            "rag_category_index_build_complete",
            category_count=len(summary),
            grouped_bucket_count=len(grouped),
            # top_categories=sorted(summary.keys())[:] if summary else [],
        )
        category_lookup: CategoryLookup = {
            self._normalize_category_key(category_name): category_name for category_name in summary
        }
        return summary, grouped, category_lookup

    @property
    def category_summary(self) -> CategorySummary:
        """Safe read access to category summary metadata."""
        return {
            name: self._copy_category_summary_entry(data)
            for name, data in self._category_summary.items()
        }

    @property
    def products_by_category(self) -> ProductsByCategory:
        """Safe read access to grouped slim product snapshots."""
        return {
            name: [self._copy_product_snapshot(item) for item in items]
            for name, items in self._products_by_category.items()
        }

    def list_categories(self) -> list[str]:
        """Return known leaf categories sorted by descending product count."""
        return [
            name
            for name, _ in sorted(
                self._category_summary.items(),
                key=lambda pair: (-int(pair[1].get("count", 0)), pair[0].lower()),
            )
        ]

    def resolve_category_name(self, category: str) -> str | None:
        """
        Resolve a user-provided category to a known leaf category.

        Tries normalized exact match first, then a single unambiguous partial match.
        """
        normalized_category = self._normalize_category_key(category)
        if not normalized_category:
            return None

        exact_match = self._category_lookup.get(normalized_category)
        if exact_match:
            return exact_match

        contains_matches = [
            category_name
            for category_name in self.list_categories()
            if normalized_category in self._normalize_category_key(category_name)
        ]
        if len(contains_matches) == 1:
            return contains_matches[0]

        return None

    @staticmethod
    def _normalize_query_text(value: str) -> str:
        """Normalize free-text queries for lightweight rule-based reranking."""
        return " ".join(str(value or "").strip().lower().split())

    def _preferred_categories_for_query(self, query: str) -> tuple[set[str], set[str]]:
        """
        Infer preferred and discouraged categories from obvious intent words.

        This is a narrow heuristic layer on top of vector search, not a replacement.
        """
        normalized_query = self._normalize_query_text(query)
        preferred: set[str] = set()
        discouraged: set[str] = set()

        direct_category_rules = {
            "short": "Shorts",
            "shorts": "Shorts",
            "t-shirt": "Tees",
            "t-shirts": "Tees",
            "t shirts": "Tees",
            "t shirt": "Tees",
            "tshirt": "Tees",
            "tshirts": "Tees",
            "tee": "Tees",
            "tees": "Tees",
            "shirt": "Tees",
            "shirts": "Tees",
            "tank": "Tanks",
            "tanks": "Tanks",
            "bra": "Bras & Tanks",
            "bras": "Bras & Tanks",
            "jacket": "Jackets",
            "jackets": "Jackets",
            "pant": "Pants",
            "pants": "Pants",
            "hoodie": "Hoodies & Sweatshirts",
            "hoodies": "Hoodies & Sweatshirts",
            "sweatshirt": "Hoodies & Sweatshirts",
            "sweatshirts": "Hoodies & Sweatshirts",
            "watch": "Watches",
            "watches": "Watches",
            "bag": "Bags",
            "bags": "Bags",
        }
        for token, category_name in direct_category_rules.items():
            if token in normalized_query:
                preferred.add(category_name)

        summer_cues = {
            "summer",
            "light",
            "lighter",
            "lightweight",
            "cool",
            "breathable",
            "hot weather",
            "warm weather",
        }
        if any(cue in normalized_query for cue in summer_cues):
            preferred.update({"Shorts", "Tees", "Tanks", "Bras & Tanks", "Performance Fabrics"})
            discouraged.update({"Hoodies & Sweatshirts", "Jackets", "Pants"})

        return preferred, discouraged

    def _strict_category_for_query(self, query: str) -> str | None:
        """
        Return one clear category intent when the query explicitly names a product type.

        This is used to stop pagination from drifting into semantically-related but
        wrong categories, e.g. "shorts" later returning pants or tees.
        """
        normalized_query = self._normalize_query_text(query).replace("-", " ")
        strict_rules = {
            "short": "Shorts",
            "shorts": "Shorts",
            "t-shirt": "Tees",
            "t-shirts": "Tees",
            "t shirts": "Tees",
            "t shirt": "Tees",
            "tshirt": "Tees",
            "tshirts": "Tees",
            "tee": "Tees",
            "tees": "Tees",
            "shirt": "Tees",
            "shirts": "Tees",
            "tank": "Tanks",
            "tanks": "Tanks",
            "bra": "Bras & Tanks",
            "bras": "Bras & Tanks",
            "jacket": "Jackets",
            "jackets": "Jackets",
            "pant": "Pants",
            "pants": "Pants",
            "hoodie": "Hoodies & Sweatshirts",
            "hoodies": "Hoodies & Sweatshirts",
            "sweatshirt": "Hoodies & Sweatshirts",
            "sweatshirts": "Hoodies & Sweatshirts",
            "watch": "Watches",
            "watches": "Watches",
            "bag": "Bags",
            "bags": "Bags",
        }

        matches = {
            category_name
            for phrase, category_name in strict_rules.items()
            if phrase in normalized_query
        }
        if len(matches) == 1:
            return next(iter(matches))
        return None

    def _rerank_products_for_query(self, query: str, products: list[Product]) -> list[Product]:
        """
        Apply a light heuristic rerank over vector results to reduce obvious bad fits.
        """
        normalized_query = self._normalize_query_text(query)
        preferred_categories, discouraged_categories = self._preferred_categories_for_query(
            normalized_query
        )
        query_terms = set(normalized_query.replace("-", " ").split())

        if not products:
            return []

        scored: list[tuple[float, Product]] = []
        for original_rank, product in enumerate(products):
            score = float(len(products) - original_rank)
            product_name = self._normalize_query_text(product.name)
            product_short = self._normalize_query_text(product.short_description)
            product_desc = self._normalize_query_text(product.description)
            product_categories = {name for name in product.category_names}

            for category_name in preferred_categories:
                if category_name in product_categories:
                    score += 12.0
            for category_name in discouraged_categories:
                if category_name in product_categories:
                    score -= 10.0

            if query_terms:
                for term in query_terms:
                    if len(term) < 3:
                        continue
                    if term in product_name:
                        score += 4.0
                    if term in product_short:
                        score += 2.0
                    if term in product_desc:
                        score += 1.0

            scored.append((score, product))

        scored.sort(key=lambda item: (-item[0], item[1].price, item[1].name.lower(), item[1].id))
        return [product for _, product in scored]

    def search_category_summaries(
        self, keyword: str | None = None
    ) -> list[tuple[str, CategorySummaryEntry]]:
        """Return category summaries sorted by descending count, optionally filtered by keyword."""
        normalized_keyword = self._normalize_category_key(keyword or "")
        matches: list[tuple[str, CategorySummaryEntry]] = []

        for category_name, summary in self._category_summary.items():
            haystacks = [
                self._normalize_category_key(category_name),
                *[self._normalize_category_key(name) for name in summary.get("subcategories", [])],
                *[self._normalize_category_key(name) for name in summary.get("parent_groups", [])],
            ]
            if not normalized_keyword or any(normalized_keyword in value for value in haystacks):
                matches.append((category_name, self._copy_category_summary_entry(summary)))

        matches.sort(key=lambda item: (-int(item[1].get("count", 0)), item[0].lower()))
        return matches

    def get_products_for_category(
        self,
        category: str,
        *,
        max_price: float | None = None,
        in_stock_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CategoryProductSnapshot]:
        """
        Internal deterministic retrieval helper for browse/category-constrained retrieval.
        """
        resolved_category = self.resolve_category_name(category)
        if not resolved_category:
            return []

        items = [
            self._copy_product_snapshot(item)
            for item in self._products_by_category.get(resolved_category, [])
        ]
        if max_price is not None:
            items = [item for item in items if item["price"] <= max_price]
        if in_stock_only:
            items = [item for item in items if item["stock_status"] == "instock"]
        safe_offset = max(0, int(offset))
        if safe_offset:
            items = items[safe_offset:]
        if limit is not None:
            items = items[: max(1, int(limit))]
        return items

    def _get_full_products_for_category(
        self,
        category: str,
        *,
        max_price: float | None = None,
        in_stock_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Product]:
        """Return full Product models for one resolved category using the cached catalog."""
        snapshots = self.get_products_for_category(
            category,
            max_price=max_price,
            in_stock_only=in_stock_only,
            limit=limit,
            offset=offset,
        )
        products: list[Product] = []
        for item in snapshots:
            product = self._product_lookup.get(int(item["id"]))
            if product is not None:
                products.append(product)
        return products

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

        self._product_lookup = {product.id: product for product in all_products}

        # 1.5 Build category intelligence caches for prompt/context and deterministic retrieval.
        self._category_summary, self._products_by_category, self._category_lookup = (
            self._build_category_indexes(all_products)
        )
        log.info(
            "rag_category_caches_ready",
            category_count=len(self._category_summary),
            grouped_category_count=len(self._products_by_category),
            sample_categories=list(self._category_summary.keys())[:],
        )

        log.info("rag_sync_building_texts", count=len(all_products))

        # 2. Build embedding texts
        texts = [p.to_embedding_text() for p in all_products]

        # 3. Embed ALL texts in a background thread (Prevents server freezing!)
        try:
            loop = asyncio.get_running_loop()
            vectors = await loop.run_in_executor(None, lambda: embedder.embed_batch(texts))
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
        offset: int = 0,
        max_price: float | None = None,
        category: str | None = None,
    ) -> list[Product]:
        """
        Semantic product search. Runs on every user voice command.
        Embed query and find most similar products using Qdrant.
        """

        # Fallback if someone speaks before the server finishes booting
        if not self._sync_complete:
            log.warning("rag_search_collection_not_ready_yet")
            return []

        strict_category = self._strict_category_for_query(query)
        if strict_category and not category:
            category_results = self._get_full_products_for_category(
                strict_category,
                max_price=max_price,
                in_stock_only=False,
                limit=max(limit, 25),
                offset=max(0, offset),
            )
            if category_results:
                reranked_category_results = self._rerank_products_for_query(query, category_results)
                log.info(
                    "rag_search_category_browse_applied",
                    query=query[:80],
                    category=strict_category,
                    available=len(category_results),
                    returned=min(limit, len(reranked_category_results)),
                )
                return reranked_category_results[:limit]

        # Run CPU-bound embedding in thread pool so it doesn't interrupt audio streams
        loop = asyncio.get_running_loop()
        try:
            retrieval_limit = max(limit, 25)
            search_results = await loop.run_in_executor(
                None,
                lambda: self.retriever.retrieve(
                    query=query,
                    limit=retrieval_limit,
                    offset=max(0, offset),
                    max_price=max_price,
                ),
            )
        except Exception as e:
            log.exception("rag_search_error", query=query[:80], error=str(e))
            return []

        if category:
            resolved_category = self.resolve_category_name(category)
            if not resolved_category:
                return []

            allowed_ids = {
                item["id"]
                for item in self.get_products_for_category(
                    resolved_category,
                    max_price=max_price,
                    in_stock_only=False,
                )
            }
            search_results = [product for product in search_results if product.id in allowed_ids]

        if strict_category:
            constrained_results = [
                product for product in search_results if strict_category in product.category_names
            ]
            if constrained_results:
                log.info(
                    "rag_search_strict_category_applied",
                    query=query[:80],
                    category=strict_category,
                    before=len(search_results),
                    after=len(constrained_results),
                )
                search_results = constrained_results

        reranked_results = self._rerank_products_for_query(query, search_results)
        return reranked_results[:limit]

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
            "category_count": len(self._category_summary),
            "embedder_ready": embedder.is_ready(),
            "embedder_error": embedder.last_error(),
        }
