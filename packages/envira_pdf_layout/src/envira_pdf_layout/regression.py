"""Explicit utilities for reading, comparing, and updating regression goldens."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .stage_trace import TRACE_SCHEMA_VERSION, compare_stage_traces, validate_trace

GOLDEN_SCHEMA_VERSION = 1


def load_trace(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def update_golden(
    output: Path,
    trace: list[dict[str, Any]],
    *,
    fixture_id: str,
    reason: str,
    force: bool = False,
) -> dict[str, Any]:
    """Write one selected golden only after validation and an explicit reason."""
    if not fixture_id.strip() or not reason.strip():
        raise ValueError("fixture_id and reason are required")
    validation = validate_trace(trace)
    if not validation["valid"] and not force:
        raise ValueError("refusing to update a golden from an invalid trace")
    previous = (
        json.loads(output.read_text(encoding="utf-8")) if output.exists() else None
    )
    environment_digests = {
        row["environment_sha256"]
        for row in trace
        if row.get("environment_sha256")
    }
    if len(environment_digests) > 1:
        raise ValueError("trace contains multiple execution environments")
    golden = {
        "golden_schema_version": GOLDEN_SCHEMA_VERSION,
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "fixture_id": fixture_id,
        "reason": reason,
        "stage_digests": {row["stage"]: row["region_digest"] for row in trace},
        "environment_sha256": next(iter(environment_digests), None),
        "validation": validation,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(golden, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"previous": previous, "current": golden}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage explicit layout regression goldens"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    compare = subparsers.add_parser("compare")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    update = subparsers.add_parser("update")
    update.add_argument("--trace", required=True, type=Path)
    update.add_argument("--output", required=True, type=Path)
    update.add_argument("--fixture", required=True)
    update.add_argument("--reason", required=True)
    update.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "compare":
        result = compare_stage_traces(
            load_trace(args.baseline), load_trace(args.candidate)
        )
    else:
        result = update_golden(
            args.output,
            load_trace(args.trace),
            fixture_id=args.fixture,
            reason=args.reason,
            force=args.force,
        )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
