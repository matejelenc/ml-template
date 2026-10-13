"""List runs and their state.

    uv run python scripts/status.py             # the 20 newest runs
    uv run python scripts/status.py -n 0        # all runs
    uv run python scripts/status.py 012-lora    # runs of one experiment

A run that says "running" but whose heartbeat is older than 5 minutes is shown as "lost":
its job was killed without the chance to record it (out of memory, node failure).
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from expkit.config import load_env, runs_dir

# The job wrapper refreshes the heartbeat every 60 seconds.
LOST_AFTER_SECONDS = 300


def run_state(run_dir: Path, now: datetime) -> dict[str, Any]:
    """State of one run folder, with stale "running" turned into "lost"."""
    try:
        status = json.loads((run_dir / "status.json").read_text())
    except (OSError, ValueError):
        # Started directly, without a launcher: there is no status.json.
        finished = (run_dir / "summary.json").is_file()
        return {"state": "done (direct)" if finished else "unknown", "age": "", "exit_code": None}
    heartbeat = datetime.strptime(status["heartbeat"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    seconds = int((now - heartbeat).total_seconds())
    state = status["state"]
    if state == "running" and seconds > LOST_AFTER_SECONDS:
        state = "lost"
    age = (
        f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
        if seconds >= 3600
        else f"{seconds // 60}m{seconds % 60:02d}s"
    )
    return {"state": state, "age": age, "exit_code": status.get("exit_code")}


def main() -> None:
    """Read the command line and print one line per run."""
    parser = argparse.ArgumentParser(description="List runs and their state.")
    parser.add_argument("experiment", nargs="?", help="only this experiment, e.g. 012-lora")
    parser.add_argument("-n", type=int, default=20, help="how many runs to show, 0 for all")
    args = parser.parse_args()

    load_env()
    run_dirs = [p for p in runs_dir().glob(f"{args.experiment or '*'}/*") if p.is_dir()]
    run_dirs.sort(key=lambda p: p.name, reverse=True)  # run IDs start with the time
    if args.n:
        run_dirs = run_dirs[: args.n]

    now = datetime.now(UTC)
    print(f"{'EXPERIMENT':<24} {'RUN':<22} {'STATE':<14} {'LAST UPDATE':<12} EXIT")
    for run_dir in run_dirs:
        state = run_state(run_dir, now)
        exit_code = "" if state["exit_code"] is None else state["exit_code"]
        print(
            f"{run_dir.parent.name:<24} {run_dir.name:<22} {state['state']:<14} "
            f"{state['age'] + ' ago' if state['age'] else '':<12} {exit_code}"
        )


if __name__ == "__main__":
    main()
