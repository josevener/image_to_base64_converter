"""Main Qt window view; contains no image business logic."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QMenu, QStackedWidget, QVBoxLayout, QWidget

from theme import load_settings, save_settings
from ui.components.tool_page import PlaceholderPage, ToolPage
from ui.header import Header
from ui.sidebar import Sidebar
from ui.statusbar import StatusBar


class MainWindow(QMainWindow):
    """Application shell that exposes navigation signals to the controller."""

    tool_requested = Signal(str)
    SECTIONS = [
        ("CONVERSION", ["Image to Base64", "Base64 to Image", "Format Converter", "ICO Generator", "Favicon Generator"]),
        ("IMAGE EDITING", ["Resize Image", "Compress Image", "Crop Image", "Rotate & Flip", "Background Remover", "Background Color"]),
        ("API TOOLS", ["API Client", "WebSocket Client", "SSE Client", "Webhook Tester", "MQTT Client", "JWT Decoder", "Base64 Encoder", "JSON Formatter", "XML Formatter", "URL Encoder"]),
        ("NETWORK TOOLS", ["Wi-Fi Connections"]),
        ("INFORMATION", ["Image Metadata", "Image Statistics", "Color Picker", "Palette Extractor"]),
        ("QR TOOLS", ["QR Code Reader", "QR Code Generator"]),
        ("LTO", ["Registration Workspace", "Official Receipt"]),
        ("BATCH PROCESSING", ["Batch Converter"]),
        ("UTILITIES", ["Input Activity Monitor", "Favorites", "History", "Settings", "About"]),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self._pages: dict[str, ToolPage] = {}
        self._sidebar_open = True
        self.setWindowTitle("Developer Toolbox")
        self.resize(1040, 690)
        self.setMinimumSize(860, 590)
        self.setAcceptDrops(True)
        self._build()
        self._apply_theme()

    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = Header()
        self.header.menu_clicked.connect(self.toggle_sidebar)
        self.header.theme_clicked.connect(self.toggle_theme)
        self.header.recent_clicked.connect(self.show_recent_menu)
        outer.addWidget(self.header)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.sidebar = Sidebar(self.SECTIONS)
        self.sidebar.tool_requested.connect(self.tool_requested.emit)
        body.addWidget(self.sidebar)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)
        self.statusbar = StatusBar()
        outer.addWidget(self.statusbar)
        self._add_shortcuts()

    def add_page(self, name: str, page: ToolPage) -> None:
        self._pages[name] = page
        self.pages.addWidget(page)

    def show_page(self, name: str) -> None:
        self.pages.setCurrentWidget(self._pages[name])
        self.header.page_name.setText(name)
        self.sidebar.set_active(name)
        self.set_status(f"{name} selected")

    def show_placeholder(self, name: str) -> None:
        page = PlaceholderPage(name)
        self.pages.addWidget(page)
        self.pages.setCurrentWidget(page)
        self.header.page_name.setText(name)
        self.sidebar.set_active(name)
        self.set_status(f"{name} selected")

    def toggle_sidebar(self) -> None:
        opening = not self._sidebar_open
        if opening:
            self.sidebar.show()
        current_width = self.sidebar.width()
        target_width = self.sidebar.EXPANDED_WIDTH if opening else 0
        self._animation = QParallelAnimationGroup(self)
        for property_name in (b"minimumWidth", b"maximumWidth"):
            animation = QPropertyAnimation(self.sidebar, property_name, self._animation)
            animation.setDuration(180)
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            animation.setStartValue(current_width)
            animation.setEndValue(target_width)
            self._animation.addAnimation(animation)
        if not opening:
            self._animation.finished.connect(self.sidebar.hide)
        self._animation.start()
        self._sidebar_open = opening

    def show_recent_menu(self) -> None:
        menu = QMenu(self)
        paths = [path for path in self.settings.get("recent_files", []) if Path(path).is_file()]
        if not paths:
            item = menu.addAction("No recent files")
            item.setEnabled(False)
        for path in paths:
            action = menu.addAction(Path(path).name)
            action.triggered.connect(lambda checked=False, value=path: self.tool_requested.emit(f"recent:{value}"))
        menu.exec(self.header.recent.mapToGlobal(self.header.recent.rect().bottomLeft()))

    def toggle_theme(self) -> None:
        self.settings["theme"] = "Light" if self.settings.get("theme") == "Dark" else "Dark"
        save_settings(self.settings)
        self._apply_theme()

    def set_status(self, message: str) -> None:
        self.statusbar.setText(message)

    def _add_shortcuts(self) -> None:
        action = QAction(self)
        action.setShortcut(QKeySequence("Ctrl+B"))
        action.triggered.connect(self.toggle_sidebar)
        self.addAction(action)

    def dragEnterEvent(self, event: object) -> None:
        if event.mimeData().hasUrls():  # type: ignore[attr-defined]
            event.acceptProposedAction()  # type: ignore[attr-defined]

    def dropEvent(self, event: object) -> None:
        urls = event.mimeData().urls()  # type: ignore[attr-defined]
        if urls:
            self.tool_requested.emit(f"drop:{urls[0].toLocalFile()}")
            event.acceptProposedAction()  # type: ignore[attr-defined]

    def _apply_theme(self) -> None:
        dark = self.settings.get("theme", "Dark") == "Dark"
        background, surface, field, text, muted, border = (
            "#151A21", "#202833", "#111820", "#F7FAFC", "#C2CBD6", "#3B4757"
        ) if dark else (
            "#F4F7FB", "#FFFFFF", "#FFFFFF", "#17212D", "#526274", "#CDD6E0"
        )
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {background}; color: {text}; font-family: 'Segoe UI'; font-size: 13px; }}
            QLabel, QCheckBox, QRadioButton {{ color: {text}; }}
            #header {{ background: {surface}; border-bottom: 1px solid {border}; }} #brand {{ color: {text}; font-size: 19px; font-weight: 700; }}
            #sidebar {{ background: {surface}; border-right: 1px solid {border}; }} #section {{ color: {muted}; font-size: 10px; font-weight: 700; margin: 10px 8px 3px; }}
            #navButton {{ color: {text}; text-align: left; border: 0; border-radius: 6px; padding: 7px 10px; background: transparent; }} #navButton[active="true"] {{ background: #2F80ED; color: white; font-weight: 700; }} #navButton:hover {{ background: #1967D2; color: white; }}
            QToolButton {{ color: {text}; border: 0; border-radius: 6px; padding: 7px 9px; }} QToolButton:hover {{ background: {border}; }}
            #card {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }} #dropArea {{ background: {field}; border: 2px dashed {border}; border-radius: 8px; color: {muted}; }}
            #statsPanel {{ background: {field}; border: 1px solid {border}; border-radius: 7px; }} #statLabel {{ color: {muted}; font-size: 10px; }} #statValue {{ color: {text}; font-weight: 600; }}
            #pageTitle {{ color: {text}; font-size: 24px; font-weight: 700; margin-top: 2px; }} #muted, #status {{ color: {muted}; }} #status {{ padding: 5px 14px; background: {surface}; border-top: 1px solid {border}; }}
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {{ background: {field}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 7px; selection-background-color: #2F80ED; selection-color: white; }}
            QListWidget {{ background: {field}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 4px; }} QListWidget::item {{ color: {text}; padding: 7px; border-radius: 4px; }} QListWidget::item:selected, QListWidget::item:hover {{ background: #2F80ED; color: white; }}
            QLineEdit::placeholder, QPlainTextEdit::placeholder {{ color: {muted}; }} QComboBox::drop-down {{ border: 0; width: 24px; }} QComboBox QAbstractItemView {{ background: {surface}; color: {text}; selection-background-color: #2F80ED; selection-color: white; }}
            QTabWidget::pane {{ border: 1px solid {border}; border-radius: 6px; }} QTabBar::tab {{ background: {surface}; color: {muted}; padding: 8px 12px; border: 1px solid {border}; border-bottom: 0; }} QTabBar::tab:selected {{ background: {field}; color: {text}; font-weight: 600; }}
            QMenu {{ background: {surface}; color: {text}; border: 1px solid {border}; }} QMenu::item:selected {{ background: #2F80ED; color: white; }}
            QPushButton {{ background: #2F80ED; color: #FFFFFF; border: 0; border-radius: 6px; padding: 8px 12px; font-weight: 600; }} QPushButton:hover {{ background: #1967D2; }} QPushButton:disabled {{ background: {border}; color: {muted}; }}
            #secondaryButton {{ background: {field}; color: {text}; border: 1px solid {border}; }} #secondaryButton:hover {{ background: {border}; }}
            QSpinBox, QDateEdit, QDateTimeEdit {{ background: {field}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 5px; }}
            QTableWidget {{ background: {field}; alternate-background-color: {surface}; color: {text}; gridline-color: {border}; border: 1px solid {border}; border-radius: 6px; selection-background-color: #2F80ED; selection-color: white; }}
            QHeaderView::section {{ background: {surface}; color: {text}; padding: 6px; border: 0; border-bottom: 1px solid {border}; }}
            #dangerButton {{ background: #A84242; }} #dangerButton:hover {{ background: #843333; }} #base64Output {{ background: {field}; color: {text}; border: 1px solid {border}; border-radius: 6px; font-family: 'Cascadia Mono'; font-size: 11px; }}
        """)
