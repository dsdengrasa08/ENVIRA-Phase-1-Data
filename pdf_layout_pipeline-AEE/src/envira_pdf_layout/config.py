"""Configuration loading and validation without filesystem side effects."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class RuntimeConfig:
    use_google_drive: bool = True
    drive_mount_point: Path = Path("/content/drive")
    project_dir: Path = Path(
        "/content/drive/MyDrive/00-ENVIRA/01-LayoutParser/phase1_docling"
    )
    offline: bool = False
    skip_pip_install: bool = False


@dataclass(frozen=True)
class DocumentConfig:
    source_pdf: Path = Path("/content/1-s2.0-S0167880921000803-main.pdf")
    page_start: int = 1
    page_end: int | None = None
    render_dpi: int = 180
    run_id: str = ""
    prefer_persistent_copy: bool = True


@dataclass(frozen=True)
class DoclingConfig:
    artifacts_dir: Path | None = None
    use_local_artifacts: bool = True
    require_saved_models: bool = True
    auto_download_models: bool = False
    force_redownload_models: bool = False
    min_model_size_mb: float = 100.0
    do_ocr: bool = False
    do_table_structure: bool = True
    do_formula_enrichment: bool = True
    do_code_enrichment: bool = False
    code_formula_preset: str = "codeformulav2"


@dataclass(frozen=True)
class Page1FilterConfig:
    enabled: bool = True
    abstract_aliases: tuple[str, ...] = ("Abstract", "Summary")
    recover_abstract_heading: bool = True
    title_y_min: float = 0.15
    title_y_max: float = 0.42
    body_anchor_y_max: float = 0.70
    lower_metadata_min_y: float = 0.68
    hard_footer_y: float = 0.92


@dataclass(frozen=True)
class HeaderFilterConfig:
    enabled: bool = True
    top_band_ratio: float = 0.14
    min_repeat_pages: int = 2


@dataclass(frozen=True)
class FigureFilterConfig:
    complete_caption_anchored: bool = True
    require_multipanel_hint: bool = True
    filter_small_edge_figures: bool = True
    header_y1_max: float = 0.12
    footer_y0_min: float = 0.90


@dataclass(frozen=True)
class FooterFilterConfig:
    enabled: bool = True
    compact_enabled: bool = True
    min_repeat_pages: int = 2
    y0_min: float = 0.88


@dataclass(frozen=True)
class TailFilterConfig:
    enabled: bool = True
    direct_backmatter_fallback: bool = True


@dataclass(frozen=True)
class ReadingOrderConfig:
    column_gap_ratio: float = 0.04
    min_column_width_ratio: float = 0.20


@dataclass(frozen=True)
class ExportConfig:
    write_raw: bool = True
    write_regions: bool = True
    write_overlays: bool = True


@dataclass(frozen=True)
class PipelineConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    document: DocumentConfig = field(default_factory=DocumentConfig)
    docling: DoclingConfig = field(default_factory=DoclingConfig)
    page1: Page1FilterConfig = field(default_factory=Page1FilterConfig)
    headers: HeaderFilterConfig = field(default_factory=HeaderFilterConfig)
    figures: FigureFilterConfig = field(default_factory=FigureFilterConfig)
    footer: FooterFilterConfig = field(default_factory=FooterFilterConfig)
    tail: TailFilterConfig = field(default_factory=TailFilterConfig)
    reading_order: ReadingOrderConfig = field(default_factory=ReadingOrderConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    exclude_labels: frozenset[str] = frozenset()

    @classmethod
    def from_env(
        cls, source_pdf: str | Path | None = None, **overrides: object
    ) -> "PipelineConfig":
        project = Path(os.environ.get("PHASE1_PROJECT_DIR", RuntimeConfig.project_dir))
        document = DocumentConfig(
            source_pdf=Path(
                source_pdf
                or os.environ.get("PHASE1_SOURCE_PDF", DocumentConfig.source_pdf)
            ),
            page_start=int(
                overrides.get("page_start", os.environ.get("PHASE1_PAGE_START", 1))
            ),
            page_end=(
                overrides.get("page_end")
                if "page_end" in overrides
                else (
                    int(os.environ["PHASE1_PAGE_END"])
                    if os.environ.get("PHASE1_PAGE_END", "").strip()
                    else None
                )
            ),
            render_dpi=int(
                overrides.get("render_dpi", os.environ.get("PHASE1_RENDER_DPI", 180))
            ),
            run_id=str(overrides.get("run_id", os.environ.get("PHASE1_RUN_ID", ""))),
            prefer_persistent_copy=_flag("PHASE1_PREFER_LOCAL_INPUT_COPY", True),
        )
        runtime = RuntimeConfig(
            use_google_drive=_flag("PHASE1_USE_GOOGLE_DRIVE", True),
            drive_mount_point=Path(
                os.environ.get("PHASE1_GDRIVE_MOUNT_POINT", "/content/drive")
            ),
            project_dir=project,
            offline=_flag("PHASE1_OFFLINE_MODE", False),
            skip_pip_install=_flag("PHASE1_SKIP_PIP_INSTALL", False),
        )
        docling = DoclingConfig(
            artifacts_dir=Path(
                os.environ.get(
                    "PHASE1_DOCLING_ARTIFACTS_DIR", project / "artifacts/docling_models"
                )
            ),
            use_local_artifacts=_flag("PHASE1_USE_LOCAL_DOCLING_ARTIFACTS", True),
            require_saved_models=_flag("PHASE1_REQUIRE_SAVED_DOCLING_MODELS", True),
            auto_download_models=_flag("PHASE1_AUTO_DOWNLOAD_DOCLING_MODELS", False),
            force_redownload_models=_flag(
                "PHASE1_FORCE_REDOWNLOAD_DOCLING_MODELS", False
            ),
            do_ocr=_flag("PHASE1_DOCLING_DO_OCR", False),
        )
        aliases = tuple(
            x.strip()
            for x in os.environ.get(
                "PHASE1_PAGE1_ABSTRACT_EQUIVALENT_ALIASES", "Abstract,Summary"
            ).split(",")
            if x.strip()
        )
        excluded = frozenset(
            x.strip().lower()
            for x in os.environ.get("PHASE1_DOCLING_EXCLUDE_LABELS", "").split(",")
            if x.strip()
        )
        config = cls(
            runtime=runtime,
            document=document,
            docling=docling,
            page1=Page1FilterConfig(
                abstract_aliases=aliases or ("Abstract", "Summary")
            ),
            exclude_labels=excluded,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.document.page_start < 1:
            raise ValueError("page_start must be at least 1")
        if (
            self.document.page_end is not None
            and self.document.page_end < self.document.page_start
        ):
            raise ValueError("page_end must not precede page_start")
        if self.document.render_dpi <= 0:
            raise ValueError("render_dpi must be positive")
