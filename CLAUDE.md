# Conventions for agents working in this project

This project was created from an ML research template. `README.md` has the workflow;
this file lists the rules.

## Ask the user before

- submitting a job (`scripts/launch/tmux.sh`, `scripts/launch/slurm.sh` without `--dry-run`)
- pushing a git tag or pushing to GitHub
- pushing to Overleaf (`make journal` without `OUT=`, `make setup`, or running an
  experiment with `journal.export` left on)
- uploading to W&B (any run without `wandb.mode=disabled`)

Safe without asking: `--dry-run` launches, `make test`, `make status`, and local runs with
`wandb.mode=disabled journal.export=false`.

## Never

- commit or print the contents of `.env`, or write a secret into any file, log or command
- commit `overleaf/`, `runs/`, `wandb/`, `data/` or model weights
- edit files in `overleaf/` directly, or touch `main.tex` there (the user's paper)
- edit anything under `generated/` in the Overleaf project: it is overwritten on export
- move or delete a `exp/*` tag
- log raw samples or images from datasets to W&B

## Conventions

- Experiment ID: `NNN-slug`, three digits, sequential. File: `conf/experiment/NNN-slug.yaml`,
  overrides only, starting with `# @package _global_` and a `# Purpose:` line.
- Tag: `exp/NNN-slug`, annotated, one per experiment, on the commit that ran. Changed code
  means a new experiment number.
- Run ID: start time plus four random characters, e.g. `20261012-195950-a3f1`.
- Run folder: `$RUNS_DIR/<experiment_id>/<run_id>/`. Its files are described in `README.md`.
  Every JSON and YAML file there carries `schema_version`; raise `SCHEMA_VERSION` in
  `src/expkit/record.py` when a field changes meaning.
- Per-server paths and secrets come from `.env`, never from committed config.
- Every secret's variable name is listed in `SECRETS` in `.env` (and `.env.example`). Only
  listed variables are redacted; nothing is guessed from names.
- Runs without `+experiment=...` are scratch runs: no tag, no journal entry.

## Code

- The user is a researcher, not a software engineer: small modules, few dependencies,
  clear comments, plain names.
- Supported: Python 3.9+ and Hydra 1.2+. Check both before finishing a change:
  `make test` and
  `uv run --isolated --python 3.9 --with 'hydra-core==1.2.0' pytest -q`
- Tests mirror the code: `src/<package>/<module>.py` is tested in
  `tests/<package>/test_<module>.py`, and `scripts/<name>.py` in `tests/scripts/test_<name>.py`.
  Each test file starts with a one-line docstring saying what it covers.
- `scripts/launch/job_wrapper.sh` must stay independent of Python and `expkit`.
- The journal export and W&B must never make a job fail.
- LaTeX: `src/expkit/templates/macros.sty` defines which macros exist, the files in
  `templates/styles/` define how they look (every style defines the same commands, listed
  at the end of `macros.sty`). Generated entries contain
  macro calls, not formatting.
