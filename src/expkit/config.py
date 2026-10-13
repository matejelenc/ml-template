"""Small helpers used by the Hydra config."""

import os
import secrets
import time
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, find_dotenv
from hydra.core.hydra_config import HydraConfig
from omegaconf import OmegaConf

from expkit import gitutil

# Run folder name for runs started without an experiment file (quick debugging runs).
SCRATCH = "scratch"

# The run ID is made once per process, so every place in the config sees the same value.
_run_id: str | None = None


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
    """Name of the chosen experiment file, e.g. "001-toy", or "scratch" if none was chosen.

    An experiment file in a subfolder, chosen with +experiment=vision/012-lora, has the
    ID "012-lora".
    """
    choice = HydraConfig.get().runtime.choices.get("experiment")
    return str(choice).split("/")[-1] if choice else SCRATCH


def load_env(path: str | Path | None = None) -> None:
    """Read .env into the environment. Call it first, before the config is built.

    A variable that is already set in the shell wins over .env. An empty line such as
    "WANDB_MODE=" counts as unset and is skipped: libraries such as W&B read their variables
    themselves and fail on an empty value.

    Args:
        path: The file to read. Default: the nearest .env in the current folder or above it.
    """
    for name, value in dotenv_values(path or find_dotenv(usecwd=True)).items():
        if value and name not in os.environ:
            os.environ[name] = value


def _env(name: str, default: Any = None) -> Any:
    """An environment variable, or the default if it is unset or empty.

    Unlike Hydra's own ${oc.env:...}, an empty line such as "RUNS_DIR=" in .env counts as unset.
    """
    return os.environ.get(name) or default


def env_path(name: str, default: str) -> str:
    """A folder named by an environment variable, as an absolute path.

    A relative folder is relative to the top folder of the repository, from whichever of
    its folders the command is run. Outside a repository it is relative to the current
    folder. The launchers (scripts/launch/common.sh) follow the same rule.

    Args:
        name: Name of the environment variable, e.g. "RUNS_DIR".
        default: Folder to use when the variable is unset or empty.

    Returns:
        The absolute path as text, because the Hydra config stores text.
    """
    path = Path(_env(name, default)).expanduser()
    return str(path if path.is_absolute() else (gitutil.repo_root() or Path.cwd()) / path)


def runs_dir() -> Path:
    """Where run folders are written: RUNS_DIR, or runs/ in the repository."""
    return Path(env_path("RUNS_DIR", "runs"))


def register_resolvers() -> None:
    """Make the resolvers of this project usable in the config.

    These are ${experiment_id:}, ${run_id:}, ${env:NAME,default} and ${path:NAME,default}.
    Call this before @hydra.main runs.
    """
    OmegaConf.register_new_resolver("env", _env, replace=True)
    OmegaConf.register_new_resolver("path", env_path, replace=True)
    OmegaConf.register_new_resolver("experiment_id", _experiment_id, replace=True)
    OmegaConf.register_new_resolver("run_id", _get_run_id, replace=True)
