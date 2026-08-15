"""Vendor-neutral lifecycle events, cancellation, and bounded operational metrics."""

from __future__ import annotations

from contextvars import ContextVar, Token
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Protocol

from .security import redact_secrets, secure_file

EVENT_SCHEMA_VERSION = 1


class EventSink(Protocol):
    def emit(self, event: dict[str, Any]) -> None: ...


class RunCancelled(RuntimeError):
    """Raised cooperatively between bounded application and pipeline stages."""


@dataclass(frozen=True)
class CancellationToken:
    cancelled: Callable[[], bool] = lambda: False
    deadline_monotonic: float | None = None

    def check(self) -> None:
        if self.cancelled():
            raise RunCancelled("run cancelled by caller")
        if self.deadline_monotonic is not None and monotonic() >= self.deadline_monotonic:
            raise RunCancelled("run deadline exceeded")


@dataclass(frozen=True)
class RunContext:
    run_id: str
    document_id: str
    source_pdf_sha256: str
    effective_config_sha256: str
    attempt: int = 1
    parent_run_id: str | None = None


@dataclass(frozen=True)
class PipelineEvent:
    event: str
    context: RunContext
    timestamp_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )
    stage: str | None = None
    page_number: int | None = None
    status: str | None = None
    elapsed_ms: float | None = None
    counters: dict[str, int | float] = field(default_factory=dict)
    issue: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        context = value.pop("context")
        return redact_secrets({"event_schema_version": EVENT_SCHEMA_VERSION, **context, **value})


@dataclass
class EventRecorder:
    context: RunContext
    sink: EventSink | Callable[[dict[str, Any]], None] | None = None
    output: Path | None = None
    file_mode: int = 0o600
    events: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, name: str, **values: Any) -> dict[str, Any]:
        event = PipelineEvent(name, self.context, **values).to_dict()
        self.events.append(event)
        if self.sink:
            try:
                emit = getattr(self.sink, "emit", self.sink)
                emit(deepcopy(event))
            except Exception as exc:
                # Observability must not corrupt semantic processing.
                event["sink_error"] = type(exc).__name__
        if self.output:
            temporary = self.output.with_name(self.output.name + ".tmp")
            temporary.write_text(
                "".join(json.dumps(row, sort_keys=True, default=str) + "\n" for row in self.events),
                encoding="utf-8",
            )
            temporary.replace(self.output)
            secure_file(self.output, self.file_mode)
        return event


_RECORDER: ContextVar[EventRecorder | None] = ContextVar("envira_event_recorder", default=None)
_CANCELLATION: ContextVar[CancellationToken | None] = ContextVar("envira_cancellation", default=None)


def bind_observability(
    recorder: EventRecorder, cancellation: CancellationToken
) -> tuple[Token, Token]:
    return _RECORDER.set(recorder), _CANCELLATION.set(cancellation)


def reset_observability(tokens: tuple[Token, Token]) -> None:
    _RECORDER.reset(tokens[0])
    _CANCELLATION.reset(tokens[1])


def current_recorder() -> EventRecorder | None:
    return _RECORDER.get()


def check_cancellation() -> None:
    token = _CANCELLATION.get()
    if token:
        token.check()


def metric_snapshot(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Return bounded, label-free counters suitable for export or adapters."""
    terminal = [row for row in events if row["event"] in {"run_completed", "run_failed", "run_cancelled"}]
    return {
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "events_total": len(events),
        "stages_completed_total": sum(row["event"] == "stage_completed" for row in events),
        "stages_recovered_total": sum(row["event"] == "stage_recovered" for row in events),
        "pages_failed_total": sum(row["event"] == "page_failed" for row in events),
        "terminal_events_total": len(terminal),
    }
