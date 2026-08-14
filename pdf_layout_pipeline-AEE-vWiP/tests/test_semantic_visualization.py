from types import SimpleNamespace

from envira_pdf_layout.visualization import _display_bbox, _semantic_display_regions


def test_formula_display_uses_expanded_visual_crop_but_text_uses_physical_bbox():
    formula = {
        "type": "Formula",
        "bbox_px": [100, 100, 300, 140],
        "visual_crop_bbox_px": [95, 90, 305, 150],
    }
    text = {
        "type": "Text",
        "bbox_px": [100, 160, 300, 200],
        "visual_crop_bbox_px": [95, 150, 305, 210],
    }
    assert _display_bbox(formula) == [95, 90, 305, 150]
    assert _display_bbox(text) == [100, 160, 300, 200]


def test_semantic_display_replaces_caption_members_with_one_group_box():
    run = SimpleNamespace(
        resolved_regions=[
            {
                "layout_region_id": "identifier",
                "page_number": 5,
                "type": "Caption",
                "bbox_px": [10, 10, 80, 30],
                "resolved_reading_order": 1,
                "emission_policy": "suppress_duplicate_text_emission",
            },
            {
                "layout_region_id": "caption",
                "page_number": 5,
                "type": "Caption",
                "bbox_px": [10, 10, 300, 70],
                "resolved_reading_order": 2,
                "emission_policy": "emit_canonical",
            },
            {
                "layout_region_id": "table",
                "page_number": 5,
                "type": "Table",
                "bbox_px": [10, 75, 300, 400],
                "resolved_reading_order": 3,
                "emission_policy": "emit_canonical",
            },
        ],
        caption_groups=[
            {
                "resolved_region_id": "table-1:caption",
                "page_number": 5,
                "text": "Table 3. Stalk yield",
                "ordered_source_region_ids": ["identifier", "caption"],
                "source_region_ids": ["identifier", "caption"],
            }
        ],
    )
    regions = _semantic_display_regions(run, {"page_number": 5})
    assert [region["layout_region_id"] for region in regions] == [
        "table-1:caption",
        "table",
    ]
    assert regions[0]["bbox_px"] == [10.0, 10.0, 300.0, 70.0]
    assert regions[0]["text"] == "Table 3. Stalk yield"


def test_semantic_display_hides_nested_children_but_physical_view_retains_them():
    run = SimpleNamespace(
        resolved_regions=[
            {
                "layout_region_id": "figure",
                "page_number": 1,
                "type": "Figure",
                "bbox_px": [10, 10, 300, 300],
                "resolved_reading_order": 1,
                "emission_policy": "emit_canonical",
            },
            {
                "layout_region_id": "panel-label",
                "page_number": 1,
                "type": "Text",
                "bbox_px": [20, 20, 40, 40],
                "resolved_reading_order": None,
                "emission_policy": "emit_as_nested_child",
            },
        ],
        caption_groups=[],
    )
    assert [
        r["layout_region_id"]
        for r in _semantic_display_regions(run, {"page_number": 1})
    ] == ["figure"]
    assert len(run.resolved_regions) == 2


def test_semantic_display_keeps_cross_table_caption_members_as_separate_boxes():
    run = SimpleNamespace(
        resolved_regions=[
            {
                "layout_region_id": "caption-left",
                "page_number": 1,
                "type": "Caption",
                "text": "Caption description",
                "bbox_px": [10, 10, 40, 300],
                "resolved_reading_order": 1,
                "emission_policy": "emit_canonical",
            },
            {
                "layout_region_id": "table-number-right",
                "page_number": 1,
                "type": "Text",
                "text": "See Table 2 for treatment codes",
                "bbox_px": [310, 10, 340, 300],
                "resolved_reading_order": 3,
                "emission_policy": "emit_canonical",
            },
            {
                "layout_region_id": "table",
                "page_number": 1,
                "type": "Table",
                "bbox_px": [45, 10, 305, 300],
                "resolved_reading_order": 2,
                "emission_policy": "emit_canonical",
            },
        ],
        caption_groups=[
            {
                "resolved_region_id": "table-1:caption",
                "page_number": 1,
                "text": "See Table 2 for treatment codes Caption description",
                "ordered_source_region_ids": ["table-number-right", "caption-left"],
                "source_region_ids": ["table-number-right", "caption-left"],
                "bbox_spans_table": True,
            }
        ],
    )

    regions = _semantic_display_regions(run, {"page_number": 1})
    caption_parts = [region for region in regions if region["type"] == "Caption"]
    assert [region["bbox_px"] for region in caption_parts] == [
        [10.0, 10.0, 40.0, 300.0],
        [310.0, 10.0, 340.0, 300.0],
    ]
    assert all(
        box[2] <= 45 or box[0] >= 305
        for box in (region["bbox_px"] for region in caption_parts)
    )
