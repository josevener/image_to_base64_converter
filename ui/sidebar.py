"""Collapsible Qt navigation sidebar."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget


class Sidebar(QFrame):
    tool_requested = Signal(str)
    EXPANDED_WIDTH = 260

    def __init__(self, sections: list[tuple[str, list[str]]]) -> None:
        super().__init__()
        self._buttons: dict[str, QPushButton] = {}
        self.setObjectName("sidebar")
        self.setMinimumWidth(self.EXPANDED_WIDTH)
        self.setMaximumWidth(self.EXPANDED_WIDTH)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        for section, tools in sections:
            label = QLabel(section)
            label.setObjectName("section")
            layout.addWidget(label)
            for tool in tools:
                button = QPushButton(tool)
                button.setObjectName("navButton")
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setProperty("active", "false")
                button.clicked.connect(lambda checked=False, name=tool: self.tool_requested.emit(name))
                layout.addWidget(button)
                self._buttons[tool] = button
        layout.addStretch()
        scroll.setWidget(content)
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(scroll)

    def set_active(self, tool_name: str) -> None:
        """Refresh persistent navigation styling for the selected tool."""
        for name, button in self._buttons.items():
            button.setProperty("active", "true" if name == tool_name else "false")
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()
