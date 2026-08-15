"""Public application factory used by the launcher notebook."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .pipeline.config import PipelineConfig
from .pipeline.docling_backend import DoclingBackend
from .pipeline.model_artifacts import ensure_model_artifacts
from .pipeline.runtime import prepare_runtime
from .service import ProcessingService
from .settings import AppSettings
from .ui import build_interface


@dataclass(frozen=True)
class ApplicationRuntime:
    settings: AppSettings
    service: ProcessingService


def initialize_application(settings: AppSettings) -> ApplicationRuntime:
    """Prepare persistent resources and initialize the Docling converter once."""
    settings = settings.normalized()
    for path in (settings.persistent_root, settings.temporary_root, settings.model_root):
        path.mkdir(parents=True, exist_ok=True)
    base = PipelineConfig.load(settings.config_path)
    base = replace(
        base,
        runtime=replace(base.runtime, project_dir=settings.persistent_root, use_google_drive=False),
        docling=replace(base.docling, artifacts_dir=settings.model_root),
    )
    base.validate()
    prepare_runtime(base.runtime)
    models = ensure_model_artifacts(base.docling)
    backend = DoclingBackend.from_config(base.docling, models["artifact_path"], base.security)
    return ApplicationRuntime(
        settings, ProcessingService(settings, base, backend, models)
    )


def create_app(runtime: ApplicationRuntime):
    """Build, but do not launch, the Gradio interface."""
    return build_interface(runtime.service, runtime.settings.max_concurrency)
