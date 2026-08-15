"""Upload-to-overlay application use case."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
from uuid import uuid4

from envira_pdf_layout.application import InputPDFError, run_pdf

from ..errors import WebAppError
from ..settings import AppSettings
from .model_service import ModelService
from .temp_workspace import temporary_workspace


@dataclass(frozen=True)
class WebProcessingResult:
    status: str
    overlay_paths: tuple[Path, ...]
    page_count: int


class ProcessingService:
    def __init__(self, settings: AppSettings, models: ModelService):
        self.settings = settings
        self.models = models

    def process(self, uploaded_pdf: str | Path) -> WebProcessingResult:
        source = Path(uploaded_pdf)
        self._validate_upload(source)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{timestamp}__{uuid4().hex[:12]}"
        with temporary_workspace(self.settings.temporary_root) as workspace:
            staged = workspace / "upload.pdf"
            shutil.copy2(source, staged)
            self._validate_pdf_structure(staged)
            config = self.settings.pipeline_config(staged, run_id)
            try:
                # Docling converter state is shared to avoid model reloads and serialized
                # until its concurrency guarantees are established.
                with self.models.conversion_lock:
                    summary = run_pdf(
                        staged,
                        self.settings.persistent_output_root,
                        config=config,
                        backend=self.models.backend,
                        model_report=self.models.model_report,
                    )
            except InputPDFError as exc:
                raise WebAppError(str(exc)) from exc
            except (FileNotFoundError, ValueError) as exc:
                raise WebAppError("The PDF could not be processed.") from exc
        overlays = tuple(path for path in summary.overlay_paths if path.is_file())
        if not overlays:
            raise WebAppError("Processing completed without displayable page overlays.")
        return WebProcessingResult(summary.status, overlays, len(overlays))

    def _validate_upload(self, source: Path) -> None:
        if not source.is_file():
            raise WebAppError("Select a PDF before starting.")
        if source.suffix.lower() != ".pdf":
            raise WebAppError("The selected file is not a PDF.")
        if source.stat().st_size > self.settings.max_upload_bytes:
            raise WebAppError("The PDF exceeds the configured upload limit.")
        with source.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise WebAppError("The selected file is not a valid PDF.")

    @staticmethod
    def _validate_pdf_structure(source: Path) -> None:
        import pymupdf as fitz
        try:
            with fitz.open(source) as document:
                if document.needs_pass:
                    raise WebAppError("Password-protected PDFs are not supported.")
                if document.page_count < 1:
                    raise WebAppError("The PDF contains no pages.")
        except WebAppError:
            raise
        except Exception as exc:
            raise WebAppError("The PDF is corrupt or unreadable.") from exc
