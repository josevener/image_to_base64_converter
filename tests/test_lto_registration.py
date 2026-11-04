"""Boundary tests for estimates, exemptions, and QR payload selection."""

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from services.lto_registration_service import RegistrationInput, automatic_validity, calculate_suggestions, renewal_window, initial_renewal_year
from services.lto_receipt_service import (
    qr_payload, generate_receipt, barcode_payload, make_qr_widget, DEFAULT_RECEIPT_FIELDS, DEFAULT_RECEIPT_CHARGES,
)
from test_lto_receipt import example_data


class RegistrationTests(unittest.TestCase):
    def test_automated_initial_term_is_based_on_selected_date(self) -> None:
        value = self.inputs(transaction="initial", initial_date=date(2026, 11, 4),
                            initial_validity_years=3, plate="AB12345", cap_initial_term=True)
        self.assertEqual(initial_renewal_year(value), 2029)
        self.assertIn("05/08/2029 - 05/14/2029", automatic_validity(value))
        earlier = replace(value, initial_date=date(2026, 1, 4))
        self.assertEqual(initial_renewal_year(earlier), 2028)
        self.assertIn("05/08/2028 - 05/14/2028", automatic_validity(earlier))
        leap = replace(value, initial_date=date(2024, 2, 29), plate="AB10002")
        self.assertIn("02/22/2027 - 02/28/2027", automatic_validity(leap))

    def test_capped_initial_term_never_exceeds_three_years(self) -> None:
        for registered in (date(2026, 1, 1), date(2026, 10, 14), date(2024, 2, 29)):
            cap = date(registered.year + 3, registered.month, 28 if registered.month == 2 and registered.day == 29 else registered.day)
            for digits in range(100):
                value = self.inputs(transaction="initial", initial_date=registered, initial_validity_years=3,
                                    plate=f"PS281{digits:02d}", cap_initial_term=True)
                year = initial_renewal_year(value)
                _, end = renewal_window(value.plate, year)
                _, next_end = renewal_window(value.plate, year + 1)
                self.assertLessEqual(end, cap)
                self.assertGreater(end, registered)
                self.assertGreater(next_end, cap)
        example = self.inputs(transaction="initial", initial_date=date(2026, 10, 14),
                              initial_validity_years=3, plate="PS28105", cap_initial_term=True)
        self.assertEqual(automatic_validity(example),
                         "This payment is valid until 05/2029 and due for renewal on 05/22/2029 - 05/31/2029.")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            automatic_validity(replace(example, renewal_year=2030, auto_initial_renewal_year=False))

    def inputs(self, **changes) -> RegistrationInput:
        value = RegistrationInput("renewal", "ABC 12345", 125, date(2020, 5, 1), date(2026, 5, 14),
                                  date(2026, 5, 20), 2026, None, Decimal("240.00"))
        return replace(value, **changes)

    def test_plate_schedule_boundaries_and_legacy(self) -> None:
        for plate, month, first, last in (("ABC12345", 5, 8, 14), ("AB1200", 10, 22, 31),
                                         ("681TZS", 1, 15, 21), ("AB1212", 2, 1, 7)):
            start, end = renewal_window(plate, 2026)
            self.assertEqual((start.month, start.day, end.day), (month, first, last))
        for plate in ("", "ABC", "AB1C23", "TEMP1", "１２３４"):
            with self.subTest(plate=plate), self.assertRaises(ValueError):
                renewal_window(plate, 2026)

    def test_penalties_require_confirmation_and_short_delay(self) -> None:
        unknown = calculate_suggestions(self.inputs())
        self.assertEqual(len(unknown.charges), 1)
        self.assertIn("unresolved", unknown.explanation)
        standard = calculate_suggestions(self.inputs(penalty_policy="standard"))
        self.assertEqual(standard.charges[1].amount, Decimal("120.00"))
        exempt = calculate_suggestions(self.inputs(penalty_policy="exempt"))
        self.assertEqual(len(exempt.charges), 1)
        old = calculate_suggestions(self.inputs(payment_date=date(2027, 5, 14), penalty_policy="standard"))
        self.assertEqual(len(old.charges), 1)
        on_time = calculate_suggestions(self.inputs(payment_date=date(2026, 5, 14), penalty_policy="standard"))
        self.assertEqual(len(on_time.charges), 1)
        rounded = calculate_suggestions(self.inputs(annual_mvuc=Decimal("1.01"), penalty_policy="standard"))
        self.assertEqual(rounded.charges[1].amount, Decimal("0.51"))
        self.assertIn("05/08/2027 - 05/14/2027", standard.validity)

    def test_initial_template_aligns_to_plate_year_and_month(self) -> None:
        initial = self.inputs(transaction="initial", initial_date=date(2024, 2, 29),
                              initial_validity_years=3, renewal_year=2027, previous_expiry=None)
        result = calculate_suggestions(initial)
        self.assertIn("05/2027", result.validity)
        self.assertEqual(result.charges[0].amount, Decimal("720.00"))
        for changes in ({"initial_validity_years": None}, {"initial_date": None},
                        {"renewal_year": 2026, "auto_initial_renewal_year": False}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                calculate_suggestions(replace(initial, **changes))
        five = calculate_suggestions(replace(initial, initial_validity_years=5, renewal_year=2029))
        self.assertEqual(five.charges[0].amount, Decimal("1200.00"))
        earlier_plate_month = calculate_suggestions(replace(initial, initial_date=date(2024, 11, 1)))
        self.assertIn("05/2027", earlier_plate_month.validity)

    def test_brand_new_defaults_do_not_reuse_the_current_year(self) -> None:
        value = self.inputs(transaction="initial", plate="Q1723B", initial_date=date(2026, 4, 23),
                            initial_validity_years=3, renewal_year=2026, previous_expiry=None)
        self.assertEqual(initial_renewal_year(value), 2029)
        self.assertEqual(automatic_validity(value),
                         "This payment is valid until 03/2029 and due for renewal on 03/01/2029 - 03/07/2029.")
        self.assertEqual(initial_renewal_year(replace(value, initial_date=date(2025, 4, 23))), 2028)
        self.assertEqual(initial_renewal_year(replace(value, initial_validity_years=5)), 2031)
        with self.assertRaisesRegex(ValueError, "Use 2029 or later"):
            automatic_validity(replace(value, auto_initial_renewal_year=False))
        self.assertIn("03/2030", automatic_validity(replace(value, renewal_year=2030, auto_initial_renewal_year=False)))

    def test_transfer_keeps_expiry_and_no_invented_fees(self) -> None:
        result = calculate_suggestions(self.inputs(transaction="transfer"))
        self.assertIn("05/14/2026", result.validity)
        self.assertFalse(result.charges)
        for changes in ({"previous_expiry": None}, {"engine_cc": 0}, {"renewal_year": 2027},
                        {"annual_mvuc": Decimal("NaN")}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                calculate_suggestions(self.inputs(**changes))

    def test_qr_selection_and_validation(self) -> None:
        data = example_data()
        self.assertEqual(qr_payload(data), data.fields["receipt_no"])
        data.fields["qr_mode"] = "summary"
        self.assertIn('"total_php":"363.50"', qr_payload(data))
        self.assertNotIn("MARIA", qr_payload(data))
        data.fields.update(qr_mode="url", qr_payload="https://example.org/receipt/123", qr_level="H")
        self.assertEqual(qr_payload(data), "https://example.org/receipt/123")
        self.assertTrue(generate_receipt(data).startswith(b"%PDF"))
        for payload in ("", "javascript:alert(1)", "https://user:pass@example.org", "https://[bad"):
            data.fields["qr_payload"] = payload
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                qr_payload(data)
        data.fields.update(qr_mode="text", qr_payload="é" * 151)
        with self.assertRaises(ValueError):
            qr_payload(data)

    def test_sample_defaults_barcode_and_qr_format(self) -> None:
        self.assertEqual(sum(item.amount for item in DEFAULT_RECEIPT_CHARGES), Decimal("948.00"))
        self.assertEqual(DEFAULT_RECEIPT_FIELDS["office_tin"], "000865491001")
        self.assertEqual(DEFAULT_RECEIPT_FIELDS["vehicle_type"], "Motorcycle Without Sidecar")
        data = example_data()
        self.assertEqual(barcode_payload(data), data.fields["transaction_no"])
        self.assertNotEqual(barcode_payload(data), data.fields["receipt_no"])
        self.assertEqual(make_qr_widget(data).qr.getModuleCount(), 49)
        data.fields.update(qr_mode="text", qr_payload="a" * 300)
        with self.assertRaisesRegex(ValueError, "does not fit Version 8"):
            make_qr_widget(data)
        data.fields["qr_version"] = "auto"
        self.assertGreater(make_qr_widget(data).qr.getModuleCount(), 49)
        data.fields["transaction_no"] = ""
        with self.assertRaises(ValueError):
            barcode_payload(data)

    def test_automatic_notice_and_mv_record_fallback(self) -> None:
        value = self.inputs(plate="DC60008", engine_cc=0, previous_expiry=None)
        self.assertEqual(automatic_validity(value),
                         "This payment is valid until 08/2027 and due for renewal on 08/22/2027 - 08/31/2027.")
        no_plate = replace(value, plate="", file_no="048000000059046")
        with self.assertRaisesRegex(ValueError, "MV file only"):
            automatic_validity(no_plate)
        confirmed = replace(no_plate, confirmed_window_start=date(2027, 8, 22),
                            confirmed_window_end=date(2027, 8, 31))
        self.assertEqual(automatic_validity(confirmed), automatic_validity(value))
        with self.assertRaises(ValueError):
            automatic_validity(replace(confirmed, confirmed_window_end=date(2027, 8, 1)))
        self.assertEqual(automatic_validity(replace(confirmed, plate="ABC12345")),
                         "This payment is valid until 05/2027 and due for renewal on 05/08/2027 - 05/14/2027.")


if __name__ == "__main__":
    unittest.main()
