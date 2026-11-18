"""Small per-machine settings file (~/.config/personal-agent-tui/settings.json)."""
from __future__ import annotations

import json
import os
from pathlib import Path


def path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "personal-agent-tui" / "settings.json"


def load() -> dict:
    try:
        return json.loads(path().read_text())
    except (OSError, ValueError):
        return {}


def save(**changes) -> None:
    data = load() | changes
    try:
        path().parent.mkdir(parents=True, exist_ok=True)
        path().write_text(json.dumps(data, indent=2) + "\n")
    except OSError:
        pass  # a read-only home should not stop the app
