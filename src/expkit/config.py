"""Small helpers used by the Hydra config."""

from __future__ import annotations

import os
import secrets
import time
from typing import Any, Optional

from hydra.core.hydra_config import HydraConfig
from omegaconf import OmegaConf

# Run folder name for runs started without an experiment file (quick debugging runs).
SCRATCH = "scratch"

# The run ID is made once per process, so every place in the config sees the same value.
_run_id: Optional[str] = None


def new_run_id() -> str:
    """Local start time plus four random characters, e.g. "20261012-195950-a3f1".

    Sorts by time, and two runs started in the same second still differ.
    """
    return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def _get_run_id() -> str:
    """The RUN_ID environment variable if set (the launcher sets it), else a new ID."""
    global _run_id
    if _run_id is None:
        _run_id = os.environ.get("RUN_ID") or new_run_id()
    return _run_id


def _experiment_id() -> str:
    """Name of the chosen experiment file, e.g. "001-toy", or "scratch" if none was chosen."""
    return HydraConfig.get().runtime.choices.get("experiment") or SCRATCH


def _env(name: str, default: Any = None) -> Any:
    """An environment variable, or the default if it is unset or empty.

    Unlike Hydra's own ${oc.env:...}, an empty line such as "RUNS_DIR=" in .env counts as unset.
    """
    return os.environ.get(name) or default


def register_resolvers() -> None:
    """Make ${experiment_id:}, ${run_id:} and ${env:NAME,default} usable in the config.

    Call this before @hydra.main runs.
    """
    OmegaConf.register_new_resolver("env", _env, replace=True)
    OmegaConf.register_new_resolver("experiment_id", _experiment_id, replace=True)
    OmegaConf.register_new_resolver("run_id", _get_run_id, replace=True)
