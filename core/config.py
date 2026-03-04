import json
import os
import base64
from pathlib import Path


CONFIG_DIR = Path.home() / ".movewriter"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "ip": "10.11.99.1",
    "password_b64": "",
    "setup_complete": False,
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
        merged = {**DEFAULTS, **stored}
        return merged
    return dict(DEFAULTS)


def save(cfg):
    _ensure_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def get_password(cfg):
    b64 = cfg.get("password_b64", "")
    if not b64:
        return ""
    try:
        return base64.b64decode(b64).decode("utf-8")
    except Exception:
        return ""


def set_password(cfg, password):
    cfg["password_b64"] = base64.b64encode(password.encode("utf-8")).decode("utf-8")
