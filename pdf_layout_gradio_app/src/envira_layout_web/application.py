"""Composition root shared by the notebook and Python launcher."""

from __future__ import annotations

from .services.model_service import ModelService
from .services.processing import ProcessingService
from .settings import AppSettings
from .ui.gradio_app import build_gradio_app


def create_app(settings: AppSettings, models: ModelService | None = None):
    settings.prepare()
    resources = models or ModelService.initialize(settings)
    return build_gradio_app(ProcessingService(settings, resources))
