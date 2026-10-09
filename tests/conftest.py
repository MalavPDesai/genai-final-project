from pathlib import Path

import pytest

from database import Database, initialize_schema, seed_from_json
from rag import PolicyRAG
from tools import HotelTools


@pytest.fixture()
def demo_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test_hotel_demo.db")
    initialize_schema(db)
    seed_from_json(db, Path(__file__).resolve().parents[1] / "demo_seed.json")
    return db


@pytest.fixture()
def rag(tmp_path: Path) -> PolicyRAG:
    root = Path(__file__).resolve().parents[1]
    return PolicyRAG(
        root / "hotel_policies.txt",
        tmp_path / "rag_cache.json",
        embedding_model="test-local",
        api_key=None,
        offline=True,
        threshold=0.05,
        min_relevance_score=0.72,
    )


@pytest.fixture()
def tools(demo_db: Database, rag: PolicyRAG) -> HotelTools:
    return HotelTools(demo_db, rag)
