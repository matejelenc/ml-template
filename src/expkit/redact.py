"""Keep secrets out of everything expkit writes to disk or uploads.

Nothing is guessed. A secret is an environment variable whose name is listed in SECRETS:

    SECRETS=WANDB_API_KEY,OVERLEAF_TOKEN

SECRETS is set in .env, next to the secrets themselves.
"""

from __future__ import annotations

import os
from typing import Any, List

REDACTED = "<redacted>"


def secret_values() -> List[str]:
    """Values of the environment variables listed in SECRETS. Unset or empty ones are skipped."""
    names = [name.strip() for name in os.environ.get("SECRETS", "").split(",")]
    values = [os.environ.get(name, "") for name in names if name]
    # Longest first, so a secret that contains another one is replaced whole.
    return sorted((value for value in values if value), key=len, reverse=True)


def redact(data: Any) -> Any:
    """Return a copy of nested dicts and lists with every secret value replaced by "<redacted>".

    A secret is replaced wherever it appears in a text value, also inside a longer text.
    """
    return _redact(data, secret_values())


def _redact(data: Any, secrets: List[str]) -> Any:
    if isinstance(data, dict):
        return {key: _redact(value, secrets) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [_redact(item, secrets) for item in data]
    if isinstance(data, str):
        for secret in secrets:
            data = data.replace(secret, REDACTED)
    return data
