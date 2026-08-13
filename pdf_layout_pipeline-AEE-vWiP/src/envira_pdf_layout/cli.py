"""Console interface that stays importable without initializing Docling or OCR."""

from __future__ import annotations

import argparse
import json
from importlib.resources import files
from pathlib import Path
import sys

from . import __version__
from .artifact_validation import validate_exported_artifacts
from .config import PipelineConfig
from .regression import load_trace
from .stage_trace import compare_stage_traces
from .application import ArtifactValidationError, DependencyUnavailableError, InputPDFError

EXIT_CONFIG = 2
EXIT_INPUT = 3
EXIT_DEPENDENCY = 4
EXIT_PARTIAL = 5
EXIT_PIPELINE = 6
EXIT_ARTIFACT = 7


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="envira-pdf-layout")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--debug", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="process one PDF")
    run.add_argument("source_pdf", type=Path)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--config", type=Path)
    run.add_argument("--page-start", type=int)
    run.add_argument("--page-end", type=int)
    run.add_argument("--error-policy", choices=("strict", "report"))
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--overwrite", action="store_true")
    mode.add_argument("--resume", action="store_true")
    validate = commands.add_parser("validate", help="validate an artifact directory")
    validate.add_argument("document_dir", type=Path)
    effective = commands.add_parser("config", help="print effective configuration")
    effective.add_argument("--config", type=Path)
    effective.add_argument("--effective", action="store_true")
    compare = commands.add_parser("compare", help="compare two stage traces")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    commands.add_parser("resources", help="show installed resource paths")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            result = validate_exported_artifacts(args.document_dir)
            _emit(result)
            return 0 if result["valid"] else EXIT_ARTIFACT
        if args.command == "config":
            _emit(PipelineConfig.load(args.config).to_dict())
            return 0
        if args.command == "compare":
            result = compare_stage_traces(load_trace(args.baseline), load_trace(args.candidate))
            _emit(result)
            return 0 if result["compatible"] else 1
        if args.command == "resources":
            root = files("envira_pdf_layout").joinpath("resources")
            _emit({"default_config": str(root.joinpath("default.yaml")), "schemas": str(root)})
            return 0
        overrides = {}
        if args.page_start is not None:
            overrides["page_start"] = args.page_start
        if args.page_end is not None:
            overrides["page_end"] = args.page_end
        if args.error_policy:
            overrides["error_policy"] = {"mode": args.error_policy}
        config = PipelineConfig.load(args.config, source_pdf=args.source_pdf, **overrides)
        summary = run_pdf(args.source_pdf, args.output_dir, config=config, overwrite=args.overwrite, resume=args.resume)
        _emit(summary.to_dict())
        return EXIT_PARTIAL if summary.status == "partial" else 0
    except InputPDFError as exc:
        return _error(exc, EXIT_INPUT, args.debug)
    except ArtifactValidationError as exc:
        return _error(exc, EXIT_ARTIFACT, args.debug)
    except DependencyUnavailableError as exc:
        return _error(exc, EXIT_DEPENDENCY, args.debug)
    except (ValueError, FileExistsError) as exc:
        return _error(exc, EXIT_CONFIG, args.debug)
    except FileNotFoundError as exc:
        return _error(exc, EXIT_INPUT, args.debug)
    except (ImportError, ModuleNotFoundError) as exc:
        return _error(exc, EXIT_DEPENDENCY, args.debug)
    except Exception as exc:
        return _error(exc, EXIT_PIPELINE, args.debug)


def _emit(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _error(exc: Exception, code: int, debug: bool) -> int:
    if debug:
        raise
    print(json.dumps({"status": "error", "exit_code": code, "error": str(exc)}), file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
