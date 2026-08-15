"""Typed application settings kept separate from notebook and UI state."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from envira_pdf_layout.config import PipelineConfig


@dataclass(frozen=True)
class AppSettings:
    app_root: Path
    persistent_output_root: Path
    temporary_root: Path
    config_profile: Path
    concurrency_limit: int = 1
    max_upload_bytes: int = 250_000_000

    @classmethod
    def load(
        cls,
        app_root: str | Path | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "AppSettings":
        env = dict(os.environ if environ is None else environ)
        root = Path(app_root or Path(__file__).resolve().parents[2]).expanduser().resolve()
        persistent = Path(
            env.get(
                "ENVIRA_WEB_OUTPUT_ROOT",
                "/content/drive/MyDrive/ENVIRA/pdf-layout-gradio",
            )
        ).expanduser().resolve()
        temporary = Path(env.get("ENVIRA_WEB_TEMP_ROOT", "/content/envira-layout-web")).expanduser().resolve()
        profile = Path(env.get("ENVIRA_WEB_CONFIG", root / "config" / "default.yaml")).expanduser().resolve()
        return cls(
            app_root=root,
            persistent_output_root=persistent,
            temporary_root=temporary,
            config_profile=profile,
            concurrency_limit=max(1, int(env.get("ENVIRA_WEB_CONCURRENCY", "1"))),
            max_upload_bytes=int(env.get("ENVIRA_WEB_MAX_UPLOAD_BYTES", "250000000")),
        )

    def prepare(self, *, validate_persistence: bool = True) -> None:
        if not self.config_profile.is_file():
            raise FileNotFoundError(f"Configuration profile not found: {self.config_profile}")
        self.temporary_root.mkdir(parents=True, exist_ok=True)
        self.persistent_output_root.mkdir(parents=True, exist_ok=True)
        if validate_persistence:
            probe = self.persistent_output_root / ".envira-write-probe"
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink()

    def pipeline_config(self, source_pdf: str | Path, run_id: str) -> PipelineConfig:
        return PipelineConfig.load(
            self.config_profile,
            source_pdf=source_pdf,
            run_id=run_id,
            runtime={
                "project_dir": self.persistent_output_root,
                "use_google_drive": False,
            },
        )
