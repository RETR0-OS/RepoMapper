from __future__ import annotations

import logging

import pytest
from hydra_graph.diagnostics import (
    LOGGER_NAME,
    Timings,
    configure_logging,
    format_event,
    log_query,
)


def test_timings_measure_each_stage_and_the_whole_operation() -> None:
    clock = [0.0]

    def monotonic() -> float:
        return clock[0]

    timings = Timings(monotonic=monotonic)
    with timings.stage("hydradb_query"):
        clock[0] += 1.5
    with timings.stage("normalize"):
        clock[0] += 0.25
    # A repeated stage adds to the same name instead of replacing it.
    with timings.stage("normalize"):
        clock[0] += 0.25

    assert timings.as_dict() == {"hydradb_query": 1500.0, "normalize": 500.0, "total": 2000.0}


def test_a_failing_stage_is_still_measured() -> None:
    clock = [0.0]
    timings = Timings(monotonic=lambda: clock[0])

    with pytest.raises(RuntimeError), timings.stage("hydradb_query"):
        clock[0] += 3.0
        raise RuntimeError("HydraDB refused")

    assert timings.as_dict()["hydradb_query"] == 3000.0


def test_event_lines_stay_on_one_line_and_stay_bounded() -> None:
    line = format_event(
        "query",
        {
            "status": "unavailable",
            "reason": "first\nsecond\rthird",
            "size": "x" * 400,
            "graph_context": True,
            "omitted": None,
        },
    )

    assert "\n" not in line and "\r" not in line
    assert line.startswith("hydra.query status=unavailable ")
    assert "reason=first second third" in line
    assert "graph_context=true" in line
    # A field that was not supplied is left out instead of printed as "None".
    assert "omitted" not in line
    assert len(line) < 700


def test_query_log_reaches_stderr_with_every_stage_and_funnel_count(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """stderr is the channel VS Code shows, so the line must arrive there.

    The service logger keeps its own handler and does not propagate, so the root
    logger stays untouched and no library output changes.
    """

    configure_logging()
    clock = [0.0]
    timings = Timings(monotonic=lambda: clock[0])
    with timings.stage("hydradb_query"):
        clock[0] += 2.0

    log_query(
        timings=timings,
        funnel={"raw_chunks": 3, "hops": 0},
        status="ready",
        outcome="no_hops",
    )

    line = capsys.readouterr().err.strip().splitlines()[-1]
    assert "outcome=no_hops" in line
    assert "ms.hydradb_query=2000.0" in line
    assert "ms.total=2000.0" in line
    assert "n.raw_chunks=3" in line
    assert "n.hops=0" in line


def test_configure_logging_is_repeatable_and_owns_only_the_service_logger() -> None:
    configure_logging()
    service_logger = logging.getLogger(LOGGER_NAME)
    before = len(service_logger.handlers)
    configure_logging()

    assert len(service_logger.handlers) == before
    # Root stays untouched, so no library log is redirected or duplicated.
    assert service_logger.propagate is False
