import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _workflow_source():
    notebook = json.loads((ROOT / "pdf_layout_pipeline_workflow.ipynb").read_text())
    return "\n".join(
        "".join(cell.get("source", [])) for cell in notebook.get("cells", [])
    )


def test_workflow_loads_the_aee_package_not_an_old_pipeline_directory():
    source = _workflow_source()
    assert "REPO_DIR / 'pdf_layout_pipeline-AEE'" in source
    assert 'repo_dir / "pdf_layout_pipeline-AEE"' in source
    assert 'PROJECT_DIR.name != "pdf_layout_pipeline-AEE"' in source


def test_workflow_displays_resolved_caption_outputs():
    source = _workflow_source()
    assert "resolved_regions_dataframe" in source
    assert "semantic_captions_dataframe" in source
    assert "render_resolved_layout_overlays" in source
    assert "render_caption_overlap_overlay" in source
    assert "layout_relationships_dataframe" in source
    assert "resolution_decisions_dataframe" in source
    assert "suppressed_regions_dataframe" in source
    assert "render_overlap_resolution_overlay" in source
    assert "overlap_resolution_diagnostics" in source
    assert "render_raw_detection_overlays" in source
    assert "render_table_context_overlay" in source
    assert "table_context_diagnostics" in source
    assert "caption_overlap_diagnostics" in source
    assert "create_caption_line_provider" in source
    assert "CONFIG_PROFILES" in source
