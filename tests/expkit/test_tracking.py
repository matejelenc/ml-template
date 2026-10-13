"""W&B tracking, tested against a fake wandb module. Nothing is uploaded."""

import json
import sys
import types

import pytest
from omegaconf import OmegaConf

from expkit import record, tracking


class FakeWandbRun:
    url = "https://wandb.ai/me/project/runs/abc"

    def __init__(self):
        self.logged, self.defined, self.finished, self.fail = [], {}, False, False

    def log(self, metrics):
        if self.fail:
            raise RuntimeError("connection lost")
        self.logged.append(metrics)

    def define_metric(self, name, step_metric=None):
        self.defined[name] = step_metric

    def finish(self):
        self.finished = True


@pytest.fixture
def fake_wandb(monkeypatch):
    """Replace the wandb module. fake.init_args holds what wandb.init was called with."""
    fake = types.ModuleType("wandb")
    fake.run, fake.init_args = FakeWandbRun(), None

    def init(**kwargs):
        fake.init_args = kwargs
        return fake.run

    fake.init = init
    monkeypatch.setitem(sys.modules, "wandb", fake)
    return fake


def make_cfg(tmp_path, mode="online", **extra):
    return OmegaConf.create(
        {
            "experiment_id": "001-toy",
            "run_id": "20260101-120000-abcd",
            "paths": {"run_dir": str(tmp_path / "run")},
            "wandb": {"mode": mode, "project": "my-project", "entity": None},
            **extra,
        }
    )


def wandb_url(run):
    return json.loads((run.dir / "run.json").read_text())["wandb_url"]


def test_start_passes_identity_and_records_the_url(tmp_path, fake_wandb):
    cfg = make_cfg(tmp_path)
    run = record.start(cfg)
    tracking.start(cfg, run)
    args = fake_wandb.init_args
    assert args["project"] == "my-project" and args["mode"] == "online"
    assert args["id"] == "20260101-120000-abcd" and args["group"] == "001-toy"
    assert args["dir"] == str(run.dir)
    assert wandb_url(run) == FakeWandbRun.url


def test_config_sent_to_wandb_is_redacted(tmp_path, fake_wandb, monkeypatch):
    monkeypatch.setenv("SECRETS", "HF_TOKEN")
    monkeypatch.setenv("HF_TOKEN", "hf-abcdef")
    cfg = make_cfg(tmp_path, hf_token="hf-abcdef")
    tracking.start(cfg, record.start(cfg))
    assert fake_wandb.init_args["config"]["hf_token"] == "<redacted>"


def test_log_and_finish_reach_wandb(tmp_path, fake_wandb):
    cfg = make_cfg(tmp_path)
    run = record.start(cfg)
    tracking.start(cfg, run)
    run.monitor(step=10, loss=0.5)
    run.finish(metrics={"loss": 0.1})
    assert fake_wandb.run.logged == [{"step": 10, "loss": 0.5}, {"final/loss": 0.1}]
    assert fake_wandb.run.defined == {"loss": "step"}
    assert fake_wandb.run.finished


def test_each_series_has_its_own_step_counter_in_wandb(tmp_path, fake_wandb):
    cfg = make_cfg(tmp_path)
    run = record.start(cfg)
    tracking.start(cfg, run)
    run.monitor(step=5, series="fold_0", loss=0.5)
    run.monitor(step=0, series="fold_1", loss=0.9, acc=0.1)  # a lower step than before
    run.monitor(step=1, series="fold_1", loss=0.8, acc=0.2)
    assert fake_wandb.run.logged == [
        {"fold_0/step": 5, "fold_0/loss": 0.5},
        {"fold_1/step": 0, "fold_1/loss": 0.9, "fold_1/acc": 0.1},
        {"fold_1/step": 1, "fold_1/loss": 0.8, "fold_1/acc": 0.2},
    ]
    assert fake_wandb.run.defined == {
        "fold_0/loss": "fold_0/step",
        "fold_1/loss": "fold_1/step",
        "fold_1/acc": "fold_1/step",
    }


def test_disabled_mode_never_touches_wandb(tmp_path, fake_wandb):
    cfg = make_cfg(tmp_path, mode="disabled")
    run = record.start(cfg)
    assert tracking.start(cfg, run) is None
    run.monitor(step=1, loss=0.5)
    assert fake_wandb.init_args is None and wandb_url(run) is None


def test_offline_mode_records_no_url(tmp_path, fake_wandb):
    cfg = make_cfg(tmp_path, mode="offline")
    run = record.start(cfg)
    tracking.start(cfg, run)
    assert fake_wandb.init_args["mode"] == "offline" and wandb_url(run) is None


def test_failed_start_does_not_stop_the_run(tmp_path, fake_wandb):
    def broken_init(**kwargs):
        raise RuntimeError("no internet")

    fake_wandb.init = broken_init
    cfg = make_cfg(tmp_path)
    run = record.start(cfg)
    assert tracking.start(cfg, run) is None
    run.monitor(step=1, loss=0.5)
    run.finish(metrics={"loss": 0.5})
    assert (run.dir / "summary.json").is_file()


def test_failure_during_training_does_not_stop_the_run(tmp_path, fake_wandb):
    cfg = make_cfg(tmp_path)
    run = record.start(cfg)
    tracking.start(cfg, run)
    fake_wandb.run.fail = True
    run.monitor(step=1, loss=0.5)
    run.monitor(step=2, loss=0.4)
    run.finish(metrics={"loss": 0.4})
    assert len((run.monitor_dir / "main.jsonl").read_text().splitlines()) == 2
    assert (run.dir / "summary.json").is_file()
