# ML research project template

A starting point for an ML research project: Hydra configs, a fixed record of every run,
W&B monitoring, launchers for tmux and Slurm, and journal entries pushed to Overleaf.

Every piece can be done by hand if the code breaks: the manual steps are listed below.

**Status:** the launchers are tested only against stand-ins for `sbatch` and `tmux`, not yet
on a real server. Running from a git worktree of the tagged commit and dataset manifests
are not built.

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
   It writes `.env` and adds `journal.tex`, `report.tex` and `generated/macros.sty` to the
   Overleaf project.
4. Check that it works: `uv run python scripts/experiment.py wandb.mode=disabled`

On every further server: `git clone`, `uv sync`, `make setup`.

### The same setup by hand

1. `cp .env.example .env && chmod 600 .env`, then fill in the values.
2. `git clone <overleaf git URL> overleaf` (user name `git`, password: the token).
3. Copy `overleaf_template/journal.tex` and `report.tex` into `overleaf/`, and
   `src/expkit/templates/macros.sty` to `overleaf/generated/macros.sty`.
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
4. Watch it in W&B, or with `make status` and `tail -f <run folder>/stdout.log`.
5. When it finishes, its entry is in the Overleaf journal. Open `journal.tex` there and
   fill in `\hypothesis{}` and `\conclusion{}`.

A run without `+experiment=...` is a scratch run for debugging: it goes to `runs/scratch/`,
gets no tag and no journal entry. Without a launcher: `uv run python scripts/experiment.py ...`

### What a launch does

- Refuses uncommitted changes (`--allow-dirty` overrides and is recorded).
- Creates the annotated tag `exp/012-lora` on the current commit and pushes it. One tag is
  one commit: after changing code, create the next experiment number.
- Creates the run folder, prints the job script and the submit command, and submits.

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
| `summary.json` | written at the end: final metrics, duration, weight files with size and SHA-256, journal files |
| `stdout.log`, `job.sh` | output and the exact job script |
| `journal/` | the figures you select for the Overleaf journal; every PDF, PNG or JPG here is exported, subfolders included |
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
run.log(step=100, loss=0.42)        # monitor/main.jsonl and W&B
run.finish(metrics={"loss": 0.01})  # summary.json
```

An experiment that trains several models or folds in one run names a series per model:

```python
run.log(step=100, series="model_a/fold_0", loss=0.42)   # monitor/model_a/fold_0.jsonl
```

Each series counts its own steps and appears in W&B as `model_a/fold_0/loss`.
`run.finish(metrics=...)` is for a handful of headline numbers. Larger tables belong in
`journal/` or `eval/` as files.

## Commands

| Command | What it does |
|---|---|
| `make setup` | write `.env`, connect Overleaf |
| `make status` | list runs and their state; `lost` means the job died without notice |
| `make journal EXP=012-lora` | push the journal entry again |
| `make journal EXP=012-lora OUT=folder` | write the entry to a folder, to upload by hand |
| `make test` | run the tests |

Useful overrides: `wandb.mode=disabled` or `offline`, `journal.export=false`.
After an offline run: `uv run wandb sync <run folder>/wandb/offline-run-*`.

## Overleaf

- `journal.tex` and each report are documents of their own. Open one in Overleaf to compile it.
- The code writes only `generated/` and adds one stub per experiment to `journal.tex`.
  Everything else is yours.
- Edit in the browser, not in the local `overleaf/` folder: the export refuses to run when
  that folder has local changes.
- Reports: copy `report.tex`, write it by hand. `\remark{...}`, `\question{Name}{...}` and
  `\expentry{012-lora}` (the generated facts of an experiment) are available.

## Secrets

Keys, tokens and passwords live only in `.env`. List the name of each one in `SECRETS`:

```
SECRETS=WANDB_API_KEY,OVERLEAF_TOKEN,HF_TOKEN
HF_TOKEN=...
```

The values of the listed variables are replaced by `<redacted>` in everything the code
writes or uploads: run folders, the printed config, W&B and the journal. Nothing is guessed
from names, so a secret that is not listed is not redacted. Never type a secret into a
config file or on the command line.

## Never commit

`.env`, `overleaf/`, `runs/`, `wandb/`, `data/`, and model weights. `.gitignore` covers them.
Log only metrics and plots to W&B, never raw data from restricted datasets.
