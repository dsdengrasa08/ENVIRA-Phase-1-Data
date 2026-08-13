"""Security, privacy, bounded-I/O, and path-confinement primitives."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any, Iterable

SECRET_NAME = re.compile(
    r"(?:token|password|passwd|secret|credential|authorization|cookie|private[_-]?key|api[_-]?key)",
    re.IGNORECASE,
)
URI_CREDENTIAL = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s:]+:[^/@\s]+@", re.I)
REDACTED = "<redacted>"


class ArtifactSecurityError(ValueError):
    pass


def redact_secrets(value: Any, *, key: str = "") -> Any:
    """Recursively redact secret-looking names and URI userinfo."""
    if SECRET_NAME.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(name): redact_secrets(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item, key=key) for item in value]
    if isinstance(value, str):
        return URI_CREDENTIAL.sub(r"\g<scheme><redacted>@", value)
    return value


def redact_region_text(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    sensitive = {"text", "orig", "raw_text", "markdown", "content"}
    return [
        {
            key: (REDACTED if key.casefold() in sensitive and item else item)
            for key, item in row.items()
        }
        for row in rows
    ]


def sanitize_payload(
    value: Any, *, include_text: bool, include_paths: bool
) -> Any:
    """Remove source content/path fields from nested export payloads."""
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            folded = str(key).casefold()
            if not include_paths and (folded.endswith("_path") or folded in {"source_pdf", "profile_path"}):
                continue
            if not include_text and folded in {"text", "orig", "raw_text", "markdown", "content"}:
                output[key] = REDACTED if item else item
            else:
                output[key] = sanitize_payload(item, include_text=include_text, include_paths=include_paths)
        return output
    if isinstance(value, (list, tuple)):
        return [sanitize_payload(item, include_text=include_text, include_paths=include_paths) for item in value]
    return value


def resolve_artifact_path(
    root: Path, value: str, *, allow_symlinks: bool = False
) -> Path:
    """Resolve a manifest path while proving it remains a regular file under root."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ArtifactSecurityError("invalid_manifest_path")
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise ArtifactSecurityError("absolute_manifest_path")
    if any(part in {"", ".", ".."} for part in posix.parts):
        raise ArtifactSecurityError("traversal_manifest_path")
    root = root.resolve(strict=True)
    unresolved = root.joinpath(*posix.parts)
    if not allow_symlinks and any(part.is_symlink() for part in [unresolved, *unresolved.parents] if part != root):
        raise ArtifactSecurityError("symlink_artifact")
    candidate = unresolved.resolve(strict=True)
    if not candidate.is_relative_to(root):
        raise ArtifactSecurityError("artifact_escapes_root")
    if not candidate.is_file():
        raise ArtifactSecurityError("artifact_not_regular_file")
    return candidate


def sha256_file(path: Path, *, max_bytes: int | None = None) -> str:
    size = path.stat().st_size
    if max_bytes is not None and size > max_bytes:
        raise ArtifactSecurityError("artifact_too_large")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def secure_directory(path: Path, mode: int = 0o700) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def secure_file(path: Path, mode: int = 0o600) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass
