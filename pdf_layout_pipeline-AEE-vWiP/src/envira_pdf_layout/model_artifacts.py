"""Validation and explicit acquisition of persistent Docling model artifacts."""

from __future__ import annotations
from contextlib import contextmanager
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from .config import DoclingConfig
from .supply_chain import validate_model_manifest


@contextmanager
def _acquisition_lock(path: Path):
    """Prevent concurrent processes from replacing the same artifact directory."""
    lock = path.with_name(path.name + ".download.lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(f"Model acquisition already in progress: {lock}") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        os.close(descriptor)
        yield
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        lock.unlink(missing_ok=True)


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
    manifest_path = Path(config.model_manifest_path or path / "model-manifest.json")
    size = folder_size_mb(path)
    verification = None
    if manifest_path.is_file():
        verification = validate_model_manifest(path, manifest_path)
    ready = bool(verification) and size >= config.min_model_size_mb
    if not config.require_model_manifest and not ready:
        ready = bool(list_candidate_model_files(path)) and size >= config.min_model_size_mb
    if config.force_redownload_models:
        ready = False
    if not ready and config.auto_download_models:
        with _acquisition_lock(path), tempfile.TemporaryDirectory(prefix="envira-model-download-", dir=path.parent) as temporary:
            staging = Path(temporary)
            completed = subprocess.run(
                ["docling-tools", "models", "download", "--output-dir", str(staging)],
                capture_output=True,
                text=True,
                timeout=config.model_download_timeout_seconds,
                check=False,
            )
            if completed.returncode:
                raise RuntimeError(
                    f"Docling model download failed: {completed.stderr.strip()}"
                )
            staged_manifest = staging / manifest_path.name
            verification = validate_model_manifest(staging, staged_manifest)
            replacement = path.with_name(path.name + ".verified-new")
            shutil.rmtree(replacement, ignore_errors=True)
            shutil.copytree(staging, replacement)
            previous = path.with_name(path.name + ".previous")
            shutil.rmtree(previous, ignore_errors=True)
            if path.exists():
                path.replace(previous)
            replacement.replace(path)
            shutil.rmtree(previous, ignore_errors=True)
            size, ready = folder_size_mb(path), True
    if config.use_local_artifacts and config.require_saved_models and not ready:
        raise FileNotFoundError(
            f"Saved Docling models are missing or incomplete at {path} ({size:.1f} MB)"
        )
    return {
        "artifact_path": path,
        "size_mb": size,
        "ready": ready,
        "preview": list_candidate_model_files(path, 10),
        "verification": verification,
    }
