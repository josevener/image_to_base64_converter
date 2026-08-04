"""Persistent application settings and theme utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SETTINGS_PATH = Path(__file__).with_name("settings.json")
DEFAULT_SETTINGS: dict[str, Any] = {"theme": "Dark", "last_folder": "", "recent_files": []}


def load_settings() -> dict[str, Any]:
    try:
        values = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return {**DEFAULT_SETTINGS, **values}
    except (OSError, json.JSONDecodeError):
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict[str, Any]) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def add_recent(settings: dict[str, Any], path: str) -> None:
    recent = [item for item in settings.get("recent_files", []) if item != path]
    settings["recent_files"] = [path, *recent][:10]
