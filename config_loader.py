"""
Config Loader
Reads and validates YAML configuration files.
"""

import yaml
import os
from pathlib import Path


def load_config(path: str = "config/config.yaml") -> dict:
    """Load main config YAML file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(p, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict):
    """Basic validation of config structure."""
    if "accounts" not in cfg:
        raise ValueError("Config must have an 'accounts' section")
    for i, acc in enumerate(cfg["accounts"]):
        if "username" not in acc or "password" not in acc:
            raise ValueError(f"Account #{i+1} must have 'username' and 'password'")


def load_accounts_from_env() -> list:
    """
    Alternative: load accounts from environment variables.
    Format: ACCOUNT_1=username:password, ACCOUNT_2=username:password, ...
    """
    accounts = []
    i = 1
    while True:
        val = os.environ.get(f"ACCOUNT_{i}")
        if not val:
            break
        parts = val.split(":", 1)
        if len(parts) == 2:
            accounts.append({"username": parts[0], "password": parts[1]})
        i += 1
    return accounts