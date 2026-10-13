# Rules for agents in this project

An ML research project created from a template. `README.md` says how to use it,
`CONTRIBUTING.md` (included at the end) how code is written. Add what is specific to the
project in the last section; keep this file short, because all of it is read in every session.

## Working with the user

- The user is a researcher, not a software engineer: small modules, few dependencies, plain
  names, clear comments.
- Do not agree to please. Name the weak points of an idea and offer a better alternative
  when you see one. The user has the final say.
- Do not commit. When a change is finished, give the user the `git add` and `git commit`
  commands.
- Run `make check` before you call a change finished.

## Ask before

- submitting a job (`scripts/launch/tmux.sh`, `scripts/launch/slurm.sh`)
- pushing a git tag or pushing to GitHub
- pushing to Overleaf (`make journal` without `OUT=`, `make setup`, or a run with
  `journal.export` left on)
- uploading to W&B (any run without `wandb.mode=disabled`)

Safe: `make check`, `make status`, and local runs with
`wandb.mode=disabled journal.export=false`.

## Never

- read, print or commit `.env`, or write a secret into any file, log or command
- commit `overleaf/`, `runs/`, `wandb/`, `data/` or model weights
- edit files in `overleaf/`: `main.tex` is the user's paper, and `generated/` is overwritten
  on export
- move or delete an `exp/*` tag
- log raw samples or images from datasets to W&B

## Conventions

- Experiment: `conf/experiment/NNN-slug.yaml`, three digits, sequential, overrides only,
  starting with `# @package _global_` and a `# Purpose:` line.
- Tag: `exp/NNN-slug`, one per experiment, on the commit that ran. Changed code means a new
  experiment number.
- A run without `+experiment=...` is a scratch run: no tag, no journal entry.
- Run folder: `$RUNS_DIR/<experiment_id>/<run_id>/`, files described in `README.md`. Raise
  `SCHEMA_VERSION` in `src/expkit/record.py` when a field in them changes meaning.
- Per-server paths and secrets come from `.env`, never from committed config. Only the
  variables listed in `SECRETS` there are redacted; nothing is guessed from names.

## This project

Nothing yet. Add here what an agent cannot see in the code: the research question, the
datasets and their restrictions, decisions that were made and why.

@CONTRIBUTING.md
