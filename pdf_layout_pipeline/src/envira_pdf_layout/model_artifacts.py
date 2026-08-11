"""Validation and explicit acquisition of persistent Docling model artifacts."""

from __future__ import annotations
import shutil
import subprocess
from pathlib import Path
from .config import DoclingConfig


def folder_size_mb(path: Path) -> float:
    return (
        sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) / 1024**2
        if path.exists()
        else 0.0
    )


def list_candidate_model_files(path: Path, limit: int = 20) -> list[Path]:
    suffixes = {".bin", ".pt", ".pth", ".safetensors", ".onnx", ".json"}
    return (
        [
            item
            for item in path.rglob("*")
            if item.is_file() and item.suffix.lower() in suffixes
        ][:limit]
        if path.exists()
        else []
    )


def ensure_model_artifacts(config: DoclingConfig) -> dict[str, object]:
    path = (
        Path(config.artifacts_dir or "artifacts/docling_models").expanduser().resolve()
    )
    path.mkdir(parents=True, exist_ok=True)
    size = folder_size_mb(path)
    ready = bool(list_candidate_model_files(path)) and size >= config.min_model_size_mb
    if config.force_redownload_models and path.exists():
        shutil.rmtree(path)
        path.mkdir(parents=True)
        ready = False
    if not ready and config.auto_download_models:
        completed = subprocess.run(
            ["docling-tools", "models", "download", "--output-dir", str(path)],
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            raise RuntimeError(
                f"Docling model download failed: {completed.stderr.strip()}"
            )
        size, ready = folder_size_mb(path), bool(list_candidate_model_files(path))
    if config.use_local_artifacts and config.require_saved_models and not ready:
        raise FileNotFoundError(
            f"Saved Docling models are missing or incomplete at {path} ({size:.1f} MB)"
        )
    return {
        "artifact_path": path,
        "size_mb": size,
        "ready": ready,
        "preview": list_candidate_model_files(path, 10),
    }
