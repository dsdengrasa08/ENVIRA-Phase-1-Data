"""Structured failure policy and execution boundaries for recoverable stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any, Callable, Generic, Literal, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class PipelineIssue:
    severity: Literal["info", "warning", "error", "fatal"]
    category: str
    stage: str
    message: str
    page_number: int | None = None
    region_ids: tuple[str, ...] = ()
    retryable: bool = False
    exception_type: str | None = None
    run_id: str | None = None
    document_id: str | None = None
    attempt: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PipelineStageError(RuntimeError):
    """A stage failed under strict policy, with its issue preserved."""

    def __init__(self, issue: PipelineIssue) -> None:
        super().__init__(f"{issue.stage}: {issue.message}")
        self.issue = issue


@dataclass(frozen=True)
class StageExecution(Generic[T]):
    value: T
    status: str
    elapsed_ms: float
    issue: PipelineIssue | None = None
    fallback: str | None = None


def execute_stage(
    *,
    name: str,
    operation: Callable[[], T],
    fallback: Callable[[], T],
    fallback_name: str,
    mode: str,
    category: str = "stage_processing_failure",
) -> StageExecution[T]:
    """Execute one package-owned stage with explicit strict/report semantics."""
    started = perf_counter()
    from .observability import RunCancelled, check_cancellation, current_recorder

    check_cancellation()
    recorder = current_recorder()
    if recorder:
        recorder.emit("stage_started", stage=name, status="running")
    try:
        result = StageExecution(
            operation(), "completed", (perf_counter() - started) * 1000
        )
        check_cancellation()
        if recorder:
            recorder.emit("stage_completed", stage=name, status=result.status, elapsed_ms=result.elapsed_ms)
        return result
    except (KeyboardInterrupt, SystemExit, RunCancelled):
        raise
    except Exception as exc:
        issue = PipelineIssue(
            severity="fatal" if mode == "strict" else "error",
            category=category,
            stage=name,
            message=str(exc) or type(exc).__name__,
            retryable=False,
            exception_type=type(exc).__name__,
            run_id=recorder.context.run_id if recorder else None,
            document_id=recorder.context.document_id if recorder else None,
            attempt=recorder.context.attempt if recorder else None,
        )
        if mode == "strict":
            if recorder:
                recorder.emit("stage_failed", stage=name, status="failed", elapsed_ms=(perf_counter() - started) * 1000, issue=issue.to_dict())
            raise PipelineStageError(issue) from exc
        result = StageExecution(
            fallback(),
            "failed_recovered",
            (perf_counter() - started) * 1000,
            issue,
            fallback_name,
        )
        if recorder:
            recorder.emit("stage_recovered", stage=name, status=result.status, elapsed_ms=result.elapsed_ms, issue=issue.to_dict())
        return result


def derive_run_status(issues: list[PipelineIssue], failed_pages: list[int]) -> str:
    if any(issue.severity == "fatal" for issue in issues):
        return "failed"
    if failed_pages or any(issue.severity == "error" for issue in issues):
        return "partial"
    if issues:
        return "complete_with_warnings"
    return "complete"


def page_failure_budget_exceeded(
    failed_pages: list[int], total_pages: int, *, max_pages: int, max_ratio: float
) -> bool:
    unique = len(set(failed_pages))
    return unique > max_pages or unique / max(total_pages, 1) > max_ratio
