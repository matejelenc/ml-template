"""Launchers and the job wrapper, tested with a fake sbatch and a fake tmux.

Each test works in a throwaway copy of the repository with a local bare repository as
"origin". No real job is submitted and nothing is pushed anywhere real.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "scripts" / "launch" / "job_wrapper.sh"

FAKE_SBATCH = """#!/usr/bin/env bash
# Stand-in for sbatch: records its arguments, prints a job ID, and (if FAKE_RUN=1) runs the
# job script at once with SLURM_JOB_ID set, like a compute node would.
echo "$@" > "$FAKE_LOG"
for argument in "$@"; do
    case "$argument" in --output=*) output="${argument#--output=}" ;; esac
    script="$argument"
done
echo 4242
if [ "${FAKE_RUN:-0}" = 1 ]; then SLURM_JOB_ID=4242 bash "$script" > "$output" 2>&1; fi
exit 0
"""

FAKE_TMUX = """#!/usr/bin/env bash
# Stand-in for tmux: "new-session -d -s NAME COMMAND" runs COMMAND at once.
echo "$@" > "$FAKE_LOG"
[ "$1" = new-session ] && bash -c "$5" > /dev/null 2>&1
exit 0
"""


def git(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def read_json(path):
    return json.loads(Path(path).read_text())


@pytest.fixture
def project(tmp_path):
    """A committed copy of the launch scripts and config, with a bare "origin"."""
    project = tmp_path / "project"
    for folder in ("scripts", "conf"):
        shutil.copytree(REPO / folder, project / folder, ignore=shutil.ignore_patterns("__pycache__"))
    (project / "conf/experiment/vision").mkdir()
    (project / "conf/experiment/vision/002-sub.yaml").write_text("# @package _global_\nseed: 2\n")
    (project / ".gitignore").write_text("runs/\n.env\n")
    git(tmp_path, "init", "-q", "--bare", "-b", "main", "origin.git")
    git(project, "init", "-q", "-b", "main")
    git(project, "config", "user.email", "test@example.com")
    git(project, "config", "user.name", "Test")
    git(project, "add", ".")
    git(project, "commit", "-q", "-m", "first")
    git(project, "remote", "add", "origin", str(tmp_path / "origin.git"))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in (("sbatch", FAKE_SBATCH), ("tmux", FAKE_TMUX)):
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    return project


def launch(project, launcher, *args, run=False, env=None):
    """Run scripts/launch/<launcher>.sh in the project copy."""
    tmp_path = project.parent
    environment = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "FAKE_LOG": str(tmp_path / "fake.log"),
        "FAKE_RUN": "1" if run else "0",
        "WANDB_MODE": "disabled",
        **(env or {}),
    }
    for name in ("RUNS_DIR", "RUN_ID", "LAUNCH_PROFILE", "SLURM_JOB_ID", "LAUNCH_SCHEDULER", "ALLOW_DIRTY"):
        if name not in (env or {}):
            environment.pop(name, None)
    return subprocess.run(
        ["bash", f"scripts/launch/{launcher}.sh", *args],
        cwd=project, env=environment, capture_output=True, text=True,
    )


def only_run(project, experiment="001-toy"):
    (run_dir,) = (project / "runs" / experiment).iterdir()
    return run_dir


# Runs the real toy experiment with the Python that runs the tests.
TOY = [sys.executable, "scripts/experiment.py", "+experiment=001-toy", "train.steps=20",
       "journal.export=false"]


# --- job wrapper ---------------------------------------------------------------------

def wrapper(run_dir, *command, **kwargs):
    return subprocess.run(["bash", str(WRAPPER), str(run_dir), *command],
                          capture_output=True, text=True, **kwargs)


def test_wrapper_records_success_and_output(tmp_path):
    result = wrapper(tmp_path / "run", "bash", "-c", "echo out; echo err >&2")
    assert result.returncode == 0
    status = read_json(tmp_path / "run/status.json")
    assert status == {"schema_version": 1, "state": "done", "heartbeat": status["heartbeat"],
                      "exit_code": 0}
    assert (tmp_path / "run/output.log").read_text() == "out\nerr\n"


def test_wrapper_records_failure_with_exit_code(tmp_path):
    result = wrapper(tmp_path / "run", "bash", "-c", "exit 7")
    assert result.returncode == 7
    status = read_json(tmp_path / "run/status.json")
    assert status["state"] == "failed" and status["exit_code"] == 7


def test_wrapper_records_a_missing_command_as_failed(tmp_path):
    result = wrapper(tmp_path / "run", "no-such-command-xyz")
    assert result.returncode == 127
    assert read_json(tmp_path / "run/status.json")["state"] == "failed"


def test_wrapper_marks_queued(tmp_path):
    subprocess.run(["bash", str(WRAPPER), "--queued", str(tmp_path / "run")], check=True)
    status = read_json(tmp_path / "run/status.json")
    assert status["state"] == "queued" and status["exit_code"] is None


def test_wrapper_needs_a_command(tmp_path):
    assert wrapper(tmp_path / "run").returncode == 2


@pytest.mark.parametrize("signal_number", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_wrapper_records_cancellation_and_stops_the_job(tmp_path, signal_number):
    """scancel and a Slurm time limit send SIGTERM, tmux kill-session SIGHUP, Ctrl-C SIGINT."""
    run_dir = tmp_path / "run"
    job = [sys.executable, "-c",
           "import os, time; print(os.getpid(), flush=True); time.sleep(60)"]
    process = subprocess.Popen(["bash", str(WRAPPER), str(run_dir), *job],
                               env={**os.environ, "HEARTBEAT_SECONDS": "1"})
    deadline = time.time() + 10
    while not (run_dir / "output.log").is_file() or not (run_dir / "output.log").read_text().strip():
        assert time.time() < deadline, "job did not start"
        time.sleep(0.05)
    job_pid = int((run_dir / "output.log").read_text().split()[0])
    assert read_json(run_dir / "status.json")["state"] == "running"

    process.send_signal(signal_number)
    assert process.wait(timeout=10) != 0
    status = read_json(run_dir / "status.json")
    assert status["state"] == "cancelled" and status["exit_code"] != 0
    with pytest.raises(ProcessLookupError):  # the job itself is gone too
        os.kill(job_pid, 0)


def test_wrapper_refreshes_the_heartbeat(tmp_path):
    run_dir = tmp_path / "run"
    process = subprocess.Popen(["bash", str(WRAPPER), str(run_dir), "sleep", "3.5"],
                               env={**os.environ, "HEARTBEAT_SECONDS": "1"})
    time.sleep(0.5)
    first = read_json(run_dir / "status.json")
    time.sleep(2.2)
    later = read_json(run_dir / "status.json")
    assert first["state"] == later["state"] == "running"
    assert later["heartbeat"] > first["heartbeat"]
    assert process.wait(timeout=10) == 0
    assert read_json(run_dir / "status.json")["state"] == "done"
    assert not list(run_dir.glob("*.tmp"))


def test_wrapper_does_not_depend_on_the_library():
    text = WRAPPER.read_text()
    assert "expkit" not in text and "python" not in text


# --- prepare: git checks and tags --------------------------------------------------------

def test_dry_run_changes_nothing(project):
    result = launch(project, "tmux", "--dry-run", *TOY)
    assert result.returncode == 0, result.stderr
    assert "would create or reuse tag exp/001-toy" in result.stdout
    assert "dry run: nothing submitted" in result.stdout
    assert git(project, "tag") == ""
    assert not (project / "runs").exists()
    assert not (project.parent / "fake.log").exists()


def test_the_exact_command_is_printed_before_submitting(project):
    result = launch(project, "tmux", "--dry-run", "scripts/experiment.py", "+experiment=001-toy",
                    "train.lr=0.3")
    assert "job_wrapper.sh" in result.stdout
    # A command that starts with a .py file is run with uv.
    assert "uv run python scripts/experiment.py +experiment=001-toy train.lr=0.3" in result.stdout
    assert "submit: tmux new-session" in result.stdout


def test_dirty_tree_is_refused(project):
    (project / "scripts/experiment.py").write_text("# edited\n")
    result = launch(project, "tmux", *TOY)
    assert result.returncode == 1
    assert "uncommitted changes" in result.stderr
    assert git(project, "tag") == "" and not (project / "runs").exists()


def test_untracked_file_counts_as_dirty(project):
    (project / "new_module.py").write_text("x = 1\n")
    assert launch(project, "tmux", *TOY).returncode == 1


def test_allow_dirty_is_recorded_in_run_json(project):
    (project / "note.txt").write_text("uncommitted\n")
    result = launch(project, "tmux", "--allow-dirty", *TOY)
    assert result.returncode == 0, result.stderr
    info = read_json(only_run(project) / "run.json")
    assert info["git"]["dirty"] is True and info["git"]["allow_dirty"] is True


def test_tag_is_annotated_with_the_purpose_and_pushed(project):
    result = launch(project, "tmux", *TOY)
    assert result.returncode == 0, result.stderr
    assert git(project, "cat-file", "-t", "exp/001-toy") == "tag"  # annotated, not lightweight
    assert git(project, "tag", "-l", "--format=%(contents:subject)", "exp/001-toy") == (
        "check that the pipeline works end to end."
    )
    assert git(project, "rev-parse", "exp/001-toy^{commit}") == git(project, "rev-parse", "HEAD")
    origin = project.parent / "origin.git"
    assert git(origin, "rev-parse", "exp/001-toy^{commit}") == git(project, "rev-parse", "HEAD")


def test_relaunch_on_the_same_commit_reuses_the_tag(project):
    assert launch(project, "tmux", *TOY).returncode == 0
    result = launch(project, "tmux", *TOY)
    assert result.returncode == 0, result.stderr
    assert "reusing it" in result.stdout
    assert len(list((project / "runs/001-toy").iterdir())) == 2


def test_tag_on_another_commit_is_refused(project):
    assert launch(project, "tmux", *TOY).returncode == 0
    git(project, "commit", "-q", "--allow-empty", "-m", "more work")
    result = launch(project, "tmux", *TOY)
    assert result.returncode == 1
    assert "already exists on another commit" in result.stderr
    assert len(list((project / "runs/001-toy").iterdir())) == 1  # nothing new was started


def test_experiment_number_used_on_another_server_is_refused(project):
    """The tag exists only on origin, on a different commit. Fetching tags reveals it."""
    other = project.parent / "other-server"
    git(project.parent, "clone", "-q", str(project), str(other))
    git(other, "config", "user.email", "test@example.com")
    git(other, "config", "user.name", "Test")
    git(other, "commit", "-q", "--allow-empty", "-m", "work on the other server")
    git(other, "tag", "-a", "exp/001-toy", "-m", "taken")
    git(other, "push", "-q", str(project.parent / "origin.git"), "exp/001-toy")
    result = launch(project, "tmux", *TOY)
    assert result.returncode == 1
    assert "already exists on another commit" in result.stderr


def test_unknown_experiment_is_refused_before_anything_happens(project):
    result = launch(project, "tmux", sys.executable, "scripts/experiment.py", "+experiment=999-typo")
    assert result.returncode == 1
    assert "no experiment file" in result.stderr
    assert git(project, "tag") == "" and not (project / "runs").exists()


def test_launch_works_without_a_remote(project):
    git(project, "remote", "remove", "origin")
    result = launch(project, "tmux", *TOY)
    assert result.returncode == 0, result.stderr
    assert git(project, "tag") == "exp/001-toy"


def test_unreachable_remote_only_warns(project):
    git(project, "remote", "set-url", "origin", str(project.parent / "gone.git"))
    result = launch(project, "tmux", *TOY)
    assert result.returncode == 0, result.stderr
    assert "could not push tag" in result.stderr
    assert read_json(only_run(project) / "status.json")["state"] == "done"


def test_scratch_run_needs_no_tag_and_no_clean_tree(project):
    (project / "note.txt").write_text("uncommitted\n")
    result = launch(project, "tmux", sys.executable, "scripts/experiment.py", "train.steps=20")
    assert result.returncode == 0, result.stderr
    assert git(project, "tag") == ""
    run_dir = only_run(project, "scratch")
    assert read_json(run_dir / "status.json")["state"] == "done"
    assert read_json(run_dir / "run.json")["experiment_id"] == "scratch"


def test_experiment_in_a_subfolder(project):
    result = launch(project, "tmux", sys.executable, "scripts/experiment.py",
                    "+experiment=vision/002-sub", "train.steps=20", "journal.export=false")
    assert result.returncode == 0, result.stderr
    assert git(project, "tag") == "exp/002-sub"
    info = read_json(only_run(project, "002-sub") / "run.json")
    assert info["experiment_id"] == "002-sub" and info["git"]["tag"] == "exp/002-sub"


def test_unknown_option_and_missing_command(project):
    assert launch(project, "tmux", "--nonsense", *TOY).returncode == 1
    assert launch(project, "tmux").returncode == 1
    assert launch(project, "tmux", "--help").returncode == 0


# --- tmux --------------------------------------------------------------------------------

def test_tmux_launch_end_to_end(project):
    result = launch(project, "tmux", *TOY)
    assert result.returncode == 0, result.stderr
    run_dir = only_run(project)
    # The session is named after the run ID.
    assert (project.parent / "fake.log").read_text().startswith(f"new-session -d -s {run_dir.name} ")
    assert read_json(run_dir / "status.json") == {
        "schema_version": 1, "state": "done", "exit_code": 0,
        "heartbeat": read_json(run_dir / "status.json")["heartbeat"],
    }
    info = read_json(run_dir / "run.json")
    assert info["run_id"] == run_dir.name
    assert info["git"]["tag"] == "exp/001-toy" and info["git"]["dirty"] is False
    assert info["launch"]["scheduler"] == "tmux" and info["launch"]["job_id"] == run_dir.name
    assert "final loss" in (run_dir / "output.log").read_text()
    assert (run_dir / "summary.json").is_file() and (run_dir / "job.sh").is_file()


def test_failed_job_is_recorded(project):
    result = launch(project, "tmux", sys.executable, "scripts/experiment.py", "+experiment=001-toy",
                    "train.steps=not-a-number")
    assert result.returncode == 0  # the launch itself worked
    run_dir = only_run(project)
    status = read_json(run_dir / "status.json")
    assert status["state"] == "failed" and status["exit_code"] != 0
    assert "not-a-number" in (run_dir / "output.log").read_text()


def test_tmux_profile_setup_lines_run_before_the_job(project):
    (project / "scripts/launch/servers/mine.sh").write_text("export FROM_PROFILE=hello\n")
    git(project, "add", ".")
    git(project, "commit", "-q", "-m", "profile")
    result = launch(project, "tmux", "--profile", "mine", "bash", "-c", "echo value=$FROM_PROFILE")
    assert result.returncode == 0, result.stderr
    assert (only_run(project, "scratch") / "output.log").read_text() == "value=hello\n"


def test_runs_dir_comes_from_dot_env(project):
    elsewhere = project.parent / "big-disk"
    (project / ".env").write_text(f'WANDB_API_KEY=x\nRUNS_DIR="{elsewhere}"\n')
    result = launch(project, "tmux", *TOY)
    assert result.returncode == 0, result.stderr
    (run_dir,) = (elsewhere / "001-toy").iterdir()
    assert read_json(run_dir / "run.json")["run_dir"] == str(run_dir)
    assert not (project / "runs").exists()


# --- Slurm ---------------------------------------------------------------------------------

def test_slurm_needs_a_profile(project):
    result = launch(project, "slurm", *TOY)
    assert result.returncode == 1 and "no profile" in result.stderr
    assert launch(project, "slurm", "--profile", "missing", *TOY).returncode == 1


def test_slurm_job_is_queued_with_the_profile_header(project):
    result = launch(project, "slurm", "--profile", "hpc-gpu", "--sbatch", "--time=12:00:00 --mem=64G",
                    *TOY)
    assert result.returncode == 0, result.stderr
    assert "submitted Slurm job 4242" in result.stdout
    run_dir = only_run(project)
    assert read_json(run_dir / "status.json")["state"] == "queued"

    lines = (run_dir / "job.sh").read_text().splitlines()
    assert lines[0] == "#!/usr/bin/env bash"
    # Slurm reads #SBATCH lines only before the first command.
    first_command = next(i for i, line in enumerate(lines) if line and not line.startswith("#"))
    sbatch_lines = [i for i, line in enumerate(lines) if line.startswith("#SBATCH")]
    assert sbatch_lines and max(sbatch_lines) < first_command
    assert "#SBATCH --gres=gpu:1" in lines

    arguments = (project.parent / "fake.log").read_text().split()
    assert arguments[0] == "--parsable" and "--job-name=001-toy" in arguments
    assert f"--output={run_dir}/slurm.log" in arguments
    # Flags for this launch come after the defaults and before the script.
    assert arguments[-3:] == ["--time=12:00:00", "--mem=64G", str(run_dir / "job.sh")]


def test_slurm_profile_from_dot_env(project):
    (project / ".env").write_text("LAUNCH_PROFILE=hpc-cpu\n")
    result = launch(project, "slurm", "--dry-run", *TOY)
    assert result.returncode == 0, result.stderr
    assert "#SBATCH --partition=cpu" in result.stdout


def test_slurm_job_end_to_end(project):
    result = launch(project, "slurm", "--profile", "hpc-gpu", *TOY, run=True)
    assert result.returncode == 0, result.stderr
    run_dir = only_run(project)
    assert read_json(run_dir / "status.json")["state"] == "done"
    info = read_json(run_dir / "run.json")
    assert info["launch"]["scheduler"] == "slurm" and info["launch"]["job_id"] == "4242"
    assert info["git"]["tag"] == "exp/001-toy"
    assert "final loss" in (run_dir / "output.log").read_text()


def test_job_runs_even_if_the_library_is_broken(project):
    """The wrapper records a crash of the Python side like any other failure."""
    result = launch(project, "tmux", sys.executable, "-c", "import expkit_missing_module")
    assert result.returncode == 0
    status = read_json(only_run(project, "scratch") / "status.json")
    assert status["state"] == "failed" and status["exit_code"] == 1


# --- make status -----------------------------------------------------------------------------

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
