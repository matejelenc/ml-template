"""The run record: files, fields, hashes and redaction."""

import hashlib
import json
import os
import re
import stat
import subprocess

import pytest
import yaml
from omegaconf import OmegaConf

from expkit import config as expkit_config
from expkit import gitutil, record

RUN_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


def make_cfg(tmp_path, **extra):
    return OmegaConf.create(
        {
            "experiment_id": "001-toy",
            "run_id": "20260101-120000-abcd",
            "paths": {"run_dir": str(tmp_path / "runs" / "001-toy" / "20260101-120000-abcd")},
            "train": {"lr": 0.1},
            **extra,
        }
    )


def read_json(path):
    return json.loads(path.read_text())


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A small git repository with one commit. Tests run inside it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "uv.lock").write_text("lock\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "first")
    monkeypatch.chdir(repo)
    return repo


# --- run ID ---------------------------------------------------------------


def test_run_id_format_and_uniqueness():
    ids = {expkit_config.new_run_id() for _ in range(50)}
    assert all(RUN_ID_PATTERN.match(run_id) for run_id in ids)
    assert len(ids) > 1  # same second, different suffix


def test_run_id_is_stable_within_a_process(monkeypatch):
    monkeypatch.delenv("RUN_ID", raising=False)
    monkeypatch.setattr(expkit_config, "_run_id", None)
    assert expkit_config._get_run_id() == expkit_config._get_run_id()


def test_run_id_from_environment(monkeypatch):
    monkeypatch.setenv("RUN_ID", "given-by-launcher")
    monkeypatch.setattr(expkit_config, "_run_id", None)
    assert expkit_config._get_run_id() == "given-by-launcher"


# --- start ----------------------------------------------------------------


def test_start_creates_the_run_folder(tmp_path, repo):
    run = record.start(make_cfg(tmp_path))
    assert (
        run.dir.is_dir() and run.weights_dir.is_dir() and run.journal_dir.is_dir() and run.eval_dir.is_dir()
    )
    assert (run.dir / "run.json").is_file()
    assert (run.dir / "config.yaml").is_file()


def test_run_json_fields(tmp_path, repo):
    run = record.start(make_cfg(tmp_path))
    info = read_json(run.dir / "run.json")
    assert info["schema_version"] == record.SCHEMA_VERSION
    assert info["experiment_id"] == "001-toy"
    assert info["run_id"] == "20260101-120000-abcd"
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", info["started_at"])
    assert info["run_dir"] == str(run.dir)
    assert set(info["git"]) == {"sha", "tag", "repo_url", "dirty", "allow_dirty"}
    assert set(info["environment"]) == {"hostname", "python", "lockfile_sha256", "cuda", "gpu_driver", "gpus"}
    assert set(info["launch"]) == {"scheduler", "job_id", "command"}
    assert info["wandb_url"] is None


def test_git_fields_clean_tree(tmp_path, repo):
    info = read_json(record.start(make_cfg(tmp_path)).dir / "run.json")
    assert re.match(r"^[0-9a-f]{40}$", info["git"]["sha"])
    assert info["git"]["dirty"] is False
    assert info["git"]["tag"] is None
    assert info["git"]["repo_url"] is None
    assert info["git"]["allow_dirty"] is False


def test_git_fields_dirty_tree_and_allow_dirty(tmp_path, repo, monkeypatch):
    (repo / "uv.lock").write_text("changed\n")
    monkeypatch.setenv("ALLOW_DIRTY", "1")
    info = read_json(record.start(make_cfg(tmp_path)).dir / "run.json")
    assert info["git"]["dirty"] is True
    assert info["git"]["allow_dirty"] is True


def test_git_tag_counts_only_on_the_running_commit(tmp_path, repo):
    git(repo, "tag", "-a", "exp/001-toy", "-m", "purpose")
    git(repo, "tag", "-a", "exp/002-other", "-m", "purpose")
    assert gitutil.info("001-toy")["tag"] == "exp/001-toy"
    git(repo, "commit", "-q", "--allow-empty", "-m", "second")
    assert gitutil.info("001-toy")["tag"] is None


def test_repo_url_has_no_credentials(repo):
    git(repo, "remote", "add", "origin", "https://user:tok123@example.com/me/project.git")
    assert gitutil.info("001-toy")["repo_url"] == "https://example.com/me/project.git"


def test_outside_a_git_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    info = read_json(record.start(make_cfg(tmp_path)).dir / "run.json")
    assert info["git"]["sha"] is None and info["git"]["dirty"] is None
    assert info["environment"]["lockfile_sha256"] is None


def test_lockfile_hash(tmp_path, repo):
    info = read_json(record.start(make_cfg(tmp_path)).dir / "run.json")
    assert info["environment"]["lockfile_sha256"] == hashlib.sha256(b"lock\n").hexdigest()


def test_gpu_fields_from_nvidia_smi(tmp_path, repo, monkeypatch):
    """A fake nvidia-smi on PATH stands in for a GPU server."""
    fake = tmp_path / "bin" / "nvidia-smi"
    fake.parent.mkdir()
    fake.write_text(
        "#!/bin/sh\n"
        'if [ -n "$1" ]; then\n'
        '  echo "NVIDIA RTX A6000, 550.54.14"; echo "NVIDIA RTX A6000, 550.54.14"\n'
        "else\n"
        '  echo "| NVIDIA-SMI 550.54.14   Driver Version: 550.54.14   CUDA Version: 12.4 |"\n'
        "fi\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ['PATH']}")
    environment = read_json(record.start(make_cfg(tmp_path)).dir / "run.json")["environment"]
    assert environment["gpus"] == ["NVIDIA RTX A6000", "NVIDIA RTX A6000"]
    assert environment["gpu_driver"] == "550.54.14"
    assert environment["cuda"] == "12.4"


def test_scheduler_detection(tmp_path, repo, monkeypatch):
    monkeypatch.setenv("SLURM_JOB_ID", "4242")
    launch = read_json(record.start(make_cfg(tmp_path)).dir / "run.json")["launch"]
    assert launch["scheduler"] == "slurm" and launch["job_id"] == "4242"


# --- config ---------------------------------------------------------------


def test_resolved_config_is_written_with_schema_version(tmp_path, repo):
    run = record.start(make_cfg(tmp_path))
    saved = yaml.safe_load((run.dir / "config.yaml").read_text())
    assert saved["schema_version"] == record.SCHEMA_VERSION
    assert saved["config"]["train"]["lr"] == 0.1


def test_secrets_reach_no_run_file(tmp_path, repo, monkeypatch):
    monkeypatch.setenv("SECRETS", "WANDB_API_KEY")
    monkeypatch.setenv("WANDB_API_KEY", "wandb-secret-123456")
    monkeypatch.setattr("sys.argv", ["experiment.py", "note=wandb-secret-123456"])
    cfg = make_cfg(tmp_path, note="uses wandb-secret-123456")
    run = record.start(cfg)
    run.update(wandb_url="https://wandb.ai/x?key=wandb-secret-123456")
    run.finish()
    for path in run.dir.rglob("*"):
        if path.is_file():
            text = path.read_text()
            assert "wandb-secret-123456" not in text, path.name
    assert "<redacted>" in (run.dir / "config.yaml").read_text()


# --- metrics and summary ----------------------------------------------------


class FakeTensor:
    """Behaves like a NumPy or PyTorch scalar: not JSON, but has .item()."""

    def item(self):
        return 0.25


def test_monitor_appends_json_lines(tmp_path, repo):
    run = record.start(make_cfg(tmp_path))
    run.monitor(step=1, loss=0.5)
    run.monitor(step=2, loss=FakeTensor(), acc=0.9)
    lines = [json.loads(line) for line in (run.monitor_dir / "main.jsonl").read_text().splitlines()]
    assert lines == [{"step": 1, "loss": 0.5}, {"step": 2, "loss": 0.25, "acc": 0.9}]


def test_metrics_can_be_appended_without_the_library(tmp_path, repo):
    run = record.start(make_cfg(tmp_path))
    with open(run.monitor_dir / "main.jsonl", "a") as file:
        file.write(json.dumps({"step": 1, "loss": 0.5}) + "\n")
    run.monitor(step=2, loss=0.4)
    assert len((run.monitor_dir / "main.jsonl").read_text().splitlines()) == 2


def test_each_series_gets_its_own_file(tmp_path, repo):
    run = record.start(make_cfg(tmp_path))
    run.monitor(step=0, loss=1.0)
    run.monitor(step=0, series="model_a/fold_0", loss=0.9)
    run.monitor(step=0, series="model_a/fold_1", loss=0.8)  # steps may start again
    run.monitor(step=1, series="model_a/fold_1", loss=0.7)
    files = sorted(str(p.relative_to(run.monitor_dir)) for p in run.monitor_dir.rglob("*.jsonl"))
    assert files == ["main.jsonl", "model_a/fold_0.jsonl", "model_a/fold_1.jsonl"]
    assert len((run.monitor_dir / "model_a/fold_1.jsonl").read_text().splitlines()) == 2


@pytest.mark.parametrize("series", ["", "../outside", "/absolute", "a//b", "a/", "with space", ".hidden"])
def test_bad_series_names_are_refused(tmp_path, repo, series):
    run = record.start(make_cfg(tmp_path))
    with pytest.raises(ValueError):
        run.monitor(step=0, series=series, loss=1.0)


def test_summary_lists_the_weight_files(tmp_path, repo):
    run = record.start(make_cfg(tmp_path))
    (run.weights_dir / "model.pt").write_bytes(b"weights" * 1000)
    (run.weights_dir / "sub").mkdir()
    (run.weights_dir / "sub" / "head.pt").write_bytes(b"head")
    run.finish(metrics={"loss": FakeTensor(), "acc": 0.9})
    summary = read_json(run.dir / "summary.json")
    assert summary["schema_version"] == record.SCHEMA_VERSION
    assert summary["metrics"] == {"loss": 0.25, "acc": 0.9}
    assert summary["duration_seconds"] >= 0
    assert summary["weights"] == [
        {
            "path": "weights/model.pt",
            "size_bytes": 7000,
            "sha256": hashlib.sha256(b"weights" * 1000).hexdigest(),
        },
        {"path": "weights/sub/head.pt", "size_bytes": 4, "sha256": hashlib.sha256(b"head").hexdigest()},
    ]


class FakeArray:
    """Behaves like a NumPy array or a tensor with several elements: item() refuses."""

    def item(self):
        raise ValueError("can only convert an array of size 1 to a Python scalar")

    def tolist(self):
        return [0.9, 0.8]


def test_an_array_metric_does_not_cost_the_run_its_summary(tmp_path, repo):
    run = record.start(make_cfg(tmp_path))
    run.monitor(step=1, per_class=FakeArray())
    run.finish(metrics={"per_class": FakeArray(), "where": tmp_path})
    assert json.loads((run.monitor_dir / "main.jsonl").read_text())["per_class"] == [0.9, 0.8]
    assert read_json(run.dir / "summary.json")["metrics"] == {"per_class": [0.9, 0.8], "where": str(tmp_path)}


def test_update_changes_run_json(tmp_path, repo):
    run = record.start(make_cfg(tmp_path))
    run.update(wandb_url="https://wandb.ai/me/project/runs/abc")
    info = read_json(run.dir / "run.json")
    assert info["wandb_url"] == "https://wandb.ai/me/project/runs/abc"
    assert info["experiment_id"] == "001-toy"  # other fields are kept
