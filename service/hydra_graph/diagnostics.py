"""Bounded, content-free diagnostics for the local service.

One line is written for each significant operation. A line holds stage names,
counts, and durations only. No repository content, no question text, and no
credential can enter a line, so a user can paste the log into a report safely.

Managed mode sends stderr to the VS Code "Repository Map Service" output channel,
so every line reaches the person who sees the failure.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from threading import Lock
from typing import Any

LOGGER_NAME = "hydra_graph"
MAX_FIELD_CHARS = 160

logger = logging.getLogger(LOGGER_NAME)


class _StderrHandler(logging.Handler):
    """Write to whichever stream is ``sys.stderr`` at the time of the record.

    Managed mode replaces ``sys.stdout`` with ``sys.stderr`` during startup, so a
    handler that captured a stream object at import time could write into the IPC
    channel and break the protocol. Resolving the stream on each record avoids it.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stream = sys.stderr
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:  # noqa: BLE001 - a log must never break a request
            self.handleError(record)


def configure_logging() -> None:
    """Attach one stderr handler to the service logger, exactly once.

    uvicorn configures only its own loggers, and the root logger keeps no handler,
    so an unconfigured service logger would drop every INFO line. This owns the
    service logger instead of the root logger, so no library output is changed.
    """

    if any(isinstance(handler, _StderrHandler) for handler in logger.handlers):
        return
    handler = _StderrHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(_configured_level())


def _configured_level() -> int:
    requested = (os.environ.get("HYDRA_LOG_LEVEL") or "INFO").strip().upper()
    return getattr(logging, requested, logging.INFO) if requested else logging.INFO


class Timings:
    """Collect the duration of each stage of one operation, in milliseconds."""

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._started = monotonic()
        self._stages: dict[str, float] = {}
        self._lock = Lock()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Measure one stage. A failing stage is still measured and recorded."""

        started = self._monotonic()
        try:
            yield
        finally:
            self.record(name, (self._monotonic() - started) * 1_000)

    def record(self, name: str, milliseconds: float) -> None:
        with self._lock:
            self._stages[name] = self._stages.get(name, 0.0) + milliseconds

    @property
    def total_ms(self) -> float:
        return (self._monotonic() - self._started) * 1_000

    def as_dict(self) -> dict[str, float]:
        """Return every stage plus the wall-clock total, rounded to 0.1 ms."""

        with self._lock:
            stages = dict(self._stages)
        stages["total"] = self.total_ms
        return {name: round(value, 1) for name, value in sorted(stages.items())}


def format_event(event: str, fields: Mapping[str, Any]) -> str:
    """Return one ``key=value`` line. A ``None`` field is left out."""

    parts = [f"hydra.{event}"]
    parts.extend(f"{key}={_safe(value)}" for key, value in fields.items() if value is not None)
    return " ".join(parts)


def log_event(event: str, **fields: Any) -> None:
    logger.info("%s", format_event(event, fields))


def log_query(
    *,
    timings: Timings,
    funnel: Mapping[str, Any] | None = None,
    **fields: Any,
) -> None:
    """Write the single funnel line for one repository query."""

    log_event(
        "query",
        **fields,
        **{f"ms.{name}": value for name, value in timings.as_dict().items()},
        **{f"n.{name}": value for name, value in (funnel or {}).items()},
    )


def _safe(value: Any) -> str:
    """Return a bounded single-line form of one field value."""

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.1f}"
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) > MAX_FIELD_CHARS:
        text = f"{text[:MAX_FIELD_CHARS]}…"
    return text or "-"
