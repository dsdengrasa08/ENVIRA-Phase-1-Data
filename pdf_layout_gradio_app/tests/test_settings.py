from pathlib import Path

from envira_layout_web.settings import AppSettings


def test_settings_are_rooted_in_standalone_app(tmp_path):
    app = tmp_path / "app"
    (app / "config").mkdir(parents=True)
    (app / "config" / "default.yaml").write_text("{}\n", encoding="utf-8")
    settings = AppSettings.load(
        app,
        environ={
            "ENVIRA_WEB_OUTPUT_ROOT": str(tmp_path / "drive"),
            "ENVIRA_WEB_TEMP_ROOT": str(tmp_path / "temp"),
        },
    )
    settings.prepare()
    assert settings.app_root == app.resolve()
    assert settings.persistent_output_root.is_dir()
    assert settings.temporary_root.is_dir()
    assert not (settings.persistent_output_root / ".envira-write-probe").exists()
