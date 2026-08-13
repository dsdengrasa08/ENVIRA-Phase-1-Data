from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.version import Version


ROOT = Path(__file__).parents[1]


def test_legacy_requirements_are_independent_of_callers_working_directory():
    requirements = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert requirements
    assert not any(requirement.startswith((".", "-e ", "file:")) for requirement in requirements)
    assert any(requirement.lower().startswith("docling") for requirement in requirements)
    assert any(requirement.lower().startswith("pytest") for requirement in requirements)


def test_regression_direct_pins_satisfy_project_contract():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = {
        Requirement(value).name.casefold(): Requirement(value)
        for value in project["dependencies"] + project["optional-dependencies"]["test"]
    }
    pins = {}
    for line in (ROOT / "constraints-regression.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, version = line.split("==", 1)
            pins[name.casefold()] = Version(version)
    assert set(declared) <= set(pins)
    for name, requirement in declared.items():
        assert pins[name] in requirement.specifier, (
            f"{name}=={pins[name]} violates {requirement.specifier}"
        )


def test_distribution_version_has_one_source_of_truth():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in pyproject["project"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"].endswith(
        "_version.__version__"
    )
