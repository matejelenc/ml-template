"""expkit.config: reading .env and the folders named in it."""

import os
import subprocess

from expkit import config
from expkit.config import load_env


def test_load_env_skips_empty_values_and_keeps_the_shell(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("WANDB_MODE=\nFROM_FILE=abc\nFROM_SHELL=file\n")
    for name in ("WANDB_MODE", "FROM_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FROM_SHELL", "shell")
    load_env(env_file)
    # An empty WANDB_MODE in the environment makes the W&B library fail at start.
    assert "WANDB_MODE" not in os.environ
    assert os.environ["FROM_FILE"] == "abc" and os.environ["FROM_SHELL"] == "shell"
    monkeypatch.delenv("FROM_FILE")


def test_a_relative_folder_is_relative_to_the_repository(tmp_path, monkeypatch):
    repo = tmp_path / "project"
    (repo / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.chdir(repo / "scripts")  # not the top folder
    monkeypatch.setenv("RUNS_DIR", "")  # empty counts as unset
    assert config.runs_dir() == repo.resolve() / "runs"
    monkeypatch.setenv("RUNS_DIR", "out/runs")
    assert config.runs_dir() == repo.resolve() / "out/runs"
    monkeypatch.setenv("RUNS_DIR", "/big/runs")
    assert config.runs_dir() == config.Path("/big/runs")
