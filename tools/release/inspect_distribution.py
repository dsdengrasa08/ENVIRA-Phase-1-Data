"""Reject unexpected or sensitive distribution contents."""

import sys
from pathlib import Path
from tarfile import open as open_tar
from zipfile import ZipFile

REQUIRED = {
    "envira_pdf_layout/cli.py",
    "envira_pdf_layout/resources/default.yaml",
    "envira_pdf_layout/resources/layout-region-v1.schema.json",
    "envira_pdf_layout/resources/artifact-manifest-v1.schema.json",
    "envira_pdf_layout/resources/model-manifest-v1.schema.json",
    "envira_pdf_layout/resources/pipeline-event-v1.schema.json",
    "envira_pdf_layout/resources/run-failure-v1.schema.json",
}
FORBIDDEN_SUFFIXES = {".ipynb", ".pdf", ".env", ".pyc"}


def names(path: Path) -> set[str]:
    if path.suffix == ".whl":
        with ZipFile(path) as archive:
            return set(archive.namelist())
    with open_tar(path, "r:gz") as archive:
        return {member.name.split("/", 1)[-1] for member in archive.getmembers()}


for value in sys.argv[1:]:
    path = Path(value)
    contents = names(path)
    if path.suffix == ".whl" and not REQUIRED <= contents:
        raise SystemExit(f"{path}: missing {sorted(REQUIRED - contents)}")
    forbidden = [
        name
        for name in contents
        if Path(name).suffix in FORBIDDEN_SUFFIXES
        or (path.suffix == ".whl" and "/tests/" in name)
    ]
    if forbidden:
        raise SystemExit(f"{path}: forbidden contents {forbidden[:10]}")
print("distribution contents verified")
