"""Application status bar view."""

from PySide6.QtWidgets import QLabel


class StatusBar(QLabel):
    def __init__(self) -> None:
        super().__init__("Ready")
        self.setObjectName("status")
        self.setMinimumHeight(28)
