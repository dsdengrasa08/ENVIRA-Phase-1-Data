"""File-oriented application service above the model-independent pipeline API."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from .artifact_validation import validate_exported_artifacts
from .config import PipelineConfig
from .security import secure_directory, secure_file


class InputPDFError(ValueError):
    pass


class DependencyUnavailableError(RuntimeError):
    pass


class ArtifactValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PipelineRunSummary:
    status: str
    document_id: str
    output_dir: Path
    manifest_path: Path
    artifact_validation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "document_id": self.document_id,
            "output_dir": str(self.output_dir),
            "manifest_path": str(self.manifest_path),
            "artifact_validation": self.artifact_validation,
        }


def effective_config_sha256(config: PipelineConfig) -> str:
    payload = json.dumps(
        config.to_dict(include_provenance=False), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def run_pdf(
    source_pdf: str | Path,
    output_dir: str | Path,
    *,
    config: PipelineConfig | None = None,
    overwrite: bool = False,
    resume: bool = False,
) -> PipelineRunSummary:
    """Run validation, conversion, processing, export, and post-export validation."""
    if overwrite and resume:
        raise ValueError("overwrite and resume are mutually exclusive")
    source = Path(source_pdf).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"PDF not found: {source}")
    with source.open("rb") as stream:
        signature = stream.read(5)
    if source.suffix.lower() != ".pdf" or signature != b"%PDF-":
        raise InputPDFError(f"input is not a readable PDF: {source}")
    root = Path(output_dir).expanduser().resolve()
    base = config or PipelineConfig.load(source_pdf=source)
    if source.stat().st_size > base.security.max_input_pdf_bytes:
        raise InputPDFError("input exceeds security.max_input_pdf_bytes")
    config = replace(
        base,
        runtime=replace(base.runtime, project_dir=root, use_google_drive=False),
        document=replace(base.document, source_pdf=source),
        docling=(
            replace(base.docling, artifacts_dir=root / "artifacts" / "docling_models")
            if base.value_sources.get("docling.artifacts_dir", "").startswith("derived:")
            else base.docling
        ),
    )
    config.validate()

    # Heavy imports and model initialization are intentionally below the file checks.
    from .docling_backend import DoclingBackend
    from .export import export_pipeline_result, mark_manifest_validated
    from .model_artifacts import ensure_model_artifacts
    from .paths import prepare_document_context
    from .pdf_io import prepare_pages
    from .pipeline import run_layout_pipeline
    from .runtime import prepare_runtime
    from .supply_chain import environment_fingerprint

    prepare_runtime(config.runtime)
    document = prepare_document_context(config)
    target = document.artifacts.document_dir
    terminal = [target / name for name in ("_SUCCESS", "_PARTIAL", "_FAILED")]
    if any(path.exists() for path in terminal):
        if resume:
            return _resume_summary(document, config)
        if not overwrite:
            raise FileExistsError(
                f"completed output already exists: {target}; use overwrite or resume"
            )
        expected_root = (
            config.runtime.project_dir / "outputs" / "docling_layout_only"
        ).resolve()
        if not target.resolve().is_relative_to(expected_root):
            raise ValueError("refusing to overwrite a directory outside the output root")
        sentinel = target / ".envira-run-root"
        if not sentinel.is_file() or sentinel.read_text(encoding="utf-8").strip() != document.doc_id:
            raise ValueError("refusing to overwrite a directory not owned by ENVIRA")
        shutil.rmtree(target)
        for directory in (
            target,
            document.artifacts.page_pdf_dir,
            document.artifacts.page_image_dir,
            document.artifacts.overlay_dir,
        ):
            secure_directory(directory, config.security.secure_directory_mode)
        sentinel.write_text(document.doc_id + "\n", encoding="utf-8")
        secure_file(sentinel, config.security.secure_file_mode)

    try:
        try:
            models = ensure_model_artifacts(config.docling)
        except FileNotFoundError as exc:
            raise DependencyUnavailableError(str(exc)) from exc
        pages = prepare_pages(document, config.document.render_dpi)
        backend = DoclingBackend.from_config(
            config.docling, models["artifact_path"], config.security
        )
        conversion = backend.convert(
            document.pdf_path, (document.page_start, document.page_end)
        )
        result = run_layout_pipeline(conversion, pages, config)
        result.diagnostics["application"] = {
            "effective_config_sha256": effective_config_sha256(config),
            "source_pdf_bytes": source.stat().st_size,
            "source_pdf_sha256": document.pdf_sha256,
            "remote_services_allowed": config.security.allow_remote_services,
            "remote_services_verified_disabled": not config.security.allow_remote_services,
            "model_verification": models.get("verification"),
            "backend_capabilities": backend.capabilities,
        }
        fingerprint = environment_fingerprint(
            config_sha256=effective_config_sha256(config),
            model=models.get("verification"),
            capabilities=backend.capabilities,
        )
        result.diagnostics["environment_fingerprint"] = fingerprint
        for stage in result.stage_trace:
            stage["environment_sha256"] = fingerprint["environment_sha256"]
        export_pipeline_result(result)
        validation = validate_exported_artifacts(target, config.security)
        if not validation["valid"]:
            raise ArtifactValidationError(
                f"artifact validation failed: {validation['errors']}"
            )
        mark_manifest_validated(document.artifacts.artifact_manifest_json)
        return PipelineRunSummary(
            result.status,
            document.doc_id,
            target,
            document.artifacts.artifact_manifest_json,
            validation,
        )
    except BaseException:
        if not config.privacy.retain_failed_artifacts and target.exists():
            shutil.rmtree(target)
            secure_directory(target, config.security.secure_directory_mode)
        else:
            (target / "_EXPORTING").unlink(missing_ok=True)
            for path in terminal:
                path.unlink(missing_ok=True)
        (target / "_FAILED").write_text("failed\n", encoding="utf-8")
        secure_file(target / "_FAILED", config.security.secure_file_mode)
        raise


def _resume_summary(document: Any, config: PipelineConfig) -> PipelineRunSummary:
    manifest_path = document.artifacts.artifact_manifest_json
    if not manifest_path.is_file():
        raise ValueError("cannot resume without an artifact manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("source_pdf_sha256") != document.pdf_sha256:
        raise ValueError("resume input hash does not match the existing run")
    if manifest.get("effective_config_sha256") != effective_config_sha256(config):
        raise ValueError("resume configuration does not match the existing run")
    validation = validate_exported_artifacts(
        document.artifacts.document_dir, config.security
    )
    if not validation["valid"]:
        raise ValueError("cannot resume an invalid artifact set")
    return PipelineRunSummary(
        manifest["run_status"],
        document.doc_id,
        document.artifacts.document_dir,
        manifest_path,
        validation,
    )
