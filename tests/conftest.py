"""Fixtures shared by several test files."""

import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"


@pytest.fixture
def project_copy(tmp_path):
    """A throwaway copy of scripts/ and conf/, plus a stand-in script and experiment.

    The copy has the real base config and the real launchers, but the script that runs is
    scripts/stand_in.py with +experiment=900-stand-in: nothing here depends on the example
    script, on its experiment file or on the settings of a project.
    """
    project = tmp_path / "project"
    for folder in ("scripts", "conf"):
        shutil.copytree(REPO / folder, project / folder, ignore=shutil.ignore_patterns("__pycache__"))
    (project / "conf" / "experiment").mkdir(exist_ok=True)
    shutil.copy(FIXTURES / "stand_in.py", project / "scripts")
    shutil.copy(FIXTURES / "900-stand-in.yaml", project / "conf" / "experiment")
    return project
