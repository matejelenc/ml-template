"""conf/experiment/: an experiment file may only change settings that the base config has."""

from pathlib import Path

import pytest
import yaml

CONF = Path(__file__).resolve().parents[2] / "conf"
EXPERIMENT_FILES = sorted((CONF / "experiment").rglob("*.yaml"))
# Hydra's own sections follow Hydra's rules, not the base config.
HYDRA_SECTIONS = ("defaults", "hydra")


def unknown_keys(overrides, base, prefix=""):
    """Dotted names of the keys in `overrides` that `base` does not have."""
    unknown = []
    for key, value in overrides.items():
        if key not in base:
            unknown.append(prefix + key)
        elif isinstance(value, dict) and isinstance(base[key], dict):
            unknown += unknown_keys(value, base[key], f"{prefix}{key}.")
    return unknown


@pytest.mark.parametrize("path", EXPERIMENT_FILES, ids=lambda path: path.stem)
def test_experiment_file_changes_only_settings_that_exist(path):
    """Hydra accepts a misspelt key without a word, and the run then uses the base value."""
    text = path.read_text()
    # Without this line Hydra files every key under "experiment:", where nothing reads it.
    assert text.startswith("# @package _global_\n"), f"{path.name} must start with '# @package _global_'"
    overrides = {
        key: value for key, value in (yaml.safe_load(text) or {}).items() if key not in HYDRA_SECTIONS
    }
    base = yaml.safe_load((CONF / "config.yaml").read_text())
    unknown = unknown_keys(overrides, base)
    assert not unknown, f"{path.name}: {', '.join(unknown)} not in conf/config.yaml. A typo?"
