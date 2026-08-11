import hashlib
from pathlib import Path

REFERENCE_SHA256 = "9cd43e2a8ca4d0129569cc63809443ee92cce9838252e3d45950162b93a6a9e1"


def test_reference_notebook_is_unchanged():
    path = (
        Path(__file__).parents[2]
        / "source_pdf_layoutparser"
        / "pdf_layoutparser_vF.ipynb"
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == REFERENCE_SHA256
