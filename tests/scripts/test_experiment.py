"""scripts/experiment.py and the Hydra config: run the toy experiment as a user would."""

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def run_experiment(tmp_path, *args, run_id="test-run"):
    """Run scripts/experiment.py with run folders redirected to a temp folder."""
    env = {
        **os.environ,
        "RUNS_DIR": str(tmp_path),
        "WANDB_MODE": "disabled",
        "OVERLEAF_DIR": str(tmp_path / "no-overleaf"),
        "OVERLEAF_GIT_URL": "",
        "RUN_ID": run_id,
    }
    return subprocess.run(
        [sys.executable, "scripts/experiment.py", "train.steps=20", "journal.export=false", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
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


def test_run_folder_matches_the_schema(tmp_path):
    result = run_experiment(tmp_path, "+experiment=001-toy")
    assert result.returncode == 0, result.stderr
    run_dir = tmp_path / "001-toy" / "test-run"
    assert sorted(path.name for path in run_dir.iterdir()) == [
        "config.yaml",
        "eval",
        "journal",
        "monitor",
        "run.json",
        "summary.json",
        "weights",
    ]  # in particular: no .hydra folder and no Hydra log file
    assert (run_dir / "weights" / "model.json").is_file()
    assert (run_dir / "journal" / "loss.pdf").is_file()


def test_run_id_is_generated_without_the_launcher(tmp_path):
    env = {
        **os.environ,
        "RUNS_DIR": str(tmp_path),
        "WANDB_MODE": "disabled",
        "OVERLEAF_DIR": str(tmp_path / "no-overleaf"),
        "OVERLEAF_GIT_URL": "",
    }
    env.pop("RUN_ID", None)
    result = subprocess.run(
        [sys.executable, "scripts/experiment.py", "train.steps=20"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    (run_dir,) = (tmp_path / "scratch").iterdir()  # exactly one folder: the ID was made once
    assert re.match(r"^\d{8}-\d{6}-[0-9a-f]{4}$", run_dir.name)
    assert f"run_id: {run_dir.name}" in result.stdout


def test_secret_on_the_command_line_is_not_printed_or_saved(tmp_path):
    env = {
        **os.environ,
        "RUNS_DIR": str(tmp_path),
        "WANDB_MODE": "disabled",
        "OVERLEAF_DIR": str(tmp_path / "no-overleaf"),
        "OVERLEAF_GIT_URL": "",
        "RUN_ID": "test-run",
        "SECRETS": "MY_API_KEY",
        "MY_API_KEY": "secret-value-123456",
    }
    result = subprocess.run(
        [sys.executable, "scripts/experiment.py", "train.steps=20", "+note=secret-value-123456"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "secret-value-123456" not in result.stdout
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert b"secret-value-123456" not in path.read_bytes(), path.name


def test_empty_variables_in_env_count_as_unset(tmp_path):
    # A line such as "WANDB_ENTITY=" in .env must not turn into an empty setting.
    env = {
        **os.environ,
        "RUNS_DIR": str(tmp_path),
        "WANDB_MODE": "disabled",
        "OVERLEAF_DIR": str(tmp_path / "no-overleaf"),
        "OVERLEAF_GIT_URL": "",
        "RUN_ID": "test-run",
        "DATA_DIR": "",
        "WANDB_ENTITY": "",
        "WANDB_PROJECT": "",
    }
    result = subprocess.run(
        [sys.executable, "scripts/experiment.py", "train.steps=20"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    # The default, as a path below the repository.
    assert f"data_dir: {REPO}/data" in result.stdout
    assert "entity: null" in result.stdout
    assert "project: ml-template" in result.stdout
