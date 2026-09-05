from envira_pdf_layout.config import PipelineConfig
from envira_pdf_layout.doctor import run_doctor


def test_doctor_reports_individual_failures_without_raising(tmp_path):
    config = PipelineConfig.load(
        environ={},
        runtime={"project_dir": tmp_path},
        operational={"minimum_free_disk_bytes": 0},
        docling={"artifacts_dir": tmp_path / "missing-models"},
    )
    report = run_doctor(config)
    assert report["doctor_schema_version"] == 1
    assert report["healthy"] is False
    checks = {row["name"]: row for row in report["checks"]}
    assert checks["configuration"]["status"] == "pass"
    assert checks["output_writable"]["status"] == "pass"
    assert checks["model_manifest"]["status"] == "fail"
