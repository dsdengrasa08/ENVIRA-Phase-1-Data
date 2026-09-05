"""Version-tolerant Docling model initialization and conversion."""

from __future__ import annotations
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any
from .config import DoclingConfig, SecurityConfig


@dataclass
class DoclingConversion:
    result: Any
    document: Any
    raw_document: dict[str, Any]
    markdown: str


def docling_document_to_dict(document: Any) -> dict[str, Any]:
    for name in ("export_to_dict", "model_dump", "dict"):
        method = getattr(document, name, None)
        if callable(method):
            return method()
    raise TypeError("Installed Docling document exposes no supported dictionary export")


class DoclingBackend:
    def __init__(self, converter: Any, capabilities: dict[str, Any] | None = None):
        self.converter = converter
        self.capabilities = capabilities or {}

    @classmethod
    def from_config(
        cls,
        config: DoclingConfig,
        artifact_path: Path | None = None,
        security: SecurityConfig | None = None,
    ) -> "DoclingBackend":
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        options = PdfPipelineOptions()
        for key, value in {
            "do_ocr": config.do_ocr,
            "do_table_structure": config.do_table_structure,
            "do_formula_enrichment": config.do_formula_enrichment,
            "do_code_enrichment": config.do_code_enrichment,
        }.items():
            if hasattr(options, key):
                setattr(options, key, value)
        security = security or SecurityConfig()
        if hasattr(options, "enable_remote_services"):
            options.enable_remote_services = False
        elif not security.allow_remote_services:
            raise RuntimeError(
                "installed Docling cannot verify that remote services are disabled"
            )
        capabilities = {
            "remote_services": "allowed" if security.allow_remote_services else "verified_disabled",
            "ocr": {"requested": config.do_ocr, "configured": bool(getattr(options, "do_ocr", False))},
            "table_structure": {"requested": config.do_table_structure, "configured": bool(getattr(options, "do_table_structure", False))},
            "formula_enrichment": {"requested": config.do_formula_enrichment, "configured": False},
            "code_enrichment": {"requested": config.do_code_enrichment, "configured": False},
            "code_formula_preset": config.code_formula_preset,
            "local_artifacts": bool(artifact_path and config.use_local_artifacts),
        }
        if config.do_formula_enrichment or config.do_code_enrichment:
            try:
                CodeFormulaVlmOptions = getattr(
                    import_module("docling.datamodel.pipeline_options"),
                    "CodeFormulaVlmOptions",
                )
                options.code_formula_options = CodeFormulaVlmOptions.from_preset(
                    config.code_formula_preset
                )
                capabilities["formula_enrichment"]["configured"] = config.do_formula_enrichment
                capabilities["code_enrichment"]["configured"] = config.do_code_enrichment
            except (ImportError, AttributeError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    "requested Docling code/formula enrichment is unavailable"
                ) from exc
        if (
            artifact_path
            and config.use_local_artifacts
            and hasattr(options, "artifacts_path")
        ):
            options.artifacts_path = artifact_path
        converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )
        return cls(converter, capabilities)

    def convert(
        self,
        pdf_path: Path,
        page_range: tuple[int, int],
        *,
        materialize_markdown: bool = True,
    ) -> DoclingConversion:
        result = self.converter.convert(str(pdf_path), page_range=page_range)
        document = result.document
        markdown_method = getattr(document, "export_to_markdown", None)
        return DoclingConversion(
            result,
            document,
            docling_document_to_dict(document),
            markdown_method()
            if materialize_markdown and callable(markdown_method)
            else "",
        )
