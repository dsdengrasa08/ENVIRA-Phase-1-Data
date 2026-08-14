"""Require release tag and built-wheel metadata versions to agree."""

import re
import sys
from pathlib import Path
from zipfile import ZipFile

tag, wheel = sys.argv[1], Path(sys.argv[2])
match = re.fullmatch(r"envira-pdf-layout-v(\d+\.\d+\.\d+)", tag)
if not match:
    raise SystemExit(f"invalid release tag: {tag}")
version = match.group(1)
with ZipFile(wheel) as archive:
    metadata = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
    fields = archive.read(metadata).decode()
if f"Version: {version}\n" not in fields:
    raise SystemExit(f"tag {version} does not match wheel metadata")
print(version)
