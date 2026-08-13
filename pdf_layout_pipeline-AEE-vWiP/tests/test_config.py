from pathlib import Path
import pytest
from envira_pdf_layout.config import (
    CaptionAssociationConfig,
    ContainmentConfig,
    DocumentConfig,
    HeaderFilterConfig,
    ErrorPolicyConfig,
    OverlapResolutionConfig,
    PipelineConfig,
    TableContextConfig,
)


def test_env_config(monkeypatch, tmp_path):
    monkeypatch.setenv("PHASE1_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("PHASE1_PAGE_START", "2")
    monkeypatch.setenv("PHASE1_DOCLING_EXCLUDE_LABELS", "picture,chart")
    config = PipelineConfig.from_env(source_pdf=Path("paper.pdf"))
    assert config.document.page_start == 2
    assert config.exclude_labels == {"picture", "chart"}


def test_yaml_environment_and_explicit_precedence(monkeypatch, tmp_path):
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "document:\n  page_start: 2\n  render_dpi: 144\n"
        "docling:\n  do_ocr: false\n  do_table_structure: false\n"
        "headers:\n  enabled: false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PHASE1_PAGE_START", "3")
    monkeypatch.setenv("PHASE1_DOCLING_DO_OCR", "true")
    config = PipelineConfig.load(profile, page_start=4, source_pdf="paper.pdf")
    assert config.document.page_start == 4
    assert config.document.render_dpi == 144
    assert config.docling.do_ocr is True
    assert config.docling.do_table_structure is False
    assert config.headers.enabled is False
    assert config.value_sources["document.page_start"] == "explicit"
    assert config.value_sources["docling.do_ocr"].startswith("environment:")


def test_every_docling_environment_option_is_loaded(monkeypatch):
    monkeypatch.setenv("PHASE1_DOCLING_DO_TABLE_STRUCTURE", "0")
    monkeypatch.setenv("PHASE1_DOCLING_DO_FORMULA_ENRICHMENT", "false")
    monkeypatch.setenv("PHASE1_DOCLING_DO_CODE_ENRICHMENT", "yes")
    monkeypatch.setenv("PHASE1_DOCLING_CODE_FORMULA_PRESET", "custom")
    monkeypatch.setenv("PHASE1_DOCLING_MIN_MODEL_SIZE_MB", "42.5")
    config = PipelineConfig.from_env()
    assert config.docling.do_table_structure is False
    assert config.docling.do_formula_enrichment is False
    assert config.docling.do_code_enrichment is True
    assert config.docling.code_formula_preset == "custom"
    assert config.docling.min_model_size_mb == 42.5


def test_predictable_environment_name_exists_for_every_typed_field(monkeypatch):
    monkeypatch.setenv("PHASE1_HEADERS_ENABLED", "false")
    monkeypatch.setenv("PHASE1_READING_ORDER_COLUMN_GAP_RATIO", "0.08")
    monkeypatch.setenv("PHASE1_EXPORT_WRITE_OVERLAYS", "0")
    config = PipelineConfig.load()
    assert config.headers.enabled is False
    assert config.reading_order.column_gap_ratio == 0.08
    assert config.export.write_overlays is False


def test_unknown_yaml_section_and_field_are_rejected(tmp_path):
    section = tmp_path / "section.yaml"
    section.write_text("mystery: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown configuration section"):
        PipelineConfig.load(section, environ={})
    field = tmp_path / "field.yaml"
    field.write_text("document:\n  mystery: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown configuration field"):
        PipelineConfig.load(field, environ={})


def test_effective_config_is_deterministic_and_json_serializable(tmp_path):
    import json

    config = PipelineConfig.load(
        environ={"PHASE1_DOCLING_EXCLUDE_LABELS": "chart,picture"},
        source_pdf=tmp_path / "paper.pdf",
    )
    first = config.to_dict()
    assert first == config.to_dict()
    assert first["document"]["source_pdf"].endswith("paper.pdf")
    assert first["exclude_labels"] == ["chart", "picture"]
    json.dumps(first)


def test_invalid_boolean_is_rejected(tmp_path):
    profile = tmp_path / "invalid.yaml"
    profile.write_text("docling:\n  do_ocr: perhaps\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a boolean"):
        PipelineConfig.load(profile, environ={})


def test_legacy_core_environment_is_captured_not_live(monkeypatch):
    monkeypatch.setenv("PHASE1_FUTURE_HEURISTIC", "captured")
    config = PipelineConfig.load()
    monkeypatch.setenv("PHASE1_FUTURE_HEURISTIC", "changed-after-load")
    assert config.legacy_core_environment["PHASE1_FUTURE_HEURISTIC"] == "captured"


def test_model_artifact_path_is_derived_from_effective_project(tmp_path):
    config = PipelineConfig.load(
        environ={"PHASE1_PROJECT_DIR": str(tmp_path)}, source_pdf="paper.pdf"
    )
    assert config.docling.artifacts_dir == tmp_path / "artifacts" / "docling_models"
    assert (
        config.value_sources["docling.artifacts_dir"] == "derived:runtime.project_dir"
    )


def test_invalid_range():
    with pytest.raises(ValueError):
        PipelineConfig(document=DocumentConfig(page_start=3, page_end=2)).validate()


def test_invalid_table_context_ratio():
    with pytest.raises(ValueError):
        PipelineConfig(
            table_context=TableContextConfig(max_vertical_gap_page_ratio=1.1)
        ).validate()


def test_invalid_caption_fragment_controls():
    with pytest.raises(ValueError):
        PipelineConfig(
            table_context=TableContextConfig(fragment_min_horizontal_overlap=1.1)
        ).validate()
    with pytest.raises(ValueError):
        PipelineConfig(
            table_context=TableContextConfig(fragment_max_line_gap_ratio=-0.1)
        ).validate()


def test_invalid_generalized_overlap_ratio():
    with pytest.raises(ValueError):
        PipelineConfig(
            overlap_resolution=OverlapResolutionConfig(duplicate_iou=1.1)
        ).validate()


def test_default_profile_uses_confirmatory_heuristics_and_auditable_policy():
    profile = Path(__file__).parents[1] / "config" / "default.yaml"
    config = PipelineConfig.load(profile, environ={})
    assert config.heuristics.publisher_mode == "confirmatory"
    assert config.heuristics.document_family == "auto"
    assert config.content_policy.preserve_excluded_sections_in_secondary_stream


def test_unknown_publisher_profile_is_rejected():
    with pytest.raises(ValueError, match="Unknown publisher profile"):
        PipelineConfig.load(
            environ={}, heuristics={"publisher_profiles": ["one_document_hack"]}
        )


def test_invalid_figure_completion_limits_are_rejected():
    with pytest.raises(ValueError, match="area_multiplier"):
        PipelineConfig.load(environ={}, figures={"max_completion_area_multiplier": 0.5})


def test_invalid_shared_containment_threshold_is_rejected():
    with pytest.raises(ValueError, match="containment strong_child_coverage"):
        PipelineConfig(
            containment=ContainmentConfig(strong_child_coverage=1.1)
        ).validate()


def test_invalid_caption_association_controls_are_rejected():
    with pytest.raises(ValueError, match="caption association ambiguity_margin"):
        PipelineConfig(
            caption_association=CaptionAssociationConfig(ambiguity_margin=-0.1)
        ).validate()


def test_invalid_header_roi_ocr_controls_are_rejected():
    with pytest.raises(ValueError, match="roi_ocr_dpi"):
        PipelineConfig(headers=HeaderFilterConfig(roi_ocr_dpi=71)).validate()
    with pytest.raises(ValueError, match="roi_ocr_language"):
        PipelineConfig(headers=HeaderFilterConfig(roi_ocr_language=" ")).validate()


def test_legacy_header_roi_ocr_environment_maps_to_typed_config():
    config = PipelineConfig.load(
        environ={
            "PHASE1_LATER_PAGE_HEADER_PDF_ROI_OCR_FALLBACK": "0",
            "PHASE1_LATER_PAGE_HEADER_PDF_ROI_OCR_DPI": "240",
            "PHASE1_LATER_PAGE_HEADER_PDF_ROI_OCR_LANGUAGE": "deu",
        }
    )
    assert not config.headers.roi_ocr_fallback
    assert config.headers.roi_ocr_dpi == 240
    assert config.headers.roi_ocr_language == "deu"


def test_default_profile_loads_caption_association_controls():
    profile = Path(__file__).parents[1] / "config" / "default.yaml"
    config = PipelineConfig.load(profile, environ={})
    assert config.caption_association.enabled
    assert config.caption_association.acceptance_score == 0.35
    assert (
        config.value_sources["caption_association.acceptance_score"]
        == f"profile:{profile.resolve()}"
    )


def test_invalid_error_policy_is_rejected():
    with pytest.raises(ValueError, match="error_policy mode"):
        PipelineConfig(error_policy=ErrorPolicyConfig(mode="guess")).validate()
    with pytest.raises(ValueError, match="max_failed_page_ratio"):
        PipelineConfig(
            error_policy=ErrorPolicyConfig(max_failed_page_ratio=1.1)
        ).validate()
