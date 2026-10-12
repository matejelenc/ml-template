"""Example entry point: a toy experiment wired to Hydra.

Run it with:
    uv run python scripts/experiment.py +experiment=001-toy
Show the merged config without running:
    uv run python scripts/experiment.py +experiment=001-toy --cfg job --resolve
"""

import random

import hydra
from dotenv import load_dotenv
from omegaconf import DictConfig, OmegaConf

from expkit.config import register_resolvers

# Read .env before Hydra builds the config, because the config uses RUNS_DIR and DATA_DIR.
load_dotenv()
register_resolvers()


def train(cfg: DictConfig) -> float:
    """Fit y = 2x + 1 with gradient descent. Stands in for real training."""
    rng = random.Random(cfg.seed)
    w, b = 0.0, 0.0
    loss = float("nan")
    for step in range(1, cfg.train.steps + 1):
        x = rng.uniform(-1, 1)
        error = (w * x + b) - (2 * x + 1)
        loss = error**2
        w -= cfg.train.lr * 2 * error * x
        b -= cfg.train.lr * 2 * error
        if step % cfg.train.log_every == 0:
            print(f"step {step:4d}  loss {loss:.6f}")
    return loss


# version_base pins Hydra's defaults, so every Hydra version from 1.2 on behaves the same.
@hydra.main(version_base="1.2", config_path="../conf", config_name="config")
def main(cfg: DictConfig) -> None:
    print(OmegaConf.to_yaml(cfg, resolve=True))
    final_loss = train(cfg)
    print(f"final loss {final_loss:.6f}")


if __name__ == "__main__":
    main()
