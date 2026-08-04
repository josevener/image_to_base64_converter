"""Top application header view."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton


class Header(QFrame):
    menu_clicked = Signal()
    theme_clicked = Signal()
    recent_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("header")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self.menu = self._tool_button("☰", self.menu_clicked.emit)
        layout.addWidget(self.menu)
        brand = QLabel("Developer Toolbox")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        layout.addStretch()
        self.page_name = QLabel("")
        self.page_name.setObjectName("muted")
        layout.addWidget(self.page_name)
        layout.addWidget(self._tool_button("☀", self.theme_clicked.emit))
        self.recent = self._tool_button("Recent ▾", self.recent_clicked.emit)
        layout.addWidget(self.recent)

    @staticmethod
    def _tool_button(text: str, callback: object) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)  # type: ignore[arg-type]
        return button
