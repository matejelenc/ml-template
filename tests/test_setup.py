"""scripts/setup.py, run in a throwaway copy of the repository.

A local bare repository stands in for the Overleaf project.
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOKEN = "olp_test-token-123456"


def git(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


@pytest.fixture
def project(tmp_path):
    project = tmp_path / "my-project"
    for folder in ("scripts", "overleaf_template"):
        shutil.copytree(REPO / folder, project / folder, ignore=shutil.ignore_patterns("__pycache__"))
    return project


@pytest.fixture
def overleaf(tmp_path):
    """A bare repository holding only main.tex, like a new Overleaf project with a paper."""
    remote = tmp_path / "overleaf.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(remote), str(seed))
    git(seed, "config", "user.email", "test@example.com")
    git(seed, "config", "user.name", "Test")
    (seed / "main.tex").write_text("the paper\n")
    git(seed, "add", ".")
    git(seed, "commit", "-q", "-m", "paper")
    git(seed, "push", "-q", "origin", "HEAD:main")
    return remote


def run_setup(project, answers):
    """Answer the questions in order: W&B key, W&B project, Overleaf URL, token, runs, data, profile."""
    env = {name: value for name, value in os.environ.items()
           if not name.startswith(("OVERLEAF_", "WANDB_"))}
    return subprocess.run([sys.executable, "scripts/setup.py"], cwd=project, env=env,
                          input="\n".join(answers) + "\n", capture_output=True, text=True)


def env_lines(project):
    return (project / ".env").read_text().splitlines()


def test_first_setup_writes_env_and_fills_the_overleaf_project(project, overleaf):
    result = run_setup(project, ["wandb-key-123456", "", f"git clone {overleaf} folder", TOKEN,
                                 "/big/runs", "", "hpc-gpu"])
    assert result.returncode == 0, result.stderr
    assert env_lines(project) == [
        "WANDB_API_KEY=wandb-key-123456",
        "WANDB_PROJECT=my-project",  # default: the folder name
        f"OVERLEAF_GIT_URL={overleaf}",  # "git clone" and the folder name are stripped
        f"OVERLEAF_TOKEN={TOKEN}",
        "RUNS_DIR=/big/runs",
        "DATA_DIR=",
        "LAUNCH_PROFILE=hpc-gpu",
    ]
    assert stat.S_IMODE((project / ".env").stat().st_mode) == 0o600

    files = git(overleaf, "ls-tree", "-r", "--name-only", "main").splitlines()
    assert files == ["generated/macros.sty", "journal.tex", "main.tex", "report.tex"]
    assert git(overleaf, "show", "main:main.tex") == "the paper"  # untouched


def test_secrets_are_not_printed_or_stored_in_the_clone(project, overleaf):
    result = run_setup(project, ["wandb-key-123456", "", str(overleaf), TOKEN, "", "", ""])
    assert result.returncode == 0, result.stderr
    assert TOKEN not in result.stdout + result.stderr
    assert "wandb-key-123456" not in result.stdout + result.stderr
    for path in (project / "overleaf" / ".git").rglob("*"):
        if path.is_file():
            assert TOKEN.encode() not in path.read_bytes(), path
    assert TOKEN not in git(project / "overleaf", "remote", "get-url", "origin")


def test_second_run_keeps_values_and_pushes_nothing(project, overleaf):
    run_setup(project, ["wandb-key-123456", "proj", str(overleaf), TOKEN, "", "", ""])
    before = env_lines(project)
    commits = git(overleaf, "rev-list", "--count", "main")
    result = run_setup(project, [""] * 7)  # Enter for every question
    assert result.returncode == 0, result.stderr
    assert env_lines(project) == before
    assert git(overleaf, "rev-list", "--count", "main") == commits
    assert "nothing to add" in result.stdout


def test_existing_files_in_overleaf_are_never_overwritten(project, overleaf, tmp_path):
    seed = tmp_path / "seed"
    (seed / "journal.tex").write_text("my own journal\n")
    git(seed, "add", ".")
    git(seed, "commit", "-q", "-m", "journal")
    git(seed, "push", "-q", "origin", "HEAD:main")
    result = run_setup(project, ["k" * 16, "", str(overleaf), TOKEN, "", "", ""])
    assert result.returncode == 0, result.stderr
    assert git(overleaf, "show", "main:journal.tex") == "my own journal"
    assert "report.tex" in git(overleaf, "ls-tree", "-r", "--name-only", "main")


def test_other_lines_in_env_are_kept(project, overleaf):
    (project / ".env").write_text("# my comment\nMY_OWN_SETTING=1\nWANDB_PROJECT=old\n")
    result = run_setup(project, ["k" * 16, "new", "", "", "", "", ""])
    assert result.returncode == 0, result.stderr
    lines = env_lines(project)
    assert lines[:3] == ["# my comment", "MY_OWN_SETTING=1", "WANDB_PROJECT=new"]
    assert stat.S_IMODE((project / ".env").stat().st_mode) == 0o600


def test_overleaf_can_be_skipped(project):
    result = run_setup(project, ["k" * 16, "", "", "", "", "", ""])
    assert result.returncode == 0, result.stderr
    assert "Overleaf: skipped" in result.stdout
    assert not (project / "overleaf").exists()


def test_wrong_overleaf_url_fails_clearly_but_env_is_written(project, tmp_path):
    result = run_setup(project, ["k" * 16, "", str(tmp_path / "no-such-repo.git"), TOKEN, "", "", ""])
    assert result.returncode == 1
    assert "Overleaf: failed" in result.stderr
    assert (project / ".env").is_file()
