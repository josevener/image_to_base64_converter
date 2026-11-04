"""The short receipt flow needs no existing vehicle or registration records."""

import os
import calendar
import hashlib
from urllib.parse import parse_qs, urlsplit
import re
import sqlite3
from datetime import datetime
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QDate, QTime, QDateTime
from services import database_service as database
from services.lto_receipt_automation import OFFICE_DEFAULTS, automated_fields, fresh_identifiers, validate_inputs, aligned_plate_endings, align_generated_plate, align_generated_references, _random_plate
from services.lto_registration_service import renewal_window
from services.lto_receipt_service import ReceiptData, qr_payload, make_qr_widget, automated_qr_url


def manual_values():
    return {**OFFICE_DEFAULTS, "payer": "EXAMPLE, TEST OWNER", "address": "123 Example Street",
            "client_id": "TEST-CLIENT-001", "color": "WHITE", "year_model": "2026",
            "payment_mode": "GCash"}


class AutomaticReceiptTests(unittest.TestCase):
    def test_opt_in_tx_format_survives_date_alignment_and_collision_retry(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "numbers.db"
            selected = datetime(2026, 10, 14)
            fields = fresh_identifiers("1396", target, selected, use_tx_format=True)
            self.assertRegex(fields["transaction_no"], r"^TX-MVIRS-20261014-[0-9]{6}$")
            changed = align_generated_references(fields, datetime(2025, 4, 28).date(), target,
                                                 use_tx_format=True)
            self.assertTrue(changed["transaction_no"].startswith("TX-MVIRS-20250428-"))
            self.assertEqual(changed["receipt_no"], fields["receipt_no"])
            default = align_generated_references(changed, datetime(2025, 4, 28).date(), target)
            self.assertTrue(default["transaction_no"].startswith("MAIRD-SAR-20250428-"))
            with patch("services.lto_receipt_automation.secrets.randbelow", return_value=54321):
                restored = align_generated_references(default, datetime(2025, 4, 28).date(), target,
                                                      use_tx_format=True)
            self.assertEqual(restored["transaction_no"], "TX-MVIRS-20250428-154321")
            self.assertEqual(restored["receipt_no"], fields["receipt_no"])

    def test_automatic_link_known_sha256_vector_and_packed_parameters(self):
        fields = {"receipt_no": "1396-000000459198", "transaction_no": "abc"}
        url = automated_qr_url(fields)
        self.assertEqual(parse_qs(urlsplit(url).query), {"p": [
            "PUBLIC_PORTAL:ORV:::NO:200:P200_OR,P200_HASH:1396-000000459198,"
            "BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD"]})
        self.assertEqual(automated_qr_url(fields), url)
        with self.assertRaisesRegex(ValueError, "receipt number"):
            automated_qr_url({**fields, "receipt_no": "OR,INJECTED:ITEM"})
        with self.assertRaisesRegex(ValueError, "Transaction number"):
            automated_qr_url({**fields, "transaction_no": ""})

    def test_both_six_character_plate_formats_keep_numeric_renewal_digits(self):
        registered = datetime(2026, 10, 14).date()
        for numbers, characters, expected in (([0, 17], ["40", "Q", "B"], "Q1740B"),
                                               ([1, 5], ["40", "T", "Z", "S"], "640TZS"),
                                               ([1, 0], ["40", "T", "Z", "S"], "140TZS"),
                                               ([1, 8], ["40", "T", "Z", "S"], "940TZS")):
            with patch("services.lto_receipt_automation.secrets.randbelow", side_effect=numbers), \
                 patch("services.lto_receipt_automation.secrets.choice", side_effect=characters):
                plate = _random_plate(registered)
            self.assertEqual(plate, expected)
            self.assertEqual(len(plate), 6)
            start, end = renewal_window(plate, 2029)
            self.assertEqual((start.month, start.day, end.day), (10, 8, 14))

    def test_durable_unique_sample_format_identifiers_and_validation(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "counter.db"
            first = fresh_identifiers("1396", target, datetime(2026, 11, 4, 10, 30))
            second = fresh_identifiers("1396", target)
            for key in ("receipt_no", "transaction_no", "plate_no", "file_no"):
                self.assertNotEqual(first[key], second[key])
            self.assertEqual(len(first["file_no"]), 15)
            self.assertRegex(first["receipt_no"], r"^1396-[0-9]{12}$")
            self.assertRegex(first["transaction_no"], r"^MAIRD-SAR-20261104-[0-9]{6}$")
            self.assertEqual(len(first["plate_no"]), 6)
            self.assertRegex(first["plate_no"], r"^(?:[A-Z][0-9]{4}[A-Z]|[0-9]{3}[A-Z]{3})$")
            self.assertNotIn("LOCAL", str(first))
            fields = automated_fields(manual_values(), first)
            self.assertEqual(fields["payment_channel"], "online")
            self.assertEqual(fields["location"], "-")
            self.assertIn("SAMPLE", fields["document_label"])
            with self.assertRaisesRegex(ValueError, "Received from"):
                validate_inputs({**manual_values(), "payer": ""})

    def test_random_fields_are_independent_and_collisions_roll_back(self):
        moment = datetime(2026, 11, 4, 10, 30)
        with TemporaryDirectory() as directory:
            target = Path(directory) / "numbers.db"
            with closing(sqlite3.connect(target)) as connection, connection:
                connection.execute("CREATE TABLE receipt_counter(id INTEGER PRIMARY KEY, value INTEGER)")
                connection.execute("INSERT INTO receipt_counter VALUES(1, 12)")
            with patch("services.lto_receipt_automation.secrets.randbelow", side_effect=[42, 12345, 7554489]), \
                 patch("services.lto_receipt_automation._random_plate", return_value="A6790B"):
                first = fresh_identifiers("1396", target, moment)
            self.assertEqual(first["receipt_no"], "1396-000000100042")
            self.assertEqual(first["transaction_no"], "MAIRD-SAR-20261104-112345")
            self.assertEqual(first["plate_no"], "A6790B")
            self.assertEqual(first["file_no"], "139626007554490")
            # The first retry inserts an OR and then collides on transaction; no partial set survives.
            collision = {**first, "receipt_no": "1396-000000999999"}
            second = {**first, "receipt_no": "1396-000000200123", "transaction_no": "MAIRD-SAR-20261104-789654",
                      "plate_no": "123YZS", "file_no": "139698765432109"}
            with patch("services.lto_receipt_automation._random_identifiers", side_effect=[collision, second]) as randomize:
                self.assertEqual(fresh_identifiers("1396", target, moment), second)
                self.assertEqual(randomize.call_count, 2)
            with closing(sqlite3.connect(target)) as connection, connection:
                self.assertEqual(connection.execute("SELECT value FROM receipt_counter").fetchone()[0], 12)
                self.assertEqual(connection.execute("SELECT count(*) FROM random_receipt_identifiers").fetchone()[0], 8)
                self.assertEqual(connection.execute("SELECT count(*) FROM random_receipt_identifiers WHERE value=?",
                                                    (collision["receipt_no"],)).fetchone()[0], 0)

    def test_generated_plate_targets_the_three_year_anniversary(self):
        self.assertEqual(set(aligned_plate_endings(datetime(2026, 10, 14).date())), {"40", "50", "60"})
        with TemporaryDirectory() as directory:
            target = Path(directory) / "numbers.db"
            original = fresh_identifiers("1396", target, datetime(2026, 10, 14))
            start, end = renewal_window(original["plate_no"], 2029)
            self.assertEqual((start.month, start.day, end.day), (10, 8, 14))
            self.assertEqual(align_generated_plate(original, datetime(2026, 10, 14).date(), target), original)
            changed = align_generated_plate(original, datetime(2026, 5, 25).date(), target)
            self.assertEqual(re.search(r"[0-9]+", changed["plate_no"]).group()[-1], "5")
            for key in ("receipt_no", "transaction_no", "file_no"):
                self.assertEqual(changed[key], original[key])
        # Early-month, leap-day and unavailable November/December plate-month boundaries.
        for registered in (datetime(2026, 1, 1), datetime(2026, 10, 3), datetime(2024, 2, 29), datetime(2026, 12, 15)):
            cap = registered.date().replace(year=registered.year + 3, day=28 if registered.month == 2 else registered.day)
            endings = aligned_plate_endings(registered.date())
            for ending in endings:
                end = renewal_window("AB000" + ending, cap.year)[1]
                if end > cap:
                    end = renewal_window("AB000" + ending, cap.year - 1)[1]
                self.assertLessEqual(end, cap)

    def test_selected_date_controls_transaction_date_and_sample_mv_year(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "numbers.db"
            fields = fresh_identifiers("1336", target, now=datetime(2026, 11, 4),
                                       registration_date=datetime(2026, 10, 14).date())
            self.assertRegex(fields["transaction_no"], r"^MAIRD-SAR-20261014-[0-9]{6}$")
            self.assertRegex(fields["file_no"], r"^13362600[0-9]{7}$")
            changed = align_generated_references(fields, datetime(2025, 4, 28).date(), target)
            self.assertEqual(changed["transaction_no"], "MAIRD-SAR-20250428-" + fields["transaction_no"].rsplit("-", 1)[-1])
            self.assertEqual(changed["file_no"], "133625" + fields["file_no"][6:])
            self.assertEqual(changed["receipt_no"], fields["receipt_no"])
            self.assertEqual(align_generated_references(changed, datetime(2025, 4, 28).date(), target), changed)
            next_day = align_generated_references(changed, datetime(2025, 4, 29).date(), target)
            self.assertEqual(next_day["file_no"], changed["file_no"])
            self.assertTrue(next_day["transaction_no"].startswith("MAIRD-SAR-20250429-"))
            older = {**next_day, "file_no": "139642483513451"}
            normalized = align_generated_references(older, datetime(2025, 4, 29).date(), target)
            self.assertRegex(normalized["file_no"], r"^13362500[0-9]{7}$")

    def test_generate_preview_export_and_fresh_without_registry(self):
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch.object(database, "DATA_DIRECTORY", folder), patch.object(database, "DATABASE_PATH", folder / "settings.db"), \
                 patch.object(database.DatabaseService, "_migrate_project_database"):
                from app import ApplicationController
                controller = ApplicationController()
                page = controller._pages["Official Receipt"]
                try:
                    self.assertTrue(page.automated())
                    self.assertFalse(page.use_tx_format.isChecked())
                    self.assertTrue(page.tabs.isHidden())
                    self.assertFalse(hasattr(page, "quick_qr_text"))
                    self.assertEqual(page.values()[0]["qr_version"], "auto")
                    self.assertEqual(page.quick_inputs["office_code"].text(), "1396")
                    controller.preview_receipt()
                    self.assertIn("Received from", page.error_banner.text())
                    self.assertFalse((folder / "lto_receipt_numbers.db").exists())
                    for key, value in manual_values().items():
                        if key in page.quick_inputs:
                            page.quick_inputs[key].setText(value)
                    page.quick_mode.setCurrentText("GCash")
                    page.fresh_button.click()
                    app.processEvents()
                    self.assertTrue(page.error_banner.isHidden(), page.error_banner.text())
                    self.assertEqual(page.document.pageCount(), 1)
                    first, charges = page.values()
                    first_qr = qr_payload(ReceiptData(first, []))
                    packed = parse_qs(urlsplit(first_qr).query)["p"][0]
                    self.assertEqual(packed, "PUBLIC_PORTAL:ORV:::NO:200:P200_OR,P200_HASH:"
                                     + first["receipt_no"] + ","
                                     + hashlib.sha256(first["transaction_no"].encode()).hexdigest().upper())
                    make_qr_widget(ReceiptData(first, [])).getBounds()
                    digits = re.search(r"[0-9]+", first["plate_no"]).group()
                    month = int(digits[-1]) or 10
                    week = int(digits[-2])
                    year = datetime.now().year + 3
                    start, end = ((1, 7) if week in (1, 2, 3) else (8, 14) if week in (4, 5, 6)
                                  else (15, 21) if week in (7, 8) else (22, calendar.monthrange(year, month)[1]))
                    today = datetime.now().date()
                    if (month, end) > (today.month, today.day):
                        year -= 1
                        if start == 22:
                            end = calendar.monthrange(year, month)[1]
                    self.assertIn(f"{month:02d}/{start:02d}/{year} - {month:02d}/{end:02d}/{year}", first["validity"])
                    self.assertEqual(first["classification"], "Private - (PVT)")
                    self.assertEqual(first["client_id"], "TEST-CLIENT-001")
                    self.assertEqual(sum(float(value) for _, value in charges), 948)
                    page.quick_inputs["color"].setText("BLACK")
                    controller.preview_receipt()
                    self.assertEqual(page.values()[0]["receipt_no"], first["receipt_no"])
                    target = folder / (first["receipt_no"] + ".pdf")
                    with patch.object(page, "export_path", return_value=str(target)) as select:
                        controller.export_receipt()
                    select.assert_called_once_with(target.name)
                    self.assertTrue(target.read_bytes().startswith(b"%PDF"))
                    self.assertEqual(page.values()[0]["receipt_no"], first["receipt_no"])
                    self.assertEqual(page.values()[0]["color"], "BLACK")
                    self.assertEqual(qr_payload(ReceiptData(page.values()[0], [])), first_qr)
                    for kind, method in (("ewallet", "Maya"), ("online", "Bank transfer"), ("cash", "Cash")):
                        page.quick_payment_type.setCurrentIndex(page.quick_payment_type.findData(kind))
                        page.quick_mode.setCurrentText(method)
                        controller.preview_receipt()
                        payment = page.values()[0]
                        self.assertEqual(payment["payment_mode"], method)
                        self.assertEqual(payment["payment_channel"], "cash" if kind == "cash" else "online")
                        self.assertEqual(payment["location"], payment["office"] if kind == "cash" else "-")
                        self.assertEqual(payment["receipt_no"], first["receipt_no"])
                    page.quick_date.setDateTime(QDateTime(QDate(2024, 12, 15), QTime(9, 30)))
                    controller.preview_receipt()
                    edited = page.values()[0]
                    self.assertNotEqual(qr_payload(ReceiptData(edited, [])), first_qr)
                    self.assertEqual(edited["date"], "12/15/2024 9:30 AM")
                    self.assertTrue(edited["transaction_no"].startswith("MAIRD-SAR-20241215-"))
                    self.assertRegex(edited["file_no"], r"^13962400[0-9]{7}$")
                    self.assertIn("2027", edited["validity"])
                    self.assertEqual(edited["receipt_no"], first["receipt_no"])
                    self.assertTrue(page.quick_date_overridden)
                    page.fresh_button.click()
                    self.assertNotEqual(page.values()[0]["receipt_no"], first["receipt_no"])
                    self.assertEqual(page.values()[0]["date"], "12/15/2024 9:30 AM")
                    current_or = page.values()[0]["receipt_no"]
                    page.quick_date.setDateTime(QDateTime(QDate(2026, 10, 14), QTime(14, 45)))
                    controller.preview_receipt()
                    october = page.values()[0]
                    self.assertEqual(october["receipt_no"], current_or)
                    self.assertEqual(october["date"], "10/14/2026 2:45 PM")
                    self.assertTrue(october["transaction_no"].startswith("MAIRD-SAR-20261014-"))
                    self.assertRegex(october["file_no"], r"^13962600[0-9]{7}$")
                    self.assertIn("10/2029", october["validity"])
                    self.assertIn("10/08/2029 - 10/14/2029", october["validity"])
                    self.assertIn(re.search(r"[0-9]+", october["plate_no"]).group()[-2:], ("40", "50", "60"))
                    original_qr = qr_payload(ReceiptData(october, []))
                    page.use_tx_format.setChecked(True)
                    controller.preview_receipt()
                    legacy = page.values()[0]
                    self.assertEqual(legacy["receipt_no"], october["receipt_no"])
                    self.assertTrue(legacy["transaction_no"].startswith("TX-MVIRS-20261014-"))
                    self.assertNotEqual(qr_payload(ReceiptData(legacy, [])), original_qr)
                    controller.preview_receipt()
                    self.assertEqual(page.values()[0]["transaction_no"], legacy["transaction_no"])
                    page.fresh_button.click()
                    self.assertTrue(page.values()[0]["transaction_no"].startswith("TX-MVIRS-20261014-"))
                    page.use_tx_format.setChecked(False)
                    controller.preview_receipt()
                    self.assertTrue(page.values()[0]["transaction_no"].startswith("MAIRD-SAR-20261014-"))
                    page.entry_mode.setCurrentIndex(1)
                    custom = "MANUAL-TEST-QR"
                    page.qr_text.setText(custom)
                    page.qr_mode.setCurrentIndex(page.qr_mode.findData("text"))
                    self.assertEqual(page.values()[0]["qr_payload"], custom)
                    page.entry_mode.setCurrentIndex(0)
                    self.assertEqual(page.values()[0]["qr_mode"], "automated")
                    controller.preview_receipt()
                    page.fresh_button.click()
                    page.entry_mode.setCurrentIndex(1)
                    self.assertEqual(page.values()[0]["qr_payload"], custom)
                    page.entry_mode.setCurrentIndex(0)
                    page.today_button.click()
                    self.assertFalse(page.quick_date_overridden)
                    page.entry_mode.setCurrentIndex(1)
                    self.assertFalse(page.tabs.isHidden())
                    self.assertEqual(page.inputs["payer"].text(), "EXAMPLE, TEST OWNER")
                    self.assertIsNone(controller._lto_workflow)
                finally:
                    controller.shutdown()
                    controller.window.close()
                    controller.window.deleteLater()
                    app.processEvents()
