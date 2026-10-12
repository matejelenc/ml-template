"""Smoke tests for the Hydra config: run the toy experiment as a user would."""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run_experiment(tmp_path, *args, run_id="test-run"):
    """Run scripts/experiment.py with run folders redirected to a temp folder."""
    env = {**os.environ, "RUNS_DIR": str(tmp_path), "RUN_ID": run_id}
    return subprocess.run(
        [sys.executable, "scripts/experiment.py", "train.steps=20", *args],
        cwd=REPO, env=env, capture_output=True, text=True,
    )


def test_experiment_file_overrides_base_config(tmp_path):
    result = run_experiment(tmp_path, "+experiment=001-toy")
    assert result.returncode == 0, result.stderr
    assert "experiment_id: 001-toy" in result.stdout
    assert "lr: 0.1" in result.stdout  # from the experiment file
    assert "seed: 0" in result.stdout  # untouched base value
    assert "final loss" in result.stdout


def test_run_folder_is_runs_dir_experiment_run_id(tmp_path):
    result = run_experiment(tmp_path, "+experiment=001-toy")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "001-toy" / "test-run").is_dir()


def test_run_without_experiment_goes_to_scratch(tmp_path):
    result = run_experiment(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "experiment_id: scratch" in result.stdout
    assert "lr: 0.05" in result.stdout  # base value
    assert (tmp_path / "scratch" / "test-run").is_dir()


def test_command_line_override_wins_over_experiment_file(tmp_path):
    result = run_experiment(tmp_path, "+experiment=001-toy", "train.lr=0.3")
    assert result.returncode == 0, result.stderr
    assert "lr: 0.3" in result.stdout


def test_unknown_experiment_fails(tmp_path):
    result = run_experiment(tmp_path, "+experiment=999-missing")
    assert result.returncode != 0

