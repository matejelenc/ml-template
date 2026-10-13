"""scripts/status.py (make status), run on hand-made run folders."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_status_lists_runs_and_detects_lost_ones(tmp_path):
    def make(experiment, run_id, state, heartbeat, exit_code=None):
        run_dir = tmp_path / experiment / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "status.json").write_text(json.dumps(
            {"schema_version": 1, "state": state, "heartbeat": heartbeat, "exit_code": exit_code}))

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    make("001-toy", "20260101-000000-aaaa", "done", "2026-01-01T00:10:00Z", 0)
    make("001-toy", "20260102-000000-bbbb", "running", "2026-01-02T00:10:00Z")  # stale
    make("002-next", "20260103-000000-cccc", "running", now)
    make("002-next", "20260104-000000-dddd", "failed", "2026-01-04T00:10:00Z", 3)
    direct = tmp_path / "003-direct" / "20260105-000000-eeee"
    direct.mkdir(parents=True)
    (direct / "summary.json").write_text("{}")

    result = subprocess.run([sys.executable, str(REPO / "scripts/status.py")],
                            env={**os.environ, "RUNS_DIR": str(tmp_path)},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    rows = {line.split()[1]: line.split()[2] for line in result.stdout.splitlines()[1:]}
    assert rows == {
        "20260101-000000-aaaa": "done", "20260102-000000-bbbb": "lost",
        "20260103-000000-cccc": "running", "20260104-000000-dddd": "failed",
        "20260105-000000-eeee": "done",
    }
    # Newest first.
    assert list(rows)[0] == "20260105-000000-eeee"

    one = subprocess.run([sys.executable, str(REPO / "scripts/status.py"), "002-next"],
                         env={**os.environ, "RUNS_DIR": str(tmp_path)}, capture_output=True, text=True)
    assert len(one.stdout.splitlines()) == 3
