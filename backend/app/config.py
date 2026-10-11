"""Application configuration loaded from environment variables."""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int = 0) -> int:
    raw = os.environ.get(key, "")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return default


def _env_float(key: str, default: float = 0.0) -> float:
    raw = os.environ.get(key, "")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return default


def _env_usd(key: str, default: float) -> float:
    """A dollar amount: finite and not negative, else ``default`` with a warning."""
    raw = os.environ.get(key, "")
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if math.isfinite(value) and value >= 0:
        return value
    logger.warning("%s=%r is not a finite, non-negative number; using %s.", key, raw, default)
    return default


@dataclass
class Settings:
    """Central configuration for the Orbis backend."""

    # --- Database (Azure PostgreSQL) ---
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL"))

    # --- Redis (Upstash) ---
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL"))

    # --- AI ---
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    embedding_model: str = "text-embedding-3-small"
    embedding_batch_size: int = 100
    embedding_max_per_cycle: int = field(
        default_factory=lambda: _env_int("EMBEDDING_MAX_PER_CYCLE", 2000)
    )
    # Global cap on Claude spend per UTC day; AI endpoints fall back past it.
    llm_daily_budget_usd: float = field(
        default_factory=lambda: _env_usd("LLM_DAILY_BUDGET_USD", 1.0)
    )

    # --- ML classification ---
    ml_topic_model: str = field(
        default_factory=lambda: _env("ML_TOPIC_MODEL", "MoritzLaurer/deberta-v3-base-zeroshot-v2.0")
    )
    ml_sentiment_model: str = field(
        default_factory=lambda: _env(
            "ML_SENTIMENT_MODEL",
            "lxyuan/distilbert-base-multilingual-cased-sentiments-student",
        )
    )
    ml_classification_enabled: bool = field(
        default_factory=lambda: (
            _env("ML_CLASSIFICATION_ENABLED", "true").lower() in ("true", "1", "yes")
        )
    )
    ml_batch_size: int = field(default_factory=lambda: _env_int("ML_BATCH_SIZE", 32))
    ml_functions_url: str = field(default_factory=lambda: _env("ML_FUNCTIONS_URL", ""))
    ml_functions_key: str = field(default_factory=lambda: _env("ML_FUNCTIONS_KEY", ""))

    # --- GDELT ---
    gdelt_doc_base_url: str = field(
        default_factory=lambda: _env(
            "GDELT_DOC_BASE_URL",
            "https://api.gdeltproject.org/api/v2/doc/doc",
        )
    )
    gdelt_geo_base_url: str = field(
        default_factory=lambda: _env(
            "GDELT_GEO_BASE_URL",
            "https://api.gdeltproject.org/api/v2/geo/geo",
        )
    )
    # --- Cache TTLs (seconds) ---
    gdelt_cache_ttl: int = field(default_factory=lambda: _env_int("GDELT_CACHE_TTL", 7200))
    # Globe data (GEO API) changes slowly — cache longer so subsequent users
    # get an instant load instead of waiting for the GDELT API.
    # 6 hours
    gdelt_geo_cache_ttl: int = field(
        default_factory=lambda: _env_int("GDELT_GEO_CACHE_TTL", 21600),
    )
    summary_cache_ttl: int = field(default_factory=lambda: _env_int("SUMMARY_CACHE_TTL", 21600))

    # --- Ingestion ---
    ingestion_interval_seconds: int = field(
        default_factory=lambda: _env_int("INGESTION_INTERVAL_SECONDS", 900)
    )  # 15 minutes

    # --- Data retention ---
    retention_days: int = 7
    db_cache_ttl: int = field(default_factory=lambda: _env_int("DB_CACHE_TTL", 300))  # 5 minutes

    # --- Clustering ---
    cluster_resolution_deg: float = field(
        default_factory=lambda: _env_float("CLUSTER_RESOLUTION_DEG", 2.0)
    )

    # --- Security ---
    api_key: str = field(default_factory=lambda: _env("ORBIS_API_KEY"))

    # --- Feature flags ---
    agent_enabled: bool = field(
        default_factory=lambda: _env("AGENT_ENABLED", "true").lower() in ("true", "1", "yes")
    )

    # --- AI model ---
    haiku_model_id: str = field(default_factory=lambda: _env("HAIKU_MODEL_ID", "claude-haiku-5-5"))
    sonnet_model_id: str = field(
        default_factory=lambda: _env("SONNET_MODEL_ID", "claude-sonnet-4-5-20241022")
    )
    agent_max_retrieval_results: int = 20
    agent_conversation_ttl: int = 3600  # 1 hour


settings = Settings()
