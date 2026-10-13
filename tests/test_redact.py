"""Secrets must never reach a file that expkit writes."""

from expkit.redact import REDACTED, redact, secret_values


def test_listed_secret_is_replaced_wherever_it_appears(monkeypatch):
    monkeypatch.setenv("SECRETS", "WANDB_API_KEY")
    monkeypatch.setenv("WANDB_API_KEY", "wandb-secret-123456")
    config = {"notes": "key is wandb-secret-123456!", "items": ["wandb-secret-123456", 3]}
    assert redact(config) == {"notes": f"key is {REDACTED}!", "items": [REDACTED, 3]}


def test_only_listed_variables_are_secrets(monkeypatch):
    # Nothing is guessed from names: an unlisted token passes through.
    monkeypatch.setenv("SECRETS", "WANDB_API_KEY")
    monkeypatch.setenv("WANDB_API_KEY", "wandb-secret-123456")
    monkeypatch.setenv("HF_TOKEN", "hf-abcdef")
    config = {"hf_token": "hf-abcdef", "api_key": "typed-by-hand"}
    assert redact(config) == config


def test_spaces_and_several_names_in_the_list(monkeypatch):
    monkeypatch.setenv("SECRETS", " WANDB_API_KEY , OVERLEAF_TOKEN,")
    monkeypatch.setenv("WANDB_API_KEY", "wandb-secret")
    monkeypatch.setenv("OVERLEAF_TOKEN", "wandb-secret-and-more")
    # Longest first, so the longer secret is not left half visible.
    assert secret_values() == ["wandb-secret-and-more", "wandb-secret"]
    assert redact("x wandb-secret-and-more y") == f"x {REDACTED} y"


def test_unset_and_empty_secrets_are_skipped(monkeypatch):
    monkeypatch.setenv("SECRETS", "WANDB_API_KEY,NOT_SET")
    monkeypatch.setenv("WANDB_API_KEY", "")
    monkeypatch.delenv("NOT_SET", raising=False)
    assert redact({"note": "text"}) == {"note": "text"}


def test_no_list_means_nothing_is_redacted(monkeypatch):
    monkeypatch.delenv("SECRETS", raising=False)
    monkeypatch.setenv("WANDB_API_KEY", "wandb-secret-123456")
    assert redact({"note": "wandb-secret-123456"}) == {"note": "wandb-secret-123456"}


def test_input_is_not_changed(monkeypatch):
    monkeypatch.setenv("SECRETS", "WANDB_API_KEY")
    monkeypatch.setenv("WANDB_API_KEY", "wandb-secret-123456")
    config = {"note": "wandb-secret-123456"}
    redact(config)
    assert config == {"note": "wandb-secret-123456"}
