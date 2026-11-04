"""Reusable Qt form sections and a readable receipt-notice editor."""

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPointF, QRegularExpression, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QFormLayout,
    QFrame, QLabel, QLineEdit, QPlainTextEdit, QScrollArea, QSizePolicy, QTabBar,
    QStyledItemDelegate, QStyleOptionViewItem, QToolButton, QVBoxLayout, QWidget,
)


class FormInteractions(QObject):
    """Keep wheel input for scrolling, even when a value control has keyboard focus."""

    def __init__(self, root: QWidget) -> None:
        super().__init__(root)
        self._wheel_targets: set[QObject] = set()
        for widget in root.findChildren(QWidget):
            if isinstance(widget, (QComboBox, QAbstractSpinBox)):
                widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                self._wheel_targets.add(widget)
                widget.installEventFilter(self)
                editor = widget.lineEdit() if isinstance(widget, QAbstractSpinBox) or widget.isEditable() else None
                if editor:
                    self._wheel_targets.add(editor)
                    editor.installEventFilter(self)
                if isinstance(widget, QAbstractSpinBox):
                    widget.setKeyboardTracking(False)
            if isinstance(widget, (QAbstractButton, QComboBox, QTabBar)):
                widget.installEventFilter(self)
                self._cursor(widget)
            elif isinstance(widget, QLineEdit):
                widget.setCursor(Qt.CursorShape.IBeamCursor)

    @staticmethod
    def _cursor(widget: QWidget) -> None:
        widget.setCursor(Qt.CursorShape.PointingHandCursor if widget.isEnabled() else Qt.CursorShape.ArrowCursor)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.EnabledChange and isinstance(watched, (QAbstractButton, QComboBox, QTabBar)):
            self._cursor(watched)
        if event.type() == QEvent.Type.Wheel and watched in self._wheel_targets:
            # Explicit forwarding also covers wheel events over embedded line editors.
            parent = watched.parentWidget()
            while parent is not None and not isinstance(parent, QScrollArea):
                parent = parent.parentWidget()
            if parent is not None:
                viewport = parent.viewport()
                forwarded = QWheelEvent(
                    QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())), event.globalPosition(),
                    event.pixelDelta(), event.angleDelta(), event.buttons(), event.modifiers(),
                    event.phase(), event.inverted(),
                )
                QApplication.sendEvent(viewport, forwarded)
            event.accept()
            return True
        return super().eventFilter(watched, event)


class PaymentAmountDelegate(QStyledItemDelegate):
    """Align money consistently and restrict editing to decimal PHP amounts."""

    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().initStyleOption(option, index)
        option.displayAlignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> QLineEdit:
        editor = QLineEdit(parent)
        editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        editor.setPlaceholderText("0.00")
        editor.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9]{0,9}(?:\.[0-9]{0,2})?"), editor))
        return editor


class FormSection(QFrame):
    expanded_changed = Signal()

    def __init__(self, title: str, description: str = "", collapsible: bool = False) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setStyleSheet("QLabel, QCheckBox { background: transparent; } QWidget#formSectionBody { background: transparent; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        self.toggle: QToolButton | None = None
        if collapsible:
            self.toggle = QToolButton()
            self.toggle.setText("+ " + title)
            self.toggle.setCheckable(True)
            self.toggle.setObjectName("formSectionToggle")
            self.toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.toggle.setMinimumHeight(28)
            self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(self.toggle)
        else:
            heading = QLabel(title)
            heading.setObjectName("formSectionTitle")
            layout.addWidget(heading)
        if description:
            description_label = QLabel(description)
            description_label.setObjectName("muted")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)
        self.body = QWidget()
        self.body.setObjectName("formSectionBody")
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setVerticalSpacing(8)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addWidget(self.body)
        if self.toggle:
            self.body.hide()
            self.toggle.toggled.connect(lambda checked: self._expand(checked, title))

    def _expand(self, checked: bool, title: str) -> None:
        self.body.setVisible(checked)
        self.toggle.setText(("− " if checked else "+ ") + title)
        self.expanded_changed.emit()

    def expanded(self) -> bool:
        return self.toggle is None or self.toggle.isChecked()


class ReceiptNoticeEdit(QPlainTextEdit):
    """Keep the text-field contract while displaying the complete renewal sentence."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(92)
        self.setTabChangesFocus(True)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, value: str) -> None:
        if value != self.toPlainText():
            self.setPlainText(value)
