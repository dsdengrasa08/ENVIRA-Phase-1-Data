from envira_pdf_layout.content_policy import apply_content_policy, section_category
from envira_pdf_layout.heuristics import (
    classify_document_family,
    page1_publisher_decision,
    publisher_matches,
)
from envira_pdf_layout.config import ContentPolicyConfig
from pathlib import Path


def test_publisher_terms_are_data_driven_and_require_generic_confirmation():
    assert publisher_matches("Visit ScienceDirect", ("elsevier_sciencedirect",))
    confirmed = page1_publisher_decision(
        text="Contents lists available at ScienceDirect",
        center_y_ratio=0.25,
        title_bottom_ratio=0.20,
        body_anchor_ratio=0.50,
        enabled_profiles=("elsevier_sciencedirect",),
        mode="confirmatory",
    )
    assert confirmed.action == "exclude"
    assert confirmed.destructive is True
    assert {item.category for item in confirmed.evidence} == {
        "publisher_specific_lexical",
        "generic_geometry",
        "generic_structure",
    }


def test_publisher_match_outside_valid_structure_is_observed_not_deleted():
    decision = page1_publisher_decision(
        text="Elsevier is discussed in this body paragraph",
        center_y_ratio=0.70,
        title_bottom_ratio=0.20,
        body_anchor_ratio=0.45,
        enabled_profiles=("elsevier_sciencedirect",),
        mode="confirmatory",
    )
    assert decision.action == "observe"
    assert decision.destructive is False


def test_evidence_only_profile_never_deletes():
    decision = page1_publisher_decision(
        text="Elsevier",
        center_y_ratio=0.25,
        title_bottom_ratio=0.2,
        body_anchor_ratio=0.5,
        enabled_profiles=("elsevier_sciencedirect",),
        mode="evidence_only",
    )
    assert decision.action == "observe"


def test_unknown_document_family_is_conservative():
    assert (
        classify_document_family(
            [{"page_number": 1, "text": "Meeting notes", "type": "Text"}]
        )["family"]
        == "unknown"
    )
    result = classify_document_family(
        [
            {"page_number": 1, "text": "Abstract", "type": "Text"},
            {"page_number": 1, "text": "Keywords", "type": "Caption"},
        ]
    )
    assert result["family"] == "scholarly_article"
    assert result["signals"]["abstract_heading"]
    report = classify_document_family(
        [{"page_number": 1, "text": "Technical Report No. 12", "type": "Text"}]
    )
    assert report["family"] == "technical_report"


def test_content_policy_restores_selected_valid_sections_only():
    excluded = [
        {
            "layout_region_id": "r1",
            "page_number": 5,
            "text": "References",
            "post_conclusion_sequence_index": 1,
        },
        {
            "layout_region_id": "r2",
            "page_number": 5,
            "text": "A. Citation",
            "post_conclusion_sequence_index": 2,
        },
        {
            "layout_region_id": "a1",
            "page_number": 6,
            "text": "Appendix A",
            "post_conclusion_sequence_index": 3,
        },
        {
            "layout_region_id": "a2",
            "page_number": 6,
            "text": "Proof",
            "post_conclusion_sequence_index": 4,
        },
    ]
    retained, remaining, decisions = apply_content_policy(
        excluded, ContentPolicyConfig(retain_appendices=True)
    )
    assert [row["layout_region_id"] for row in retained] == ["a1", "a2"]
    assert [row["layout_region_id"] for row in remaining] == ["r1", "r2"]
    assert decisions[-1]["section_category"] == "appendices"
    assert section_category("Acknowledgments") == "acknowledgements"
    assert section_category("References", language="unsupported") is None


def test_publisher_terms_are_not_embedded_in_production_filter_code():
    package = Path(__file__).parents[1] / "src" / "envira_pdf_layout"
    core = (package / "independent_core.py").read_text(encoding="utf-8").casefold()
    assert "page1_upper_drop_text_re" not in core
    assert "compact_footer_publisher_re" not in core
    assert "compact_footer_publisher_word_re" not in core
    profile_source = (package / "heuristics.py").read_text(encoding="utf-8")
    assert "PDF_HASH" not in profile_source
    assert "bbox_px" not in profile_source
