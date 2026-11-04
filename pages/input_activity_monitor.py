"""Consent-based aggregate keyboard activity monitor view."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QSpinBox, QVBoxLayout

from pages.components import ImageToolPage
from services.input_activity_service import InputActivityService
from services.screenshot_service import ScreenshotService


class InputActivityMonitorPage(ImageToolPage):
    """Shows safe, local keyboard-activity metrics and explicit user controls."""

    PRIVACY_NOTICE = (
        "Privacy notice: This tool records aggregate keyboard activity only. It does not save typed text, "
        "passwords, clipboard data, application content, or key combinations. Optional screen captures are saved "
        "only while visibly enabled. All processing remains local."
    )

    def __init__(self) -> None:
        super().__init__("Input Activity Monitor", "For authorized use on your own device or an organization-managed device with written consent.")
        self.service = InputActivityService()
        repository_root = Path(__file__).resolve().parent.parent
        self.screenshot_service = ScreenshotService(repository_root / "exports" / "screenshots")
        self.values: dict[str, QLabel] = {}
        self._build_content()
        self.timer = QTimer(self)
        self.timer.setInterval(1_000)
        self.timer.timeout.connect(self.refresh_summary)
        self.screenshot_timer = QTimer(self)
        self.screenshot_timer.timeout.connect(self.capture_screens)
        self.refresh_summary()

    def _build_content(self) -> None:
        indicator = QFrame()
        indicator.setObjectName("card")
        indicator_layout = QHBoxLayout(indicator)
        self.status_indicator = QLabel()
        self.status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_indicator.setMinimumWidth(180)
        indicator_layout.addWidget(self.status_indicator)
        description = QLabel("Monitoring never begins automatically. Authorization is required before it can be started.")
        description.setObjectName("muted")
        description.setWordWrap(True)
        indicator_layout.addWidget(description, 1)
        self.content_layout.addWidget(indicator)

        self.authorization = QCheckBox("I confirm that I am authorized to monitor this device and have obtained required user consent.")
        self.authorization.toggled.connect(self.refresh_summary)
        self.content_layout.addWidget(self.authorization)

        capture_card = QFrame()
        capture_card.setObjectName("card")
        capture_layout = QHBoxLayout(capture_card)
        self.capture_enabled = QCheckBox("Enable periodic screen captures while monitoring is active")
        self.capture_enabled.toggled.connect(self._update_capture_schedule)
        self.capture_enabled.toggled.connect(self.refresh_summary)
        capture_layout.addWidget(self.capture_enabled, 1)
        capture_layout.addWidget(QLabel("Interval (seconds):"))
        self.capture_interval = QSpinBox()
        self.capture_interval.setRange(5, 3_600)
        self.capture_interval.setValue(60)
        self.capture_interval.setSuffix(" s")
        self.capture_interval.valueChanged.connect(self._update_capture_schedule)
        self.capture_interval.valueChanged.connect(self.refresh_summary)
        capture_layout.addWidget(self.capture_interval)
        self.content_layout.addWidget(capture_card)

        self.capture_status = QLabel()
        self.capture_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.capture_status.setObjectName("muted")
        self.content_layout.addWidget(self.capture_status)

        metrics_card = QFrame()
        metrics_card.setObjectName("card")
        grid = QGridLayout(metrics_card)
        metrics = (
            ("TOTAL KEYBOARD EVENTS", "total_keyboard_events"), ("EVENTS PER MINUTE", "events_per_minute"),
            ("ACTIVE DURATION", "active_duration_seconds"), ("LETTERS", "letters"),
            ("NUMBERS", "numbers"), ("NAVIGATION KEYS", "navigation_keys"),
            ("FUNCTION KEYS", "function_keys"), ("MODIFIER KEYS", "modifier_keys"),
            ("SHORTCUTS", "shortcuts"), ("OTHER KEYS", "other"),
        )
        for index, (label, key) in enumerate(metrics):
            panel = QFrame()
            panel.setObjectName("statsPanel")
            layout = QVBoxLayout(panel)
            name = QLabel(label)
            name.setObjectName("statLabel")
            value = QLabel("0")
            value.setObjectName("statValue")
            layout.addWidget(name)
            layout.addWidget(value)
            self.values[key] = value
            grid.addWidget(panel, index // 5, index % 5)
        self.content_layout.addWidget(metrics_card)

        buttons = QHBoxLayout()
        self.start_button = self.button("Start Monitoring", self.start_monitoring)
        self.pause_button = self.button("Pause", self.pause_monitoring)
        self.stop_button = self.button("Stop", self.stop_monitoring, danger=True)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.pause_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.button("Reset", self.reset_monitoring))
        buttons.addWidget(self.button("Export Summary", self.export_summary))
        buttons.addStretch()
        self.content_layout.addLayout(buttons)

        audit_card = QFrame()
        audit_card.setObjectName("card")
        audit_layout = QVBoxLayout(audit_card)
        audit_layout.addWidget(QLabel(f"AUDIT LOG — LOCAL WINDOWS USER: {self.service.username}"))
        self.audit_log = QPlainTextEdit()
        self.audit_log.setObjectName("base64Output")
        self.audit_log.setReadOnly(True)
        self.audit_log.setMaximumHeight(125)
        audit_layout.addWidget(self.audit_log)
        self.content_layout.addWidget(audit_card)

        notice = QLabel(self.PRIVACY_NOTICE)
        notice.setWordWrap(True)
        notice.setObjectName("muted")
        self.content_layout.addWidget(notice)
        self.content_layout.addStretch()

    def start_monitoring(self) -> None:
        if not self.authorization.isChecked():
            return
        try:
            self.service.start()
        except (OSError, RuntimeError) as error:
            QMessageBox.warning(self, "Input Activity Monitor", f"Monitoring could not start.\n{error}")
            return
        self.timer.start()
        self._update_capture_schedule()
        self.status_changed.emit("Keyboard activity monitoring is active")
        self.refresh_summary()

    def pause_monitoring(self) -> None:
        self.service.pause()
        self.screenshot_timer.stop()
        self.status_changed.emit("Keyboard activity monitoring is paused")
        self.refresh_summary()

    def stop_monitoring(self) -> None:
        self.service.stop()
        self.timer.stop()
        self.screenshot_timer.stop()
        self.status_changed.emit("Keyboard activity monitoring stopped")
        self.refresh_summary()

    def reset_monitoring(self) -> None:
        self.service.reset()
        self.timer.stop()
        self.screenshot_timer.stop()
        self.status_changed.emit("Keyboard activity summary reset")
        self.refresh_summary()

    def export_summary(self) -> None:
        try:
            repository_root = Path(__file__).resolve().parent.parent
            path = self.service.export_csv(repository_root / "exports")
        except OSError as error:
            QMessageBox.warning(self, "Export summary", f"Could not save the aggregate CSV file.\n{error}")
            return
        self.status_changed.emit(f"Aggregate summary saved to exports/{path.name}")
        QMessageBox.information(self, "Export summary", f"Aggregate-only summary saved to:\n{path}")

    def _update_capture_schedule(self) -> None:
        """Run Qt's timer even while minimized, but only after the visible opt-in."""
        if self.capture_enabled.isChecked() and self.service.is_running:
            self.screenshot_timer.start(self.capture_interval.value() * 1_000)
            self.service.record_audit_event(f"Periodic screen captures enabled ({self.capture_interval.value()} seconds)")
        else:
            self.screenshot_timer.stop()

    def capture_screens(self) -> None:
        """Capture connected displays only during an opt-in, visibly active session."""
        if not (self.capture_enabled.isChecked() and self.service.is_running):
            self.screenshot_timer.stop()
            return
        screens = [(screen.name(), screen.grabWindow(0)) for screen in QGuiApplication.screens()]
        try:
            paths = self.screenshot_service.save_capture(screens)
        except OSError as error:
            self.screenshot_timer.stop()
            self.capture_enabled.setChecked(False)
            QMessageBox.warning(self, "Screen capture", f"Screen capture stopped because it could not save an image.\n{error}")
            return
        self.service.record_audit_event(f"Saved {len(paths)} screen capture(s) locally")
        self.status_changed.emit(f"Saved {len(paths)} screen capture(s) to exports/screenshots")
        self.refresh_summary()

    def refresh_summary(self) -> None:
        summary = self.service.summary()
        for key, label in self.values.items():
            if key == "active_duration_seconds":
                seconds = int(float(summary[key]))
                label.setText(f"{seconds // 60:02}:{seconds % 60:02}")
            elif key == "events_per_minute":
                label.setText(f"{float(summary[key]):.1f}")
            else:
                label.setText(str(summary[key]))
        active = self.service.is_running
        self.status_indicator.setText("MONITORING ACTIVE" if active else "MONITORING PAUSED")
        color = "#36B37E" if active else "#9AA5B1"
        self.status_indicator.setStyleSheet(f"color: {color}; font-weight: 700;")
        self.start_button.setEnabled(self.authorization.isChecked() and not active)
        self.pause_button.setEnabled(active)
        self.stop_button.setEnabled(self.service.has_listener)
        capture_active = self.screenshot_timer.isActive()
        if capture_active:
            self.capture_status.setText(
                f"SCREEN CAPTURE ACTIVE — every {self.capture_interval.value()} seconds; continues while this app is minimized."
            )
            self.capture_status.setStyleSheet("color: #D97706; font-weight: 700;")
        elif self.capture_enabled.isChecked():
            self.capture_status.setText("SCREEN CAPTURE ARMED — begins when monitoring starts.")
            self.capture_status.setStyleSheet("color: #9AA5B1; font-weight: 700;")
        else:
            self.capture_status.setText("SCREEN CAPTURE OFF — enable the checkbox above to opt in.")
            self.capture_status.setStyleSheet("color: #9AA5B1;")
        entries = self.service.audit_entries()
        self.audit_log.setPlainText("\n".join(f"{entry.timestamp} | {entry.username} | {entry.action}" for entry in entries))
        cursor = self.audit_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.audit_log.setTextCursor(cursor)

    def shutdown(self) -> None:
        """Release the listener when the application is closing."""
        self.timer.stop()
        self.screenshot_timer.stop()
        self.service.stop()
