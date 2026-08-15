"""Side-effect-minimized operational preflight checks."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path
import shutil
from typing import Any

from .config import PipelineConfig
from .supply_chain import validate_model_manifest


def run_doctor(config: PipelineConfig) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def record(name: str, operation) -> None:
        try:
            detail = operation()
            checks.append({"name": name, "status": "pass", "detail": detail})
        except Exception as exc:
            checks.append({"name": name, "status": "fail", "exception_type": type(exc).__name__, "detail": str(exc)})

    record("configuration", lambda: (config.validate(), "valid")[1])
    root = config.runtime.project_dir.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    record("output_writable", lambda: _writable(root))
    record("free_disk", lambda: _disk(root, config.operational.minimum_free_disk_bytes))
    model_root = Path(config.docling.artifacts_dir or root / "artifacts" / "docling_models").expanduser().resolve()
    manifest = Path(config.docling.model_manifest_path or model_root / "model-manifest.json")
    record("model_manifest", lambda: validate_model_manifest(model_root, manifest))
    record("docling", lambda: {"version": version("docling"), "import": bool(import_module("docling"))})
    record("ocr", lambda: {"requested": config.docling.do_ocr, "pytesseract": _optional_version("pytesseract")})
    record("resources", lambda: _resources())
    return {
        "doctor_schema_version": 1,
        "healthy": all(row["status"] == "pass" for row in checks),
        "requested_capabilities": {
            "ocr": config.docling.do_ocr,
            "table_structure": config.docling.do_table_structure,
            "formula_enrichment": config.docling.do_formula_enrichment,
            "code_enrichment": config.docling.do_code_enrichment,
            "remote_services_allowed": config.security.allow_remote_services,
            "local_artifacts": config.docling.use_local_artifacts,
        },
        "checks": checks,
    }


def _writable(root: Path) -> str:
    probe = root / ".envira-doctor-write-test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    return "writable"


def _disk(root: Path, minimum: int) -> dict[str, int]:
    free = shutil.disk_usage(root).free
    if free < minimum:
        raise OSError(f"free disk {free} is below required {minimum}")
    return {"free_bytes": free, "minimum_bytes": minimum}


def _optional_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _resources() -> list[str]:
    root = files("envira_gradio.pipeline").joinpath("resources")
    required = ["default.yaml", "layout-region-v1.schema.json", "artifact-manifest-v1.schema.json"]
    missing = [name for name in required if not root.joinpath(name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing packaged resources: {missing}")
    return required
