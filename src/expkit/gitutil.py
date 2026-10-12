"""Git helpers. Every function returns None instead of raising when git is unavailable."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional, Union

PathLike = Union[str, Path]


def git(*args: str, cwd: Optional[PathLike] = None) -> Optional[str]:
    """Run a git command and return its output, or None if it failed."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def repo_root(cwd: Optional[PathLike] = None) -> Optional[Path]:
    """Top folder of the git repository, or None outside a repository."""
    root = git("rev-parse", "--show-toplevel", cwd=cwd)
    return Path(root) if root else None


def experiment_tag(experiment_id: str) -> str:
    """Tag name for an experiment, e.g. "exp/012-lora"."""
    return f"exp/{experiment_id}"


def info(experiment_id: str, cwd: Optional[PathLike] = None) -> dict:
    """Which code a run used: commit, experiment tag, repository URL, uncommitted changes."""
    status = git("status", "--porcelain", cwd=cwd)
    # The tag counts only if it sits on the commit that is running.
    tag = git("tag", "--points-at", "HEAD", "--list", experiment_tag(experiment_id), cwd=cwd)
    url = git("remote", "get-url", "origin", cwd=cwd)
    return {
        "sha": git("rev-parse", "HEAD", cwd=cwd),
        "tag": tag or None,
        # Drop a user name or token written into the URL (https://user:token@host/...).
        "repo_url": re.sub(r"//[^@/]+@", "//", url) if url else None,
        "dirty": None if status is None else bool(status),
    }
