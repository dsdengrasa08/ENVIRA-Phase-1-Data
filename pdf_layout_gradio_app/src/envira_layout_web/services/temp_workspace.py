"""Private request-scoped temporary workspaces."""

from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile
from typing import Iterator


@contextmanager
def temporary_workspace(root: Path) -> Iterator[Path]:
    root.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="run-", dir=root))
    workspace.chmod(0o700)
    try:
        yield workspace
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
