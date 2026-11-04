"""Local-only, aggregate keyboard activity collection and summary export."""

from __future__ import annotations

import csv
import getpass
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pynput import keyboard


@dataclass(frozen=True)
class AuditEntry:
    """A non-sensitive record of a user-visible monitoring state change."""

    timestamp: str
    username: str
    action: str


class InputActivityService:
    """Counts key categories during explicit monitoring without retaining key content."""

    CATEGORY_NAMES = (
        "letters", "numbers", "navigation_keys", "function_keys", "modifier_keys", "shortcuts", "other",
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listener: keyboard.Listener | None = None
        self._counts: Counter[str] = Counter()
        self._started_at: float | None = None
        self._accumulated_seconds = 0.0
        self._running = False
        self._modifier_down: set[Any] = set()
        self._audit_log: list[AuditEntry] = []
        self._username = getpass.getuser()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def has_listener(self) -> bool:
        with self._lock:
            return self._listener is not None

    @property
    def username(self) -> str:
        return self._username

    def start(self) -> None:
        """Start or resume collection after the user has explicitly authorized it."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._started_at = time.monotonic()
            self._add_audit_entry("Monitoring started")
            if self._listener is None:
                self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
                self._listener.start()

    def pause(self) -> None:
        """Pause event counting while preserving the session's aggregate summary."""
        with self._lock:
            if not self._running:
                return
            self._finish_active_interval()
            self._modifier_down.clear()
            self._add_audit_entry("Monitoring paused")

    def stop(self) -> None:
        """Stop collection and release the listener; the aggregate summary remains."""
        listener: keyboard.Listener | None
        with self._lock:
            if self._running:
                self._finish_active_interval()
                self._modifier_down.clear()
            listener, self._listener = self._listener, None
            if listener is not None:
                self._add_audit_entry("Monitoring stopped")
        if listener is not None:
            listener.stop()

    def reset(self) -> None:
        """Clear only the aggregate metrics, retaining the transparent audit trail."""
        self.stop()
        with self._lock:
            self._counts.clear()
            self._accumulated_seconds = 0.0
            self._add_audit_entry("Aggregate metrics reset")

    def summary(self) -> dict[str, float | int]:
        with self._lock:
            duration = self._active_duration()
            total = sum(self._counts.values())
            result: dict[str, float | int] = {
                "total_keyboard_events": total,
                "events_per_minute": round(total / (duration / 60), 1) if duration else 0.0,
                "active_duration_seconds": round(duration, 1),
            }
            result.update({name: self._counts[name] for name in self.CATEGORY_NAMES})
            return result

    def audit_entries(self) -> tuple[AuditEntry, ...]:
        with self._lock:
            return tuple(self._audit_log)

    def record_audit_event(self, action: str) -> None:
        """Record a visible, non-sensitive user-facing action in the local audit panel."""
        with self._lock:
            self._add_audit_entry(action)

    def export_csv(self, directory: str | Path) -> Path:
        """Create a timestamped aggregate-only CSV in the requested local directory."""
        destination = Path(directory)
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / f"input_activity_summary_{datetime.now():%Y%m%d_%H%M%S}.csv"
        summary = self.summary()
        with path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=["exported_at", "windows_username", *summary.keys()])
            writer.writeheader()
            writer.writerow({"exported_at": self._timestamp(), "windows_username": self.username, **summary})
        return path

    def _on_press(self, key: Any) -> None:
        with self._lock:
            if not self._running:
                return
            is_modifier = key in self._modifier_keys()
            category = self._category_for(key, is_modifier)
            self._counts[category] += 1
            if is_modifier:
                self._modifier_down.add(key)

    def _on_release(self, key: Any) -> None:
        with self._lock:
            self._modifier_down.discard(key)

    def _category_for(self, key: Any, is_modifier: bool) -> str:
        if is_modifier:
            return "modifier_keys"
        if self._modifier_down:
            return "shortcuts"
        if isinstance(key, keyboard.KeyCode) and key.char:
            if key.char.isalpha():
                return "letters"
            if key.char.isdigit():
                return "numbers"
        if key in self._navigation_keys():
            return "navigation_keys"
        name = getattr(key, "name", "")
        return "function_keys" if name.startswith("f") and name[1:].isdigit() else "other"

    def _finish_active_interval(self) -> None:
        if self._started_at is not None:
            self._accumulated_seconds += time.monotonic() - self._started_at
        self._started_at = None
        self._running = False

    def _active_duration(self) -> float:
        if self._running and self._started_at is not None:
            return self._accumulated_seconds + time.monotonic() - self._started_at
        return self._accumulated_seconds

    def _add_audit_entry(self, action: str) -> None:
        self._audit_log.append(AuditEntry(self._timestamp(), self.username, action))

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _modifier_keys() -> set[Any]:
        return {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
                keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r,
                keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r,
                keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r}

    @staticmethod
    def _navigation_keys() -> set[Any]:
        return {keyboard.Key.up, keyboard.Key.down, keyboard.Key.left, keyboard.Key.right,
                keyboard.Key.home, keyboard.Key.end, keyboard.Key.page_up, keyboard.Key.page_down,
                keyboard.Key.insert, keyboard.Key.delete}
