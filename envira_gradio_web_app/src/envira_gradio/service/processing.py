"""Request-scoped PDF processing service with persistent output publication."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
import threading
from uuid import uuid4

from PIL import Image

from ..pipeline.application import run_pdf
from ..pipeline.config import PipelineConfig
from ..pipeline.docling_backend import DoclingBackend
from ..settings import AppSettings


class ProcessingService:
    """Validate a Gradio upload, process it, and return only final overlay images."""

    def __init__(
        self,
        settings: AppSettings,
        base_config: PipelineConfig,
        backend: DoclingBackend,
        model_report: dict | None = None,
    ):
        self.settings = settings
        self.base_config = base_config
        self.backend = backend
        self.model_report = model_report
        self._processing_lock = threading.Lock()

    def process(
        self, uploaded_pdf: str | Path | None, progress=None
    ) -> list[tuple[Image.Image, str]]:
        if not uploaded_pdf:
            raise ValueError("Select a PDF before starting processing.")
        source = Path(uploaded_pdf).expanduser().resolve()
        if progress:
            progress(0.02, desc="Validating PDF")
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "__" + uuid4().hex[:10]
        self.settings.temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="request-", dir=self.settings.temporary_root) as temp:
            staged = Path(temp) / source.name
            shutil.copy2(source, staged)
            config = replace(
                self.base_config,
                document=replace(self.base_config.document, source_pdf=staged, run_id=run_id),
            )
            if progress:
                progress(0.08, desc="Running layout detection")
            with self._processing_lock:
                summary = run_pdf(
                    staged,
                    self.settings.persistent_root,
                    config=config,
                    backend=self.backend,
                    model_report=self.model_report,
                    overwrite=False,
                )
            overlays = sorted(summary.overlay_paths)
            if not overlays:
                raise RuntimeError("Processing completed without producing overlay images")
            if progress:
                progress(1.0, desc="Complete")
            # Do not give Gradio paths into the mounted Drive. Gradio may reject
            # files outside its cache/allowed paths, and allowing the whole Drive
            # output root would expose private pipeline artifacts through its file
            # route. Materialize detached images instead; these pixels come from
            # the exact validated overlay files that remain persistent in Drive.
            gallery_items = []
            for index, path in enumerate(overlays, 1):
                with Image.open(path) as image:
                    gallery_items.append((image.convert("RGB").copy(), f"Page {index}"))
            return gallery_items
