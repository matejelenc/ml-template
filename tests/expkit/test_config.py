"""expkit.config: reading .env."""

import os

from expkit.config import load_env


def test_load_env_skips_empty_values_and_keeps_the_shell(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("WANDB_MODE=\nFROM_FILE=abc\nFROM_SHELL=file\n")
    for name in ("WANDB_MODE", "FROM_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FROM_SHELL", "shell")
    load_env(env_file)
    # An empty WANDB_MODE in the environment makes the W&B library fail at start.
    assert "WANDB_MODE" not in os.environ
    assert os.environ["FROM_FILE"] == "abc" and os.environ["FROM_SHELL"] == "shell"
    monkeypatch.delenv("FROM_FILE")
