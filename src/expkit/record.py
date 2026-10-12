"""The run record: the files that document one run.

A run folder is $RUNS_DIR/<experiment_id>/<run_id>/ and contains:

    run.json               where the run came from (code, machine, command), written at start
    config.resolved.yaml   the final merged config, secrets redacted
    metrics.jsonl          one JSON object per line: {"step": 100, "loss": 0.42}
    summary.json           final metrics, weight files and artifacts, written at the end
    artifacts/             plots and tables (small)
    weights/               model weights (stay on the server)
    wandb/                 W&B's own files, only when W&B tracking is on

status.json and stdout.log are written by the launcher, not here.

Use it from training code like this:

    run = record.start(cfg)
    run.log(step=100, loss=0.42)
    run.finish(metrics={"loss": 0.01})
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shlex
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from omegaconf import DictConfig, OmegaConf

from expkit import gitutil
from expkit.redact import redact

log = logging.getLogger(__name__)

# Raise this number whenever a field is renamed, removed or changes meaning.
SCHEMA_VERSION = 1

# Config keys that differ between two runs of the same settings. Left out of config_sha256.
_NOT_SETTINGS = ("experiment_id", "run_id", "paths")


def utc_now() -> str:
    """Current time in UTC, e.g. "2026-10-12T18:00:30Z"."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    """SHA-256 of a file, read in chunks so large weight files do not fill the memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, data: dict) -> None:
    """Write JSON through a temporary file, so a crash never leaves a half-written file."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(temporary, path)


def config_hash(config: dict) -> str:
    """SHA-256 of the settings. Equal for two runs with the same settings, on any server."""
    settings = {key: value for key, value in config.items() if key not in _NOT_SETTINGS}
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def _gpu_info() -> dict:
    """GPU names, driver and CUDA version from nvidia-smi. Empty values without a GPU."""
    info: Dict[str, Any] = {"cuda": None, "gpu_driver": None, "gpus": []}
    try:
        query = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout
        header = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, check=True, timeout=30
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return info
    for line in query.strip().splitlines():
        name, _, driver = line.rpartition(",")
        info["gpus"].append(name.strip())
        info["gpu_driver"] = driver.strip()
    match = re.search(r"CUDA Version:\s*([\d.]+)", header)
    info["cuda"] = match.group(1) if match else None
    return info


def _environment() -> dict:
    """The machine and software the run used."""
    root = gitutil.repo_root() or Path.cwd()
    lockfile = root / "uv.lock"
    return {
        "hostname": socket.gethostname(),
        "python": platform.python_version(),
        "lockfile_sha256": sha256_file(lockfile) if lockfile.is_file() else None,
        **_gpu_info(),
    }


def _launch() -> dict:
    """How the run was started. Phase 6 launchers refine this."""
    if os.environ.get("SLURM_JOB_ID"):
        scheduler, job_id = "slurm", os.environ["SLURM_JOB_ID"]
    elif os.environ.get("TMUX"):
        scheduler, job_id = "tmux", None
    else:
        scheduler, job_id = "none", None
    return {"scheduler": scheduler, "job_id": job_id, "command": shlex.join(sys.argv)}


def _plain(value: Any) -> Any:
    """Turn a NumPy or PyTorch number into a plain Python number for JSON."""
    if hasattr(value, "item"):
        return value.item()
    return str(value)


class Run:
    """One run folder. Create it with record.start(cfg)."""

    def __init__(self, run_dir: Path):
        self.dir = run_dir
        self.weights_dir = run_dir / "weights"
        self.artifacts_dir = run_dir / "artifacts"
        # Set by tracking.start(). While it is None, nothing is sent to W&B.
        self.wandb: Any = None
        self._started = time.monotonic()

    def log(self, step: int, **metrics: Any) -> None:
        """Append one line to metrics.jsonl: run.log(step=100, loss=0.42).

        Also sends the metrics to W&B when tracking is on.
        """
        with open(self.dir / "metrics.jsonl", "a") as file:
            file.write(json.dumps({"step": step, **metrics}, default=_plain) + "\n")
        self._wandb("log", metrics, step=step)

    def update(self, **fields: Any) -> None:
        """Add or change fields in run.json, e.g. run.update(wandb_url=...)."""
        path = self.dir / "run.json"
        write_json(path, redact({**json.loads(path.read_text()), **fields}))

    def finish(self, metrics: Optional[Dict[str, Any]] = None) -> dict:
        """Write summary.json: final metrics, every file in weights/ and artifacts/.

        Also closes the W&B run when tracking is on.
        """
        summary = {
            "schema_version": SCHEMA_VERSION,
            "finished_at": utc_now(),
            "duration_seconds": round(time.monotonic() - self._started, 1),
            "metrics": json.loads(json.dumps(metrics or {}, default=_plain)),
            "weights": [
                {
                    "path": str(path.relative_to(self.dir)),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in _files(self.weights_dir)
            ],
            "artifacts": [str(path.relative_to(self.dir)) for path in _files(self.artifacts_dir)],
        }
        write_json(self.dir / "summary.json", summary)
        self._wandb("log", {f"final/{name}": value for name, value in summary["metrics"].items()})
        self._wandb("finish")
        return summary

    def _wandb(self, method: str, *args: Any, **kwargs: Any) -> None:
        """Call a method of the W&B run. A W&B error stops W&B tracking, never the training."""
        if self.wandb is None:
            return
        try:
            getattr(self.wandb, method)(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - any W&B failure is non-fatal
            log.warning("W&B failed, continuing without it: %s", error)
            self.wandb = None


def _files(folder: Path) -> List[Path]:
    """All files below a folder, sorted, so the listing is the same every time."""
    return sorted(path for path in folder.rglob("*") if path.is_file())


def start(cfg: DictConfig) -> Run:
    """Create the run folder and write run.json and config.resolved.yaml.

    Uses cfg.paths.run_dir, cfg.experiment_id and cfg.run_id from the base config.
    """
    run = Run(Path(cfg.paths.run_dir).resolve())
    run.weights_dir.mkdir(parents=True, exist_ok=True)
    run.artifacts_dir.mkdir(parents=True, exist_ok=True)

    config = redact(OmegaConf.to_container(cfg, resolve=True))
    with open(run.dir / "config.resolved.yaml", "w") as file:
        yaml.safe_dump({"schema_version": SCHEMA_VERSION, "config": config}, file, sort_keys=False)

    run_info = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": cfg.experiment_id,
        "run_id": cfg.run_id,
        "started_at": utc_now(),
        "run_dir": str(run.dir),
        "git": {
            **gitutil.info(cfg.experiment_id),
            # The launcher sets ALLOW_DIRTY=1 when started with --allow-dirty.
            "allow_dirty": os.environ.get("ALLOW_DIRTY") == "1",
        },
        "environment": _environment(),
        "launch": _launch(),
        "config_sha256": config_hash(config),
        "wandb_url": None,
    }
    write_json(run.dir / "run.json", redact(run_info))
    return run
