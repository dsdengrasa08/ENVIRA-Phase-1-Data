from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import pytest

from envira_layout_web.errors import WebAppError
from envira_layout_web.services.processing import ProcessingService
from envira_layout_web.settings import AppSettings


def service(tmp_path):
    profile = tmp_path / "default.yaml"
    profile.write_text("{}\n", encoding="utf-8")
    settings = AppSettings(
        app_root=tmp_path,
        persistent_output_root=tmp_path / "drive",
        temporary_root=tmp_path / "temp",
        config_profile=profile,
        max_upload_bytes=20,
    )
    return ProcessingService(
        settings,
        SimpleNamespace(backend=object(), model_report={}, conversion_lock=Lock()),
    )


def test_rejects_non_pdf_extension(tmp_path):
    upload = tmp_path / "input.txt"
    upload.write_bytes(b"%PDF-")
    with pytest.raises(WebAppError, match="not a PDF"):
        service(tmp_path)._validate_upload(upload)


def test_rejects_spoofed_pdf(tmp_path):
    upload = tmp_path / "input.pdf"
    upload.write_bytes(b"hello")
    with pytest.raises(WebAppError, match="not a valid PDF"):
        service(tmp_path)._validate_upload(upload)


def test_rejects_oversized_upload(tmp_path):
    upload = tmp_path / "input.pdf"
    upload.write_bytes(b"%PDF-" + b"x" * 30)
    with pytest.raises(WebAppError, match="upload limit"):
        service(tmp_path)._validate_upload(upload)
