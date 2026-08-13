import json
from importlib.resources import files

import yaml


def test_installed_default_profile_and_schemas_are_package_resources():
    root = files("envira_pdf_layout").joinpath("resources")
    assert yaml.safe_load(root.joinpath("default.yaml").read_text())["document"]["page_start"] == 1
    assert json.loads(root.joinpath("layout-region-v1.schema.json").read_text())["properties"]["region_schema_version"]["const"] == 1
    assert json.loads(root.joinpath("artifact-manifest-v1.schema.json").read_text())["properties"]["schema_version"]["const"] == 1
    assert json.loads(root.joinpath("model-manifest-v1.schema.json").read_text())["properties"]["model_manifest_schema_version"]["const"] == 1
