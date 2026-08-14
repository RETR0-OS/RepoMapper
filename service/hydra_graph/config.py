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
    request_timeout_seconds: float = 20.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.25
    poll_interval_seconds: float = 1.0
    poll_timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if not self.collection.strip() or not self.evolution_collection.strip():
            raise ValueError("HydraDB collection names must not be blank")
        if self.collection == self.evolution_collection:
            raise ValueError("Current and evolution collections must be distinct")

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
                env.get("HYDRA_DB_TIMEOUT_SECONDS"), 20.0, "HYDRA_DB_TIMEOUT_SECONDS"
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
                120.0,
                "HYDRA_DB_POLL_TIMEOUT_SECONDS",
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
