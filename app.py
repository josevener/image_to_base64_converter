"""Application controller: connects Qt views to image services."""

from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence

from pages.base64_to_image import Base64ToImagePage
from pages.api_client import ApiClientPage
from pages.background_remover import BackgroundRemoverPage
from pages.compress import CompressPage
from pages.crop import CropPage
from pages.favicon_generator import FaviconGeneratorPage
from pages.format_converter import FormatConverterPage
from pages.ico_generator import IcoGeneratorPage
from pages.image_to_base64 import ImageToBase64Page
from pages.metadata import MetadataPage
from pages.qr_generator import QrGeneratorPage
from pages.qr_reader import QrReaderPage
from pages.resize import ResizePage
from pages.rotate import RotatePage
from pages.settings import SettingsPage
from pages.wifi_connections import WifiConnectionsPage
from ui.main_window import MainWindow


class ApplicationController:
    """Owns page navigation and is the MVC controller for the application."""

    def __init__(self) -> None:
        self.window = MainWindow()
        self._pages = {
            "Image to Base64": ImageToBase64Page(),
            "Base64 to Image": Base64ToImagePage(),
            "API Client": ApiClientPage(),
            "Format Converter": FormatConverterPage(),
            "ICO Generator": IcoGeneratorPage(),
            "Favicon Generator": FaviconGeneratorPage(),
            "Resize Image": ResizePage(),
            "Compress Image": CompressPage(),
            "Crop Image": CropPage(),
            "Rotate & Flip": RotatePage(),
            "Background Remover": BackgroundRemoverPage(),
            "Image Metadata": MetadataPage(),
            "QR Code Reader": QrReaderPage(),
            "QR Code Generator": QrGeneratorPage(),
            "Settings": SettingsPage(),
            "Wi-Fi Connections": WifiConnectionsPage(),
        }
        for name, page in self._pages.items():
            page.status_changed.connect(self.window.set_status)
            self.window.add_page(name, page)
        self.window.tool_requested.connect(self.show_tool)
        self._add_shortcuts()
        self.show_tool("Image to Base64")

    def _add_shortcuts(self) -> None:
        page = self._pages["Image to Base64"]
        for key, callback in (
            ("Ctrl+O", page.browse_image), ("Ctrl+C", lambda: page.copy_output(False)),
            ("Ctrl+S", page.save_output), ("Ctrl+L", page.clear),
            ("Ctrl+V", page.paste_image),
        ):
            action = QAction(self.window)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(callback)
            self.window.addAction(action)

    def show_tool(self, name: str) -> None:
        """Show an available page or the application's standard future-tool page."""
        if name.startswith("recent:") or name.startswith("drop:"):
            path = name.split(":", 1)[1]
            page = self._pages["Image to Base64"]
            self.window.show_page("Image to Base64")
            page.load_image(path)  # type: ignore[attr-defined]
            return
        if name in self._pages:
            self.window.show_page(name)
        else:
            self.window.show_placeholder(name)

    def show(self) -> None:
        self.window.show()
