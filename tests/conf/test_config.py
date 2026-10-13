"""conf/config.yaml: the bookkeeping part of the base config, run through a stand-in script.

Each test runs tests/fixtures/stand_in.py in a throwaway copy of the project (see
tests/conftest.py), as a user would run a script of their own.
"""

import os
import re
import subprocess
import sys

import yaml

EXPERIMENT = "+experiment=900-stand-in"


def run_script(project, *args, **env):
    """Run the stand-in script. Run folders go to runs/ next to the project copy."""
    environment = {**os.environ, "RUNS_DIR": str(project.parent / "runs"), "WANDB_MODE": "disabled", **env}
    for name in ("RUN_ID", "SECRETS", "DATA_DIR", "WANDB_PROJECT", "WANDB_ENTITY"):
        if name not in env:
            environment.pop(name, None)
    return subprocess.run(
        [sys.executable, "scripts/stand_in.py", *args],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
    )


def test_experiment_file_overrides_base_config(project_copy):
    result = run_script(project_copy, EXPERIMENT)
    assert result.returncode == 0, result.stderr
    assert "experiment_id: 900-stand-in" in result.stdout
    assert "seed: 7" in result.stdout  # from the experiment file


def test_command_line_override_wins_over_experiment_file(project_copy):
    result = run_script(project_copy, EXPERIMENT, "seed=9")
    assert result.returncode == 0, result.stderr
    assert "seed: 9" in result.stdout


def test_unknown_experiment_fails(project_copy):
    assert run_script(project_copy, "+experiment=999-missing").returncode != 0


def test_run_folder_is_runs_dir_experiment_run_id(project_copy):
    result = run_script(project_copy, EXPERIMENT, RUN_ID="test-run")
    assert result.returncode == 0, result.stderr
    assert (project_copy.parent / "runs" / "900-stand-in" / "test-run" / "run.json").is_file()


def test_run_without_experiment_goes_to_scratch(project_copy):
    result = run_script(project_copy, RUN_ID="test-run")
    assert result.returncode == 0, result.stderr
    assert "experiment_id: scratch" in result.stdout
    assert (project_copy.parent / "runs" / "scratch" / "test-run").is_dir()


def test_run_id_is_generated_without_the_launcher(project_copy):
    result = run_script(project_copy)
    assert result.returncode == 0, result.stderr
    (run_dir,) = (project_copy.parent / "runs" / "scratch").iterdir()  # one folder: the ID was made once
    assert re.match(r"^\d{8}-\d{6}-[0-9a-f]{4}$", run_dir.name)
    assert f"run_id: {run_dir.name}" in result.stdout


def test_hydra_adds_nothing_to_the_run_folder(project_copy):
    result = run_script(project_copy, RUN_ID="test-run")
    assert result.returncode == 0, result.stderr
    run_dir = project_copy.parent / "runs" / "scratch" / "test-run"
    assert sorted(path.name for path in run_dir.iterdir()) == [
        "config.yaml",
        "eval",
        "journal",
        "monitor",
        "run.json",
        "summary.json",
        "weights",
    ]  # in particular: no .hydra folder and no Hydra log file


def test_multirun_is_refused_because_its_jobs_would_share_a_run_folder(project_copy):
    # Hydra's own sweep folder goes next to the project copy, like the run folders.
    result = run_script(project_copy, "-m", "+probe=1,2", f"hydra.sweep.dir={project_copy.parent / 'sweep'}")
    assert result.returncode != 0
    assert "multirun (-m) is not supported" in result.stdout + result.stderr
    assert not list(project_copy.parent.rglob("summary.json"))


def test_secret_on_the_command_line_is_not_printed_or_saved(project_copy):
    result = run_script(
        project_copy, "+note=secret-value-123456", SECRETS="MY_API_KEY", MY_API_KEY="secret-value-123456"
    )
    assert result.returncode == 0, result.stderr
    assert "secret-value-123456" not in result.stdout
    for path in (project_copy.parent / "runs").rglob("*"):
        if path.is_file():
            assert b"secret-value-123456" not in path.read_bytes(), path.name


def test_empty_variables_in_env_count_as_unset(project_copy):
    # A line such as "WANDB_ENTITY=" in .env must not turn into an empty setting.
    result = run_script(project_copy, RUN_ID="test-run", DATA_DIR="", WANDB_ENTITY="", WANDB_PROJECT="")
    assert result.returncode == 0, result.stderr
    saved = yaml.safe_load((project_copy.parent / "runs/scratch/test-run/config.yaml").read_text())["config"]
    # The defaults of the base config: a folder below the project, a project name, no entity.
    assert saved["paths"]["data_dir"] == str(project_copy.resolve() / "data")
    assert saved["wandb"]["project"] and saved["wandb"]["entity"] is None
