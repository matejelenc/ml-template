"""Keep secrets out of everything expkit writes to disk."""

from __future__ import annotations

import os
import re
from typing import Any, List

REDACTED = "<redacted>"

# A config key or environment variable with one of these in its name holds a secret.
_SECRET_NAME = re.compile(r"secret|password|passwd|api_?key|credential|token$", re.IGNORECASE)
# Model settings whose names end in "token" or "tokens" but are not secrets.
_NOT_SECRET = re.compile(r"(pad|eos|bos|unk|sep|cls|mask)_?token$", re.IGNORECASE)
# Shorter values are too likely to match ordinary text by accident.
_MIN_SECRET_LENGTH = 8


def is_secret_name(name: str) -> bool:
    """True for names such as api_key, hf_token or db_password. False for max_tokens or pad_token."""
    return bool(_SECRET_NAME.search(name)) and not _NOT_SECRET.search(name)


def secret_values() -> List[str]:
    """Values of environment variables with secret-looking names, e.g. WANDB_API_KEY."""
    values = [
        value
        for name, value in os.environ.items()
        if is_secret_name(name) and len(value) >= _MIN_SECRET_LENGTH
    ]
    # Longest first, so a secret that contains another one is replaced whole.
    return sorted(values, key=len, reverse=True)


def redact(data: Any) -> Any:
    """Return a copy of nested dicts and lists with secrets replaced by "<redacted>".

    Two rules:
    1. A text value under a secret-looking key is replaced entirely.
    2. A known secret value is replaced wherever it appears, whatever the key is called.
    """
    return _redact(data, secret_values())


def _redact(data: Any, secrets: List[str]) -> Any:
    if isinstance(data, dict):
        return {
            key: REDACTED
            if isinstance(value, str) and value and is_secret_name(str(key))
            else _redact(value, secrets)
            for key, value in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [_redact(item, secrets) for item in data]
    if isinstance(data, str):
        for secret in secrets:
            data = data.replace(secret, REDACTED)
    return data
