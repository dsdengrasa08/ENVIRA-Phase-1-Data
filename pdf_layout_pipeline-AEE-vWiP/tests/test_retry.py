import json

import pytest

from envira_pdf_layout.retry import build_retry_plan


def write_run(root, config, pdf_hash="abc"):
    (root / "pipeline_diagnostics.json").write_text(
        json.dumps({"document": {"pdf_hash": pdf_hash}}), encoding="utf-8"
    )
    (root / "effective_config.json").write_text(json.dumps(config), encoding="utf-8")
    (root / "page_diagnostics.jsonl").write_text(
        json.dumps({"page_number": 1, "status": "completed"})
        + "\n"
        + json.dumps({"page_number": 2, "status": "failed"})
        + "\n",
        encoding="utf-8",
    )
    (root / "artifact_manifest.json").write_text(
        json.dumps({"run_id": "parent", "attempt": 2}), encoding="utf-8"
    )


def test_retry_plan_selects_only_failed_pages_after_identity_checks(tmp_path):
    config = {"profile": "test"}
    write_run(tmp_path, config)
    plan = build_retry_plan(
        tmp_path, expected_pdf_hash="abc", expected_effective_config=config
    )
    assert plan["failed_pages"] == [2]
    assert plan["retryable"]
    assert plan["parent_run_id"] == "parent"
    assert plan["attempt"] == 3


def test_retry_plan_rejects_incompatible_input_or_config(tmp_path):
    write_run(tmp_path, {"profile": "old"})
    with pytest.raises(ValueError, match="PDF hash"):
        build_retry_plan(
            tmp_path,
            expected_pdf_hash="different",
            expected_effective_config={"profile": "old"},
        )
    with pytest.raises(ValueError, match="configuration"):
        build_retry_plan(
            tmp_path,
            expected_pdf_hash="abc",
            expected_effective_config={"profile": "new"},
        )
