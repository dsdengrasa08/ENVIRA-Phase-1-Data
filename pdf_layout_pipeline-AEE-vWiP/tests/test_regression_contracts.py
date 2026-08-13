import json
from pathlib import Path

import pytest

from envira_pdf_layout.artifact_validation import validate_relationship_graph
from envira_pdf_layout.caption_association import associate_captions
from envira_pdf_layout.config import CaptionAssociationConfig, ContainmentConfig
from envira_pdf_layout.layout_overlap import resolve_layout_overlaps
from envira_pdf_layout.nested_containment import (
    analyze_nested_containment,
    resolve_nested_hierarchy,
)
from envira_pdf_layout.schema import normalize_relationship_schema


FIXTURES = Path(__file__).parent / "fixtures" / "regression"
PAGES = [{"page_number": 1, "image_width_px": 700, "image_height_px": 700}]


@pytest.mark.regression
@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
def test_generated_regression_fixture_contracts(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == 1
    regions = fixture["regions"]
    for index, region in enumerate(regions, 1):
        region.setdefault("docling_label", region["type"].lower())
        region.setdefault("layout_reading_order", index)
        region.setdefault("reading_order_column", "single")
    overlap = resolve_layout_overlaps(regions, PAGES)
    proposals = analyze_nested_containment(
        overlap.regions, overlap.relationships, config=ContainmentConfig()
    )
    hierarchy = resolve_nested_hierarchy(
        overlap.regions, proposals, ContainmentConfig()
    )
    captions = associate_captions(
        hierarchy.regions, PAGES, config=CaptionAssociationConfig()
    )
    relationships = [
        normalize_relationship_schema(relationship)
        for relationship in hierarchy.relationships + captions
    ]
    assert validate_relationship_graph(hierarchy.regions, relationships)["valid"]
    expected = fixture["expected"]
    if "nested_child_ids" in expected:
        assert {row["layout_region_id"] for row in hierarchy.nested_regions} == set(
            expected["nested_child_ids"]
        )
    if "caption_parent_id" in expected:
        associated = [row for row in captions if row["status"] == "associated"]
        assert associated[0]["parent_region_id"] == expected["caption_parent_id"]
