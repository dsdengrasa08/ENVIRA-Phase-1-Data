import pytest

from envira_pdf_layout.failures import (
    PipelineStageError,
    derive_run_status,
    execute_stage,
    page_failure_budget_exceeded,
)
from envira_pdf_layout.config import ErrorPolicyConfig, PipelineConfig
from envira_pdf_layout.pipeline import _collect_core_page_failures
from types import SimpleNamespace


def fail():
    raise ValueError("bad stage")


def test_report_mode_uses_declared_fallback_and_marks_partial():
    execution = execute_stage(
        name="caption_association",
        operation=fail,
        fallback=lambda: [],
        fallback_name="retain_unattached",
        mode="report",
    )
    assert execution.value == []
    assert execution.status == "failed_recovered"
    assert execution.fallback == "retain_unattached"
    assert execution.issue.exception_type == "ValueError"
    assert derive_run_status([execution.issue], []) == "partial"


def test_strict_mode_preserves_issue_and_exception_chain():
    with pytest.raises(PipelineStageError) as raised:
        execute_stage(
            name="hierarchy",
            operation=fail,
            fallback=list,
            fallback_name="retain_top_level",
            mode="strict",
        )
    assert raised.value.issue.severity == "fatal"
    assert isinstance(raised.value.__cause__, ValueError)


def test_keyboard_interrupt_is_never_converted_to_partial_result():
    with pytest.raises(KeyboardInterrupt):
        execute_stage(
            name="stage",
            operation=lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
            fallback=list,
            fallback_name="none",
            mode="report",
        )


def test_page_failure_budget_uses_count_and_ratio():
    assert page_failure_budget_exceeded([1, 2], 10, max_pages=1, max_ratio=1)
    assert page_failure_budget_exceeded([1, 2], 10, max_pages=10, max_ratio=0.1)
    assert not page_failure_budget_exceeded([1], 10, max_pages=1, max_ratio=0.1)


def test_core_ocr_failures_become_failed_pages_and_budget_is_enforced():
    result = SimpleNamespace(
        diagnostics={
            "later_headers": {
                "pdf_roi_ocr_error_pages": [{"page_number": 2, "error": "bad scan"}]
            }
        },
        failed_pages=[],
        failed_stages=[],
        issues=[],
        pages=[{"page_number": 1}, {"page_number": 2}],
    )
    config = PipelineConfig(
        error_policy=ErrorPolicyConfig(
            mode="report", max_failed_pages=0, max_failed_page_ratio=0
        )
    )
    _collect_core_page_failures(result, config)
    assert result.failed_pages == [2]
    assert result.failed_stages == ["independent_core"]
    assert {issue["category"] for issue in result.issues} == {
        "page_ocr_failure",
        "page_failure_budget_exceeded",
    }
