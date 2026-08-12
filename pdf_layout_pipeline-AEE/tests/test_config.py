from pathlib import Path
import pytest
from envira_pdf_layout.config import (
    CaptionValidationConfig,
    DocumentConfig,
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


def test_yaml_profiles_then_environment_overrides(monkeypatch, tmp_path):
    defaults = tmp_path / "defaults.yaml"
    profile = tmp_path / "profile.yaml"
    defaults.write_text("document:\n  render_dpi: 144\nheaders:\n  enabled: false\n")
    profile.write_text("document:\n  page_start: 3\n")
    monkeypatch.setenv("PHASE1_PAGE_START", "4")
    config = PipelineConfig.from_env(profiles=(defaults, profile))
    assert config.document.render_dpi == 144
    assert config.document.page_start == 4
    assert config.headers.enabled is False


def test_yaml_rejects_unknown_keys(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("document:\n  misspelled_option: true\n")
    with pytest.raises(ValueError, match="misspelled_option"):
        PipelineConfig.from_yaml(path)


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


def test_invalid_caption_validation_controls():
    with pytest.raises(ValueError):
        PipelineConfig(
            caption_validation=CaptionValidationConfig(max_parent_gap_page_ratio=1.1)
        ).validate()
    with pytest.raises(ValueError):
        PipelineConfig(
            caption_validation=CaptionValidationConfig(max_parent_gap_page_ratio=0)
        ).validate()
    with pytest.raises(ValueError):
        PipelineConfig(
            caption_validation=CaptionValidationConfig(min_segment_lines=0)
        ).validate()
    with pytest.raises(ValueError):
        PipelineConfig(
            caption_validation=CaptionValidationConfig(provider_quality_threshold=1.1)
        ).validate()
    with pytest.raises(ValueError):
        PipelineConfig(
            caption_validation=CaptionValidationConfig(parent_ambiguity_margin=-0.1)
        ).validate()
