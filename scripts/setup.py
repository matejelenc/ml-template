"""One-time setup of a project on a machine. Safe to run again: it keeps what is there.

    uv run python scripts/setup.py

It asks for the settings, writes them to .env (a copy of .env.example, readable only by you), clones the Overleaf
project into overleaf/ and adds the journal and report skeletons to it if they are missing.
Press Enter to keep a value shown in [brackets]. README.md lists the same steps by hand.
"""

import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

from expkit import journal

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
TEMPLATE_DIR = ROOT / "overleaf_template"

# (name in .env, question, is it a secret)
QUESTIONS = [
    ("WANDB_API_KEY", "W&B API key (wandb.ai/authorize)", True),
    ("WANDB_PROJECT", "W&B project name", False),
    ("OVERLEAF_GIT_URL", "Overleaf git URL (Menu > Git in the Overleaf project; empty to skip Overleaf)", False),
    ("OVERLEAF_TOKEN", "Overleaf git token (Account settings > Git integration)", True),
    ("RUNS_DIR", "Folder for run outputs on this machine (empty for runs/ in the repo)", False),
    ("DATA_DIR", "Folder with datasets on this machine (empty for data/ in the repo)", False),
    ("LAUNCH_PROFILE", "Default launcher settings, a file name in scripts/launch/servers/ without .sh (empty for none)", False),
]

# Stored in the Overleaf clone's own git config. Git runs it when it needs the password and
# it reads the token from .env, so the token exists in one file only.
CLONE_CREDENTIAL_HELPER = (
    '!f() { test "$1" = get || exit 0; echo username=git; '
    'echo "password=$(grep -m1 "^OVERLEAF_TOKEN=" "$(git rev-parse --show-toplevel)/../.env" '
    "| cut -d= -f2- | tr -d \"\\\"\\r'\")\"; }; f"
)


def read_env(path: Path) -> dict:
    """KEY=VALUE lines of .env as a dict. Comments and blank lines are ignored."""
    values = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                name, value = line.split("=", 1)
                values[name.strip()] = value.strip().strip("\"'")
    return values


def write_env(path: Path, values: dict, template: Path = ENV_EXAMPLE) -> None:
    """Update .env: change the given keys, keep every other line, permissions 600.

    A new .env starts as a copy of the template, so it has the same sections and comments.
    """
    source = path if path.is_file() else template
    lines = source.read_text().splitlines() if source.is_file() else []
    remaining = dict(values)
    for index, line in enumerate(lines):
        name = line.split("=", 1)[0].strip()
        if "=" in line and name in remaining:
            lines[index] = f"{name}={remaining.pop(name)}"
    lines += [f"{name}={value}" for name, value in remaining.items()]
    # Create the file with the right permissions from the start, so it is never readable
    # by others, not even for a moment.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def secrets_list(current: str) -> str:
    """The SECRETS line for .env: the names already listed plus the secrets asked for here."""
    names = [name.strip() for name in current.split(",") if name.strip()]
    names += [name for name, _, secret in QUESTIONS if secret and name not in names]
    return ",".join(names)


def ask(question: str, current: str, secret: bool) -> str:
    """Ask one question. Enter keeps the current value. Secrets are never shown."""
    shown = "keep current" if (secret and current) else current
    prompt = f"{question} [{shown}]: " if shown else f"{question}: "
    if secret and sys.stdin.isatty():
        answer = getpass.getpass(prompt)
    else:
        answer = input(prompt)
    return answer.strip() or current


def clean_overleaf_url(url: str) -> str:
    """Accept the whole line Overleaf shows: "git clone https://git@git.overleaf.com/<id> <folder>"."""
    parts = url.split()
    if parts[:2] == ["git", "clone"] and len(parts) > 2:
        return parts[2]
    return url.strip()


def setup_overleaf(values: dict) -> None:
    """Clone the Overleaf project and add the skeleton files that are missing."""
    if not values.get("OVERLEAF_GIT_URL"):
        print("Overleaf: skipped (no git URL). Journal entries can still be written to a folder:")
        print("  make journal EXP=<experiment> OUT=<folder>")
        return
    os.environ["OVERLEAF_GIT_URL"] = values["OVERLEAF_GIT_URL"]
    os.environ["OVERLEAF_TOKEN"] = values.get("OVERLEAF_TOKEN", "")
    clone = ROOT / "overleaf"

    journal._ensure_clone(clone)
    subprocess.run(["git", "config", "--local", "--replace-all", "credential.helper", ""],
                   cwd=clone, check=True)
    subprocess.run(["git", "config", "--local", "--add", "credential.helper", CLONE_CREDENTIAL_HELPER],
                   cwd=clone, check=True)
    if journal._git(clone, "status", "--porcelain").stdout.strip():
        print(f"Overleaf: {clone} has local changes, left as it is. Check: git -C overleaf status")
        return
    journal._git(clone, "pull", "--rebase")

    # Add skeletons only where no file exists. main.tex (the paper) is never touched.
    added = []
    for source in sorted(TEMPLATE_DIR.glob("*")):
        if source.is_file() and not (clone / source.name).exists():
            shutil.copyfile(source, clone / source.name)
            added.append(source.name)
    journal.write_macros(clone)
    journal._git(clone, "add", "generated", *added)
    if journal._git(clone, "diff", "--cached", "--quiet", check=False).returncode == 0:
        print("Overleaf: clone is ready, nothing to add.")
        return
    journal._git(clone, "commit", "-m", "Add journal and report skeletons")
    journal._git(clone, "push", "origin", "HEAD")
    print(f"Overleaf: pushed {', '.join(added + ['generated/'])}.")


def main() -> int:
    print(f"Setting up {ROOT}\n")
    current = read_env(ENV_FILE)
    defaults = {"WANDB_PROJECT": ROOT.name}
    # Names of the variables that expkit.redact removes from everything it writes.
    values = {"SECRETS": secrets_list(current.get("SECRETS", ""))}
    for name, question, secret in QUESTIONS:
        values[name] = ask(question, current.get(name) or defaults.get(name, ""), secret)
    values["OVERLEAF_GIT_URL"] = clean_overleaf_url(values["OVERLEAF_GIT_URL"])
    write_env(ENV_FILE, values)
    print(f"\nWrote {ENV_FILE} (permissions 600).")

    try:
        setup_overleaf(values)
    except journal.SyncError as error:
        print(f"Overleaf: failed: {error}", file=sys.stderr)
        print("Fix the URL or token and run this script again. Everything else is set up.",
              file=sys.stderr)
        return 1
    print("\nDone. Try it: uv run python scripts/experiment.py wandb.mode=disabled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
