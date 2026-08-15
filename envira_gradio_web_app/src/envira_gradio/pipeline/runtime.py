"""Runtime preparation for Colab, local, and server execution."""

from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import sys
from .config import RuntimeConfig


def in_colab() -> bool:
    return importlib.util.find_spec("google.colab") is not None


def prepare_runtime(config: RuntimeConfig) -> dict[str, object]:
    colab = in_colab()
    if config.use_google_drive and colab:
        from google.colab import drive

        drive.mount(str(config.drive_mount_point), force_remount=False)
    cache_root = config.project_dir / "cache"
    persistent_hf_cache = cache_root / "huggingface"
    # Gradio stores its native frpc executable under HF_HOME. Executing that
    # binary from a Google Drive/FUSE mount is unreliable in Colab even when the
    # emulated permission bits say it is executable. Keep HF_HOME runtime-local,
    # while directing downloaded Hugging Face model blobs to persistent Drive.
    hf_home = (
        config.local_cache_root / "huggingface" if colab else persistent_hf_cache
    )
    paths = {
        "hf_home": hf_home,
        "hf_hub_cache": persistent_hf_cache / "hub",
        "pip_cache": cache_root / "pip",
        "torch_cache": cache_root / "torch",
    }
    for path in (config.project_dir, *paths.values()):
        Path(path).mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "HF_HOME": str(paths["hf_home"]),
            "HF_HUB_CACHE": str(paths["hf_hub_cache"]),
            "PIP_CACHE_DIR": str(paths["pip_cache"]),
            "TORCH_HOME": str(paths["torch_cache"]),
        }
    )
    tunneling = sys.modules.get("gradio.tunneling")
    if colab and tunneling is not None:
        loaded_binary = Path(getattr(tunneling, "BINARY_PATH", "")).resolve()
        expected_folder = (paths["hf_home"] / "gradio" / "frpc").resolve()
        if not loaded_binary.is_relative_to(expected_folder):
            raise RuntimeError(
                "Gradio was imported before the Colab-local HF_HOME was configured. "
                "Restart the Colab runtime, then use Run All so the frpc tunnel binary "
                f"loads from {expected_folder} instead of {loaded_binary}."
            )
    if config.offline:
        os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    return {"in_colab": colab, "project_dir": config.project_dir, **paths}
