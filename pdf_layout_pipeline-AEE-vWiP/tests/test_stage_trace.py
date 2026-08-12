from envira_pdf_layout.stage_trace import compare_stage_traces, snapshot, validate_trace


def region(region_id, typ="Text", bbox=None, page=1):
    return {
        "layout_region_id": region_id,
        "page_number": page,
        "type": typ,
        "bbox_px": bbox or [0, 0, 10, 10],
    }


def test_snapshot_records_deterministic_counts_and_region_delta():
    first = snapshot("input", [region("a"), region("b", "Figure", page=2)])
    second = snapshot(
        "resolved",
        [region("b", "Figure", page=2), region("c")],
        previous=first,
        relationships=[{"kind": "DUPLICATE"}],
        decisions=[{"action": "canonicalize"}],
    )
    assert first["counts_by_page"] == {"1": 1, "2": 1}
    assert first["counts_by_type"] == {"Figure": 1, "Text": 1}
    assert second["added_region_ids"] == ["c"]
    assert second["removed_region_ids"] == ["a"]
    assert second["relationship_count"] == second["decision_count"] == 1
    assert first["region_digest"] != second["region_digest"]


def test_snapshot_detects_geometry_and_type_changes_without_id_change():
    first = snapshot("first", [region("a")])
    second = snapshot(
        "second", [region("a", typ="Caption", bbox=[1, 1, 20, 20])], previous=first
    )
    assert second["added_region_ids"] == second["removed_region_ids"] == []
    assert second["geometry_changed_region_ids"] == ["a"]
    assert second["type_changed_region_ids"] == ["a"]


def test_trace_validation_surfaces_duplicate_ids_and_bad_geometry():
    broken = snapshot(
        "broken",
        [region("same"), region("same", bbox=[5, 5, 1, 1])],
    )
    validation = validate_trace([broken])
    assert not validation["valid"]
    assert validation["failures"][0]["stage"] == "broken"
    assert broken["invariants"]["invalid_geometry_region_ids"] == ["same"]


def test_optional_stage_invariants_participate_in_validation():
    row = snapshot("hierarchy", [region("a")])
    row["invariants"]["partition_valid"] = False
    assert not validate_trace([row])["valid"]


def test_missing_identity_page_and_nonfinite_geometry_are_reported_not_crashed():
    broken = snapshot(
        "broken",
        [{"layout_region_id": "", "type": "Text", "bbox_px": [0, 0, float("inf"), 1]}],
        elapsed_ms=1.23456,
    )
    assert broken["elapsed_ms"] == 1.235
    assert not broken["invariants"]["all_region_ids_present"]
    assert not broken["invariants"]["valid_page_numbers"]
    assert not broken["invariants"]["valid_geometry"]


def test_trace_comparison_reports_first_semantic_divergence():
    baseline = [snapshot("core", [region("a")]), snapshot("final", [region("a")])]
    candidate = [
        snapshot("core", [region("a")]),
        snapshot("final", [region("a", typ="Caption")]),
    ]
    comparison = compare_stage_traces(baseline, candidate)
    assert not comparison["compatible"]
    assert comparison["first_divergent_stage"] == "final"
    assert comparison["differences"][0]["type_changed_region_ids"] == ["a"]


def test_trace_comparison_ignores_runtime_only_changes():
    assert compare_stage_traces(
        [snapshot("core", [region("a")], elapsed_ms=1)],
        [snapshot("core", [region("a")], elapsed_ms=999)],
    )["compatible"]
