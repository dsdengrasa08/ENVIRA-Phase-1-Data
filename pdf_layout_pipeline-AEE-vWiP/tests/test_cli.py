import json

from envira_pdf_layout import __version__
from envira_pdf_layout.cli import EXIT_ARTIFACT, EXIT_CANCELLED, EXIT_CONFIG, main
from envira_pdf_layout.observability import RunCancelled


def test_cli_version_and_help_do_not_initialize_models(capsys):
    assert main(["resources"]) == 0
    resources = json.loads(capsys.readouterr().out)
    assert resources["default_config"].endswith("default.yaml")


def test_cli_effective_config_is_machine_readable(capsys):
    assert main(["config", "--effective"]) == 0
    assert "runtime" in json.loads(capsys.readouterr().out)


def test_cli_invalid_config_and_artifacts_use_stable_exit_codes(tmp_path, capsys):
    invalid = tmp_path / "bad.yaml"
    invalid.write_text("unknown: true\n", encoding="utf-8")
    assert main(["config", "--config", str(invalid)]) == EXIT_CONFIG
    assert json.loads(capsys.readouterr().err)["exit_code"] == EXIT_CONFIG
    assert main(["validate", str(tmp_path)]) == EXIT_ARTIFACT
    assert json.loads(capsys.readouterr().out)["valid"] is False


def test_public_version_is_stable():
    assert __version__ == "0.1.0"


def test_compare_exit_code_reflects_trace_compatibility(tmp_path, capsys):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps({"stage": "one", "region_digest": "same", "region_signatures": {}}) + "\n",
        encoding="utf-8",
    )
    assert main(["compare", str(trace), str(trace)]) == 0
    assert json.loads(capsys.readouterr().out)["compatible"] is True


def test_cancelled_run_has_stable_exit_code(monkeypatch, tmp_path, capsys):
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF-")
    monkeypatch.setattr("envira_pdf_layout.cli.run_pdf", lambda *args, **kwargs: (_ for _ in ()).throw(RunCancelled("cancelled")))
    assert main(["run", str(source), "--output-dir", str(tmp_path / "out")]) == EXIT_CANCELLED
    assert json.loads(capsys.readouterr().err)["exit_code"] == EXIT_CANCELLED
