from __future__ import annotations

from voice_commerce.models.product import Product, ProductCategory
from voice_commerce.services.rag_service import RagService
from voice_commerce.core.voice import prompts
def _product(
    *,
    product_id: int,
    name: str,
    price: float,
    category_paths: list[str],
    stock_status: str = "instock",
) -> Product:
    return Product(
        id=product_id,
        name=name,
        price=price,
        stock_status=stock_status,
        categories=[ProductCategory(name=path, slug=path.lower().replace(" ", "-")) for path in category_paths],
    )


def test_parse_category_path_single_two_three_level() -> None:
    single = RagService._parse_category_path("Shoes")
    assert single == {
        "full_path": "Shoes",
        "main_category": "Shoes",
        "sub_category": "Shoes",
        "leaf_category": "Shoes",
    }

    two_level = RagService._parse_category_path("Men > Shoes")
    assert two_level == {
        "full_path": "Men > Shoes",
        "main_category": "Men",
        "sub_category": "Shoes",
        "leaf_category": "Shoes",
    }

    three_level = RagService._parse_category_path("Men > Shoes > Running")
    assert three_level == {
        "full_path": "Men > Shoes > Running",
        "main_category": "Men",
        "sub_category": "Shoes",
        "leaf_category": "Running",
    }


def test_build_category_indexes_summary_and_grouped_snapshots() -> None:
    rag = RagService()
    products = [
        _product(product_id=1, name="Road Runner", price=120.0, category_paths=["Men > Shoes > Running"]),
        _product(product_id=2, name="Trail Pro", price=180.0, category_paths=["Men > Shoes > Trail"], stock_status="outofstock"),
        _product(product_id=3, name="Lift Tee", price=35.0, category_paths=["Women > Apparel > Tops"]),
    ]

    summary, grouped = rag._build_category_indexes(products)

    assert set(summary.keys()) == {"Running", "Trail", "Tops"}
    assert summary["Running"]["count"] == 1
    assert summary["Trail"]["count"] == 1
    assert summary["Tops"]["count"] == 1

    running_items = grouped["Running"]
    assert len(running_items) == 1
    assert {"id", "name", "price", "stock_status", "main_category", "sub_category", "leaf_category", "full_path"} <= set(
        running_items[0].keys()
    )
    assert running_items[0]["main_category"] == "Men"
    assert running_items[0]["leaf_category"] == "Running"


def test_safe_read_accessors_return_copies() -> None:
    rag = RagService()
    rag._category_summary = {
        "Men": {
            "count": 1,
            "example_names": ["Road Runner"],
            "min_price": 99.0,
            "max_price": 99.0,
            "subcategories": ["Shoes"],
        }
    }
    rag._products_by_category = {
        "Men": [
            {
                "id": 1,
                "name": "Road Runner",
                "price": 99.0,
                "stock_status": "instock",
                "main_category": "Men",
                "sub_category": "Shoes",
                "leaf_category": "Running",
                "full_path": "Men > Shoes > Running",
            }
        ]
    }

    summary_copy = rag.category_summary
    grouped_copy = rag.products_by_category

    summary_copy["Men"]["example_names"].append("Mutated")
    grouped_copy["Men"][0]["name"] = "Changed"

    assert rag._category_summary["Men"]["example_names"] == ["Road Runner"]
    assert rag._products_by_category["Men"][0]["name"] == "Road Runner"


def test_prompt_includes_category_summary_or_fallback() -> None:
    with_summary = prompts.build_system_prompt(
        transcript=[],
        assistant_name="PHOENIX",
        store_name="NEXFIT",
        store_tagline="Sports gear",
        category_list="Shoes, Apparel",
        category_summary_text="- Shoes | 25 products | $45.00-$199.00 | Road Runner, Trail Pro",
        is_resumed_session=False,
    )
    assert "Category intelligence:" in with_summary
    assert "Shoes | 25 products" in with_summary

    with_fallback = prompts.build_system_prompt(
        transcript=[],
        assistant_name="PHOENIX",
        store_name="NEXFIT",
        store_tagline="Sports gear",
        category_list="Shoes, Apparel",
        is_resumed_session=False,
    )
    assert "Category intelligence is warming up; use live context + tools." in with_fallback


def test_format_category_summary_compact_lines() -> None:
    text = prompts.format_category_summary(
        {
            "Shoes": {
                "count": 25,
                "min_price": 45.0,
                "max_price": 199.0,
                "example_names": ["Road Runner", "Trail Pro"],
            },
            "Apparel": {
                "count": 9,
                "min_price": 20.0,
                "max_price": 79.0,
                "example_names": ["Lift Tee", "Sprint Shorts"],
            },
        }
    )
    assert "- Shoes | 25 products | $45-$199 | Road Runner, Trail Pro" in text
    assert "- Apparel | 9 products | $20-$79 | Lift Tee, Sprint Shorts" in text
