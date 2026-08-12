import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "pdf_layout_pipeline_workflow.ipynb"


def _workflow_source():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return "\n".join(
        "".join(cell.get("source", [])) for cell in notebook.get("cells", [])
    )


def test_workflow_is_strict_json_and_has_valid_cell_shapes():
    """Guard the browser/Colab parser, not only Python source wiring."""
    raw = NOTEBOOK.read_bytes()
    assert raw.endswith(b"\n")
    assert b"<<<<<<<" not in raw and b">>>>>>>" not in raw
    notebook = json.loads(raw.decode("utf-8"))
    assert notebook["nbformat"] == 4
    assert isinstance(notebook["cells"], list)
    for cell in notebook["cells"]:
        assert cell["cell_type"] in {"code", "markdown", "raw"}
        assert isinstance(cell["source"], list)
        assert isinstance(cell["metadata"], dict)
        if cell["cell_type"] == "code":
            assert cell["execution_count"] is None
            assert isinstance(cell["outputs"], list)


def test_workflow_loads_the_vbackup_package_with_caption_decomposition():
    source = _workflow_source()
    assert "pdf_layout_pipeline-AEE-vBackup/requirements.txt" in source
    assert 'repo_dir / "pdf_layout_pipeline-AEE-vBackup"' in source
    assert 'PROJECT_DIR.name != "pdf_layout_pipeline-AEE-vBackup"' in source


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
