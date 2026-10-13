"""Journal export: turn a finished run into LaTeX and push it to the Overleaf project.

What is written, relative to the top folder of the Overleaf project:

    generated/macros.sty, styles/      overwritten on every export
    generated/<experiment_id>/         overwritten on every export: entry.tex and the files
                                       from the run's journal/ folder
    journal.tex                        a stub is added ONCE per experiment, below the entry
                                       of the day; nothing else is changed

Everything else in the Overleaf project (main.tex with the paper, reports) belongs to you
and is never touched.

    journal.export(run_dir)                  # push to Overleaf
    journal.export(run_dir, out="folder")    # write to a local folder instead (manual upload)
"""

from __future__ import annotations

import csv
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
from typing import Any, List, Optional, Tuple, Union

from expkit import __version__, gitutil

log = logging.getLogger(__name__)

PathLike = Union[str, Path]

# What the export picks up from the journal/ folder of a run.
FIGURE_TYPES = (".pdf", ".png", ".jpg", ".jpeg")
TABLE_TYPE = ".csv"  # typeset as a table
TEX_TYPE = ".tex"  # included as it is
# Size guard: the Overleaf project holds plots, tables and short text only.
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ENTRY_BYTES = 10 * 1024 * 1024
MAX_TABLE_ROWS = 50
MAX_TABLE_COLUMNS = 12
# Longer values are cut in the entry.
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
    """A metric value as short, LaTeX-safe text."""
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


# --- Rendering ------------------------------------------------------------------------

def _export_name(path: Path, journal_dir: Path) -> str:
    """A file name that is safe in LaTeX: "plots/val loss.pdf" becomes "plots-val-loss.pdf"."""
    stem = "-".join(path.relative_to(journal_dir).with_suffix("").parts)
    return re.sub(r"[^A-Za-z0-9-]+", "-", stem).strip("-") + path.suffix.lower()


def _choose_files(run_dir: Path) -> Tuple[List[Tuple[Path, str]], List[Tuple[str, str]]]:
    """Files of journal/ to export as (source, new name), and skipped ones as (name, reason).

    Sorted by path, so file names decide the order in the entry.
    """
    journal_dir = run_dir / "journal"
    chosen, skipped, total = [], [], 0
    for path in sorted(journal_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (*FIGURE_TYPES, TABLE_TYPE, TEX_TYPE):
            continue
        name, size = _export_name(path, journal_dir), path.stat().st_size
        if size > MAX_FILE_BYTES:
            skipped.append((path.name, f"larger than {MAX_FILE_BYTES // 1024 // 1024} MB"))
        elif total + size > MAX_ENTRY_BYTES:
            skipped.append((path.name, "entry size limit reached"))
        elif name == "entry.tex":
            skipped.append((path.name, "the name entry.tex is taken by the generated entry"))
        else:
            total += size
            chosen.append((path, name))
    return chosen, skipped


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def render_table(path: Path, caption: str) -> List[str]:
    """A .csv file as an exptable: the first row is the header, cells are kept as written.

    Raises ValueError with the reason if the file is not a small table.
    """
    try:
        with open(path, newline="", encoding="utf-8") as file:
            rows = [row for row in csv.reader(file) if any(cell.strip() for cell in row)]
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValueError("not a readable .csv file") from error
    if len(rows) < 2:
        raise ValueError("a table needs a header row and at least one more row")
    width = max(len(row) for row in rows)
    if len(rows) - 1 > MAX_TABLE_ROWS or width > MAX_TABLE_COLUMNS:
        raise ValueError(f"more than {MAX_TABLE_ROWS} rows or {MAX_TABLE_COLUMNS} columns")
    rows = [[cell.strip() for cell in row] + [""] * (width - len(row)) for row in rows]
    # Columns of numbers are right-aligned, the others left-aligned.
    columns = ""
    for index in range(width):
        cells = [row[index] for row in rows[1:] if row[index]]
        columns += "r" if cells and all(_is_number(cell) for cell in cells) else "l"
    lines = ["\\begin{exptable}{%s}{%s}" % (columns, tex_escape(caption))]
    lines.append("\\exphead{%s}" % " & ".join(tex_escape(cell) for cell in rows[0]))
    lines += ["\\exprow{%s}" % " & ".join(tex_escape(cell) for cell in row) for row in rows[1:]]
    lines.append("\\end{exptable}")
    return lines


def render_entry(run_dir: Path, files: List[Tuple[Path, str]],
                 skipped: List[Tuple[str, str]]) -> str:
    """The text of entry.tex: facts, then results, each as macro calls. macros.sty does the layout.

    `files` are the chosen files of journal/ as (source, name in the export).
    """
    info = json.loads((run_dir / "run.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())
    experiment_id, git = info["experiment_id"], info["git"]
    skipped = list(skipped)

    lines = [
        f"% Generated by expkit {__version__} from run {info['run_id']}.",
        "% Do not edit: this file is overwritten on every export.",
        "\\begin{expinfo}",
        "\\expcode{Run}{%s}" % tex_escape(info["run_id"]),
        "\\expcode{Code}{%s at %s}" % (tex_escape(git["tag"] or "no tag"),
                                       tex_escape((git["sha"] or "unknown")[:10])),
        "\\expfact{Started}{%s on %s}" % (tex_escape(info["started_at"][:10]),
                                          tex_escape(info["environment"]["hostname"])),
        "\\expfact{Duration}{%s}" % tex_escape(format_duration(summary["duration_seconds"])),
    ]
    if info.get("wandb_url"):
        lines.append("\\expwandb{%s}" % info["wandb_url"])
    if git["dirty"]:
        lines.append("\\expdirty")
    lines.append("\\end{expinfo}")

    if summary["metrics"]:
        lines.append("\\begin{expmetrics}")
        lines += ["\\expmetric{%s}{%s}" % (tex_escape(name), format_value(value))
                  for name, value in summary["metrics"].items()]
        lines.append("\\end{expmetrics}")

    for source, name in files:
        suffix, caption = source.suffix.lower(), Path(name).stem
        if suffix == TABLE_TYPE:
            try:
                lines += render_table(source, caption)
            except ValueError as error:
                skipped.append((source.name, str(error)))
        elif suffix == TEX_TYPE:
            lines.append("\\exptex{generated/%s/%s}" % (experiment_id, Path(name).stem))
        else:
            lines.append("\\expfigure{generated/%s/%s}{%s}" % (experiment_id, name, tex_escape(caption)))
    for name, reason in skipped:
        lines.append("\\expskipped{%s}{%s}" % (tex_escape(name), tex_escape(reason)))
    return "\n".join(lines) + "\n"


def stub(experiment_id: str) -> str:
    """The lines added once to journal.tex. The first line is the marker.

    Order: heading, generated facts and results, then the notes written by hand.
    """
    return (
        f"\n% exp:{experiment_id}\n"
        f"\\experiment{{{tex_escape(experiment_id)}}}\n"
        f"\\input{{generated/{experiment_id}/entry}}\n"
        "\\about{}\n"
        "\\relevance{}\n"
        "\\hypothesis{}\n"
        "\\conclusion{}\n"
    )


# The journal skeleton that ships with the repository, used if journal.tex does not exist yet.
JOURNAL_TEMPLATE = Path(__file__).resolve().parents[2] / "overleaf_template" / "journal.tex"
_END_DOCUMENT = "\\end{document}"


def _entry_start(text: str, date: str) -> Optional[re.Match]:
    """Where the entry of a day starts: the line "\\entry{2026-10-13}"."""
    return re.search(rf"^[ \t]*\\entry\{{{re.escape(date)}\}}", text, flags=re.MULTILINE)


def _add_stub(journal: Path, experiment_id: str, date: str) -> None:
    """Add the stub to journal.tex, below the entry of `date`, unless its marker is there.

    With an entry of that day, the stub goes to the end of it. Without one, a new entry is
    started at the end of the document. Nothing else in the file is changed.
    """
    if journal.is_file():
        text = journal.read_text()
    elif JOURNAL_TEMPLATE.is_file():
        text = JOURNAL_TEMPLATE.read_text()
    else:
        raise FileNotFoundError(f"{journal} does not exist and {JOURNAL_TEMPLATE} is missing too")
    if re.search(rf"^% exp:{re.escape(experiment_id)}\s*$", text, flags=re.MULTILINE):
        return
    # The end of the document: just above the last \end{document}, or the end of the file.
    position = text.rfind(_END_DOCUMENT)
    position = len(text) if position < 0 else position
    addition = stub(experiment_id)
    today = _entry_start(text, date)
    if today:
        # The end of that day: the next \entry line, if there is one.
        following = re.search(r"^[ \t]*\\entry\{", text[today.end():], flags=re.MULTILINE)
        if following:
            position = today.end() + following.start()
    else:
        addition = f"\n\\entry{{{date}}}\n" + addition
    before, after = text[:position], text[position:]
    if before and not before.endswith("\n"):
        before += "\n"
    journal.write_text(before + addition + ("\n" + after if after else ""))


def write_macros(root: Path) -> None:
    """Write generated/macros.sty and generated/styles/ from the copies that ship with expkit."""
    templates = resources.files("expkit").joinpath("templates")
    (root / "generated" / "styles").mkdir(parents=True, exist_ok=True)
    (root / "generated" / "macros.sty").write_text(templates.joinpath("macros.sty").read_text())
    for style in templates.joinpath("styles").iterdir():
        if style.name.endswith(".sty"):
            (root / "generated" / "styles" / style.name).write_text(style.read_text())


def write_entry(run_dir: Path, root: Path, date: Optional[str] = None) -> str:
    """Write macros, the generated entry and the journal stub below `root`.

    `root` is the Overleaf clone, or any folder when exporting for manual upload.
    `date` is the day whose entry gets a new stub, e.g. "2026-10-13" (default: today).
    Returns the experiment ID.
    """
    experiment_id = json.loads((run_dir / "run.json").read_text())["experiment_id"]
    files, skipped = _choose_files(run_dir)
    write_macros(root)
    dest = root / "generated" / experiment_id
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    for source, name in files:
        if source.suffix.lower() != TABLE_TYPE:  # tables are written into entry.tex
            shutil.copyfile(source, dest / name)
    (dest / "entry.tex").write_text(render_entry(run_dir, files, skipped))
    _add_stub(root / "journal.tex", experiment_id, date or time.strftime("%Y-%m-%d"))
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
