import json

import pytest

from envira_pdf_layout.regression import update_golden
from envira_pdf_layout.stage_trace import snapshot


def region():
    return {
        "layout_region_id": "a",
        "page_number": 1,
        "type": "Text",
        "bbox_px": [0, 0, 10, 10],
    }


def test_golden_update_requires_reason_and_writes_versioned_contract(tmp_path):
    output = tmp_path / "golden.json"
    with pytest.raises(ValueError, match="reason"):
        update_golden(
            output, [snapshot("final", [region()])], fixture_id="case", reason=""
        )
    result = update_golden(
        output,
        [snapshot("final", [region()])],
        fixture_id="case",
        reason="approved behavior",
    )
    stored = json.loads(output.read_text(encoding="utf-8"))
    assert result["previous"] is None
    assert stored["golden_schema_version"] == stored["trace_schema_version"] == 1
    assert stored["stage_digests"]["final"]


def test_golden_update_refuses_failed_invariant_without_force(tmp_path):
    row = snapshot("final", [region()])
    row["invariants"]["partition_valid"] = False
    with pytest.raises(ValueError, match="invalid trace"):
        update_golden(tmp_path / "golden.json", [row], fixture_id="case", reason="bad")
