"""Resizable, single-page Qt PDF preview with deterministic local rendering."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QLabel, QScrollArea


class PdfPreview(QScrollArea):
    def __init__(self) -> None:
        super().__init__()
        self._document: QPdfDocument | None = None
        self._source = QPixmap()
        self._paper = QLabel()
        self._paper.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._paper.setStyleSheet("background: #80858b; padding: 6px;")
        self.setWidget(self._paper)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def set_document(self, document: QPdfDocument | None) -> None:
        self._document = document
        self._source = QPixmap()
        if document is not None and document.pageCount():
            page = document.pagePointSize(0)
            self._source = QPixmap.fromImage(document.render(0, QSize(1600, round(1600 * page.height() / page.width()))))
        self._render()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._render()

    def _render(self) -> None:
        if self._source.isNull():
            self._paper.clear()
            return
        width = max(80, self.viewport().width() - 24)
        height = round(width * self._source.height() / self._source.width())
        # Resize the cached page so layout/theme changes do not repeatedly invoke PDF rendering.
        pixmap = self._source.scaled(QSize(width * 2, height * 2), Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        pixmap.setDevicePixelRatio(2)
        self._paper.setPixmap(pixmap)
        self._paper.adjustSize()
