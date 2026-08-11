from envira_pdf_layout.table_context import associate_table_context


def region(region_id, typ, bbox, text="", order=1, column="single", page=1):
    return {
        "layout_region_id": region_id,
        "page_number": page,
        "type": typ,
        "docling_label": typ.lower(),
        "text": text,
        "bbox_px": bbox,
        "layout_reading_order": order,
        "reading_order_column": column,
    }


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
    assert group["caption_fragment_association"]["strategy"] == "seeded_local_graph"
    assert [item["type"] for item in regions] == [
        "Caption",
        "Text",
        "Text",
        "Text",
        "Table",
    ]


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
