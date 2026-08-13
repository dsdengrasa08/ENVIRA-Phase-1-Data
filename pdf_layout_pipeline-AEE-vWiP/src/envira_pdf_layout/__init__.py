"""ENVIRA PDF layout extraction and inspection pipeline."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("envira-pdf-layout")
except PackageNotFoundError:  # source checkout before installation
    from ._version import __version__

from .config import PipelineConfig
from .pipeline import run_layout_pipeline
from .types import PipelineResult
from .application import PipelineRunSummary, run_pdf
from .artifact_validation import validate_exported_artifacts as validate_artifacts

__all__ = [
    "PipelineConfig",
    "PipelineResult",
    "PipelineRunSummary",
    "run_layout_pipeline",
    "run_pdf",
    "validate_artifacts",
    "__version__",
]
