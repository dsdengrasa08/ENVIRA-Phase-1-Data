"""Application-lifetime Docling model and backend initialization."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from envira_pdf_layout.docling_backend import DoclingBackend
from envira_pdf_layout.model_artifacts import ensure_model_artifacts
from envira_pdf_layout.runtime import prepare_runtime

from ..settings import AppSettings


@dataclass
class ModelService:
    backend: DoclingBackend
    model_report: dict[str, Any]
    conversion_lock: Lock

    @classmethod
    def initialize(cls, settings: AppSettings) -> "ModelService":
        bootstrap_source = settings.temporary_root / "model-bootstrap.pdf"
        config = settings.pipeline_config(bootstrap_source, "model-bootstrap")
        prepare_runtime(config.runtime)
        report = ensure_model_artifacts(config.docling)
        backend = DoclingBackend.from_config(
            config.docling, report["artifact_path"], config.security
        )
        return cls(backend=backend, model_report=report, conversion_lock=Lock())
