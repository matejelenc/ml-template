---
name: experiment
description: Create a numbered experiment config and launch it with tmux or Slurm. Use when the user wants to run, launch or submit an experiment or a job.
argument-hint: "[what to change, e.g. lr 0.01 on hpc-gpu]"
---

# Launch an experiment

What the user asked for: $ARGUMENTS

Go through the steps in order. Steps 4 and 6 wait for the user. The conventions (IDs, tags,
what needs confirmation) are in `CLAUDE.md`; the workflow is in `README.md`.

1. **Settle what runs.** You need: which script (default `scripts/experiment.py`), which
   config values change, and where it runs. If one of them is unclear, ask before writing
   anything. Give your opinion on the experiment itself if you see a problem with it, such
   as two things changed at once, or no baseline to compare with.

2. **Write the config.** List `conf/experiment/` and take the next free number. Create
   `conf/experiment/NNN-slug.yaml` with overrides only:
   ```yaml
   # @package _global_
   # Purpose: one line on why this experiment exists (becomes the git tag message).
   train:
     lr: 0.01
   ```
   Every key must already exist in `conf/config.yaml`. To run an existing experiment again
   on the same code (another seed), reuse its file. If the code changed since its tag
   `exp/NNN-slug` was created, it is a new experiment with a new number.

3. **Check the config.** This prints the merged config and starts nothing:
   ```
   uv run python scripts/experiment.py +experiment=NNN-slug --cfg job
   ```
   Show the user the values that differ from the base config.

4. **Have it committed.** The launcher refuses uncommitted changes, because the tag must
   point at the code that runs. Run `make check`, then give the user the `git add` and
   `git commit` commands and wait. Do not pass `--allow-dirty` unless the user asks for it.

5. **Dry run.** Slurm if the server has `sbatch`, tmux otherwise:
   ```
   scripts/launch/slurm.sh --dry-run scripts/experiment.py +experiment=NNN-slug
   scripts/launch/tmux.sh  --dry-run scripts/experiment.py +experiment=NNN-slug
   ```
   The Slurm profile comes from `LAUNCH_PROFILE` in `.env`. If the launcher reports that
   there is none, show the user the profiles in `scripts/launch/servers/` and pass their
   choice with `--profile NAME`. Show the user the tag, the run folder and the submit
   command from the output.

6. **Submit, after the user confirms.** Say what the real launch does before asking: it
   creates and pushes the tag `exp/NNN-slug`, the run uploads to W&B, and its journal entry
   is pushed to Overleaf when it finishes. Then run the same command without `--dry-run`.

7. **Report.** Give the run ID, the run folder, and the watch and cancel commands that the
   launcher printed. `make status` shows the state later.
