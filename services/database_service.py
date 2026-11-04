"""SQLite persistence for application settings, recents, and API history."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any
from typing import Iterator
from contextlib import contextmanager


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
DATA_DIRECTORY = LOCAL_APP_DATA / "DeveloperToolbox"
DATABASE_PATH = DATA_DIRECTORY / "developer_toolbox.db"
PREVIOUS_USER_DATABASE_PATH = LOCAL_APP_DATA / "ImageToolkitPro" / "image_toolkit.db"
LEGACY_DATABASE_PATH = PROJECT_ROOT / "config" / "image_toolkit.db"
LEGACY_SETTINGS_PATH = PROJECT_ROOT / "settings.json"
DEFAULT_SETTINGS: dict[str, Any] = {"theme": "Light", "last_folder": "", "recent_files": []}


class DatabaseService:
    """Small repository that opens a short-lived SQLite connection per operation."""

    def __init__(self) -> None:
        DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
        self._migrate_project_database()
        self._initialize()

    @staticmethod
    def _migrate_project_database() -> None:
        """Copy the earlier project-local database once, preserving it as a backup."""
        if DATABASE_PATH.exists():
            return
        for source in (PREVIOUS_USER_DATABASE_PATH, LEGACY_DATABASE_PATH):
            if source.is_file():
                shutil.copy2(source, DATABASE_PATH)
                return

    @staticmethod
    @contextmanager
    def _connect() -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(DATABASE_PATH)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        is_new = not DATABASE_PATH.exists()
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recent_files (
                    path TEXT PRIMARY KEY,
                    opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS api_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    method TEXT NOT NULL,
                    url TEXT NOT NULL,
                    status_code INTEGER,
                    elapsed_ms REAL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
        if is_new:
            self._migrate_legacy_settings()

    def _migrate_legacy_settings(self) -> None:
        values = DEFAULT_SETTINGS.copy()
        try:
            values.update(json.loads(LEGACY_SETTINGS_PATH.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
        self.save_settings(values)

    def load_settings(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
            recent = connection.execute("SELECT path FROM recent_files ORDER BY opened_at DESC LIMIT 10").fetchall()
        settings = DEFAULT_SETTINGS.copy()
        settings.update({row["key"]: json.loads(row["value"]) for row in rows})
        settings["recent_files"] = [row["path"] for row in recent]
        return settings

    def save_settings(self, settings: dict[str, Any]) -> None:
        values = {key: value for key, value in settings.items() if key != "recent_files"}
        with self._connect() as connection:
            connection.executemany(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(key, json.dumps(value)) for key, value in values.items()],
            )
            for path in settings.get("recent_files", []):
                connection.execute(
                    "INSERT INTO recent_files(path, opened_at) VALUES(?, CURRENT_TIMESTAMP) ON CONFLICT(path) DO UPDATE SET opened_at = CURRENT_TIMESTAMP",
                    (path,),
                )
            connection.execute("""
                DELETE FROM recent_files WHERE path NOT IN (
                    SELECT path FROM recent_files ORDER BY opened_at DESC LIMIT 10
                )
            """)

    def record_api_history(self, method: str, url: str, status_code: int | None, elapsed_ms: float | None) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO api_history(method, url, status_code, elapsed_ms) VALUES (?, ?, ?, ?)",
                (method, url, status_code, elapsed_ms),
            )
