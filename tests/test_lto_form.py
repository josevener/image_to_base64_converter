"""Conditional form flows must reveal the inputs needed for each task."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea
from pages.lto_official_receipt import LtoOfficialReceiptPage
from ui.receipt_form import FormSection


class ReceiptFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.page = LtoOfficialReceiptPage()
        self.page.entry_mode.setCurrentIndex(1)  # Existing tests exercise the complete manual form.
        self.page.inputs["plate_no"].setText("ABC12345")

    def tearDown(self) -> None:
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def test_regular_renewal_keeps_estimation_optional(self) -> None:
        self.assertTrue(self.page.initial_section.isHidden())
        self.assertTrue(self.page.file_section.isHidden())
        self.assertTrue(self.page.previous_section.isHidden())
        self.assertFalse(self.page.estimate_section.expanded())
        self.assertTrue(self.page.inputs["validity"].isReadOnly())
        self.page.estimate_section.toggle.setChecked(True)
        self.assertFalse(self.page.previous_section.isHidden())

    def test_initial_and_transfer_show_relevant_dates(self) -> None:
        self.page.transaction.setCurrentIndex(1)
        self.assertFalse(self.page.initial_section.isHidden())
        self.assertTrue(self.page.initial_known.isChecked())
        self.assertEqual(self.page.initial_years.currentData(), 3)
        self.assertTrue(self.page.renewal_year.isReadOnly())
        self.page.auto_initial_year.setChecked(False)
        self.assertFalse(self.page.renewal_year.isReadOnly())
        self.assertTrue(self.page.previous_section.isHidden())
        self.page.transaction.setCurrentIndex(2)
        self.assertTrue(self.page.initial_section.isHidden())
        self.assertFalse(self.page.previous_section.isHidden())
        self.assertTrue(self.page.previous_expiry.isEnabled())
        self.assertTrue(self.page.estimate_section.isHidden())
        self.assertFalse(self.page.renewal_year.isReadOnly())

    def test_no_plate_and_manual_notice(self) -> None:
        self.page.inputs["plate_no"].clear()
        self.assertFalse(self.page.file_section.isHidden())
        self.page.auto_validity.setChecked(False)
        self.assertTrue(self.page.file_section.isHidden())
        self.assertFalse(self.page.inputs["validity"].isReadOnly())
        self.page.inputs["validity"].setText("Confirmed dates from OR/CR")
        self.assertEqual(self.page.values()[0]["validity"], "Confirmed dates from OR/CR")

    def test_online_payment_preserves_cash_details(self) -> None:
        self.page.inputs["cashier"].setText("Example cashier")
        self.page.payment_channel.setCurrentIndex(1)
        self.assertTrue(self.page.cash_section.isHidden())
        self.assertEqual(self.page.values()[0]["cashier"], "")
        self.page.payment_channel.setCurrentIndex(0)
        self.assertFalse(self.page.cash_section.isHidden())
        self.assertEqual(self.page.values()[0]["cashier"], "Example cashier")

    def test_wheel_scrolls_form_without_changing_focused_values(self) -> None:
        self.page.resize(1000, 460)
        self.page.show()
        self.page.payment_channel.setCurrentIndex(1)
        cases = ((0, self.page.date, self.page.date.dateTime),
                 (2, self.page.renewal_year, self.page.renewal_year.value),
                 (2, self.page.engine_cc, self.page.engine_cc.value),
                 (2, self.page.transaction, self.page.transaction.currentIndex),
                 (3, self.page.payment_channel, self.page.payment_channel.currentIndex),
                 (3, self.page.mode, self.page.mode.currentText),
                 (4, self.page.qr_level, self.page.qr_level.currentText),
                 (4, self.page.qr_version, self.page.qr_version.currentIndex))
        for tab, control, get_value in cases:
            with self.subTest(control=control):
                self.page.tabs.setCurrentIndex(tab)
                for section in self.page.findChildren(FormSection):
                    if section.toggle and section.body.isAncestorOf(control):
                        section.toggle.setChecked(True)
                self.app.processEvents()
                area = control.parentWidget()
                while not isinstance(area, QScrollArea):
                    area = area.parentWidget()
                scrollbar = area.verticalScrollBar()
                self.assertGreater(scrollbar.maximum(), 0)
                targets = [control]
                if hasattr(control, "lineEdit") and control.lineEdit() is not None:
                    targets.append(control.lineEdit())
                for target in targets:
                    scrollbar.setValue(0)
                    control.setFocus()
                    before = get_value()
                    position = target.rect().center()
                    wheel = QWheelEvent(QPointF(position), QPointF(target.mapToGlobal(position)),
                                        QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
                    self.app.sendEvent(target, wheel)
                    self.assertEqual(get_value(), before)
                    self.assertGreater(scrollbar.value(), 0)

    def test_keyboard_adjustment_and_click_cursors(self) -> None:
        year = self.page.renewal_year.value()
        QTest.keyClick(self.page.renewal_year, Qt.Key.Key_Up)
        self.assertEqual(self.page.renewal_year.value(), year + 1)
        self.assertEqual(self.page.next_button.cursor().shape(), Qt.CursorShape.PointingHandCursor)
        self.assertEqual(self.page.back_button.cursor().shape(), Qt.CursorShape.ArrowCursor)
        self.page.tabs.setCurrentIndex(1)
        self.assertEqual(self.page.back_button.cursor().shape(), Qt.CursorShape.PointingHandCursor)
        self.assertEqual(self.page.inputs["office"].cursor().shape(), Qt.CursorShape.IBeamCursor)
