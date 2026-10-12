"""Secrets must never reach a file that expkit writes."""

import pytest

from expkit.redact import REDACTED, is_secret_name, redact


@pytest.mark.parametrize(
    "name", ["api_key", "WANDB_API_KEY", "apikey", "hf_token", "token", "OVERLEAF_TOKEN",
             "db_password", "client_secret", "credentials"],
)
def test_secret_names(name):
    assert is_secret_name(name)


@pytest.mark.parametrize(
    "name", ["max_tokens", "num_tokens", "tokenizer", "pad_token", "eos_token", "bos_token_id",
             "lr", "key_dim", "monkey"],
)
def test_ordinary_names(name):
    assert not is_secret_name(name)


def test_value_under_secret_key_is_replaced():
    config = {"model": {"hf_token": "abc", "max_tokens": 128}, "lr": 0.1}
    assert redact(config) == {"model": {"hf_token": REDACTED, "max_tokens": 128}, "lr": 0.1}


def test_empty_and_non_text_values_are_kept():
    config = {"api_key": None, "password": "", "use_auth_token": True}
    assert redact(config) == config


def test_known_secret_is_replaced_under_any_key(monkeypatch):
    monkeypatch.setenv("WANDB_API_KEY", "wandb-secret-123456")
    config = {"notes": "key is wandb-secret-123456!", "items": ["wandb-secret-123456", 3]}
    assert redact(config) == {"notes": f"key is {REDACTED}!", "items": [REDACTED, 3]}


def test_short_environment_values_are_ignored(monkeypatch):
    # A short value such as "1" would otherwise be cut out of unrelated text.
    monkeypatch.setenv("SOME_TOKEN", "1")
    assert redact({"note": "step 1 of 10"}) == {"note": "step 1 of 10"}


def test_input_is_not_changed():
    config = {"api_key": "abc"}
    redact(config)
    assert config == {"api_key": "abc"}
