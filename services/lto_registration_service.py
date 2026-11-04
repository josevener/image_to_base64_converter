"""Offline registration estimates. Rules and fees are explicit, reviewable inputs."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from services.lto_receipt_service import Charge


@dataclass(frozen=True)
class RegistrationInput:
    transaction: str
    plate: str
    engine_cc: int
    initial_date: date | None
    previous_expiry: date | None
    payment_date: date
    renewal_year: int
    initial_validity_years: int | None
    annual_mvuc: Decimal
    penalty_policy: str = "unconfirmed"
    file_no: str = ""
    confirmed_window_start: date | None = None
    confirmed_window_end: date | None = None
    auto_initial_renewal_year: bool = True
    cap_initial_term: bool = False


@dataclass(frozen=True)
class RegistrationSuggestions:
    validity: str
    charges: tuple[Charge, ...]
    explanation: str


def renewal_window(plate: str, year: int) -> tuple[date, date]:
    """Use the final two digits of a single numeric plate section, including legacy suffix plates."""
    normalized = re.sub(r"[\s-]", "", plate.upper())
    if not re.fullmatch(r"[A-Z]*[0-9]{2,}[A-Z]*", normalized):
        raise ValueError("Enter a plate with one numeric section of at least two digits. Mixed or temporary formats need manual dates.")
    digits = re.search(r"[0-9]+", normalized).group()
    month = int(digits[-1]) or 10
    week_digit = int(digits[-2])
    start, end = ((1, 7) if week_digit in (1, 2, 3) else
                  (8, 14) if week_digit in (4, 5, 6) else
                  (15, 21) if week_digit in (7, 8) else
                  (22, calendar.monthrange(year, month)[1]))
    return date(year, month, start), date(year, month, end)


def _add_years(value: date, years: int) -> date:
    year = value.year + years
    return date(year, value.month, min(value.day, calendar.monthrange(year, value.month)[1]))


def registration_window(value: RegistrationInput, year: int) -> tuple[date, date]:
    if value.plate.strip():
        return renewal_window(value.plate, year)
    file_no = re.sub(r"[\s-]", "", value.file_no)
    if not re.fullmatch(r"[0-9]{15}", file_no):
        raise ValueError("Enter a plate number or a 15-digit MV file number with confirmed OR/CR renewal dates.")
    start, end = value.confirmed_window_start, value.confirmed_window_end
    if start is None or end is None:
        raise ValueError("MV file only: enter the confirmed renewal start/end dates from OR/CR on Registration.")
    if end < start or (end - start).days > 366:
        raise ValueError("Confirmed renewal end must be on or after start, within one year.")
    return start, end


def validity_notice(expiry: date, start: date, end: date) -> str:
    return (f"This payment is valid until {expiry:%m/%Y} and due for renewal on "
            f"{start:%m/%d/%Y} - {end:%m/%d/%Y}.")


def initial_renewal_year(value: RegistrationInput) -> int:
    """Resolve the initial-registration template year independently of the receipt's current year."""
    if value.initial_date is None or value.initial_validity_years not in (1, 3, 5):
        raise ValueError("Enter the first registration date and select its validity period.")
    minimum_year = value.initial_date.year + value.initial_validity_years
    if value.cap_initial_term and value.plate.strip():
        anniversary = _add_years(value.initial_date, value.initial_validity_years)
        _, end = renewal_window(value.plate, minimum_year)
        latest_year = minimum_year - (1 if end > anniversary else 0)
        year = latest_year if value.auto_initial_renewal_year else value.renewal_year
        if year > latest_year:
            raise ValueError("The selected plate window exceeds the initial validity limit. Use automatic calculation or an earlier renewal year.")
        if year < value.initial_date.year or year > 2100:
            raise ValueError("The selected first renewal year is outside the supported registration period.")
        return year
    year = minimum_year if value.auto_initial_renewal_year else value.renewal_year
    if year < minimum_year:
        raise ValueError(f"A {value.initial_validity_years}-year registration starting in {value.initial_date.year} reaches renewal in {minimum_year}. Use {minimum_year} or later, or turn on automatic first renewal year.")
    if year > 2100:
        raise ValueError("The calculated first renewal year is outside the supported range (up to 2100).")
    return year


def automatic_validity(value: RegistrationInput) -> str:
    """Calculate the notice independently of fee-estimation inputs."""
    if value.transaction == "renewal":
        start, end = registration_window(value, value.renewal_year + 1)
        return validity_notice(end, start, end)
    if value.transaction == "initial":
        year = initial_renewal_year(value)
        start, end = registration_window(value, year)
        if end.year < year:
            raise ValueError(f"The confirmed OR/CR renewal dates must be in {year} or later for this initial registration.")
        if value.cap_initial_term:
            anniversary = _add_years(value.initial_date, value.initial_validity_years)
            if end > anniversary or end <= value.initial_date:
                raise ValueError("The renewal window must end after registration and no later than the initial validity limit.")
        # Automated samples use the latest complete plate window within the term cap.
        return validity_notice(end, start, end)
    elif value.transaction == "transfer":
        if value.previous_expiry is None:
            raise ValueError("Transfer needs the existing official expiry date.")
        expiry = value.previous_expiry
    else:
        raise ValueError("Select a registration transaction type.")
    start, end = registration_window(value, value.renewal_year)
    return validity_notice(expiry, start, end)


def calculate_suggestions(value: RegistrationInput) -> RegistrationSuggestions:
    if value.transaction not in ("renewal", "initial", "transfer"):
        raise ValueError("Select a registration transaction type.")
    if not 1 <= value.engine_cc <= 3000:
        raise ValueError("Engine displacement must be between 1 and 3000 cc.")
    if not 1900 <= value.renewal_year <= 2100:
        raise ValueError("Renewal year must be between 1900 and 2100.")
    rate = value.annual_mvuc
    if not rate.is_finite() or not Decimal("0") < rate <= Decimal("1000000"):
        raise ValueError("Enter a confirmed annual MVUC between PHP 0.01 and 1,000,000.00.")
    if rate != rate.quantize(Decimal("0.01")):
        raise ValueError("Annual MVUC may have at most two decimal places.")
    if value.initial_date and value.initial_date > value.payment_date:
        raise ValueError("Initial registration date cannot be after the receipt date.")
    if value.initial_date and value.previous_expiry and value.previous_expiry < value.initial_date:
        raise ValueError("Previous expiry cannot be before initial registration.")
    if value.penalty_policy not in ("unconfirmed", "exempt", "standard"):
        raise ValueError("Select a valid penalty policy.")

    notes = [f"Motorcycle: {value.engine_cc} cc. Annual MVUC entered: PHP {rate:,.2f}.",
             "Estimates only. Confirm the applicable rule, fees, and official expiry before applying."]
    charges: list[Charge] = []
    if value.transaction == "initial":
        year = initial_renewal_year(value)
        charges.append(Charge("MVUC", rate * value.initial_validity_years))
        notes.append(f"Initial validity uses the selected {value.initial_validity_years}-year template, aligned to the plate month in {year}. Confirm the final dates and partial-year charges against OR/CR.")
        start, end = registration_window(value, year)
        validity = automatic_validity(value)
    else:
        if value.previous_expiry is None:
            raise ValueError("Enter the previous official expiry for renewal or transfer.")
        if value.transaction == "transfer":
            expiry = value.previous_expiry
            start, end = registration_window(value, value.renewal_year)
            validity = validity_notice(expiry, start, end)
            notes.append("Transfer keeps the existing registration expiry. Transfer fees are assessed manually; no renewal charges suggested.")
        else:
            if value.renewal_year != value.previous_expiry.year:
                raise ValueError("For a regular annual renewal, renewal year must match the previous expiry year. Assess multi-year arrears manually.")
            start, end = registration_window(value, value.renewal_year + 1)
            validity = validity_notice(end, start, end)
            charges.append(Charge("MVUC", rate))
            if value.payment_date > value.previous_expiry:
                if value.penalty_policy == "exempt":
                    notes.append("No late charge suggested: you confirmed that an exemption/grace period covers this payment.")
                elif value.payment_date < _add_years(value.previous_expiry, 1) and value.penalty_policy == "standard":
                    charges.append(Charge("Delinquent Registration", (rate * Decimal("0.5")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)))
                    notes.append("50% MVUC late estimate uses the confirmed standard policy for a delay of less than one year.")
                else:
                    notes.append("Late charges unresolved: verify exemptions and assess arrears manually. No penalty has been added.")
            else:
                notes.append("Payment is on or before the entered expiry; no late charge suggested.")

    notes.extend([f"Nominal plate renewal window: {start:%B %d, %Y} to {end:%B %d, %Y}.",
                  "Windows show calendar dates; holidays, office closures, and extensions are not applied automatically.",
                  "Science tax, legal research, insurance, inspection, transfer fees, and other charges are excluded. Enter assessed amounts on Payment.",
                  "Initial validity is user-confirmed; no automatic choice between the historical three-year rule and later policy changes.",
                  "Sources: LTO Driver's Manual Vol. 2 (registration schedule); LTO Memo 09 Nov 2023 (late renewal); check current LTO advisories for exemptions."])
    return RegistrationSuggestions(validity, tuple(charges), "\n\n".join(notes))
