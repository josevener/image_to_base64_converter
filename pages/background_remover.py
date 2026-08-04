"""Background-remover view backed by the local background service."""

from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QSlider, QVBoxLayout

from pages.components import ImageToolPage
from services.background_service import BackgroundRemovalResult, remove_uniform_background
from services.image_service import SUPPORTED_EXTENSIONS, is_supported_image
from theme import load_settings


class BackgroundWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def run(self, source: str, output: str, tolerance: int) -> None:
        try:
            self.completed.emit(remove_uniform_background(source, output, tolerance))
        except ValueError as error:
            self.failed.emit(str(error))


class BackgroundRemoverPage(ImageToolPage):
    """Remove uniform edge-connected backgrounds and export transparent PNGs."""

    def __init__(self) -> None:
        super().__init__("Background Remover", "Remove a connected, near-uniform background and export a transparent PNG.")
        self.settings = load_settings()
        self.source_path: str | None = None
        self.output_path: Path | None = None
        self._build_content()

    def _build_content(self) -> None:
        workspace = QHBoxLayout()
        workspace.setSpacing(14)
        source_card = self._preview_card("ORIGINAL", "Choose an image to begin")
        self.source_preview = source_card[1]
        source_layout = source_card[0]
        source_layout.addWidget(self.button("Browse Image", self.browse_image))
        workspace.addWidget(source_card[2])
        output_card = self._preview_card("TRANSPARENT RESULT", "Processed image will appear here")
        self.result_preview = output_card[1]
        output_layout = output_card[0]
        self.tolerance_label = QLabel("Background tolerance: 36")
        self.tolerance_label.setObjectName("muted")
        output_layout.addWidget(self.tolerance_label)
        self.tolerance = QSlider(Qt.Orientation.Horizontal)
        self.tolerance.setRange(8, 100)
        self.tolerance.setValue(36)
        self.tolerance.valueChanged.connect(lambda value: self.tolerance_label.setText(f"Background tolerance: {value}"))
        output_layout.addWidget(self.tolerance)
        self.remove_button = self.button("Remove Background", self.remove_background)
        self.remove_button.setEnabled(False)
        output_layout.addWidget(self.remove_button)
        self.save_button = self.button("Save Transparent PNG", self.save_result)
        self.save_button.setEnabled(False)
        output_layout.addWidget(self.save_button)
        workspace.addWidget(output_card[2])
        self.content_layout.addLayout(workspace, 1)

    @staticmethod
    def _preview_card(title: str, message: str) -> tuple[QVBoxLayout, QLabel, QFrame]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.addWidget(QLabel(title))
        preview = QLabel(message)
        preview.setObjectName("dropArea")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumSize(300, 320)
        preview.setWordWrap(True)
        layout.addWidget(preview, 1)
        return layout, preview, card

    def browse_image(self) -> None:
        filters = " ".join(f"*{extension}" for extension in SUPPORTED_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(self, "Select an image", self.settings.get("last_folder", ""), f"Image files ({filters})")
        if path and is_supported_image(path):
            self.source_path = path
            self._show_image(self.source_preview, path)
            self.remove_button.setEnabled(True)
            self.status_changed.emit(f"Loaded {Path(path).name}")

    def remove_background(self) -> None:
        if not self.source_path:
            return
        self.status_changed.emit("Removing background…")
        temporary = Path(tempfile.gettempdir()) / "developer_toolbox_background_removed.png"
        self._worker = BackgroundWorker(self)
        self._worker.completed.connect(self._completed)
        self._worker.failed.connect(self._failed)
        threading.Thread(target=self._worker.run, args=(self.source_path, str(temporary), self.tolerance.value()), daemon=True).start()

    def _completed(self, result: BackgroundRemovalResult) -> None:
        self.output_path = result.output
        self._show_image(self.result_preview, result.output)
        self.save_button.setEnabled(True)
        self.status_changed.emit(f"Background removed from {result.dimensions[0]} × {result.dimensions[1]} image")

    def _failed(self, message: str) -> None:
        QMessageBox.warning(self, "Background remover", message)
        self.status_changed.emit(message)

    def save_result(self) -> None:
        if not self.output_path:
            return
        destination, _ = QFileDialog.getSaveFileName(self, "Save transparent PNG", "background-removed.png", "PNG files (*.png)")
        if destination:
            shutil.copyfile(self.output_path, destination)
            self.status_changed.emit(f"Saved {Path(destination).name}")

    @staticmethod
    def _show_image(label: QLabel, path: str | Path) -> None:
        pixmap = QPixmap.fromImage(QImage(str(path))).scaled(300, 290, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pixmap)
