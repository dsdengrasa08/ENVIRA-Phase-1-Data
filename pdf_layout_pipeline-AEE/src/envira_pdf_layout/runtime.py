"""Runtime preparation for Colab, local, and server execution."""

from __future__ import annotations
import importlib.util
import os
from pathlib import Path
from .config import RuntimeConfig


def in_colab() -> bool:
    return importlib.util.find_spec("google.colab") is not None


def prepare_runtime(config: RuntimeConfig) -> dict[str, object]:
    if config.use_google_drive and in_colab():
        from google.colab import drive

        drive.mount(str(config.drive_mount_point), force_remount=False)
    cache_root = config.project_dir / "cache"
    paths = {
        "hf_cache": cache_root / "huggingface",
        "pip_cache": cache_root / "pip",
        "torch_cache": cache_root / "torch",
    }
    for path in (config.project_dir, *paths.values()):
        Path(path).mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "HF_HOME": str(paths["hf_cache"]),
            "PIP_CACHE_DIR": str(paths["pip_cache"]),
            "TORCH_HOME": str(paths["torch_cache"]),
        }
    )
    if config.offline:
        os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    return {"in_colab": in_colab(), "project_dir": config.project_dir, **paths}
