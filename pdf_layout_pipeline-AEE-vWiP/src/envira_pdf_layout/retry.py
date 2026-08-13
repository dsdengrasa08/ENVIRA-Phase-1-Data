"""Safe planning for selective retries of page-isolated failures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_retry_plan(
    run_dir: Path,
    *,
    expected_pdf_hash: str,
    expected_effective_config: dict[str, Any],
) -> dict[str, Any]:
    """Validate prior identity/config and return only explicitly failed pages."""
    diagnostics = json.loads(
        (run_dir / "pipeline_diagnostics.json").read_text(encoding="utf-8")
    )
    config = json.loads((run_dir / "effective_config.json").read_text(encoding="utf-8"))
    pages = [
        json.loads(line)
        for line in (run_dir / "page_diagnostics.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    manifest_path = run_dir / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    recorded_hash = diagnostics.get("document", {}).get("pdf_hash")
    if recorded_hash is not None and recorded_hash != expected_pdf_hash:
        raise ValueError("input PDF hash differs from the failed run")
    if config != expected_effective_config:
        raise ValueError("effective configuration differs from the failed run")
    failed_pages = sorted(
        int(page["page_number"]) for page in pages if page.get("status") == "failed"
    )
    return {
        "schema_version": 1,
        "pdf_hash": expected_pdf_hash,
        "failed_pages": failed_pages,
        "retryable": bool(failed_pages),
        "parent_run_id": manifest.get("run_id"),
        "attempt": int(manifest.get("attempt", 1)) + 1,
    }
