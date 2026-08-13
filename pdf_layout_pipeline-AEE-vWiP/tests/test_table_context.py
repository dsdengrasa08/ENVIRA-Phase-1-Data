from envira_pdf_layout.table_context import associate_table_context


def region(
    region_id, typ, bbox, text="", order=1, column="single", page=1, orientation=None
):
    value = {
        "layout_region_id": region_id,
        "page_number": page,
        "type": typ,
        "docling_label": typ.lower(),
        "text": text,
        "bbox_px": bbox,
        "layout_reading_order": order,
        "reading_order_column": column,
    }
    if orientation is not None:
        value["orientation"] = {
            "angle_degrees": orientation,
            "confidence": 1.0,
            "source": "test_fixture",
        }
    return value


PAGES = [{"page_number": 1, "image_width_px": 1000, "image_height_px": 1000}]


def associate(regions):
    return associate_table_context(regions, PAGES, document_id="doc")


def test_identifier_caption_and_multiple_notes_are_grouped_without_bbox_change():
    regions = [
        region("id", "Text", [100, 100, 700, 130], "Table S7. Outcomes by group", 1),
        region(
            "caption", "Text", [100, 134, 700, 164], "Measured at the final visit", 2
        ),
        region("table", "Table", [100, 170, 700, 500], order=3),
        region("note1", "Text", [100, 506, 700, 530], "Note: values are estimates", 4),
        region("note2", "Footnote", [100, 534, 700, 558], "* p < .05", 5),
    ]
    group = associate(regions)[0]
    assert group["internal_id"] == "doc:p0001:t01"
    assert group["table_bbox"] == [100, 170, 700, 500]
    assert group["printed_label"].lower() == "table s7"
    assert group["identifier_region_ids"] == ["id"]
    assert group["caption_region_ids"] == ["id", "caption"]
    assert group["note_region_ids"] == ["note1", "note2"]
    assert regions[0]["type"] == "Text"


def test_optional_context_and_ordinary_paragraph_rejection():
    table = region("table", "Table", [100, 200, 700, 500], order=2)
    paragraph = region(
        "paragraph",
        "Text",
        [100, 506, 700, 560],
        "Results were subsequently compared with the earlier observations in the study.",
        3,
    )
    group = associate([table, paragraph])[0]
    assert group["caption_region_ids"] == []
    assert group["note_region_ids"] == []
    assert group["confidence"] == 1.0


def test_column_constraint_prevents_cross_column_caption():
    regions = [
        region(
            "left-text", "Caption", [40, 100, 440, 145], "Table 2. Wrong", 1, "left"
        ),
        region(
            "right-caption",
            "Caption",
            [550, 100, 950, 145],
            "Table 8. Right",
            2,
            "right",
        ),
        region("table", "Table", [550, 150, 950, 500], order=3, column="right"),
    ]
    group = associate(regions)[0]
    assert group["identifier_region_ids"] == ["right-caption"]


def test_section_heading_is_a_stopping_boundary():
    regions = [
        region("candidate", "Caption", [100, 100, 700, 130], "Table 4. Too far", 1),
        region("heading", "Section-header", [100, 135, 700, 160], "Results", 2),
        region("table", "Table", [100, 165, 700, 500], order=3),
    ]
    group = associate(regions)[0]
    assert "candidate" not in group["identifier_region_ids"]


def test_figure_caption_containing_later_table_label_never_becomes_table_caption():
    regions = [
        region(
            "combined-figure-caption",
            "Caption",
            [100, 100, 900, 190],
            "Fig. 1. Seasonal precipitation and temperature. Table 2 Field treatment establishment.",
            1,
        ),
        region("table", "Table", [100, 195, 900, 600], order=2),
    ]

    group = associate(regions)[0]
    assert group["identifier_region_ids"] == []
    assert group["caption_region_ids"] == []


def test_figure_caption_is_hard_boundary_during_table_caption_growth():
    regions = [
        region("table-label", "Caption", [100, 80, 300, 105], "Table 2.", 1),
        region(
            "figure-caption",
            "Caption",
            [100, 108, 900, 160],
            "Fig. 1. Seasonal precipitation and temperature.",
            2,
        ),
        region("table", "Table", [100, 165, 900, 600], order=3),
    ]

    group = associate(regions)[0]
    assert "figure-caption" not in group["caption_region_ids"]


def test_side_by_side_tables_use_exclusive_candidate_ownership():
    regions = [
        region(
            "left-caption", "Caption", [50, 100, 450, 140], "Table 1. Left", 1, "left"
        ),
        region(
            "right-caption",
            "Caption",
            [550, 100, 950, 140],
            "Table 2. Right",
            2,
            "right",
        ),
        region("left-table", "Table", [50, 145, 450, 500], order=3, column="left"),
        region("right-table", "Table", [550, 145, 950, 500], order=4, column="right"),
    ]
    groups = associate(regions)
    assert groups[0]["identifier_region_ids"] == ["left-caption"]
    assert groups[1]["identifier_region_ids"] == ["right-caption"]


def test_slight_caption_table_boundary_overlap_is_associated_without_bbox_change():
    caption = region("caption", "Caption", [100, 100, 700, 205], "Table 3. Results", 1)
    table = region("table", "Table", [100, 200, 700, 500], order=2)
    group = associate([caption, table])[0]
    assert group["identifier_region_ids"] == ["caption"]
    assert group["caption_region_ids"] == ["caption"]
    assert group["table_bbox"] == [100, 200, 700, 500]
    assert group["associations"][0]["features"]["boundary_overlap_page_ratio"] > 0


def test_table_label_variants_are_supporting_metadata():
    labels = ["TABLE IV. Roman", "Table B.3 Appendix", "Extended Data Table 2 Results"]
    for index, label in enumerate(labels):
        groups = associate(
            [
                region("caption", "Text", [100, 100, 700, 140], label, 1),
                region("table", "Table", [100, 145, 700, 500], order=2),
            ]
        )
        assert groups[0]["printed_label"], (index, label)


def test_seeded_caption_graph_grows_multiple_text_fragments():
    regions = [
        region("label", "Caption", [100, 80, 220, 105], "Table 12.", 1),
        region(
            "line1", "Text", [100, 108, 700, 133], "Description of measured outcomes", 2
        ),
        region(
            "line2",
            "Text",
            [100, 136, 700, 161],
            "continued for all treatment groups",
            3,
        ),
        region("line3", "Text", [100, 164, 700, 189], "and sampling periods.", 4),
        region("table", "Table", [100, 194, 700, 600], order=5),
    ]

    group = associate(regions)[0]

    assert group["identifier_region_ids"] == ["label"]
    assert group["caption_region_ids"] == ["line1", "line2", "line3"]
    fragment_edges = [
        item
        for item in group["associations"]
        if item["proposed_role"] == "caption_fragment"
    ]
    assert len(fragment_edges) == 3
    assert group["caption_fragment_association"]["strategy"] == (
        "caption_table_corridor_then_seeded_local_graph"
    )
    assert [item["type"] for item in regions] == [
        "Caption",
        "Text",
        "Text",
        "Text",
        "Table",
    ]


def test_all_text_between_caption_and_table_is_caption_even_if_paragraph_like():
    regions = [
        region("label", "Caption", [100, 80, 220, 105], "Table 13.", 1),
        region(
            "description",
            "Text",
            [100, 108, 700, 153],
            "Soil density, pH, total carbon, total nitrogen, clay, silt and sand were measured.",
            2,
        ),
        region("table", "Table", [100, 158, 700, 600], order=3),
    ]

    group = associate(regions)[0]

    assert group["identifier_region_ids"] == ["label"]
    assert group["caption_region_ids"] == ["description"]
    edge = next(
        item
        for item in group["associations"]
        if item["proposed_role"] == "caption_fragment"
    )
    assert edge["features"]["body_text_semantics_ignored"] is True


def test_seeded_graph_rejects_nearby_body_paragraph():
    regions = [
        region(
            "paragraph",
            "Text",
            [100, 75, 700, 105],
            "Results were compared with earlier observations in the study.",
            1,
        ),
        region("caption", "Caption", [100, 108, 700, 135], "Table 7. Outcomes", 2),
        region("table", "Table", [100, 140, 700, 500], order=3),
    ]

    group = associate(regions)[0]

    assert group["caption_region_ids"] == ["caption"]
    assert "paragraph" not in group["caption_region_ids"]


def test_caption_below_table_can_grow_a_continuation():
    regions = [
        region("table", "Table", [100, 100, 700, 500], order=1),
        region("label", "Caption", [100, 505, 700, 532], "Table 9.", 2),
        region(
            "description",
            "Text",
            [100, 535, 700, 562],
            "Description printed below the table",
            3,
        ),
    ]

    group = associate(regions)[0]

    assert group["identifier_region_ids"] == ["label"]
    assert group["caption_region_ids"] == ["description"]


def test_fragment_competing_between_tables_remains_unassigned():
    regions = [
        region("left-label", "Caption", [50, 100, 450, 125], "Table 1.", 1, "left"),
        region("right-label", "Caption", [550, 100, 950, 125], "Table 2.", 2, "right"),
        region("wide", "Text", [50, 128, 950, 153], "Shared-looking nearby text", 3),
        region("left-table", "Table", [50, 158, 450, 500], order=4, column="left"),
        region("right-table", "Table", [550, 158, 950, 500], order=5, column="right"),
    ]

    groups = associate(regions)

    assert all("wide" not in group["caption_region_ids"] for group in groups)


def test_overlap_relationship_evidence_is_retained_on_fragment_edge():
    regions = [
        region("label", "Caption", [100, 100, 700, 125], "Table 4.", 1),
        region("line", "Text", [100, 128, 700, 153], "continued caption", 2),
        region("table", "Table", [100, 158, 700, 500], order=3),
    ]
    relationship = {
        "left_region_id": "label",
        "right_region_id": "line",
        "kind": "FRAGMENT_CANDIDATE",
    }

    group = associate_table_context(
        regions,
        PAGES,
        document_id="doc",
        relationships=[relationship],
    )[0]
    edge = next(
        item
        for item in group["associations"]
        if item["proposed_role"] == "caption_fragment"
    )

    assert edge["features"]["relationship_kinds"] == ["FRAGMENT_CANDIDATE"]
    assert edge["features"]["components"]["overlap_evidence"] == 0.5


def test_identifier_text_is_semantic_first_even_when_detector_order_is_later():
    from envira_pdf_layout.caption_overlap import build_caption_groups

    regions = [
        region(
            "continuation", "Caption", [100, 100, 700, 125], "continued description", 1
        ),
        region("identifier", "Text", [100, 128, 700, 153], "Table 4. Results", 2),
        region("table", "Table", [100, 158, 700, 500], order=3),
    ]
    logical = associate(regions)
    groups = build_caption_groups(regions, logical, [], PAGES)
    assert groups[0]["ordered_source_region_ids"][0] == "identifier"
    assert groups[0]["text"] == "Table 4. Results continued description"


def test_fragmented_table_identifier_is_reconstructed_from_adjacent_boxes():
    regions = [
        region("word", "Text", [100, 100, 180, 125], "Table", 1),
        region("number", "Text", [185, 100, 220, 125], "4.", 2),
        region("description", "Text", [225, 100, 700, 125], "Experimental results", 3),
        region("table", "Table", [100, 130, 700, 500], order=4),
    ]
    group = associate(regions)[0]
    assert group["identifier_region_ids"] == ["word", "number", "description"]
    assert all(region["type"] == "Text" for region in regions[:3])


def test_rotated_table_accepts_caption_on_table_local_side():
    regions = [
        region("identifier", "Text", [80, 100, 120, 800], "Table S2. Outcomes", 1),
        region("table", "Table", [125, 100, 600, 800], order=2),
    ]
    group = associate(regions)[0]
    assert group["identifier_region_ids"] == ["identifier"]
    assert group["associations"][0]["direction"] == "left"


def test_rotated_caption_and_table_can_have_different_page_columns():
    regions = [
        region(
            "caption",
            "Caption",
            [80, 100, 120, 800],
            "Seasonal emissions by treatment.",
            1,
            "left",
        ),
        region(
            "table-number-text",
            "Text",
            [30, 100, 75, 800],
            "Table 2. Treatment codes.",
            2,
            "left",
        ),
        region("table", "Table", [125, 100, 600, 800], order=3, column="right"),
    ]

    group = associate(regions)[0]
    assert group["caption_side"] == "left"
    assert group["identifier_region_ids"] == ["table-number-text"]
    assert group["caption_region_ids"] == ["caption", "table-number-text"]
    caption_edge = next(
        edge for edge in group["associations"] if edge["region_id"] == "caption"
    )
    assert caption_edge["features"]["rotated_side_column_override"] is True


def test_short_table_number_continues_rotated_caption_axis_and_selects_its_side():
    from envira_pdf_layout.caption_overlap import build_caption_groups

    regions = [
        region(
            "table-number-text",
            "Text",
            [30, 760, 75, 800],
            "Table 2.",
            1,
            "left",
        ),
        region(
            "caption-left",
            "Caption",
            [30, 100, 75, 755],
            "Seasonal emissions by treatment.",
            2,
            "left",
        ),
        region("table", "Table", [80, 100, 600, 800], order=3, column="right"),
        region(
            "caption-right",
            "Caption",
            [605, 100, 655, 800],
            "Values in parentheses represent standard errors.",
            4,
            "right",
        ),
    ]

    group = associate(regions)[0]
    assert group["caption_side"] == "left"
    assert group["identifier_region_ids"] == ["table-number-text"]
    assert group["caption_region_ids"] == ["caption-left"]
    assert "caption-right" not in group["caption_region_ids"]
    caption_group = build_caption_groups(regions, [group], [], PAGES)[0]
    assert caption_group["ordered_source_region_ids"] == [
        "table-number-text",
        "caption-left",
    ]
    assert caption_group["text"] == "Table 2. Seasonal emissions by treatment."


def test_rotated_table_does_not_merge_opposite_side_detection_into_caption():
    from envira_pdf_layout.caption_overlap import build_caption_groups

    regions = [
        region(
            "caption-left",
            "Text",
            [80, 100, 120, 800],
            "Table 2. Seasonal emissions by treatment",
            1,
        ),
        region("table", "Table", [125, 100, 600, 800], order=2),
        region(
            "note-right",
            "Caption",
            [605, 100, 650, 800],
            "Values in parentheses represent standard errors",
            3,
        ),
    ]

    logical = associate(regions)
    group = logical[0]
    assert group["caption_side"] == "left"
    assert group["identifier_region_ids"] == ["caption-left"]
    assert "note-right" not in group["caption_region_ids"]

    caption = build_caption_groups(regions, logical, [], PAGES)[0]
    assert caption["ordered_source_region_ids"] == ["caption-left"]
    assert caption["bbox_px"] == [80.0, 100.0, 120.0, 800.0]
    assert caption["bbox_px"][2] < group["table_bbox"][0]


def test_fragmented_identifier_cannot_be_synthesized_across_table():
    regions = [
        region("word", "Text", [80, 100, 120, 800], "Table", 1),
        region("table", "Table", [125, 100, 600, 800], order=2),
        region("number", "Text", [605, 100, 650, 800], "4. Results", 3),
    ]

    group = associate(regions)[0]
    assert group["identifier_region_ids"] == []
    assert group["caption_region_ids"] == []


def test_body_table_reference_does_not_join_adjacent_caption():
    from envira_pdf_layout.caption_overlap import build_caption_groups

    regions = [
        region("table", "Table", [125, 100, 600, 800], order=1),
        region(
            "caption",
            "Caption",
            [605, 100, 650, 800],
            "Values in parentheses represent standard errors.",
            2,
        ),
        region(
            "table-number-text",
            "Text",
            [655, 100, 700, 800],
            "See Table 2 for treatment codes.",
            3,
        ),
    ]

    logical = associate(regions)
    group = logical[0]
    assert group["caption_side"] == "right"
    assert group["identifier_region_ids"] == []
    assert group["caption_region_ids"] == ["caption"]

    caption = build_caption_groups(regions, logical, [], PAGES)[0]
    assert caption["ordered_source_region_ids"] == ["caption"]
    assert "See Table 2" not in caption["text"]
    assert caption["bbox_px"] == [605.0, 100.0, 650.0, 800.0]
    assert caption["bbox_px"][0] > group["table_bbox"][2]


def test_leading_identifier_selects_its_lane_instead_of_crossing_table():
    from envira_pdf_layout.caption_overlap import build_caption_groups

    regions = [
        region(
            "caption-left",
            "Caption",
            [80, 100, 120, 800],
            "Seasonal emissions by treatment.",
            1,
        ),
        region("table", "Table", [125, 100, 600, 800], order=2),
        region(
            "table-number-text",
            "Text",
            [605, 100, 650, 800],
            "Table 2. Treatment codes.",
            3,
        ),
    ]

    logical = associate(regions)
    group = logical[0]
    assert group["caption_side"] == "right"
    assert group["identifier_region_ids"] == ["table-number-text"]
    assert group["caption_region_ids"] == ["table-number-text"]

    caption = build_caption_groups(regions, logical, [], PAGES)[0]
    assert caption["bbox_spans_table"] is False
    assert caption["bbox_parts"] == [[605.0, 100.0, 650.0, 800.0]]
    assert caption["bbox_px"] == [605.0, 100.0, 650.0, 800.0]
    assert caption["bbox_px"][0] > group["table_bbox"][2]


def test_explicit_270_degree_orientation_orders_identifier_before_caption():
    from envira_pdf_layout.caption_overlap import build_caption_groups

    regions = [
        region(
            "caption",
            "Caption",
            [30, 100, 75, 755],
            "Seasonal emissions by treatment.",
            1,
            orientation=270,
        ),
        region(
            "identifier",
            "Text",
            [30, 760, 75, 800],
            "Table S3.",
            2,
            orientation=270,
        ),
        region("table", "Table", [80, 100, 600, 800], order=3),
    ]
    logical = associate(regions)
    caption = build_caption_groups(regions, logical, [], PAGES)[0]
    assert caption["ordered_source_region_ids"] == ["identifier", "caption"]
    assert caption["text"] == "Table S3. Seasonal emissions by treatment."
    assert caption["orientation"]["angle_degrees"] == 270
    assert caption["geometry_space"] == "table_local_orientation"


def test_incompatible_orientation_does_not_join_caption():
    regions = [
        region(
            "caption", "Caption", [30, 100, 75, 755], "Seasonal emissions.", 1,
            orientation=90,
        ),
        region(
            "identifier", "Text", [30, 760, 75, 800], "Table 4.", 2,
            orientation=0,
        ),
        region("table", "Table", [80, 100, 600, 800], order=3),
    ]
    group = associate(regions)[0]
    assert group["identifier_region_ids"] == ["identifier"]
    assert group["caption_region_ids"] == []


def test_rotated_caption_graph_grows_plain_text_in_normalized_space():
    regions = [
        region(
            "identifier",
            "Caption",
            [30, 100, 75, 250],
            "Table 4. Seasonal emissions",
            1,
            orientation=90,
        ),
        region(
            "continuation",
            "Text",
            [30, 255, 75, 500],
            "under different treatments.",
            2,
            orientation=90,
        ),
        region("table", "Table", [80, 100, 600, 800], order=3),
    ]
    group = associate(regions)[0]
    assert group["caption_region_ids"] == ["identifier", "continuation"]
    edge = next(
        edge for edge in group["associations"] if edge["region_id"] == "continuation"
    )
    assert edge["features"]["geometry_space"] == "table_local_orientation"


def test_rotated_table_cell_identifier_is_not_caption_content():
    regions = [
        region(
            "caption", "Caption", [30, 100, 75, 500], "Seasonal emissions.", 1,
            orientation=90,
        ),
        region("table", "Table", [80, 100, 600, 800], order=2),
        region(
            "cell", "Text", [200, 200, 240, 500], "Table 4", 3,
            orientation=90,
        ),
    ]
    group = associate(regions)[0]
    assert "cell" not in group["identifier_region_ids"]
    assert "cell" not in group["caption_region_ids"]


def test_compact_identifier_overlapping_rotated_caption_boundary_is_grouped():
    """A small detector boundary overlap must not strand the Table label as Text."""
    from envira_pdf_layout.caption_overlap import build_caption_groups

    regions = [
        region(
            "identifier",
            "Text",
            [64, 315, 78, 340],
            "Table 2.",
            3,
            orientation=90,
        ),
        region(
            "caption",
            "Caption",
            [72, 20, 84, 320],
            "Seasonal emissions under different treatments.",
            1,
            orientation=90,
        ),
        region("table", "Table", [85, 20, 495, 320], order=2),
    ]

    logical = associate(regions)
    group = logical[0]
    assert group["identifier_region_ids"] == ["identifier"]
    assert group["caption_region_ids"] == ["caption", "identifier"]
    edge = next(
        edge for edge in group["associations"] if edge["region_id"] == "identifier"
    )
    assert edge["features"]["orientation_relation"] == "normalized_boundary_overlap"

    caption = build_caption_groups(regions, logical, [], PAGES)[0]
    assert caption["ordered_source_region_ids"] == ["identifier", "caption"]
    assert caption["text"] == (
        "Table 2. Seasonal emissions under different treatments."
    )
