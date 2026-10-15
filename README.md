# ML research project template

A starting point for an ML research project: Hydra configs, a fixed record of every run,
W&B monitoring, launchers for tmux and Slurm, and journal entries pushed to Overleaf.

Every piece can be done by hand if the code breaks: the manual steps are listed below.

**Status:** the tmux launcher, W&B and the Overleaf journal are tested on a real server. The
Slurm launcher is tested only against a stand-in for `sbatch`, not yet on a real cluster.
Running from a git worktree of the tagged commit and dataset manifests are not built.

## Start a new project

1. Create the repository from this template and install:
   ```
   gh repo create my-project --private --template matejelenc/ml-template --clone
   cd my-project && uv sync
   ```
2. Create a blank project on Overleaf. `main.tex` there is your paper; the code never
   touches it. Copy the project's git URL (Menu > Git) and create a git token
   (Account settings > Git integration).
3. Run the setup and answer the questions:
   ```
   make setup
   ```
   It writes `.env` and adds `journal.tex`, `report.tex` and `generated/` (macros and
   styles) to the Overleaf project.
4. Check that it works: `uv run python scripts/experiment.py wandb.mode=disabled`

On every further server: `git clone`, `uv sync`, `make setup`.

### The same setup by hand

1. `cp .env.example .env && chmod 600 .env`, then fill in the values.
2. `git clone <overleaf git URL> overleaf` (user name `git`, password: the token).
3. Copy `overleaf_template/journal.tex` and `report.tex` into `overleaf/`, and
   `src/expkit/templates/macros.sty` and `styles/` into `overleaf/generated/`.
4. In `overleaf/`: `git add . && git commit -m "skeletons" && git push`.

## Run an experiment

1. Write code and commit it.
2. Add `conf/experiment/012-lora.yaml` with overrides only, and commit it:
   ```yaml
   # @package _global_
   # Purpose: one line on why this experiment exists (becomes the git tag message).
   train:
     lr: 0.1
   ```
3. Launch it. The command can be any script:
   ```
   scripts/launch/tmux.sh  scripts/experiment.py +experiment=012-lora
   scripts/launch/slurm.sh --profile hpc-gpu scripts/experiment.py +experiment=012-lora
   ```
   Add `--dry-run` to see what would happen without doing it.
4. Watch it in W&B, or with `make status` and `tail -f <run folder>/output.log`.
5. When it finishes, the run is in the Overleaf journal, below the entry of the day. Open
   `journal.tex` there and fill in `\about{}`, `\relevance{}`, `\hypothesis{}` and
   `\conclusion{}`. One left empty prints nothing.

A run without `+experiment=...` is a scratch run for debugging: it goes to `runs/scratch/`,
gets no tag and no journal entry. Without a launcher: `uv run python scripts/experiment.py ...`

### What a launch does

- Refuses uncommitted changes (`--allow-dirty` overrides and is recorded). A scratch run
  is not checked.
- Creates the annotated tag `exp/012-lora` on the current commit. One tag is one commit:
  after changing code, create the next experiment number.
- Creates the run folder, prints the job script and the submit command, and submits.
- Pushes the tag once the job is submitted. If tmux or Slurm refuses the job, nothing ran:
  the run folder is marked `failed` and a tag made by this launch is removed again, so the
  corrected launch can use the same number.
- The job gets the environment of the shell that launched it, so
  `CUDA_VISIBLE_DEVICES=1 scripts/launch/tmux.sh ...` runs on GPU 1. For this, each tmux job
  has a tmux server of its own: it does not appear in `tmux ls`. Use the commands the
  launcher prints, `tmux -L <run id> attach` and `tmux -L <run id> kill-session`.

One run is one setting. Hydra's multirun (`-m`) is refused, because all its jobs would write
to the same run folder: launch once per seed or value instead.

Slurm settings live in `scripts/launch/servers/<profile>.sh`: `#SBATCH` lines, then setup
commands such as `module load`. Override single flags with `--sbatch "--time=12:00:00"`.
Set a default profile with `LAUNCH_PROFILE` in `.env`.

## Where things are

```
conf/config.yaml              base config
conf/experiment/              one file per experiment, overrides only (NNN-slug.yaml)
scripts/experiment.py         example entry point: copy it for your own scripts
scripts/launch/               launchers, job wrapper, per-server settings
src/expkit/                   the bookkeeping library (record, tracking, journal)
tests/                        one folder per source folder, one file per module
CONTRIBUTING.md               ways of working: how code is written here
CLAUDE.md, .claude/           rules and settings for Claude Code (see below)
overleaf_template/            skeletons copied into the Overleaf project by the setup
overleaf/                     your clone of the Overleaf project (not in git)
```

A run folder is `$RUNS_DIR/<experiment>/<run id>/`:

| File | Content |
|---|---|
| `run.json` | written at the start: commit, tag, machine, command, W&B link |
| `status.json` | `queued`, `running`, `done`, `failed` or `cancelled`, with a heartbeat time |
| `config.yaml` | the final config, secrets redacted |
| `monitor/` | numbers logged during training, one JSON object per step; the local copy of what W&B gets. `main.jsonl`, plus one file per named series |
| `summary.json` | written at the end: final metrics, duration, weight files with size and SHA-256 |
| `output.log`, `job.sh` | everything the job printed, errors included, and the exact job script |
| `journal/` | what you select for the Overleaf journal: figures, tables and LaTeX files, subfolders included (see Overleaf below) |
| `eval/` | everything else from evaluation (predictions, statistics, further plots); organized as you like, never read by the code |
| `weights/` | model weights; they stay on the server |

`run.json` and `summary.json` are separate on purpose. `run.json` says where a run came from
and exists from the first second, so a crashed run still has it. `summary.json` says what
the run produced and exists only when the run finished: a run folder without it did not
finish, and the journal export skips it.

In your own script, the bookkeeping is four lines (see `scripts/experiment.py`):

```python
run = record.start(cfg)             # run.json, config.yaml
tracking.start(cfg, run)            # W&B
run.monitor(step=100, loss=0.42)        # monitor/main.jsonl and W&B
run.finish(metrics={"loss": 0.01})  # summary.json
```

An experiment that trains several models or folds in one run names a series per model:

```python
run.monitor(step=100, series="model_a/fold_0", loss=0.42)   # monitor/model_a/fold_0.jsonl
```

Each series counts its own steps and appears in W&B as `model_a/fold_0/loss`.
`run.finish(metrics=...)` is for a handful of headline numbers. Larger tables belong in
`journal/` or `eval/` as files.

### Text output

There is no logging method of its own. Use `print` or Python's `logging` as you like:
both launchers save all output of the job, tracebacks and library warnings included, in
`output.log`. The launchers set `PYTHONUNBUFFERED=1`, so what a job prints reaches the file
at once and is kept even when the job is cancelled. Under Slurm, `slurm.log` holds what was printed before the job started, for
example a failed `module load`. A bare `uv run python scripts/...` keeps no log file and
is meant for quick debugging.

## Commands

| Command | What it does |
|---|---|
| `make setup` | write `.env`, connect Overleaf |
| `make status` | list runs and their state; `lost` means the job died without notice |
| `make journal EXP=012-lora` | push the journal entry of the newest finished run again (`RUN=<run id>` for another one) |
| `make journal EXP=012-lora OUT=folder` | write the entry to a folder, to upload by hand |
| `make test` | run the tests |
| `make format` | format the code and apply safe automatic fixes |
| `make check` | run before a commit: formatting, lint rules, type hints, tests |
| `make docs` | build the reference pages of `src/` from the docstrings into `docs/api/` |

The tests mirror the code: `src/expkit/record.py` is tested in `tests/expkit/test_record.py`,
`scripts/setup.py` in `tests/scripts/test_setup.py`, `conf/` in `tests/conf/`. Tests for your
own package go in `tests/<package>/`. Run one part with `uv run pytest tests/<package>`.

Only `tests/scripts/test_experiment.py` depends on the example: delete it together with
`scripts/experiment.py`. All other tests run a stand-in script from `tests/fixtures/`, so
they keep passing when you replace the example, its experiment file and the `train`
settings with your own.

How to change the code (type hints, docstrings, tests, commits) is in
[CONTRIBUTING.md](CONTRIBUTING.md).

Useful overrides: `wandb.mode=disabled` or `offline`, `journal.export=false`.
After an offline run: `uv run wandb sync <run folder>/wandb/offline-run-*`.

## Overleaf

- `journal.tex` and each report are documents of their own. Open one in Overleaf to compile it.
  Both start with a title block: set `\project{}`, `\author{}` and `\supervisors{}` at the
  top of the file.
- The look comes from a style file, named at the top of each document:
  ```latex
  \usepackage[default]{generated/macros}
  ```
  The template ships one style, `default`. To make your own, copy
  `src/expkit/templates/styles/default.sty` to a new name in the same folder, change it, and
  use the new name as the option. A style defines the colours and the commands listed at
  the end of `macros.sty`; the macros you write in the documents stay the same. The next
  export copies the new file to Overleaf.
- The code writes only `generated/` and adds one stub per run to `journal.tex`.
  Everything else is yours.
- Edit in the browser, not in the local `overleaf/` folder: the export refuses to run when
  that folder has local changes.

### Journal

The journal is organized by day. An entry is a date; experiments, meetings and other notes are
subentries below it, each with its own colour:

```latex
\entry{2026-10-13}
\meeting{Ana, Bor}{What we discussed.}{Next steps, decisions, advice.}
\other[Optional title]
Anything you want to write down.
```

Write the date out. `\today` would not work: it changes every time the document is compiled.

Every run that finishes is added at the end of the entry of that day, and the entry is
created if it does not exist yet. Three seeds of one experiment give three subentries, each
with its run ID. Nothing is overwritten: the files of a run are in
`generated/<experiment>/<run id>/`. To drop a broken run, delete its lines from `journal.tex`
in Overleaf. Each subentry shows, in this order: a block that identifies the run, the
results, and your notes.

The results come from the `journal/` folder of the run, in the order of the file names
(prefix them with `01-`, `02-` to choose the order):

| File | What happens |
|---|---|
| `.pdf`, `.png`, `.jpg` | shown as a figure |
| `.csv` | typeset as a table; the first row is the header. At most 50 rows and 12 columns |
| `.tex` | included as it is. A LaTeX error in it breaks the journal until you fix the file and export again |

Files over 2 MB are left out, and the entry says so.

### Reports

Copy `report.tex` for each report and write it by hand. Coloured blocks go directly into the
text, right after the paragraph they belong to:

```latex
\remark{Something worth pointing out.}
\question{A question.}
\question[Ana]{A question for one supervisor.}
\issue{A problem with the setup that cannot be solved right now.}
\expentry{012-lora/20261013-101500-a3f1}    % facts and results of one run
```

## Secrets

Keys, tokens and passwords live only in `.env`. List the name of each one in `SECRETS`:

```
SECRETS=WANDB_API_KEY,OVERLEAF_TOKEN,HF_TOKEN
HF_TOKEN=...
```

The values of the listed variables are replaced by `<redacted>` in the config (printed,
saved in the run folder and sent to W&B) and in `run.json`. Nothing is guessed from names,
so a secret that is not listed is not redacted.

That is all that is redacted. What your own code prints goes to `output.log` as it is, and
the launcher prints the command and saves it in `job.sh` as it is. So never print a secret,
and never type one into a config file or on the command line.

## Claude Code

The project carries its own setup for Claude Code, the same on every server:

| File | What it does |
|---|---|
| `CLAUDE.md` | rules and conventions, read in every session. Add project knowledge in its last section |
| `.claude/settings.json` | permissions and hooks, enforced by the program |
| `.claude/skills/experiment/` | the steps of launching an experiment. Type `/experiment lr 0.01 on hpc-gpu`, or just ask for an experiment |
| `.claude/skills/audit/` | a high-level review of the whole repository in a fresh context: design, stale code, risks to results. Type `/audit`, or `/audit the data pipeline`. It reports and changes nothing |
| `.claude/hooks/check.sh` | runs `make check` when Claude finishes a turn in which it changed code, and hands a failure back to it once |

The permissions: Claude cannot read `.env` or edit `overleaf/`. It always asks before a
launcher (a `--dry-run` included), `git push`, `git tag`, `make journal` and `make setup`
(and the two scripts behind them), even if you allowed such a command earlier. The checks (`make check`, `pytest`, `ruff`,
`mypy`) run without asking. Patterns match the text of a command, so they catch the usual
forms, not every possible one.

Settings of your own go in `.claude/settings.local.json`, which is not committed.

## Never commit

`.env`, `overleaf/`, `runs/`, `wandb/`, `data/`, and model weights. `.gitignore` covers them.
Log only metrics and plots to W&B, never raw data from restricted datasets.
