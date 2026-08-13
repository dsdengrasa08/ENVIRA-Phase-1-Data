from pathlib import Path


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
