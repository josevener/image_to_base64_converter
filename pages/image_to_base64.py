"""Image-to-Base64 view backed by the image service."""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTextEdit, QVBoxLayout

from pages.components import ImageToolPage
from services.image_service import ConversionResult, SUPPORTED_EXTENSIONS, convert_image, is_supported_image
from theme import add_recent, load_settings, save_settings


class ConversionWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def run(self, path: str) -> None:
        try:
            self.completed.emit(convert_image(path))
        except ValueError as error:
            self.failed.emit(str(error))


class ImageToBase64Page(ImageToolPage):
    """Fully functional Base64 encoding page."""

    def __init__(self) -> None:
        super().__init__("Image to Base64", "Encode an image as raw Base64 or a ready-to-use Data URI.")
        self.result: ConversionResult | None = None
        self.settings = load_settings()
        self._build_content()

    def _build_content(self) -> None:
        workspace = QHBoxLayout()
        workspace.setSpacing(14)
        left = QFrame()
        left.setObjectName("card")
        left.setFixedWidth(300)
        left_layout = QVBoxLayout(left)
        self.preview = QLabel("Drop an image anywhere\nor browse to begin")
        self.preview.setObjectName("dropArea")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(290)
        left_layout.addWidget(self.preview, 1)
        left_layout.addWidget(self.button("Browse Image", self.browse_image))
        self.open_button = self.button("Open Image", self.open_image)
        self.open_button.setEnabled(False)
        left_layout.addWidget(self.open_button)
        workspace.addWidget(left)
        right = QFrame()
        right.setObjectName("card")
        right_layout = QVBoxLayout(right)
        self.uri_checkbox = QCheckBox("Include Data URI Prefix")
        self.uri_checkbox.toggled.connect(self.refresh_output)
        right_layout.addWidget(self.uri_checkbox)
        stats = QFrame()
        stats.setObjectName("statsPanel")
        stats_layout = QGridLayout(stats)
        stats_layout.setContentsMargins(10, 8, 10, 8)
        self.stat_values: dict[str, QLabel] = {}
        for index, name in enumerate(("Image Size", "Dimensions", "File Type", "Base64 Length", "Encoding Time")):
            row, column = divmod(index, 3)
            label = QLabel(name)
            label.setObjectName("statLabel")
            value = QLabel("—")
            value.setObjectName("statValue")
            self.stat_values[name] = value
            cell = QVBoxLayout()
            cell.addWidget(label)
            cell.addWidget(value)
            stats_layout.addLayout(cell, row, column)
        right_layout.addWidget(stats)
        self.output = QTextEdit()
        self.output.setObjectName("base64Output")
        self.output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.output.setReadOnly(True)
        right_layout.addWidget(self.output, 1)
        actions = QGridLayout()
        self.copy_raw = self.button("Copy Base64", lambda: self.copy_output(False))
        self.copy_uri = self.button("Copy Data URI", lambda: self.copy_output(True))
        self.save_button = self.button("Save as .txt", self.save_output)
        self.clear_button = self.button("Clear", self.clear, danger=True)
        for button in (self.copy_raw, self.copy_uri, self.save_button):
            button.setEnabled(False)
        actions.addWidget(self.copy_raw, 0, 0)
        actions.addWidget(self.copy_uri, 0, 1)
        actions.addWidget(self.save_button, 0, 2)
        actions.addWidget(self.clear_button, 1, 2)
        right_layout.addLayout(actions)
        workspace.addWidget(right, 1)
        self.content_layout.addLayout(workspace, 1)

    def browse_image(self) -> None:
        patterns = " ".join(f"*{extension}" for extension in SUPPORTED_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(self, "Select an image", self.settings.get("last_folder", ""), f"Image files ({patterns})")
        if path:
            self.load_image(path)

    def load_image(self, path: str) -> None:
        if not is_supported_image(path):
            QMessageBox.warning(self, "Invalid image", "Invalid image file.")
            return
        self.status_changed.emit("Converting image…")
        self._worker = ConversionWorker(self)
        self._worker.completed.connect(self._complete)
        self._worker.failed.connect(self._failed)
        threading.Thread(target=self._worker.run, args=(path,), daemon=True).start()

    def _complete(self, result: ConversionResult) -> None:
        self.result = result
        self.settings["last_folder"] = str(result.path.parent)
        add_recent(self.settings, str(result.path))
        save_settings(self.settings)
        pixmap = QPixmap.fromImage(QImage(str(result.path))).scaled(264, 270, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pixmap)
        self.stat_values["Image Size"].setText(self.size_text(result.size_bytes))
        self.stat_values["Dimensions"].setText(f"{result.dimensions[0]} × {result.dimensions[1]} px")
        self.stat_values["File Type"].setText(result.mime_type)
        self.stat_values["Base64 Length"].setText(f"{len(result.raw_base64):,} characters")
        self.stat_values["Encoding Time"].setText(f"{result.elapsed_ms:.1f} ms")
        self.refresh_output()
        for button in (self.copy_raw, self.copy_uri, self.save_button, self.open_button):
            button.setEnabled(True)
        self.status_changed.emit(f"Converted {result.path.name}")

    def _failed(self, message: str) -> None:
        QMessageBox.warning(self, "Conversion error", message)
        self.status_changed.emit(message)

    def refresh_output(self) -> None:
        self.output.setPlainText(self.result.text(self.uri_checkbox.isChecked()) if self.result else "")

    def copy_output(self, data_uri: bool) -> None:
        if self.result:
            QApplication.clipboard().setText(self.result.text(data_uri))
            self.status_changed.emit("Copied!")

    def save_output(self) -> None:
        if self.result:
            path, _ = QFileDialog.getSaveFileName(self, "Save Base64", "", "Text files (*.txt)")
            if path:
                Path(path).write_text(self.result.text(self.uri_checkbox.isChecked()), encoding="utf-8")
                self.status_changed.emit(f"Saved {Path(path).name}")

    def open_image(self) -> None:
        if self.result:
            os.startfile(self.result.path)  # type: ignore[attr-defined]

    def paste_image(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard.mimeData().hasImage():
            path = Path(tempfile.gettempdir()) / "developer_toolbox_clipboard.png"
            clipboard.image().save(str(path), "PNG")
            self.load_image(str(path))
        else:
            self.status_changed.emit("Clipboard does not contain an image.")

    def clear(self) -> None:
        self.result = None
        self.preview.setPixmap(QPixmap())
        self.preview.setText("Drop an image anywhere\nor browse to begin")
        for value in self.stat_values.values():
            value.setText("—")
        self.output.clear()
        for button in (self.copy_raw, self.copy_uri, self.save_button, self.open_button):
            button.setEnabled(False)
        self.status_changed.emit("Ready")
