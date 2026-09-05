"""Typed application settings supplied by the launcher or another host."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class AppSettings:
    """Host-owned paths and launch-independent application controls."""

    persistent_root: Path
    config_path: Path
    temporary_root: Path = Path(tempfile.gettempdir()) / "envira_gradio"
    model_root: Path | None = None
    max_concurrency: int = 1

    def normalized(self) -> "AppSettings":
        persistent = self.persistent_root.expanduser().resolve()
        temporary = self.temporary_root.expanduser().resolve()
        config = self.config_path.expanduser().resolve()
        model = (self.model_root or persistent / "models" / "docling").expanduser().resolve()
        if not config.is_file():
            raise FileNotFoundError(f"Configuration file not found: {config}")
        if persistent == temporary or persistent.is_relative_to(temporary):
            raise ValueError("Persistent output root must not be inside the temporary root")
        return AppSettings(persistent, config, temporary, model, max(1, self.max_concurrency))
