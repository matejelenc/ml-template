"""scripts/experiment.py: the example runs from start to end. Delete this file with the example."""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_the_example_runs_and_fills_its_run_folder(tmp_path):
    # A scratch run without W&B: nothing is uploaded and no journal entry is pushed.
    env = {**os.environ, "RUNS_DIR": str(tmp_path), "WANDB_MODE": "disabled", "RUN_ID": "test-run"}
    result = subprocess.run(
        [sys.executable, "scripts/experiment.py", "train.steps=20"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    run_dir = tmp_path / "scratch" / "test-run"
    assert (run_dir / "summary.json").is_file()
    assert (run_dir / "journal" / "loss.pdf").is_file()
    assert (run_dir / "weights" / "model.json").is_file()
