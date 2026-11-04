"""Regression checks for monetary validation and the exported receipt artifact."""

import os
import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from services.lto_receipt_service import (
    Charge, ReceiptData, amount_in_words, generate_receipt, parse_amount, save_receipt, receipt_filename,
)


def example_data() -> ReceiptData:
    return ReceiptData({
        "receipt_no": "TEST-2026-000001", "payer": "TEST, MARIA PEÑA",
        "address": "123 Example Street, Dasmariñas, Cavite", "office": "TEST DISTRICT OFFICE",
        "office_code": "0000", "office_address": "EXAMPLE OFFICE ADDRESS",
        "office_tin": "000000000000", "date": "11/04/2026 4:05 PM",
        "payer_tin": "", "client_id": "TEST-CLIENT-ID", "transaction_no": "TX-MVIRS-20261104-123456",
        "plate_no": "TEST123", "file_no": "000000000000000", "classification": "Private - (PVT)",
        "vehicle_type": "Motorcycle Without Sidecar", "fuel_type": "Gas", "aircon_type": "N/A",
        "color": "RED/MATTE BLACK", "year_model": "2021",
        "validity": "Valid until 11/2027. Renewal due 11/15/2027-11/21/2027.",
        "payment_mode": "Cash", "location": "Test District Office", "cashier": "Example Cashier",
        "pos_machine": "TEST MV - CASHIER",
    }, [Charge("MVUC", Decimal("240.00")), Charge("Science Tax", Decimal("9.00")),
        Charge("Science Tax Late Registration", Decimal("4.50")),
        Charge("Surcharge", Decimal("100.00")), Charge("Legal Research Fee", Decimal("10.00"))])


class ReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_money_and_words(self) -> None:
        self.assertEqual(example_data().total, Decimal("363.50"))
        self.assertEqual(amount_in_words(Decimal("363.50")),
                         "THREE HUNDRED SIXTY-THREE PESOS AND 50/100 CENTAVO(S)")
        self.assertEqual(amount_in_words(Decimal("1001001.01")),
                         "ONE MILLION ONE THOUSAND ONE PESOS AND 01/100 CENTAVO(S)")
        for invalid in ("NaN", "Infinity", "-1", "0", "2.001", "1000000000", "text"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_amount(invalid)

    def test_required_fields_and_item_limit(self) -> None:
        data = example_data()
        data.fields["payer"] = ""
        with self.assertRaisesRegex(ValueError, "Received from"):
            generate_receipt(data)
        data = example_data()
        with self.assertRaises(ValueError):
            generate_receipt(ReceiptData(data.fields, data.charges * 2))

    def test_pdf_content_and_local_export(self) -> None:
        for mode in ("Cash", "GCash"):
            with self.subTest(mode=mode):
                data = example_data()
                data.fields["payment_mode"] = mode
                content = generate_receipt(data)
                document = QPdfDocument()
                buffer = QBuffer()
                buffer.setData(content)
                buffer.open(QIODevice.OpenModeFlag.ReadOnly)
                document.load(buffer)
                self.assertEqual(document.pageCount(), 1)
                text = document.getAllText(0).text()
                for expected in ("363.50", "TEST-2026-000001", "MARIA PEÑA", mode,
                                 "This is a system generated Official Receipt. No Signatures needed."):
                    self.assertIn(expected, text)
                self.assertNotIn("ALLAN MOTAN", text)
                if mode == "GCash":
                    self.assertNotIn("CASHIER:", text)
                    self.assertNotIn("POS MACHINE:", text)
                    self.assertNotIn("Test District Office", text)
                    self.assertIn("LOCATION:", text)
                else:
                    self.assertIn("CASHIER:", text)
                    self.assertIn("POS MACHINE:", text)
                document.close()
                with TemporaryDirectory() as folder:
                    path = Path(folder) / "receipt.pdf"
                    path.write_bytes(b"old content")
                    save_receipt(str(path), content)
                    self.assertEqual(path.read_bytes(), content)

    def test_receipt_filename_is_windows_safe(self) -> None:
        self.assertEqual(receipt_filename("1396-000000580411"), "1396-000000580411.pdf")
        self.assertEqual(receipt_filename("CON"), "_CON.pdf")
        self.assertEqual(receipt_filename('OR/2026:01?'), "OR_2026_01_.pdf")

    def test_eight_items_and_escaped_user_text(self) -> None:
        data = example_data()
        data.fields["payer"] = "TEST & EXAMPLE <PERSON>"
        data.charges[:] = [Charge(f"Payment item {i + 1}", Decimal("1.01")) for i in range(8)]
        content = generate_receipt(data)
        document = QPdfDocument()
        buffer = QBuffer()
        buffer.setData(content)
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        document.load(buffer)
        self.assertEqual(document.pageCount(), 1)
        text = document.getAllText(0).text()
        self.assertIn("TEST & EXAMPLE <PERSON>", text)
        self.assertIn("Payment item 8", text)
        self.assertIn("8.08", text)
        document.close()


if __name__ == "__main__":
    unittest.main()
