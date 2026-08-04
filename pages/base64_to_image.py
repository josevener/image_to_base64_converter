"""Base64-to-image view backed by the Base64 service."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)

from pages.components import ImageToolPage
from services.base64_service import decode_data_uri, save_as_image


class Base64ToImagePage(ImageToolPage):
    """Decode Base64/Data URI text, preview it, and save as an image file."""

    FORMATS = {"PNG": "*.png", "JPEG": "*.jpg", "WEBP": "*.webp"}

    def __init__(self) -> None:
        super().__init__("Base64 to Image", "Paste raw Base64 or a Data URI, then preview and save the image.")
        self.decoded_data: bytes | None = None
        self.mime_type = "image/png"
        self._build_content()

    def _build_content(self) -> None:
        workspace = QHBoxLayout()
        workspace.setSpacing(14)
        input_card = QFrame()
        input_card.setObjectName("card")
        input_layout = QVBoxLayout(input_card)
        input_layout.addWidget(QLabel("BASE64 INPUT"))
        self.input = QTextEdit()
        self.input.setObjectName("base64Output")
        self.input.setPlaceholderText("Paste Base64 or data:image/...;base64,... here")
        self.input.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        input_layout.addWidget(self.input, 1)
        actions = QHBoxLayout()
        actions.addWidget(self.button("Paste from Clipboard", self.paste_text))
        actions.addWidget(self.button("Preview Image", self.preview_image))
        input_layout.addLayout(actions)
        workspace.addWidget(input_card, 1)

        preview_card = QFrame()
        preview_card.setObjectName("card")
        preview_card.setFixedWidth(330)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.addWidget(QLabel("IMAGE PREVIEW"))
        self.preview = QLabel("Paste Base64 and select\nPreview Image")
        self.preview.setObjectName("dropArea")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(275)
        preview_layout.addWidget(self.preview, 1)
        self.details = QLabel("No image decoded.")
        self.details.setObjectName("muted")
        self.details.setWordWrap(True)
        preview_layout.addWidget(self.details)
        self.format_choice = QComboBox()
        self.format_choice.addItems(self.FORMATS)
        preview_layout.addWidget(self.format_choice)
        self.save_button = self.button("Save Image", self.save_image)
        self.save_button.setEnabled(False)
        preview_layout.addWidget(self.save_button)
        preview_layout.addWidget(self.button("Clear", self.clear, danger=True))
        workspace.addWidget(preview_card)
        self.content_layout.addLayout(workspace, 1)

    def paste_text(self) -> None:
        self.input.setPlainText(QApplication.clipboard().text())
        self.status_changed.emit("Base64 pasted from clipboard")

    def preview_image(self) -> None:
        try:
            self.mime_type, self.decoded_data = decode_data_uri(self.input.toPlainText())
            image = QImage.fromData(self.decoded_data)
            if image.isNull():
                raise ValueError("Invalid Base64 image data.")
        except ValueError as error:
            QMessageBox.warning(self, "Invalid Base64", str(error))
            self.status_changed.emit(str(error))
            return
        pixmap = QPixmap.fromImage(image).scaled(292, 260, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pixmap)
        self.details.setText(f"{self.mime_type}  •  {image.width()} × {image.height()} px  •  {self.size_text(len(self.decoded_data))}")
        self.save_button.setEnabled(True)
        self.status_changed.emit("Image decoded successfully")

    def save_image(self) -> None:
        if not self.decoded_data:
            return
        image_format = self.format_choice.currentText()
        extension = self.FORMATS[image_format]
        destination, _ = QFileDialog.getSaveFileName(self, "Save Image", f"base64-image.{extension[2:]}", f"{image_format} files ({extension})")
        if not destination:
            return
        try:
            save_as_image(self.input.toPlainText(), destination, image_format)
        except ValueError as error:
            QMessageBox.warning(self, "Unable to save image", str(error))
            return
        self.status_changed.emit(f"Saved {Path(destination).name}")

    def clear(self) -> None:
        self.decoded_data = None
        self.input.clear()
        self.preview.setPixmap(QPixmap())
        self.preview.setText("Paste Base64 and select\nPreview Image")
        self.details.setText("No image decoded.")
        self.save_button.setEnabled(False)
        self.status_changed.emit("Ready")
