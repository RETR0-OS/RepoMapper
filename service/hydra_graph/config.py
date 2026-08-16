"""Runtime configuration for the local Hydra Graph service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_API_URL = "https://api.hydradb.com"


@dataclass(frozen=True, slots=True)
class HydraDBConfig:
    """HydraDB v2 connection settings.

    A missing key is represented instead of rejected at process startup so the
    service can expose an honest ``unavailable`` health state.
    """

    api_key: str | None
    database: str
    collection: str = "current"
    evolution_collection: str = "evolution"
    api_url: str = DEFAULT_API_URL
    # A thinking-mode query with graph context is the slowest read this service makes.
    # Measured at about 33 s against a 6,210-source repository, so the former 20 s
    # budget cut off every such query before HydraDB could answer.
    request_timeout_seconds: float = 90.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.25
    poll_interval_seconds: float = 1.0
    poll_timeout_seconds: float = 1800.0
    status_batch_size: int = 100
    # A query returns a small, fixed number of relation groups, and it ranks HydraDB's
    # own concept relations beside this repository's graph. The stored graph is read
    # per source instead. These bound that read, because it costs one request each.
    relation_sources: int = 12
    relation_workers: int = 8
    # A question matches a handful of chunks, but the code that connects them is not
    # among them, so every relation that would join them cites a chunk outside the
    # answer and is dropped. One further read fetches those endpoints. Zero disables it.
    completion_sources: int = 10

    def __post_init__(self) -> None:
        if not self.collection.strip() or not self.evolution_collection.strip():
            raise ValueError("HydraDB collection names must not be blank")
        if self.collection == self.evolution_collection:
            raise ValueError("Current and evolution collections must be distinct")
        if not 1 <= self.status_batch_size <= 500:
            raise ValueError("HYDRA_DB_STATUS_BATCH_SIZE must be between 1 and 500")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.database)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> HydraDBConfig:
        env = os.environ if environ is None else environ
        return cls(
            api_key=_clean(env.get("HYDRA_DB_API_KEY")),
            database=_clean(env.get("HYDRA_DB_DATABASE")) or "",
            collection=_clean(env.get("HYDRA_DB_COLLECTION")) or "current",
            evolution_collection=(_clean(env.get("HYDRA_DB_EVOLUTION_COLLECTION")) or "evolution"),
            api_url=(_clean(env.get("HYDRA_DB_API_URL")) or DEFAULT_API_URL).rstrip("/"),
            request_timeout_seconds=_positive_float(
                env.get("HYDRA_DB_TIMEOUT_SECONDS"), 90.0, "HYDRA_DB_TIMEOUT_SECONDS"
            ),
            max_retries=_non_negative_int(
                env.get("HYDRA_DB_MAX_RETRIES"), 2, "HYDRA_DB_MAX_RETRIES"
            ),
            retry_backoff_seconds=_non_negative_float(
                env.get("HYDRA_DB_RETRY_BACKOFF_SECONDS"),
                0.25,
                "HYDRA_DB_RETRY_BACKOFF_SECONDS",
            ),
            poll_interval_seconds=_positive_float(
                env.get("HYDRA_DB_POLL_INTERVAL_SECONDS"),
                1.0,
                "HYDRA_DB_POLL_INTERVAL_SECONDS",
            ),
            poll_timeout_seconds=_positive_float(
                env.get("HYDRA_DB_POLL_TIMEOUT_SECONDS"),
                1800.0,
                "HYDRA_DB_POLL_TIMEOUT_SECONDS",
            ),
            status_batch_size=_positive_int(
                env.get("HYDRA_DB_STATUS_BATCH_SIZE"),
                100,
                "HYDRA_DB_STATUS_BATCH_SIZE",
            ),
            relation_sources=_positive_int(
                env.get("HYDRA_DB_RELATION_SOURCES"), 12, "HYDRA_DB_RELATION_SOURCES"
            ),
            relation_workers=_positive_int(
                env.get("HYDRA_DB_RELATION_WORKERS"), 8, "HYDRA_DB_RELATION_WORKERS"
            ),
            completion_sources=_non_negative_int(
                env.get("HYDRA_DB_COMPLETION_SOURCES"), 10, "HYDRA_DB_COMPLETION_SOURCES"
            ),
        )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _positive_float(value: str | None, default: float, name: str) -> float:
    result = default if value is None else float(value)
    if result <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return result


def _non_negative_float(value: str | None, default: float, name: str) -> float:
    result = default if value is None else float(value)
    if result < 0:
        raise ValueError(f"{name} must be zero or greater")
    return result


def _non_negative_int(value: str | None, default: int, name: str) -> int:
    result = default if value is None else int(value)
    if result < 0:
        raise ValueError(f"{name} must be zero or greater")
    return result


def _positive_int(value: str | None, default: int, name: str) -> int:
    result = default if value is None else int(value)
    if result < 1:
        raise ValueError(f"{name} must be one or greater")
    return result
