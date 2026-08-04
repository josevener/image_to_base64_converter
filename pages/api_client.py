"""Professional HTTP API Client page view."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
)

from pages.components import ImageToolPage
from services.http_service import HttpResponse, parse_key_values, request_api
from services.database_service import DatabaseService


class HttpWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def run(self, request: dict[str, object]) -> None:
        try:
            self.completed.emit(request_api(**request))
        except ValueError as error:
            self.failed.emit(str(error))


class ApiClientPage(ImageToolPage):
    """Tabbed REST/HTTP client using the standard-library HTTP service."""

    METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

    def __init__(self) -> None:
        super().__init__("API Client", "Build, send, and inspect HTTP requests without leaving Developer Toolbox.")
        self._build_content()

    def _build_content(self) -> None:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        request_bar = QHBoxLayout()
        self.method = QComboBox()
        self.method.addItems(self.METHODS)
        self.method.setMinimumWidth(100)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://api.example.com/v1/resource")
        self.send_button = self.button("Send Request", self.send_request)
        request_bar.addWidget(self.method)
        request_bar.addWidget(self.url, 1)
        request_bar.addWidget(self.send_button)
        layout.addLayout(request_bar)
        self.tabs = QTabWidget()
        self.params = self._editor()
        self.params.setPlaceholderText("limit=10\npage=1")
        self.headers = self._editor()
        self.headers.setPlaceholderText("Accept: application/json")
        self.body = self._editor()
        self.body.setPlaceholderText('{\n  "example": true\n}')
        self.tests = self._editor("Request tests will be added here.")
        self.tests.setReadOnly(True)
        self.tabs.addTab(self.params, "Params")
        self.tabs.addTab(self.headers, "Headers")
        self.tabs.addTab(self._authorization_tab(), "Authorization")
        self.tabs.addTab(self.body, "Body")
        self.tabs.addTab(self.tests, "Tests")
        self.response_tab = self._response_tab()
        self.tabs.addTab(self.response_tab, "Response")
        layout.addWidget(self.tabs, 1)
        self.content_layout.addWidget(card, 1)

    @staticmethod
    def _editor(text: str = "") -> QPlainTextEdit:
        editor = QPlainTextEdit(text)
        editor.setObjectName("base64Output")
        editor.setPlaceholderText("One entry per line")
        return editor

    def _authorization_tab(self) -> QFrame:
        panel = QFrame()
        layout = QFormLayout(panel)
        self.authorization = QComboBox()
        self.authorization.addItems(["No auth", "Bearer token", "Basic auth"])
        self.credential = QLineEdit()
        self.credential.setPlaceholderText("Token, or username:password for Basic auth")
        self.credential.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("Type", self.authorization)
        layout.addRow("Credential", self.credential)
        return panel

    def _response_tab(self) -> QFrame:
        panel = QFrame()
        layout = QVBoxLayout(panel)
        self.response_meta = QLabel("Send a request to view the response.")
        self.response_meta.setObjectName("muted")
        self.response_body = self._editor()
        self.response_body.setReadOnly(True)
        layout.addWidget(self.response_meta)
        layout.addWidget(self.response_body, 1)
        return panel

    def send_request(self) -> None:
        try:
            request = {
                "method": self.method.currentText(),
                "url": self.url.text(),
                "params": parse_key_values(self.params.toPlainText()),
                "headers": parse_key_values(self.headers.toPlainText()),
                "body": self.body.toPlainText(),
                "authorization": self.authorization.currentText(),
                "credential": self.credential.text(),
            }
        except ValueError as error:
            QMessageBox.warning(self, "Invalid request", str(error))
            return
        self.send_button.setEnabled(False)
        self.status_changed.emit("Sending HTTP request…")
        self._worker = HttpWorker(self)
        self._worker.completed.connect(self._completed)
        self._worker.failed.connect(self._failed)
        threading.Thread(target=self._worker.run, args=(request,), daemon=True).start()

    def _completed(self, response: HttpResponse) -> None:
        self.send_button.setEnabled(True)
        DatabaseService().record_api_history(self.method.currentText(), self.url.text(), response.status_code, response.elapsed_ms)
        self.response_meta.setText(f"{response.status_code} {response.reason}  •  {response.elapsed_ms:.1f} ms  •  {response.size_bytes:,} bytes")
        self.response_body.setPlainText(response.body)
        self.tabs.setCurrentWidget(self.response_tab)
        self.status_changed.emit(f"Response received: {response.status_code}")

    def _failed(self, message: str) -> None:
        self.send_button.setEnabled(True)
        QMessageBox.warning(self, "Request failed", message)
        self.status_changed.emit(message)
