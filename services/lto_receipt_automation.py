"""Generate local receipt data without a registry or imported OR/CR records."""

from __future__ import annotations

from datetime import date, datetime
import calendar
from pathlib import Path
import re
import secrets
import sqlite3
import string

from services import database_service
from services.lto_receipt_service import DEFAULT_RECEIPT_FIELDS
from services.lto_registration_service import renewal_window


OFFICE_DEFAULTS = {
    "office": "VALENZUELA DISTRICT OFFICE",
    "office_code": "1396",
    "office_address": "CRISTOBAL ST. GEN. T. DE LEON VALENZUELA",
}
MANUAL_FIELDS = {
    "payer": "Received from", "address": "Recipient address", "color": "Color",
    "year_model": "Year model", "office": "Field office", "office_code": "Office code",
    "office_address": "Office address", "client_id": "LTO client / business ID",
    "payment_mode": "Mode of payment",
}


def validate_inputs(values: dict[str, str]) -> dict[str, str]:
    """Validate before reserving fresh random identifiers."""
    result = {key: values.get(key, "").strip() for key in MANUAL_FIELDS}
    for key, label in MANUAL_FIELDS.items():
        if not result[key]:
            raise ValueError(f"{label} is required.")
        if len(result[key]) > (180 if key == "address" else 100):
            raise ValueError(f"{label} is too long.")
    if not re.fullmatch(r"[0-9]{4}", result["office_code"]):
        raise ValueError("Office code must contain four digits, as shown on the sample receipt.")
    if not re.fullmatch(r"[0-9]{4}", result["year_model"]) or not 1900 <= int(result["year_model"]) <= 2100:
        raise ValueError("Year model must be a four-digit year between 1900 and 2100.")
    return result


def aligned_plate_endings(registered: date) -> list[str]:
    """Find the closest standard plate window at or before the three-year cap."""
    year = registered.year + 3
    cap = date(year, registered.month, min(registered.day, calendar.monthrange(year, registered.month)[1]))
    for candidate_year in (year, year - 1):
        candidates = []
        for digits in range(100):
            ending = f"{digits:02d}"
            _, end = renewal_window("AA000" + ending, candidate_year)
            if end <= cap:
                candidates.append((end, ending))
        if candidates:
            closest = max(end for end, _ in candidates)
            return [ending for end, ending in candidates if end == closest]
    raise ValueError("No plate window is available within the validity cap.")


def _random_plate(registered: date) -> str:
    ending = secrets.choice(aligned_plate_endings(registered))
    if secrets.randbelow(2) == 0:
        return (secrets.choice(string.ascii_uppercase) + f"{secrets.randbelow(100):02d}"
                + ending + secrets.choice(string.ascii_uppercase))
    return (str(1 + secrets.randbelow(9)) + ending
            + "".join(secrets.choice(string.ascii_uppercase) for _ in range(3)))


def _random_identifiers(office_code: str, moment: datetime, registered: date | None = None,
                        use_tx_format: bool = False) -> dict[str, str]:
    """Independent random values in the sample's shapes, with no advancing series."""
    selected = registered or moment.date()
    prefix = "TX-MVIRS" if use_tx_format else "MAIRD-SAR"
    return {
        "receipt_no": f"{office_code}-{100000 + secrets.randbelow(900000):012d}",
        "transaction_no": f"{prefix}-{selected:%Y%m%d}-{100000 + secrets.randbelow(900000):06d}",
        "plate_no": _random_plate(selected),
        "file_no": _random_mv_file(office_code, selected),
        "date": moment.strftime("%m/%d/%Y %I:%M %p"),
    }


def _random_mv_file(office_code: str, selected: date) -> str:
    """Sample convention: office + selected YY + zero-padded nine-digit random suffix."""
    return f"{office_code}{selected:%y}{1 + secrets.randbelow(9999999):09d}"


def fresh_identifiers(office_code: str, path: Path | None = None, now: datetime | None = None,
                      registration_date: date | None = None, *, use_tx_format: bool = False) -> dict[str, str]:
    """Reserve random identifiers atomically; store no payer information."""
    moment = now or datetime.now()
    target = path or database_service.DATA_DIRECTORY / "lto_receipt_numbers.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, timeout=10)
    try:
        connection.execute("""CREATE TABLE IF NOT EXISTS random_receipt_identifiers (
            kind TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(kind, value)
        )""")
        for _ in range(100):
            fields = _random_identifiers(office_code, moment, registration_date, use_tx_format)
            try:
                with connection:
                    connection.executemany(
                        "INSERT INTO random_receipt_identifiers(kind, value) VALUES (?, ?)",
                        [(key, fields[key]) for key in ("receipt_no", "transaction_no", "plate_no", "file_no")],
                    )
                return fields
            except sqlite3.IntegrityError:
                # Roll back the entire set and retry if any random value is already reserved.
                continue
        raise ValueError("Could not reserve unused random identifiers. Generate the receipt again.")
    finally:
        connection.close()


def align_generated_plate(identifiers: dict[str, str], registered: date,
                         path: Path | None = None) -> dict[str, str]:
    """Date edits may replace the sample plate, while retaining OR/transaction/MV IDs."""
    plate = identifiers["plate_no"]
    supported = re.fullmatch(r"(?:[A-Z][0-9]{4}[A-Z]|[1-9][0-9]{2}[A-Z]{3})", plate)
    digits = re.search(r"[0-9]+", plate)
    if supported and digits.group()[-2:] in aligned_plate_endings(registered):
        return identifiers
    target = path or database_service.DATA_DIRECTORY / "lto_receipt_numbers.db"
    connection = sqlite3.connect(target, timeout=10)
    try:
        for _ in range(100):
            plate = _random_plate(registered)
            try:
                with connection:
                    connection.execute("INSERT INTO random_receipt_identifiers VALUES (?, ?)", ("plate_no", plate))
                return {**identifiers, "plate_no": plate}
            except sqlite3.IntegrityError:
                continue
        raise ValueError("Could not reserve an unused date-aligned sample plate.")
    finally:
        connection.close()


def align_generated_references(identifiers: dict[str, str], selected: date,
                               path: Path | None = None, *, use_tx_format: bool = False) -> dict[str, str]:
    """Keep references date-consistent, reserving changed values before displaying them."""
    office = identifiers["receipt_no"].split("-", 1)[0]
    prefix = "TX-MVIRS" if use_tx_format else "MAIRD-SAR"
    transaction = f"{prefix}-{selected:%Y%m%d}-{identifiers['transaction_no'].rsplit('-', 1)[-1]}"
    suffix = identifiers["file_no"][6:]
    mv_file = (f"{office}{selected:%y}{suffix}" if re.fullmatch(r"00[0-9]{7}", suffix) and int(suffix)
               else _random_mv_file(office, selected))
    changes = {key: value for key, value in (("transaction_no", transaction), ("file_no", mv_file))
               if value != identifiers[key]}
    if not changes:
        return identifiers
    target = path or database_service.DATA_DIRECTORY / "lto_receipt_numbers.db"
    connection = sqlite3.connect(target, timeout=10)
    try:
        for _ in range(100):
            try:
                with connection:
                    connection.executemany("INSERT INTO random_receipt_identifiers VALUES (?, ?)", list(changes.items()))
                return {**identifiers, **changes}
            except sqlite3.IntegrityError:
                if "transaction_no" in changes:
                    changes["transaction_no"] = f"{prefix}-{selected:%Y%m%d}-{100000 + secrets.randbelow(900000):06d}"
                if "file_no" in changes:
                    changes["file_no"] = _random_mv_file(office, selected)
        raise ValueError("Could not reserve unused date-aligned transaction/MV file references.")
    finally:
        connection.close()


def automated_fields(values: dict[str, str], identifiers: dict[str, str], payment_date: datetime | None = None) -> dict[str, str]:
    fields = {**DEFAULT_RECEIPT_FIELDS, **validate_inputs(values), **identifiers}
    if payment_date is not None:
        fields["date"] = payment_date.strftime("%m/%d/%Y %I:%M %p")
    online = fields["payment_mode"].casefold() != "cash"
    fields.update({
        "payment_channel": "online" if online else "cash",
        "location": "-" if online else fields["office"],
        "cashier": "", "pos_machine": "" if online else f"{fields['office_code']} - CASHIER",
        "payer_tin": "", "qr_mode": "automated", "qr_version": "auto", "qr_level": "M",
        "document_label": "SAMPLE - GENERATED DATA",
    })
    return fields
