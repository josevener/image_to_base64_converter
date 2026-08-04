"""Wi-Fi Connections view backed by the Windows Wi-Fi service."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QVBoxLayout

from pages.components import ImageToolPage
from services.wifi_service import WifiProfile, WifiServiceError, profile_details, saved_profiles


class WifiWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def load_profiles(self) -> None:
        try:
            self.completed.emit(saved_profiles())
        except WifiServiceError as error:
            self.failed.emit(str(error))

    def load_details(self, profile_name: str, include_password: bool = False) -> None:
        try:
            self.completed.emit(profile_details(profile_name, include_password))
        except WifiServiceError as error:
            self.failed.emit(str(error))


class WifiConnectionsPage(ImageToolPage):
    """List saved/current networks and display selected non-sensitive details."""

    def __init__(self) -> None:
        super().__init__("Wi-Fi Connections", "View the current connection and saved Wi-Fi profiles on this Windows device.")
        self._loaded_once = False
        self._selected_profile: str | None = None
        self._build_content()

    def showEvent(self, event: object) -> None:
        super().showEvent(event)  # type: ignore[arg-type]
        if not self._loaded_once:
            self._loaded_once = True
            QTimer.singleShot(0, self.refresh_profiles)

    def _build_content(self) -> None:
        workspace = QHBoxLayout()
        workspace.setSpacing(14)
        list_card = QFrame()
        list_card.setObjectName("card")
        list_card.setFixedWidth(320)
        list_layout = QVBoxLayout(list_card)
        list_layout.addWidget(QLabel("SAVED NETWORKS"))
        self.networks = QListWidget()
        self.networks.currentItemChanged.connect(self.load_details)
        list_layout.addWidget(self.networks, 1)
        list_layout.addWidget(self.button("Refresh Wi-Fi Networks", self.refresh_profiles))
        workspace.addWidget(list_card)
        detail_card = QFrame()
        detail_card.setObjectName("card")
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.addWidget(QLabel("NETWORK INFORMATION"))
        self.details = QPlainTextEdit("Choose a saved Wi-Fi network to view its information.")
        self.details.setObjectName("base64Output")
        self.details.setReadOnly(True)
        detail_layout.addWidget(self.details, 1)
        self.show_password_button = self.button("Show Saved Password", self.show_password)
        self.show_password_button.setEnabled(False)
        detail_layout.addWidget(self.show_password_button)
        note = QLabel("Passwords are shown only after you explicitly select this button; they are never stored by the app.")
        note.setObjectName("muted")
        detail_layout.addWidget(note)
        workspace.addWidget(detail_card, 1)
        self.content_layout.addLayout(workspace, 1)

    def refresh_profiles(self) -> None:
        self.status_changed.emit("Reading Wi-Fi profiles…")
        self._worker = WifiWorker(self)
        self._worker.completed.connect(self._profiles_loaded)
        self._worker.failed.connect(self._failed)
        threading.Thread(target=self._worker.load_profiles, daemon=True).start()

    def _profiles_loaded(self, profiles: list[WifiProfile]) -> None:
        self.networks.clear()
        for profile in profiles:
            label = f"● {profile.name}" if profile.is_current else profile.name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, profile.name)
            self.networks.addItem(item)
        self.status_changed.emit(f"Loaded {len(profiles)} saved Wi-Fi profiles")

    def load_details(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        self._selected_profile = str(item.data(Qt.ItemDataRole.UserRole))
        self.show_password_button.setEnabled(True)
        self._request_details(self._selected_profile, include_password=False)

    def show_password(self) -> None:
        if not self._selected_profile:
            return
        response = QMessageBox.question(
            self,
            "Show saved password",
            "The saved Wi-Fi password will be shown on screen. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if response == QMessageBox.StandardButton.Yes:
            self._request_details(self._selected_profile, include_password=True)

    def _request_details(self, name: str, include_password: bool) -> None:
        self.status_changed.emit("Reading Wi-Fi details…")
        self._worker = WifiWorker(self)
        self._worker.completed.connect(self._details_loaded)
        self._worker.failed.connect(self._failed)
        threading.Thread(target=self._worker.load_details, args=(name, include_password), daemon=True).start()

    def _details_loaded(self, details: dict[str, str]) -> None:
        self.details.setPlainText("\n".join(f"{key}: {value}" for key, value in details.items()))
        self.status_changed.emit("Wi-Fi network information loaded")

    def _failed(self, message: str) -> None:
        QMessageBox.warning(self, "Wi-Fi Connections", message)
        self.status_changed.emit(message)
