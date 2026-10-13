"""Keep secrets out of everything expkit writes to disk or uploads.

Nothing is guessed. A secret is an environment variable whose name is listed in SECRETS:

    SECRETS=WANDB_API_KEY,OVERLEAF_TOKEN

SECRETS is set in .env, next to the secrets themselves.
"""

import os
from typing import Any

from omegaconf import DictConfig, OmegaConf

REDACTED = "<redacted>"


def secret_values() -> list[str]:
    """Values of the environment variables listed in SECRETS. Unset or empty ones are skipped."""
    names = [name.strip() for name in os.environ.get("SECRETS", "").split(",")]
    values = [os.environ.get(name, "") for name in names if name]
    # Longest first, so a secret that contains another one is replaced whole.
    return sorted((value for value in values if value), key=len, reverse=True)


def redact(data: Any) -> Any:
    """Return a copy of nested dicts and lists with every secret value replaced by `<redacted>`.

    A secret is replaced wherever it appears in a text value, also inside a longer text.

    Args:
        data: Nested dicts and lists of plain values, such as a config or the content of
            a JSON file.

    Returns:
        A copy of `data`. The original is not changed.
    """
    return _redact(data, secret_values())


def redact_config(cfg: DictConfig) -> dict[str, Any]:
    """The final config as a plain dict, every ${...} filled in and secrets replaced.

    Use this whenever the config is printed, saved or uploaded.
    """
    return redact(OmegaConf.to_container(cfg, resolve=True))


def _redact(data: Any, secrets: list[str]) -> Any:
    if isinstance(data, dict):
        return {key: _redact(value, secrets) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [_redact(item, secrets) for item in data]
    if isinstance(data, str):
        for secret in secrets:
            data = data.replace(secret, REDACTED)
    return data
