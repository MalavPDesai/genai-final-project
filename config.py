from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_text(name: str, default: str) -> str:
    raw = os.getenv(name)
    return raw.strip() if raw and raw.strip() else default


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw.strip()) if raw and raw.strip() else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a numeric value.") from exc


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    database_path: Path = _env_path("DATABASE_PATH", BASE_DIR / "hotel_demo.db")
    policy_path: Path = _env_path("POLICY_PATH", BASE_DIR / "hotel_policies.txt")
    rag_cache_path: Path = _env_path("RAG_CACHE_PATH", BASE_DIR / ".rag_embeddings.json")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    openai_model: str = _env_text("OPENAI_MODEL", "gpt-6-luna")
    openai_embedding_model: str = _env_text("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    # Candidate retrieval stays permissive; the stronger evidence gate below decides
    # whether a policy answer is actually allowed.
    policy_candidate_threshold: float = _env_float("POLICY_CANDIDATE_THRESHOLD", 0.08)
    min_policy_relevance_score: float = _env_float("MIN_POLICY_RELEVANCE_SCORE", 0.72)
    offline_mode: bool = _env_bool("OFFLINE_MODE", default=not bool(os.getenv("OPENAI_API_KEY")))
    enable_test_failure_mode: bool = _env_bool("ENABLE_TEST_FAILURE_MODE", default=True)


settings = Settings()
