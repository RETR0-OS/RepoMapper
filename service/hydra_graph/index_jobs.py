"""In-process records for background indexing runs.

Indexing a large repository takes far longer than one HTTP request may stay
open, so ``POST /api/index`` accepts the work and reports progress through a job
record. The record lives only in this process: it is deliberately not persisted,
because a restarted service cannot know whether an interrupted upload left
HydraDB in a mixed state, and a resumed-looking job would make that unsafe state
look verified.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"

JOB_STATES = frozenset({JOB_RUNNING, JOB_COMPLETED, JOB_FAILED, JOB_CANCELLED})
JOB_PHASES = frozenset(
    {"analyzing", "clearing_stale_graphs", "uploading", "verifying", "deleting", "done"}
)

MAX_FINISHED_JOBS = 8

JOB_DURABILITY_MESSAGE = (
    "This index job record lives in the running Repository Map service process. "
    "It is not saved to disk: if the service stops, the record and the run are lost "
    "and indexing must be started again."
)


class IndexJobActive(RuntimeError):
    """Raised when a repository already has a running index job."""


@dataclass(slots=True)
class IndexJob:
    """One background indexing run and the progress reported against it."""

    job_id: str
    repository_id: str
    revision_id: str
    state: str = JOB_RUNNING
    phase: str = "analyzing"
    total_batches: int = 0
    uploaded_batches: int = 0
    total_sources: int = 0
    verified_sources: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: str | None = None
    result: dict[str, Any] | None = None
    durable: bool = False
    # A worker thread writes these fields while HTTP requests read them, so a
    # reader must not observe half of one update. Typed loosely because
    # ``threading.RLock`` is a factory function, not a class.
    lock: Any = field(default_factory=RLock, repr=False, compare=False)

    def as_dict(self) -> dict[str, Any]:
        with self.lock:
            return {
                "job_id": self.job_id,
                "repository_id": self.repository_id,
                "revision_id": self.revision_id,
                "state": self.state,
                "phase": self.phase,
                "total_batches": self.total_batches,
                "uploaded_batches": self.uploaded_batches,
                "total_sources": self.total_sources,
                "verified_sources": self.verified_sources,
                "failed": dict(self.failed),
                "started_at": self.started_at,
                "updated_at": self.updated_at,
                "error": self.error,
                "result": self.result,
                "durable": False,
                "message": JOB_DURABILITY_MESSAGE,
            }


_MUTABLE_FIELDS = frozenset(
    {
        "state",
        "phase",
        "total_batches",
        "uploaded_batches",
        "total_sources",
        "verified_sources",
        "failed",
        "error",
        "result",
    }
)


class IndexJobStore:
    """Track index jobs for one repository scope, bounded and thread-safe."""

    def __init__(self, *, max_finished: int = MAX_FINISHED_JOBS) -> None:
        if max_finished < 1:
            raise ValueError("max_finished must be positive")
        self._lock = RLock()
        self._jobs: OrderedDict[str, IndexJob] = OrderedDict()
        self._finished: list[str] = []
        self._cancelled: set[str] = set()
        self._max_finished = max_finished

    def start(
        self,
        *,
        repository_id: str,
        revision_id: str,
        total_batches: int,
        total_sources: int,
    ) -> IndexJob:
        with self._lock:
            if self.active(repository_id) is not None:
                raise IndexJobActive(f"An index job is already running for {repository_id}")
            job = IndexJob(
                job_id=f"idx_{uuid.uuid4().hex}",
                repository_id=repository_id,
                revision_id=revision_id,
                total_batches=max(0, total_batches),
                total_sources=max(0, total_sources),
            )
            self._jobs[job.job_id] = job
            return job

    def get(self, job_id: str) -> IndexJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def active(self, repository_id: str) -> IndexJob | None:
        with self._lock:
            for job in self._jobs.values():
                if job.repository_id == repository_id and job.state == JOB_RUNNING:
                    return job
        return None

    def update(self, job_id: str, **fields: Any) -> None:
        unknown = set(fields).difference(_MUTABLE_FIELDS)
        if unknown:
            raise ValueError(f"Unknown index job fields: {', '.join(sorted(unknown))}")
        job = self.get(job_id)
        if job is None:
            # A retained job may already have been dropped; progress from a late
            # worker must never raise inside that worker's thread.
            return
        with job.lock:
            for name, value in fields.items():
                setattr(job, name, dict(value) if name == "failed" else value)
            job.updated_at = time.time()

    def cancel(self, job_id: str) -> bool:
        """Request cancellation; the worker decides when it can stop safely."""

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state != JOB_RUNNING:
                return False
            self._cancelled.add(job_id)
            return True

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def finish(
        self,
        job_id: str,
        *,
        state: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if state not in JOB_STATES or state == JOB_RUNNING:
            raise ValueError(f"Invalid terminal index job state: {state}")
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            with job.lock:
                job.state = state
                job.result = result
                job.error = error
                job.phase = "done"
                job.updated_at = time.time()
            if job_id not in self._finished:
                self._finished.append(job_id)
            self._prune()

    def _prune(self) -> None:
        # Retention is bounded because nothing else ever removes a record, and
        # a finished record holds a whole preview payload.
        while len(self._finished) > self._max_finished:
            dropped = self._finished.pop(0)
            self._jobs.pop(dropped, None)
            self._cancelled.discard(dropped)
