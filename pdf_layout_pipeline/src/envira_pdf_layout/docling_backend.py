"""Version-tolerant Docling model initialization and conversion."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .config import DoclingConfig


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
    def __init__(self, converter: Any):
        self.converter = converter

    @classmethod
    def from_config(
        cls, config: DoclingConfig, artifact_path: Path | None = None
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
        if (
            artifact_path
            and config.use_local_artifacts
            and hasattr(options, "artifacts_path")
        ):
            options.artifacts_path = artifact_path
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )
        return cls(converter)

    def convert(self, pdf_path: Path, page_range: tuple[int, int]) -> DoclingConversion:
        result = self.converter.convert(str(pdf_path), page_range=page_range)
        document = result.document
        markdown_method = getattr(document, "export_to_markdown", None)
        return DoclingConversion(
            result,
            document,
            docling_document_to_dict(document),
            markdown_method() if callable(markdown_method) else "",
        )
