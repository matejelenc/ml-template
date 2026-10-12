"""Journal export: turn a finished run into LaTeX and push it to the Overleaf project.

What is written, relative to the top folder of the Overleaf project:

    generated/macros.sty               overwritten on every export
    generated/<experiment_id>/         overwritten on every export: entry.tex and figures
    journal.tex                        a stub is appended ONCE per experiment, nothing else

Everything else in the Overleaf project belongs to you and is never touched.

    journal.export(run_dir)                  # push to Overleaf
    journal.export(run_dir, out="folder")    # write to a local folder instead (manual upload)
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import random
import re
import shutil
import subprocess
import time
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from expkit import __version__, gitutil
from expkit.record import NOT_SETTINGS

log = logging.getLogger(__name__)

PathLike = Union[str, Path]

# Size guard: the Overleaf project holds plots, tables and short text only.
FIGURE_TYPES = (".pdf", ".png", ".jpg", ".jpeg")
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ENTRY_BYTES = 10 * 1024 * 1024
# Longer config values are cut in the entry. The full value stays in config.resolved.yaml.
MAX_VALUE_LENGTH = 60

PUSH_ATTEMPTS = 5
# Wait between attempts, multiplied by a random factor so two jobs do not retry in step.
RETRY_WAIT_SECONDS = 2.0
GIT_TIMEOUT_SECONDS = 120


# --- LaTeX text helpers ---------------------------------------------------------

_TEX_SPECIAL = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def tex_escape(text: Any) -> str:
    """Make any text safe to place in LaTeX, e.g. "train_loss" becomes "train\\_loss"."""
    return "".join(_TEX_SPECIAL.get(char, char) for char in str(text))


def format_value(value: Any) -> str:
    """A config or metric value as short, LaTeX-safe text."""
    if isinstance(value, float):
        text = f"{value:.4g}"
    elif isinstance(value, (dict, list)):
        text = json.dumps(value)
    else:
        text = str(value)
    if len(text) > MAX_VALUE_LENGTH:
        text = text[: MAX_VALUE_LENGTH - 3] + "..."
    return tex_escape(text)


def format_duration(seconds: float) -> str:
    """Seconds as "1h 02m", "3m 05s" or "12 s"."""
    seconds = int(round(seconds))
    hours, minutes, secs = seconds // 3600, seconds % 3600 // 60, seconds % 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs} s"


# --- Reading a run folder -----------------------------------------------------------

def _read_config(path: Path) -> Optional[dict]:
    return yaml.safe_load(path.read_text())["config"] if path.is_file() else None


def find_run(experiment_id: str, run_id: Optional[str] = None,
             runs_dir: Optional[PathLike] = None) -> Path:
    """Folder of a finished run: the given run, or the newest one of the experiment."""
    experiment_dir = Path(runs_dir or os.environ.get("RUNS_DIR") or "runs") / experiment_id
    if run_id:
        candidates = [experiment_dir / run_id]
    else:
        # Run IDs start with the time, so sorting by name sorts by time.
        candidates = sorted(experiment_dir.glob("*"), reverse=True)
    for run_dir in candidates:
        if (run_dir / "summary.json").is_file():
            return run_dir
    raise FileNotFoundError(f"No finished run (with summary.json) found in {experiment_dir}")


# --- Config diff --------------------------------------------------------------------

_ABSENT = object()


def _flatten(config: dict, prefix: str = "") -> Dict[str, Any]:
    """{"train": {"lr": 0.1}} becomes {"train.lr": 0.1}."""
    flat: Dict[str, Any] = {}
    for key, value in config.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            flat.update(_flatten(value, name + "."))
        else:
            flat[name] = value
    return flat


def config_diff(base: dict, config: dict) -> List[Tuple[str, Any, Any]]:
    """Settings that differ from the base config, as (name, base value, run value).

    A setting missing on one side has the value None there and is shown as a dash.
    Keys that are not experiment settings (run ID, paths, W&B) are left out.
    """
    flat_base = _flatten({k: v for k, v in base.items() if k not in NOT_SETTINGS})
    flat_run = _flatten({k: v for k, v in config.items() if k not in NOT_SETTINGS})
    rows = []
    for name in sorted(set(flat_base) | set(flat_run)):
        before, after = flat_base.get(name, _ABSENT), flat_run.get(name, _ABSENT)
        if before != after:
            rows.append((name, before, after))
    return rows


def _diff_cell(value: Any) -> str:
    return "---" if value is _ABSENT else format_value(value)


# --- Rendering ------------------------------------------------------------------------

def _figure_name(path: Path, artifacts_dir: Path) -> str:
    """A file name that is safe in LaTeX: "plots/val loss.pdf" becomes "plots-val-loss.pdf"."""
    stem = "-".join(path.relative_to(artifacts_dir).with_suffix("").parts)
    return re.sub(r"[^A-Za-z0-9-]+", "-", stem).strip("-") + path.suffix.lower()


def _choose_figures(run_dir: Path) -> Tuple[List[Tuple[Path, str]], List[Tuple[str, str]]]:
    """Figures to copy as (source, new name), and skipped ones as (name, reason)."""
    artifacts_dir = run_dir / "artifacts"
    chosen, skipped, total = [], [], 0
    for path in sorted(artifacts_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in FIGURE_TYPES:
            continue
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            skipped.append((path.name, f"larger than {MAX_FILE_BYTES // 1024 // 1024} MB"))
        elif total + size > MAX_ENTRY_BYTES:
            skipped.append((path.name, "entry size limit reached"))
        else:
            total += size
            chosen.append((path, _figure_name(path, artifacts_dir)))
    return chosen, skipped


def render_entry(run_dir: Path, figures: List[str], skipped: List[Tuple[str, str]]) -> str:
    """The text of entry.tex: facts only, each as one macro call. macros.sty does the layout."""
    info = json.loads((run_dir / "run.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())
    config = _read_config(run_dir / "config.resolved.yaml") or {}
    base = _read_config(run_dir / "config.base.yaml")
    experiment_id, git = info["experiment_id"], info["git"]

    lines = [
        f"% Generated by expkit {__version__} from run {info['run_id']}.",
        "% Do not edit: this file is overwritten on every export.",
        "\\expfacts{%s}{%s}{%s}{%s}{%s}{%s}" % (
            tex_escape(info["started_at"][:10]),
            tex_escape(info["run_id"]),
            tex_escape(git["tag"] or "no tag"),
            tex_escape((git["sha"] or "unknown")[:10]),
            tex_escape(info["environment"]["hostname"]),
            tex_escape(format_duration(summary["duration_seconds"])),
        ),
    ]
    if git["dirty"]:
        lines.append("\\expdirty")
    if info.get("wandb_url"):
        lines.append("\\expwandb{%s}" % info["wandb_url"])

    if base is None:
        lines.append("\\expnobaseline")
    else:
        changes = config_diff(base, config)
        if changes:
            lines.append("\\begin{expconfig}")
            lines += ["\\expchange{%s}{%s}{%s}" % (tex_escape(name), _diff_cell(a), _diff_cell(b))
                      for name, a, b in changes]
            lines.append("\\end{expconfig}")
        else:
            lines.append("\\expnochanges")

    if summary["metrics"]:
        lines.append("\\begin{expmetrics}")
        lines += ["\\expmetric{%s}{%s}" % (tex_escape(name), format_value(value))
                  for name, value in summary["metrics"].items()]
        lines.append("\\end{expmetrics}")

    for name in figures:
        lines.append("\\expfigure{generated/%s/%s}{%s}" % (experiment_id, name, tex_escape(name)))
    for name, reason in skipped:
        lines.append("\\expskipped{%s}{%s}" % (tex_escape(name), tex_escape(reason)))
    return "\n".join(lines) + "\n"


def stub(experiment_id: str) -> str:
    """The lines appended once to journal.tex. The first line is the marker."""
    return (
        f"\n% exp:{experiment_id}\n"
        f"\\experiment{{{tex_escape(experiment_id)}}}\n"
        "\\hypothesis{}\n"
        f"\\input{{generated/{experiment_id}/entry}}\n"
        "\\conclusion{}\n"
    )


def _add_stub(journal: Path, experiment_id: str) -> None:
    """Append the stub to journal.tex unless its marker is already there."""
    text = journal.read_text() if journal.is_file() else "% Journal. See README.md.\n"
    if re.search(rf"^% exp:{re.escape(experiment_id)}\s*$", text, flags=re.MULTILINE):
        return
    if text and not text.endswith("\n"):
        text += "\n"
    journal.write_text(text + stub(experiment_id))


def write_macros(root: Path) -> None:
    """Write generated/macros.sty from the copy that ships with expkit."""
    (root / "generated").mkdir(parents=True, exist_ok=True)
    source = resources.files("expkit").joinpath("templates/macros.sty").read_text()
    (root / "generated" / "macros.sty").write_text(source)


def write_entry(run_dir: Path, root: Path) -> str:
    """Write macros, the generated entry and the journal stub below `root`.

    `root` is the Overleaf clone, or any folder when exporting for manual upload.
    Returns the experiment ID.
    """
    experiment_id = json.loads((run_dir / "run.json").read_text())["experiment_id"]
    figures, skipped = _choose_figures(run_dir)
    write_macros(root)
    dest = root / "generated" / experiment_id
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    for source, name in figures:
        shutil.copyfile(source, dest / name)
    entry = render_entry(run_dir, [name for _, name in figures], skipped)
    (dest / "entry.tex").write_text(entry)
    _add_stub(root / "journal.tex", experiment_id)
    return experiment_id


# --- Sync with Overleaf ---------------------------------------------------------------

class SyncError(RuntimeError):
    """The export could not be pushed. The run itself is unaffected."""


# Git asks this helper for the password. It answers with OVERLEAF_TOKEN from the environment,
# so the token is never stored in a git config, a URL or a credentials file.
_CREDENTIAL_HELPER = (
    '!f() { test "$1" = get && echo username=git && echo "password=$OVERLEAF_TOKEN"; }; f'
)


def _git(repo: Optional[Path], *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run git for the Overleaf clone: never asks questions, never hangs forever."""
    command = [
        "git",
        "-c", "credential.helper=",  # ignore other helpers
        "-c", f"credential.helper={_CREDENTIAL_HELPER}",
        "-c", "user.name=expkit",
        "-c", "user.email=expkit@localhost",
        *args,
    ]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        result = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True,
                                timeout=GIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise SyncError(f"git {args[0]} timed out after {GIT_TIMEOUT_SECONDS} s") from error
    if check and result.returncode != 0:
        raise SyncError(f"git {args[0]} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result


def overleaf_dir() -> Path:
    """The Overleaf clone: OVERLEAF_DIR, or overleaf/ in the top folder of the repository."""
    if os.environ.get("OVERLEAF_DIR"):
        return Path(os.environ["OVERLEAF_DIR"])
    return (gitutil.repo_root() or Path.cwd()) / "overleaf"


def _ensure_clone(repo: Path) -> None:
    """Clone the Overleaf project if this server does not have it yet."""
    if (repo / ".git").exists():
        return
    url = os.environ.get("OVERLEAF_GIT_URL")
    if not url:
        raise SyncError(f"{repo} is missing and OVERLEAF_GIT_URL is not set, so it cannot be cloned")
    _git(None, "clone", url, str(repo))


def sync(run_dir: PathLike, repo: Optional[PathLike] = None, _before_push=None) -> str:
    """Write the entry into the Overleaf clone and push it.

    Returns "pushed" or "unchanged". Raises SyncError if it cannot be pushed.

    Each attempt starts from the newest state of the Overleaf project (you may have edited it
    in the browser). If the push is rejected because someone pushed in between, the local
    commit is dropped and the whole step is repeated. The export only ever adds its own
    files, so nothing of yours is merged or overwritten.
    """
    run_dir = Path(run_dir)
    repo = Path(repo) if repo else overleaf_dir()
    repo.parent.mkdir(parents=True, exist_ok=True)
    # One export at a time per clone: two jobs can finish in the same second.
    with open(repo.with_name(repo.name + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _ensure_clone(repo)
        if _git(repo, "status", "--porcelain").stdout.strip():
            raise SyncError(
                f"{repo} has local changes. Edit the journal in Overleaf, not in this folder. "
                f"Check with: git -C {repo} status"
            )
        for attempt in range(1, PUSH_ATTEMPTS + 1):
            _git(repo, "pull", "--rebase")
            try:
                experiment_id = write_entry(run_dir, repo)
                _git(repo, "add", "generated", "journal.tex")
                if _git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
                    return "unchanged"
                _git(repo, "commit", "-m", f"journal: {experiment_id}")
            except BaseException:
                # Leave the clone as it was. Everything changed at this point is ours.
                _git(repo, "reset", "--hard", "HEAD", check=False)
                _git(repo, "clean", "-fd", "generated", check=False)
                raise
            if _before_push:  # used by tests to simulate a push from elsewhere
                _before_push()
            push = _git(repo, "push", "origin", "HEAD", check=False)
            if push.returncode == 0:
                return "pushed"
            # Drop our commit and start again from the newest remote state.
            _git(repo, "reset", "--hard", "HEAD~1")
            log.info("Overleaf push rejected (attempt %d of %d): %s",
                     attempt, PUSH_ATTEMPTS, push.stderr.strip())
            if attempt < PUSH_ATTEMPTS:
                time.sleep(RETRY_WAIT_SECONDS * random.random())
        raise SyncError(f"push to Overleaf failed {PUSH_ATTEMPTS} times: {push.stderr.strip()}")


# --- Entry points ---------------------------------------------------------------------

def export(run_dir: PathLike, out: Optional[PathLike] = None) -> str:
    """Export one finished run. With `out`, write to that folder and push nothing."""
    run_dir = Path(run_dir)
    if out is not None:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        write_entry(run_dir, out)
        return f"written to {out}"
    return sync(run_dir)


def export_at_job_end(run_dir: PathLike) -> None:
    """Export at the end of a job. Never raises: a journal problem must not fail a run."""
    try:
        log.info("Journal export: %s", export(run_dir))
    except Exception as error:  # noqa: BLE001 - see docstring
        experiment_id = Path(run_dir).parent.name
        log.warning("Journal export failed: %s", error)
        log.warning("Retry later with: make journal EXP=%s", experiment_id)
