import inspect

import pytest

from envira_pdf_layout import run_pdf, run_layout_pipeline, validate_artifacts
from envira_pdf_layout.application import InputPDFError, PipelineRunSummary


def test_application_api_is_file_oriented_and_public():
    assert list(inspect.signature(run_pdf).parameters) == [
        "source_pdf",
        "output_dir",
        "config",
        "overwrite",
        "resume",
    ]
    assert callable(run_layout_pipeline)
    assert callable(validate_artifacts)
    assert "output_dir" in PipelineRunSummary.__annotations__


def test_application_rejects_non_pdf_before_model_initialization(tmp_path):
    source = tmp_path / "input.pdf"
    source.write_text("not a PDF", encoding="utf-8")
    with pytest.raises(InputPDFError, match="not a readable PDF"):
        run_pdf(source, tmp_path / "output")


def test_application_requires_an_existing_input(tmp_path):
    with pytest.raises(FileNotFoundError, match="PDF not found"):
        run_pdf(tmp_path / "missing.pdf", tmp_path / "output")
