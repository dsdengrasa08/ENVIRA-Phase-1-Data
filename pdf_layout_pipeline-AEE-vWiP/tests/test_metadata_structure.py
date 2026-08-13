from types import SimpleNamespace

from envira_pdf_layout.config import Page1FilterConfig
from envira_pdf_layout.filtering.metadata_structure import (
    normalize_page1_metadata_structure,
)
from envira_pdf_layout.filtering.front_matter_roles import (
    classify_page1_front_matter_roles,
)


def region(identifier, text, x0, y0, x1, y1, typ="Text", page=1):
    return {
        "layout_region_id": identifier,
        "page_number": page,
        "text": text,
        "orig": text,
        "type": typ,
        "docling_label": typ.lower().replace("-", "_"),
        "bbox_px": [x0, y0, x1, y1],
        "width_px": x1 - x0,
        "height_px": y1 - y0,
        "area_px": (x1 - x0) * (y1 - y0),
    }


def page_map():
    return {1: SimpleNamespace(width_px=1000, height_px=1000)}


def by_id(result):
    return {row["layout_region_id"]: row for row in result.regions}


def test_infers_container_heading_and_groups_descriptor_value_continuations():
    rows = [
        region("container", "PUBLICATION DATA", 60, 300, 290, 320),
        region("history-label", "Manuscript record:", 60, 335, 250, 352),
        region(
            "history-values",
            "Submitted 2 January 2024\nAccepted 8 March 2024",
            60,
            356,
            290,
            390,
        ),
        region("terms-label", "Index terms:", 60, 410, 190, 427),
        region(
            "terms-a", "soil carbon\ncrop systems\nwater management", 60, 431, 260, 480
        ),
        region("terms-b", "nutrient cycling", 60, 484, 190, 501),
        region("abstract", "Abstract", 360, 335, 470, 355, "Section-header"),
        region(
            "abstract-body",
            "This is a sufficiently long scientific paragraph. " * 4,
            360,
            360,
            900,
            500,
        ),
    ]

    result = normalize_page1_metadata_structure(rows, page_map(), Page1FilterConfig())
    indexed = by_id(result)

    assert indexed["container"]["type"] == "Caption"
    assert indexed["container"]["source_type"] == "Text"
    assert indexed["container"]["semantic_role"] == "metadata_container_heading"
    assert "terms-a" not in indexed
    assert "terms-b" not in indexed
    grouped = next(
        row
        for row in result.regions
        if row.get("metadata_field_category") == "scientific_descriptors"
        and row.get("semantic_role") == "metadata_field_value"
    )
    assert grouped["type"] == "Text"
    assert grouped["source_region_ids"] == ["terms-a", "terms-b"]
    assert grouped["bbox_px"] == [60.0, 431.0, 260.0, 501.0]
    assert grouped["text"] == (
        "soil carbon\ncrop systems\nwater management\nnutrient cycling"
    )
    assert indexed["abstract-body"]["text"].startswith("This is")


def test_new_field_label_stops_previous_field_and_columns_do_not_cross():
    rows = [
        region("terms-label", "Subject terms:", 50, 300, 180, 320),
        region("term", "forest ecology", 50, 325, 180, 345),
        region("codes-label", "Classification codes:", 50, 350, 230, 370),
        region("code", "Q12; R14", 50, 375, 150, 395),
        region("other-column", "unrelated narrow text", 620, 325, 780, 345),
    ]

    result = normalize_page1_metadata_structure(rows, page_map(), Page1FilterConfig())
    indexed = by_id(result)

    assert indexed["term"]["metadata_field_category"] == "scientific_descriptors"
    assert indexed["code"]["metadata_field_category"] == "scientific_descriptors"
    assert "metadata_field_id" not in indexed["other-column"]
    assert indexed["term"]["metadata_field_id"] != indexed["code"]["metadata_field_id"]


def test_heading_without_multiple_populated_fields_is_not_reclassified():
    rows = [
        region("heading", "DOCUMENT DETAILS", 50, 300, 250, 320),
        region("terms-label", "Topic areas:", 50, 330, 170, 350),
        region("term", "hydrology", 50, 355, 150, 375),
    ]

    result = normalize_page1_metadata_structure(rows, page_map(), Page1FilterConfig())

    assert by_id(result)["heading"]["type"] == "Text"
    assert "semantic_role" not in by_id(result)["heading"]


def test_horizontal_inline_field_is_annotated_without_manufacturing_duplicates():
    rows = [region("inline", "Index terms: forests; soils; climate", 50, 300, 420, 325)]

    result = normalize_page1_metadata_structure(rows, page_map(), Page1FilterConfig())

    assert len(result.regions) == 1
    inline = result.regions[0]
    assert inline["layout_region_id"] == "inline"
    assert inline["text"] == rows[0]["text"]
    assert inline["semantic_role"] == "metadata_field_label_and_value"
    assert inline["metadata_field_category"] == "scientific_descriptors"
    assert result.diagnostics["populated_field_count"] == 1


def test_ambiguous_prose_and_later_pages_are_unchanged():
    rows = [
        region(
            "prose",
            "Classification codes improve retrieval. This paragraph explains the experimental indexing method in detail.",
            50,
            300,
            700,
            360,
        ),
        region("page2", "Subject terms:", 50, 100, 180, 120, page=2),
    ]

    result = normalize_page1_metadata_structure(rows, page_map(), Page1FilterConfig())

    assert {row["layout_region_id"] for row in result.regions} == {"prose", "page2"}
    assert all("metadata_field_id" not in row for row in result.regions)


def test_history_policy_filters_only_history_field_after_structure_inference():
    rows = [
        region("container", "DOCUMENT DATA", 50, 250, 250, 270),
        region("history-label", "Submission timeline:", 50, 280, 210, 300),
        region(
            "history-values",
            "Submitted 2 January 2024\nRevised 3 February 2024\nAccepted 4 March 2024",
            50,
            305,
            270,
            355,
        ),
        region("terms-label", "Subject areas:", 50, 365, 190, 385),
        region("term-a", "soil science", 50, 390, 180, 410),
        region("term-b", "agroecology", 50, 415, 170, 435),
        region("abstract", "Abstract", 350, 280, 470, 300, "Section-header"),
        region(
            "abstract-body",
            "This scientific paragraph presents the study question and its results. "
            "It remains substantive body content for the article.",
            350,
            305,
            900,
            380,
        ),
        region("intro", "1 Introduction", 50, 500, 220, 525, "Section-header"),
    ]

    structured = normalize_page1_metadata_structure(
        rows, page_map(), Page1FilterConfig()
    )
    classified = classify_page1_front_matter_roles(
        structured.regions, page_map(), Page1FilterConfig()
    )
    kept = {row["layout_region_id"]: row for row in classified.kept}
    excluded = {row["layout_region_id"]: row for row in classified.excluded}

    assert kept["container"]["type"] == "Caption"
    descriptor = next(
        row
        for row in kept.values()
        if row.get("metadata_field_category") == "scientific_descriptors"
        and row.get("semantic_role") == "metadata_field_value"
    )
    assert descriptor["source_region_ids"] == ["term-a", "term-b"]
    assert any(
        row.get("metadata_field_category") == "administrative_history"
        for row in excluded.values()
    )
    assert all(
        row.get("document_role") == "article_history" for row in excluded.values()
    )


def test_merged_label_values_absorb_detached_final_value_and_enable_container():
    """Model the detector shape seen in narrow first-page metadata columns."""
    rows = [
        region("container", "P U B L I C A T I O N  D A T A", 50, 250, 280, 270),
        region(
            "history",
            "Submission timeline:\nSubmitted 2 January 2024\nAccepted 4 March 2024",
            50,
            280,
            275,
            345,
        ),
        region(
            "terms-main",
            "Subject terms:\nNitrogen balance\nAgricultural pollution\nProcess model\nWatershed",
            50,
            365,
            285,
            455,
        ),
        region("terms-final", "Livestock production", 50, 458, 230, 476),
        region("abstract", "Abstract", 350, 280, 470, 300, "Section-header"),
    ]

    result = normalize_page1_metadata_structure(rows, page_map(), Page1FilterConfig())
    indexed = by_id(result)

    assert indexed["container"]["type"] == "Caption"
    assert "terms-main" not in indexed
    assert "terms-final" not in indexed
    descriptor = next(
        row
        for row in result.regions
        if row.get("metadata_field_category") == "scientific_descriptors"
        and row.get("semantic_role") == "metadata_field_value"
    )
    assert descriptor["source_region_ids"] == ["terms-main", "terms-final"]
    assert descriptor["bbox_px"] == [50.0, 365.0, 285.0, 476.0]
    assert descriptor["text"].endswith("Watershed\nLivestock production")
