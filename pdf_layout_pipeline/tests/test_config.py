from pathlib import Path
import pytest
from envira_pdf_layout.config import DocumentConfig, PipelineConfig


def test_env_config(monkeypatch, tmp_path):
    monkeypatch.setenv("PHASE1_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("PHASE1_PAGE_START", "2")
    monkeypatch.setenv("PHASE1_DOCLING_EXCLUDE_LABELS", "picture,chart")
    config = PipelineConfig.from_env(source_pdf=Path("paper.pdf"))
    assert config.document.page_start == 2
    assert config.exclude_labels == {"picture", "chart"}


def test_invalid_range():
    with pytest.raises(ValueError):
        PipelineConfig(document=DocumentConfig(page_start=3, page_end=2)).validate()
