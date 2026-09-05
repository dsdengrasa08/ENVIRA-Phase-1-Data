import json
from pathlib import Path

import pytest

from envira_pdf_layout.schema import (
    BBoxValue,
    apply_geometry_change,
    initialize_region_schema,
    migrate_region,
    normalize_relationship_schema,
    validate_region_schema,
)


PAGE = {"page_number": 1, "image_width_px": 100, "image_height_px": 200}


def region():
    return {"layout_region_id": "r1", "page_number": 1, "type": "Figure", "bbox_px": [10, 20, 30, 50]}


def test_bbox_value_rejects_degenerate_and_non_finite_geometry():
    assert BBoxValue.from_value([1, 2, 5, 8]).area == 24
    with pytest.raises(ValueError):
        BBoxValue.from_value([1, 2, 1, 8])
    with pytest.raises(ValueError):
        BBoxValue.from_value([1, 2, float("nan"), 8])


def test_region_schema_initializes_roles_metrics_and_history():
    value = initialize_region_schema(region(), page_record=PAGE)
    assert value["source_bbox_px"] == value["resolved_bbox_px"] == value["bbox_px"]
    assert value["physical_bbox_px"] == [10.0, 20.0, 30.0, 50.0]
    assert (value["width_px"], value["height_px"], value["area_px"]) == (20, 30, 600)
    assert value["coordinate_space"]["page_height"] == 200
    assert value["geometry_history"][0]["stage"] == "region_conversion"
    assert validate_region_schema(value, PAGE) == []


def test_geometry_lifecycle_records_accepted_and_rejected_proposals():
    value = initialize_region_schema(region(), page_record=PAGE)
    apply_geometry_change(value, [5, 10, 40, 60], stage="completion", reason="caption", accepted=True, page_record=PAGE)
    assert value["geometry_version"] == 2
    assert value["bbox_px"] == [5.0, 10.0, 40.0, 60.0]
    apply_geometry_change(value, [0, 0, 90, 190], stage="completion", reason="barrier", accepted=False, page_record=PAGE)
    assert value["geometry_version"] == 2
    assert value["bbox_px"] == [5.0, 10.0, 40.0, 60.0]
    assert [event["accepted"] for event in value["geometry_history"]] == [True, True, False]
    assert validate_region_schema(value, PAGE) == []


def test_validator_detects_bounds_metrics_and_alias_drift():
    value = initialize_region_schema(region(), page_record=PAGE)
    value["bbox_px"] = [10, 20, 110, 50]
    errors = validate_region_schema(value, PAGE)
    assert "bbox_outside_page" in errors
    assert "derived_geometry_mismatch" in errors
    assert "physical_geometry_alias_mismatch" in errors


def test_migration_is_copying_idempotent_and_rejects_future_versions():
    legacy = region()
    migrated = migrate_region(legacy)
    assert "region_schema_version" not in legacy
    assert migrate_region(migrated) == migrated
    with pytest.raises(ValueError):
        migrate_region({**legacy, "region_schema_version": 99})


def test_relationship_and_json_schemas_are_versioned():
    relationship = normalize_relationship_schema({"kind": "CAPTION_OF"})
    assert relationship["relationship_schema_version"] == 1
    root = Path(__file__).parents[1] / "schemas"
    assert json.loads((root / "layout-region-v1.schema.json").read_text())["properties"]["region_schema_version"]["const"] == 1
    assert json.loads((root / "layout-relationship-v1.schema.json").read_text())["properties"]["relationship_schema_version"]["const"] == 1
