"""Example entry point: a toy experiment wired to Hydra.

Run it with:
    uv run python scripts/experiment.py +experiment=001-toy
Show the merged config without running:
    uv run python scripts/experiment.py +experiment=001-toy --cfg job --resolve
"""

import json
import random

import hydra
from dotenv import load_dotenv
from omegaconf import DictConfig, OmegaConf

from expkit import journal, record, tracking
from expkit.config import SCRATCH, register_resolvers
from expkit.redact import redact

# Read .env before Hydra builds the config, because the config uses RUNS_DIR and DATA_DIR.
load_dotenv()
register_resolvers()


def train(cfg: DictConfig, run: record.Run) -> float:
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
            run.log(step=step, loss=loss)
    plot_loss(run)
    # Weights go into the run folder. A real project would call torch.save here.
    (run.weights_dir / "model.json").write_text(json.dumps({"w": w, "b": b}))
    return loss


def plot_loss(run: record.Run) -> None:
    """Save the loss curve as a PDF in artifacts/. The journal entry includes every figure there."""
    import matplotlib

    matplotlib.use("Agg")  # no display needed on a server
    import matplotlib.pyplot as plt

    rows = [json.loads(line) for line in (run.dir / "metrics.jsonl").read_text().splitlines()]
    figure, axis = plt.subplots(figsize=(5, 3))
    axis.plot([row["step"] for row in rows], [row["loss"] for row in rows])
    axis.set(xlabel="step", ylabel="loss", yscale="log")
    figure.tight_layout()
    # A fixed creation date keeps the file identical between identical runs.
    figure.savefig(run.artifacts_dir / "loss.pdf", metadata={"CreationDate": None})
    plt.close(figure)


# version_base pins Hydra's defaults, so every Hydra version from 1.2 on behaves the same.
@hydra.main(version_base="1.2", config_path="../conf", config_name="config")
def main(cfg: DictConfig) -> None:
    # Printed output ends up in log files, so secrets are removed here too.
    print(OmegaConf.to_yaml(redact(OmegaConf.to_container(cfg, resolve=True))))
    run = record.start(cfg)
    tracking.start(cfg, run)
    final_loss = train(cfg, run)
    run.finish(metrics={"loss": final_loss})
    print(f"final loss {final_loss:.6f}")
    print(f"run folder: {run.dir}")
    # Scratch runs are for debugging and get no journal entry.
    if cfg.journal.export and cfg.experiment_id != SCRATCH:
        journal.export_at_job_end(run.dir)


if __name__ == "__main__":
    main()
