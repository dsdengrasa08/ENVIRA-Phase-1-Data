from pathlib import Path
from types import SimpleNamespace

from envira_pdf_layout.config import PipelineConfig
from envira_pdf_layout.modular_pipeline import run_modular_pipeline
from envira_pdf_layout.types import ArtifactPaths, DocumentIdentity, PageRecord, PageSet


def test_modular_pipeline_does_not_require_reference_notebook(tmp_path):
    artifacts = ArtifactPaths(
        project_dir=tmp_path,
        document_dir=tmp_path,
        input_pdf=tmp_path / "input.pdf",
        page_pdf_dir=tmp_path,
        page_image_dir=tmp_path,
        overlay_dir=tmp_path / "overlays",
        raw_json=tmp_path / "raw.json",
        raw_markdown=tmp_path / "raw.md",
        page_records_jsonl=tmp_path / "pages.jsonl",
        regions_jsonl=tmp_path / "regions.jsonl",
        post_body_assets_jsonl=tmp_path / "assets.jsonl",
        post_body_asset_regions_jsonl=tmp_path / "asset-regions.jsonl",
        logical_tables_jsonl=tmp_path / "tables.jsonl",
        raw_regions_jsonl=tmp_path / "raw-regions.jsonl",
        resolved_regions_jsonl=tmp_path / "resolved.jsonl",
        caption_relationships_jsonl=tmp_path / "caption-rel.jsonl",
        caption_groups_jsonl=tmp_path / "captions.jsonl",
        layout_relationships_jsonl=tmp_path / "relationships.jsonl",
        resolution_decisions_jsonl=tmp_path / "decisions.jsonl",
        suppressed_regions_jsonl=tmp_path / "suppressed.jsonl",
        summary_csv=tmp_path / "summary.csv",
    )
    document = DocumentIdentity(
        tmp_path / "source.pdf",
        tmp_path / "input.pdf",
        "source.pdf",
        "abc",
        "doc",
        1,
        1,
        1,
        artifacts,
    )
    page = PageRecord(
        1, tmp_path / "page.pdf", tmp_path / "page.png", 1000, 1200, 500, 600
    )
    conversion = SimpleNamespace(
        raw_document={
            "label": "text",
            "text": "Body text",
            "prov": [{"page_no": 1, "bbox": {"l": 50, "t": 100, "r": 450, "b": 130}}],
        },
        markdown="Body text",
    )
    result = run_modular_pipeline(
        conversion, PageSet(document, [page]), PipelineConfig()
    )
    assert result.diagnostics["implementation"] == "envira_pdf_layout.modular_pipeline"
    assert result.final_regions[0]["layout_reading_order"] == 1
    assert result.pages[0]["counts"]["final_region_count"] == 1
