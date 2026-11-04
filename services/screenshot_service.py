"""Local persistence for user-approved screen captures."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol


class SavablePixmap(Protocol):
    """Minimal Qt pixmap interface required to save a PNG image."""

    def save(self, file_name: str, format: str) -> bool: ...


class ScreenshotService:
    """Stores screenshots locally without network transmission or hidden capture."""

    def __init__(self, output_directory: str | Path) -> None:
        self._output_directory = Path(output_directory)

    def save_capture(self, screens: list[tuple[str, SavablePixmap]]) -> list[Path]:
        """Save approved screen images directly in the local screenshot directory."""
        self._output_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        saved_paths: list[Path] = []
        for index, (screen_name, pixmap) in enumerate(screens, start=1):
            safe_name = "".join(char if char.isalnum() else "_" for char in screen_name).strip("_")
            path = self._output_directory / f"capture_{timestamp}_screen_{index}_{safe_name or 'display'}.png"
            if not pixmap.save(str(path), "PNG"):
                raise OSError(f"Could not write screenshot: {path.name}")
            saved_paths.append(path)
        return saved_paths
