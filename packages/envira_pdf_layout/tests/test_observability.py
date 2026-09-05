from time import monotonic

import pytest

from envira_pdf_layout.failures import execute_stage
from envira_pdf_layout.observability import (
    CancellationToken,
    EventRecorder,
    RunCancelled,
    RunContext,
    bind_observability,
    metric_snapshot,
    reset_observability,
)


def context():
    return RunContext("run", "doc", "a" * 64, "b" * 64)


def test_stage_events_are_paired_and_correlated(tmp_path):
    recorder = EventRecorder(context(), output=tmp_path / "events.jsonl")
    tokens = bind_observability(recorder, CancellationToken())
    try:
        result = execute_stage(
            name="example",
            operation=lambda: 7,
            fallback=lambda: 0,
            fallback_name="zero",
            mode="strict",
        )
    finally:
        reset_observability(tokens)
    assert result.value == 7
    assert [row["event"] for row in recorder.events] == ["stage_started", "stage_completed"]
    assert {row["run_id"] for row in recorder.events} == {"run"}
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 2


def test_sink_failure_is_isolated_and_metrics_are_bounded():
    def broken(_event):
        raise RuntimeError("collector unavailable")

    recorder = EventRecorder(context(), sink=broken)
    event = recorder.emit("run_completed", status="complete")
    assert event["sink_error"] == "RuntimeError"
    assert metric_snapshot(recorder.events)["terminal_events_total"] == 1


def test_cancellation_propagates_without_fallback():
    recorder = EventRecorder(context())
    tokens = bind_observability(
        recorder, CancellationToken(deadline_monotonic=monotonic() - 1)
    )
    fallback_called = False

    def fallback():
        nonlocal fallback_called
        fallback_called = True

    try:
        with pytest.raises(RunCancelled, match="deadline"):
            execute_stage(
                name="example",
                operation=lambda: None,
                fallback=fallback,
                fallback_name="none",
                mode="report",
            )
    finally:
        reset_observability(tokens)
    assert fallback_called is False


def test_events_redact_secret_named_fields():
    recorder = EventRecorder(context())
    row = recorder.emit("run_failed", issue={"api_key": "secret", "message": "safe"})
    assert row["issue"] == {"api_key": "<redacted>", "message": "safe"}


def test_sink_cannot_mutate_recorded_event():
    def mutating(event):
        event["issue"]["message"] = "changed"

    recorder = EventRecorder(context(), sink=mutating)
    recorder.emit("run_failed", issue={"message": "original"})
    assert recorder.events[0]["issue"]["message"] == "original"
