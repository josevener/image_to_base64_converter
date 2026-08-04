"""Common layout helpers for concrete image-tool views."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout

from ui.components.tool_page import ToolPage


class ImageToolPage(ToolPage):
    """Standard title and content area for image-related pages."""

    def __init__(self, title: str, description: str) -> None:
        super().__init__()
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(16, 14, 16, 14)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        self.content_layout.addWidget(heading)
        copy = QLabel(description)
        copy.setObjectName("muted")
        self.content_layout.addWidget(copy)

    @staticmethod
    def button(text: str, callback: Callable[[], None], danger: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        if danger:
            button.setObjectName("dangerButton")
        return button

    @staticmethod
    def size_text(value: int) -> str:
        return f"{value / 1024 / 1024:.2f} MB" if value >= 1024 * 1024 else f"{value / 1024:.1f} KB"
