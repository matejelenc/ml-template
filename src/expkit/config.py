"""Small helpers used by the Hydra config."""

from hydra.core.hydra_config import HydraConfig
from omegaconf import OmegaConf

# Run folder name for runs started without an experiment file (quick debugging runs).
SCRATCH = "scratch"


def _experiment_id() -> str:
    """Name of the chosen experiment file, e.g. "001-toy", or "scratch" if none was chosen."""
    return HydraConfig.get().runtime.choices.get("experiment") or SCRATCH


def register_resolvers() -> None:
    """Make ${experiment_id:} usable in the config. Call this before @hydra.main runs."""
    OmegaConf.register_new_resolver("experiment_id", _experiment_id, replace=True)
