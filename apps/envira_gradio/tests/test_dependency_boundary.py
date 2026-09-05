"""The web application consumes the canonical pipeline package without vendoring it."""
from pathlib import Path


def test_application_does_not_vendor_pipeline_sources():
    package = Path(__file__).resolve().parents[1] / "src" / "envira_gradio"
    assert not (package / "pipeline").exists()


def test_application_declares_pipeline_dependency():
    metadata = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert '"envira-pdf-layout==0.1.8"' in metadata
