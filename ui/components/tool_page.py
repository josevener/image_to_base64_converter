"""Base view class and reusable planned-tool page."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class ToolPage(QWidget):
    """Common page contract used by the application controller."""

    status_changed = Signal(str)


class PlaceholderPage(ToolPage):
    """Consistent view for tools whose service workflow is not implemented yet."""

    def __init__(self, title: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description = QLabel("This tool has its own MVC page and is ready for its workflow implementation.")
        description.setObjectName("muted")
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        layout.addWidget(description)
