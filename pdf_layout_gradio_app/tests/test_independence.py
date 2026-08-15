from pathlib import Path


def test_runtime_sources_do_not_reference_reference_folder():
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in (root / "src").rglob("*.py"):
        if "pdf_layout_pipeline-AEE-vWiP" in path.read_text(encoding="utf-8"):
            offenders.append(path)
    assert not offenders
