"""Review registration estimates before applying them to the receipt form."""

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)
from ui.receipt_form import FormInteractions


class RegistrationSuggestionsDialog(QDialog):
    def __init__(self, validity: str, charges: list[tuple[str, str]], explanation: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review registration suggestions")
        self.resize(620, 540)
        layout = QVBoxLayout(self)
        heading = QLabel("Review the estimates, then choose which receipt fields to replace.")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        lines = ["SUGGESTED VALIDITY", validity, "", "SUGGESTED PAYMENT ITEMS"]
        lines.extend(f"{label}: PHP {amount}" for label, amount in charges)
        if not charges:
            lines.append("None. Existing payment items will be retained.")
        lines.extend(["", explanation])
        details.setPlainText("\n".join(lines))
        layout.addWidget(details)
        self.apply_validity = QCheckBox("Replace the validity / renewal notice")
        self.apply_validity.setChecked(True)
        self.apply_charges = QCheckBox("Replace ALL existing payment items with these suggestions")
        self.apply_charges.setEnabled(bool(charges))
        layout.addWidget(self.apply_validity)
        layout.addWidget(self.apply_charges)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._interactions = FormInteractions(self)
