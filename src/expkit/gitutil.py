"""Git helpers. Nothing here raises when git is unavailable: the values are None instead."""

import re
import subprocess
from pathlib import Path
from typing import Any

PathLike = str | Path


def git(*args: str, cwd: PathLike | None = None) -> str | None:
    """Run a git command.

    Args:
        *args: The arguments after "git", e.g. "rev-parse", "HEAD".
        cwd: Folder to run in. Default: the current folder.

    Returns:
        What the command printed, or None if it failed or git is not installed.
    """
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def repo_root(cwd: PathLike | None = None) -> Path | None:
    """Top folder of the git repository, or None outside a repository."""
    root = git("rev-parse", "--show-toplevel", cwd=cwd)
    return Path(root) if root else None


def experiment_tag(experiment_id: str) -> str:
    """Tag name for an experiment, e.g. "exp/012-lora"."""
    return f"exp/{experiment_id}"


def info(experiment_id: str, cwd: PathLike | None = None) -> dict[str, Any]:
    """Which code a run used.

    Args:
        experiment_id: The experiment, e.g. "012-lora". Its tag is looked up.
        cwd: A folder inside the repository. Default: the current folder.

    Returns:
        A dict with "sha", "tag" (None unless the tag is on the running commit), "repo_url"
        and "dirty" (True with uncommitted changes). Every value is None outside a repository.
    """
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
