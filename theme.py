"""Persistent application settings and theme utilities."""

from __future__ import annotations

from typing import Any

from services.database_service import DatabaseService

DEFAULT_SETTINGS: dict[str, Any] = {"theme": "Light", "last_folder": "", "recent_files": []}


def load_settings() -> dict[str, Any]:
    return DatabaseService().load_settings()


def save_settings(settings: dict[str, Any]) -> None:
    DatabaseService().save_settings(settings)


def add_recent(settings: dict[str, Any], path: str) -> None:
    recent = [item for item in settings.get("recent_files", []) if item != path]
    settings["recent_files"] = [path, *recent][:10]
