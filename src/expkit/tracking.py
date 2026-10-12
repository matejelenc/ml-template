"""Weights & Biases (W&B) tracking.

    run = record.start(cfg)
    tracking.start(cfg, run)   # from here on, run.log(...) also sends to W&B

Modes, set with wandb.mode in the config or WANDB_MODE in the environment:
    online     live curves at wandb.ai
    offline    for nodes without internet; upload later with: wandb sync <run folder>/wandb/offline-run-*
    disabled   no W&B at all

Log metrics and plots only. Never log samples, images or other raw data from restricted
or licensed datasets.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from omegaconf import DictConfig, OmegaConf

from expkit.record import Run
from expkit.redact import redact

log = logging.getLogger(__name__)


def start(cfg: DictConfig, run: Run) -> Optional[Any]:
    """Start a W&B run and attach it to the run record. Returns None if W&B is off or failed.

    A W&B problem (no internet, wrong key) must not stop training, so it only logs a warning.
    The local run record is complete either way.
    """
    if cfg.wandb.mode == "disabled":
        return None
    try:
        import wandb

        wandb_run = wandb.init(
            project=cfg.wandb.project,
            entity=cfg.wandb.entity,
            mode=cfg.wandb.mode,
            # Same ID as the run folder, so a W&B run and its folder are easy to match.
            id=cfg.run_id,
            name=f"{cfg.experiment_id}/{cfg.run_id}",
            group=cfg.experiment_id,
            config=redact(OmegaConf.to_container(cfg, resolve=True)),
            # W&B's own files go inside the run folder, not into the repo.
            dir=str(run.dir),
        )
    except Exception as error:  # noqa: BLE001 - any W&B failure is non-fatal
        log.warning("W&B could not start, continuing without it: %s", error)
        return None
    run.wandb = wandb_run
    # An offline run has no URL until it is uploaded with wandb sync.
    run.update(wandb_url=wandb_run.url if cfg.wandb.mode == "online" else None)
    return wandb_run
