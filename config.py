"""Load and save system configuration from YAML.

A config is a dict with these required keys:
    f1, f2, L, r0, q, r_diaphragm, I0
and an optional `module_name` for bookkeeping.
"""

import yaml


REQUIRED_KEYS = ("f1", "f2", "L", "r0", "q", "r_diaphragm", "I0")


def validate(config):
    """Raise ValueError if the config is missing required keys."""
    missing = [k for k in REQUIRED_KEYS if k not in config]
    if missing:
        raise ValueError(f"Config missing required keys: {missing}")


def load_config(path):
    """Read YAML config from `path` and return it as a dict."""
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if not isinstance(config, dict):
        raise ValueError(f"Config file {path!r} did not parse to a dict.")
    validate(config)
    return config


def save_config(path, config):
    """Write `config` dict to `path` as YAML (validates first)."""
    validate(config)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(dict(config), f, sort_keys=False)
