from __future__ import annotations

import threading

import pytest
from hydra_graph.index_jobs import (
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_RUNNING,
    MAX_FINISHED_JOBS,
    IndexJobActive,
    IndexJobStore,
)


def start(store: IndexJobStore, repository_id: str = "hack-hydra", revision_id: str = "rev-a"):
    return store.start(
        repository_id=repository_id,
        revision_id=revision_id,
        total_batches=3,
        total_sources=60,
    )


def test_job_record_exposes_progress_fields_and_never_claims_durability() -> None:
    store = IndexJobStore()

    record = start(store).as_dict()

    assert set(record) == {
        "job_id",
        "repository_id",
        "revision_id",
        "state",
        "phase",
        "total_batches",
        "uploaded_batches",
        "total_sources",
        "verified_sources",
        "failed",
        "started_at",
        "updated_at",
        "error",
        "result",
        "durable",
        "message",
    }
    assert record["state"] == JOB_RUNNING
    assert record["phase"] == "analyzing"
    assert record["total_batches"] == 3
    assert record["total_sources"] == 60
    assert record["durable"] is False
    assert record["result"] is None
    assert "lost" in record["message"]
    assert "not saved to disk" in record["message"]


def test_job_lifecycle_records_progress_then_the_final_payload() -> None:
    store = IndexJobStore()
    job = start(store)

    store.update(job.job_id, phase="uploading", uploaded_batches=2, total_batches=3)
    running = store.get(job.job_id).as_dict()
    store.update(job.job_id, phase="verifying", verified_sources=60, total_sources=60)
    store.finish(
        job.job_id,
        state=JOB_COMPLETED,
        result={"preview": {}, "sync": {"status": "ready"}},
    )
    completed = store.get(job.job_id).as_dict()

    assert running["phase"] == "uploading"
    assert running["uploaded_batches"] == 2
    assert running["updated_at"] >= running["started_at"]
    assert completed["state"] == JOB_COMPLETED
    assert completed["phase"] == "done"
    assert completed["verified_sources"] == 60
    assert completed["result"] == {"preview": {}, "sync": {"status": "ready"}}
    assert completed["error"] is None


def test_a_failed_job_keeps_its_bounded_reason() -> None:
    store = IndexJobStore()
    job = start(store)

    store.finish(job.job_id, state=JOB_FAILED, error="Indexing failed. TimeoutError: no response")

    record = store.get(job.job_id).as_dict()
    assert record["state"] == JOB_FAILED
    assert record["error"].startswith("Indexing failed.")
    assert record["result"] is None
    with pytest.raises(ValueError, match="terminal"):
        store.finish(job.job_id, state=JOB_RUNNING)


def test_one_running_job_per_repository_and_a_finished_job_frees_the_slot() -> None:
    store = IndexJobStore()
    first = start(store)

    other_repository = start(store, repository_id="other-repository")
    with pytest.raises(IndexJobActive):
        start(store)

    assert store.active("hack-hydra") is first
    assert store.active("other-repository") is other_repository
    store.finish(first.job_id, state=JOB_COMPLETED)
    assert store.active("hack-hydra") is None
    second = start(store)
    assert second.job_id != first.job_id


def test_cancellation_is_a_flag_the_worker_reads() -> None:
    store = IndexJobStore()
    job = start(store)

    assert store.is_cancelled(job.job_id) is False
    assert store.cancel(job.job_id) is True
    assert store.is_cancelled(job.job_id) is True
    # The flag alone must not end the job; only the worker reports the outcome.
    assert store.get(job.job_id).state == JOB_RUNNING
    store.finish(job.job_id, state=JOB_CANCELLED)

    assert store.get(job.job_id).state == JOB_CANCELLED
    assert store.cancel(job.job_id) is False
    assert store.cancel("idx_unknown") is False
    assert store.is_cancelled("idx_unknown") is False


def test_retention_keeps_only_the_most_recently_finished_jobs() -> None:
    store = IndexJobStore()
    finished = []
    for index in range(MAX_FINISHED_JOBS + 4):
        job = start(store, revision_id=f"rev-{index}")
        store.finish(job.job_id, state=JOB_COMPLETED)
        finished.append(job.job_id)

    kept = [job_id for job_id in finished if store.get(job_id) is not None]

    assert kept == finished[-MAX_FINISHED_JOBS:]
    assert store.get(finished[0]) is None
    # A dropped record must not make a late progress write raise in the worker.
    store.update(finished[0], phase="uploading")


def test_a_running_job_is_never_dropped_by_retention() -> None:
    store = IndexJobStore()
    running = start(store, repository_id="long-running")
    for index in range(MAX_FINISHED_JOBS + 3):
        job = start(store, revision_id=f"rev-{index}")
        store.finish(job.job_id, state=JOB_COMPLETED)

    assert store.get(running.job_id) is not None
    assert store.active("long-running") is running


def test_update_refuses_unknown_fields() -> None:
    store = IndexJobStore()
    job = start(store)

    with pytest.raises(ValueError, match="Unknown index job fields"):
        store.update(job.job_id, durable=True)
    assert store.get(job.job_id).as_dict()["durable"] is False


def test_concurrent_writers_and_readers_keep_the_record_consistent() -> None:
    store = IndexJobStore()
    job = start(store)
    ready = threading.Event()
    failures: list[BaseException] = []
    snapshots: list[dict[str, object]] = []

    def write(worker: int) -> None:
        ready.wait(2)
        try:
            for step in range(200):
                store.update(
                    job.job_id,
                    phase="uploading",
                    uploaded_batches=step,
                    total_batches=200,
                    failed={f"source-{worker}": "pending"},
                )
        except BaseException as exc:  # noqa: BLE001 - reported through the test
            failures.append(exc)

    def read() -> None:
        ready.wait(2)
        try:
            for _ in range(200):
                record = store.get(job.job_id).as_dict()
                # A reader must never see a half-applied update.
                assert record["total_batches"] == 200 or record["uploaded_batches"] == 0
                snapshots.append(record)
        except BaseException as exc:  # noqa: BLE001 - reported through the test
            failures.append(exc)

    threads = [threading.Thread(target=write, args=(index,)) for index in range(6)]
    threads += [threading.Thread(target=read) for _ in range(2)]
    for thread in threads:
        thread.start()
    ready.set()
    for thread in threads:
        thread.join(10)

    assert failures == []
    assert len(snapshots) == 400
    assert store.get(job.job_id).uploaded_batches == 199


def test_concurrent_starts_yield_exactly_one_running_job() -> None:
    store = IndexJobStore()
    ready = threading.Event()
    started: list[str] = []
    rejected: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        ready.wait(2)
        try:
            job = start(store)
        except IndexJobActive:
            with lock:
                rejected.append("rejected")
        else:
            with lock:
                started.append(job.job_id)

    threads = [threading.Thread(target=attempt) for _ in range(12)]
    for thread in threads:
        thread.start()
    ready.set()
    for thread in threads:
        thread.join(10)

    assert len(started) == 1
    assert len(rejected) == 11
    assert store.active("hack-hydra").job_id == started[0]
