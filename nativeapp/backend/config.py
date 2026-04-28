"""Config persistence for MoveWriter Native.

Simplified from movewriterapp — no SSH fields needed since we run locally.
"""
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".movewriter"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "service_installed": False,
    "keyboard_mac": "",
    "keyboard_name": "",
    "keyboard_layout": "US English",
}


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load():
    _ensure_dir()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            stored = json.load(f)
        return {**DEFAULTS, **stored}
    return dict(DEFAULTS)


def save(cfg):
    _ensure_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
