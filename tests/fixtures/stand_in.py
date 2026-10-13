"""Stand-in for a script of the project: the bookkeeping calls of a run, and no training.

The tests copy this file into scripts/ of a throwaway project, next to a copy of conf/ (see
tests/conftest.py). It follows scripts/experiment.py without the toy training, W&B and the
journal export. The tests of the config and of the launchers use it, so they keep working
when a project replaces the example with its own code.
"""

import hydra
from omegaconf import DictConfig, OmegaConf

from expkit import record
from expkit.config import load_env, register_resolvers
from expkit.redact import redact_config

load_env()
register_resolvers()


@hydra.main(version_base="1.2", config_path="../conf", config_name="config")
def main(cfg: DictConfig) -> None:
    """Print the config, then write a complete run folder."""
    print(OmegaConf.to_yaml(redact_config(cfg)))
    run = record.start(cfg)
    run.monitor(step=1, loss=0.5)
    run.finish(metrics={"loss": 0.5})
    print(f"run folder: {run.dir}")


if __name__ == "__main__":
    main()
