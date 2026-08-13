import inspect
import json
from types import SimpleNamespace

import pytest

from envira_pdf_layout import run_pdf, run_layout_pipeline, validate_artifacts
import envira_pdf_layout.application as application
from envira_pdf_layout.application import InputPDFError, PipelineRunSummary
from envira_pdf_layout.config import PipelineConfig


def test_application_api_is_file_oriented_and_public():
    assert list(inspect.signature(run_pdf).parameters) == [
        "source_pdf",
        "output_dir",
        "config",
        "overwrite",
        "resume",
        "event_sink",
        "cancellation_token",
        "attempt",
        "parent_run_id",
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


def test_application_checks_free_disk_before_model_initialization(tmp_path, monkeypatch):
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF-")
    config = PipelineConfig.load(
        environ={}, operational={"minimum_free_disk_bytes": 10**30}
    )
    monkeypatch.setattr(application.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    with pytest.raises(InputPDFError, match="free disk"):
        run_pdf(source, tmp_path / "output", config=config)


def test_failure_report_is_sanitized_and_atomic(tmp_path):
    context = SimpleNamespace(
        run_id="run",
        document_id="doc",
        source_pdf_sha256="a" * 64,
        effective_config_sha256="b" * 64,
        attempt=1,
        parent_run_id=None,
    )
    config = PipelineConfig.load(environ={})
    application._write_failure(
        tmp_path,
        context,
        RuntimeError("/private/path token=secret"),
        "failed",
        config,
    )
    payload = json.loads((tmp_path / "run_failure.json").read_text())
    assert payload["message"] == "pipeline execution failed"
    assert "private_traceback" not in payload
    assert not (tmp_path / "run_failure.json.tmp").exists()


def test_resume_uses_full_sha256_not_display_hash(tmp_path, monkeypatch):
    manifest = tmp_path / "artifact_manifest.json"
    config = PipelineConfig.load(environ={})
    manifest.write_text(
        json.dumps(
            {
                "run_status": "complete",
                "source_pdf_sha256": "a" * 64,
                "effective_config_sha256": application.effective_config_sha256(config),
            }
        ),
        encoding="utf-8",
    )
    document = SimpleNamespace(
        pdf_hash="same-short-id",
        pdf_sha256="b" * 64,
        doc_id="doc",
        artifacts=SimpleNamespace(
            artifact_manifest_json=manifest,
            document_dir=tmp_path,
        ),
    )
    monkeypatch.setattr(
        application, "validate_exported_artifacts", lambda *_: {"valid": True}
    )
    with pytest.raises(ValueError, match="input hash"):
        application._resume_summary(document, config)
