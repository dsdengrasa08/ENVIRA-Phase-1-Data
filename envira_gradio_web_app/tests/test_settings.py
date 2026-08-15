from pathlib import Path

import pytest

from envira_gradio.settings import AppSettings


def test_settings_keep_temporary_and_persistent_roots_separate(tmp_path: Path):
    config = tmp_path / "config.yaml"
    config.write_text("{}\n")
    with pytest.raises(ValueError):
        AppSettings(tmp_path, config, tmp_path).normalized()


def test_default_model_root_is_persistent(tmp_path: Path):
    config = tmp_path / "config.yaml"
    config.write_text("{}\n")
    settings = AppSettings(tmp_path / "drive", config, tmp_path / "temp").normalized()
    assert settings.model_root == (tmp_path / "drive" / "models" / "docling").resolve()
