from types import SimpleNamespace

from envira_pdf_layout.visualization import _semantic_display_regions


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
