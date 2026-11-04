"""Local, input-driven LTO receipt layout and PDF generation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
import os
import tempfile
import json
import hashlib
import re
from urllib.parse import urlencode, urlsplit
from xml.sax.saxutils import escape

from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


@dataclass(frozen=True)
class Charge:
    description: str
    amount: Decimal


DEFAULT_RECEIPT_FIELDS = {
    "classification": "Private - (PVT)", "vehicle_type": "Motorcycle Without Sidecar",
    "fuel_type": "Gas", "aircon_type": "N/A", "office_tin": "000865491001",
}
DEFAULT_RECEIPT_CHARGES = (
    Charge("Cost of plate", Decimal("120.00")),
    Charge("MVUC", Decimal("720.00")),
    Charge("Science Tax", Decimal("40.50")),
    Charge("Science Tax Penalty", Decimal("7.50")),
    Charge("Transfer Fee", Decimal("50.00")),
    Charge("Legal Research Fee", Decimal("10.00")),
)
LATE_REGISTRATION_CHARGE = Charge("Penalty Late Registration", Decimal("120.00"))


@dataclass(frozen=True)
class ReceiptData:
    fields: dict[str, str]
    charges: list[Charge]

    @property
    def total(self) -> Decimal:
        return sum((charge.amount for charge in self.charges), Decimal("0.00"))

    def validate(self) -> None:
        for key, label in (("receipt_no", "Receipt number"), ("payer", "Received from"),
                           ("address", "Address"), ("office", "Field office"),
                           ("transaction_no", "Transaction number")):
            if not self.fields.get(key, "").strip():
                raise ValueError(f"{label} is required.")
        if not 1 <= len(self.charges) <= 8:
            raise ValueError("Enter between one and eight payment items.")
        for charge in self.charges:
            if not charge.description.strip() or len(charge.description) > 60:
                raise ValueError("Each payment item needs a description of at most 60 characters.")
            if not charge.amount.is_finite() or not Decimal("0") < charge.amount <= Decimal("999999999.99"):
                raise ValueError("Payment amounts must be between PHP 0.01 and 999,999,999.99.")
            if charge.amount != charge.amount.quantize(Decimal("0.01")):
                raise ValueError("Payment amounts may have at most two decimal places.")
        if self.total > Decimal("999999999.99"):
            raise ValueError("The total must not exceed PHP 999,999,999.99.")
        for key, value in self.fields.items():
            if key == "qr_payload":
                continue
            if len(value) > (180 if key in ("address", "validity") else 100):
                raise ValueError(f"{key.replace('_', ' ').title()} is too long.")
        if (len(self.fields["receipt_no"]) > 40 or not self.fields["receipt_no"].isascii()
                or not self.fields["receipt_no"].isprintable()):
            raise ValueError("Receipt number must contain at most 40 printable ASCII characters.")
        qr_payload(self)
        barcode_payload(self)
        online_payment(self.fields)


def online_payment(fields: dict[str, str]) -> bool:
    mode = fields.get("payment_mode", "").strip()
    channel = fields.get("payment_channel", "cash" if mode.casefold() == "cash" else "online")
    if not mode or channel not in ("cash", "online"):
        raise ValueError("Select a payment type and enter a payment method.")
    if (channel == "cash") != (mode.casefold() == "cash"):
        raise ValueError("Choose Cash for cash payments, or an online method such as GCash for online payments.")
    return channel == "online"


def receipt_filename(receipt_no: str) -> str:
    """Use the OR number while respecting Windows filename rules."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", receipt_no.strip()).rstrip(". ")
    if not name:
        name = "official_receipt"
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name + ".pdf"


def barcode_payload(data: ReceiptData) -> str:
    payload = data.fields.get("transaction_no", "").strip()
    if not payload or len(payload) > 60 or not payload.isascii() or not payload.isprintable():
        raise ValueError("Transaction number must contain 1 to 60 printable ASCII characters for Code 128.")
    return payload


def make_qr_widget(data: ReceiptData) -> qr.QrCodeWidget:
    version = data.fields.get("qr_version", "8")
    if version not in ("auto", "8"):
        raise ValueError("Choose QR version 8 or automatic sizing.")
    widget = qr.QrCodeWidget(qr_payload(data), barLevel=data.fields.get("qr_level", "M"),
                             qrVersion=8 if version == "8" else None, barBorder=4)
    try:
        widget.getBounds()
    except Exception as error:
        # ReportLab raises a plain Exception for fixed-version QR capacity overflow.
        if "code length overflow" not in str(error):
            raise
        raise ValueError("The QR payload does not fit Version 8 at this correction level. Shorten it or select Automatic sizing.") from error
    return widget


AUTOMATED_QR_ENDPOINT = "https://portal-lto-gov-phi.vercel.app/ords/f"


def automated_qr_url(fields: dict[str, str]) -> str:
    """Build a test reference locally; this digest does not authenticate issuance."""
    receipt = fields.get("receipt_no", "").strip()
    transaction = fields.get("transaction_no", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{1,40}", receipt):
        raise ValueError("Automated QR requires a receipt number with letters, digits, or hyphens.")
    if not transaction:
        raise ValueError("Transaction number is required for the automated QR.")
    digest = hashlib.sha256(transaction.encode("utf-8")).hexdigest().upper()
    # APEX packs both item names and their corresponding values into one f argument.
    packed = f"PUBLIC_PORTAL:ORV:::NO:200:P200_OR,P200_HASH:{receipt},{digest}"
    return AUTOMATED_QR_ENDPOINT + "?" + urlencode({"p": packed}, safe=":,")


def qr_payload(data: ReceiptData) -> str:
    """Return the selected payload without fetching URLs or creating verification claims."""
    mode = data.fields.get("qr_mode", "reference")
    if data.fields.get("qr_level", "M") not in ("L", "M", "Q", "H"):
        raise ValueError("Select a valid QR error correction level.")
    if mode == "automated":
        payload = automated_qr_url(data.fields)
    elif mode == "reference":
        payload = data.fields.get("receipt_no", "")
    elif mode == "summary":
        payload = json.dumps({"receipt": data.fields.get("receipt_no", ""),
                              "plate": data.fields.get("plate_no", ""),
                              "total_php": f"{data.total:.2f}"}, ensure_ascii=False, separators=(",", ":"))
    elif mode in ("text", "url"):
        payload = data.fields.get("qr_payload", "").strip()
        if mode == "url":
            try:
                parsed = urlsplit(payload)
                if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError("Enter an existing HTTP or HTTPS URL without embedded credentials.")
            except ValueError as error:
                raise ValueError("Enter a valid existing HTTP or HTTPS URL without embedded credentials.") from error
    else:
        raise ValueError("Select a valid QR payload type.")
    if not payload or len(payload.encode("utf-8")) > 300:
        raise ValueError("QR payload must contain between 1 and 300 UTF-8 bytes for readable printing.")
    return payload


def parse_amount(value: str) -> Decimal:
    try:
        amount = Decimal(value.strip())
        if not amount.is_finite() or amount <= 0 or amount > Decimal("999999999.99"):
            raise ValueError("Enter a payment amount between 0.01 and 999,999,999.99.")
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError("Payment amounts may have at most two decimal places.")
        return amount
    except InvalidOperation as error:
        raise ValueError("Enter a valid payment amount, for example 420.00.") from error


def amount_in_words(amount: Decimal) -> str:
    ones = ("ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE "
            "THIRTEEN FOURTEEN FIFTEEN SIXTEEN SEVENTEEN EIGHTEEN NINETEEN").split()
    tens = "ZERO TEN TWENTY THIRTY FORTY FIFTY SIXTY SEVENTY EIGHTY NINETY".split()

    def words(number: int) -> str:
        if number < 20:
            return ones[number]
        if number < 100:
            return tens[number // 10] + ("-" + ones[number % 10] if number % 10 else "")
        if number < 1000:
            return ones[number // 100] + " HUNDRED" + (" " + words(number % 100) if number % 100 else "")
        for scale, name in ((1000000, "MILLION"), (1000, "THOUSAND")):
            if number >= scale:
                return words(number // scale) + " " + name + (" " + words(number % scale) if number % scale else "")
        raise ValueError("Amount is out of range.")

    whole = int(amount)
    cents = int((amount - whole) * 100)
    return words(whole) + (" PESO" if whole == 1 else " PESOS") + (f" AND {cents:02d}/100 CENTAVO(S)" if cents else "")


def save_receipt(path: str, content: bytes) -> None:
    """Replace only after writing successfully, preserving an existing file on failure."""
    target = Path(path)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".pdf", delete=False) as stream:
            temporary = stream.name
            stream.write(content)
        os.replace(temporary, target)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()


def generate_receipt(data: ReceiptData) -> bytes:
    """Render a fresh A4 receipt; sample PDF and its personal data are never reused."""
    data.validate()
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(595.5, 842.25))
    pdf.setTitle("LTO Official Receipt - " + data.fields["receipt_no"])
    pdf.setAuthor("Developer Toolbox")
    # An explicit paper background also makes PNG/Qt previews render consistently.
    pdf.setFillColor(colors.white)
    pdf.rect(0, 0, 595.5, 842.25, fill=1, stroke=0)
    pdf.setFillColor(colors.black)
    fields = data.fields
    assets = Path(__file__).resolve().parent.parent / "assets" / "logos"

    def text(x: float, y: float, value: str, size: float = 8, bold: bool = False,
             width: float = 350, height: float = 30, align: int = 0,
             leading: float | None = None, draw: bool = True) -> float:
        style = ParagraphStyle("receipt", fontName="Helvetica-Bold" if bold else "Helvetica",
                               fontSize=size, leading=leading or size + 2, alignment=align)
        paragraph = Paragraph(escape(value).replace("\n", "<br/>"), style)
        _, h = paragraph.wrap(width, height)
        if h > height:
            raise ValueError("Text does not fit the receipt. Shorten: " + value[:55])
        if draw:
            paragraph.drawOn(pdf, x, 842.25 - y - h)
        return h

    def line(y: float, x1: float = 126, x2: float = 475) -> None:
        pdf.setStrokeColor(colors.HexColor("#555555"))
        pdf.setLineWidth(0.5)
        pdf.line(x1, 842.25 - y, x2, 842.25 - y)

    # Paint the watermark first so its opaque white pixels cannot cover identity text.
    name_h = text(0, 0, fields["payer"], 8, True, width=296, height=22, draw=False)
    address_h = text(0, 0, fields["address"], 8, True, width=296, height=32, draw=False)
    predicted_address_rule = 217 + name_h + 2 + 15 + address_h + 2
    predicted_id_top = max(predicted_address_rule + 17, 270)
    predicted_id_h = max(10,
                         text(0, 0, fields.get("payer_tin", ""), 8, width=130, draw=False),
                         text(0, 0, fields.get("client_id", ""), 8, True, width=239, draw=False))
    watermark = assets / "lto-bg.png"
    if watermark.exists():
        pdf.saveState()
        pdf.translate(0, 333 - (predicted_id_top + predicted_id_h + 2 + 7))
        pdf.drawImage(str(watermark), 177, 296.25, width=241, height=241, mask="auto", preserveAspectRatio=True)
        pdf.restoreState()

    for filename, x in (("dotr.png", 122), ("lto.png", 419)):
        path = assets / filename
        if path.exists():
            pdf.drawImage(str(path), x, 713, width=62, height=62, mask="auto", preserveAspectRatio=True)
    text(190, 72, "Republic of the Philippines", 7, width=220, align=1)
    text(186, 82, "DEPARTMENT OF TRANSPORTATION", 9, width=230, align=1)
    text(186, 94, "LAND TRANSPORTATION OFFICE", 10, True, width=230, align=1)
    text(186, 108, fields.get("office_address", ""), 7, width=230, height=24, align=1)
    text(114, 140, "Field Office:", 7)
    text(170, 140, fields["office"], 7, True, width=180, height=20, align=1)
    line(153, 170, 352)
    text(114, 157, "Office Code:", 7)
    text(170, 157, fields.get("office_code", ""), 7, width=180, align=1)
    line(169, 170, 352)
    text(374, 140, "TIN:", 7)
    text(397, 140, fields.get("office_tin", ""), 7, width=90, align=1)
    line(153, 397, 489)
    text(374, 157, "Date:", 7)
    text(397, 157, fields.get("date", ""), 7, width=92, align=1)
    line(169, 397, 489)
    pdf.setFillColor(colors.HexColor("#505050"))
    pdf.rect(105, 842.25 - 199, 120, 18, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(110, 842.25 - 194, "OFFICIAL RECEIPT")
    pdf.setFillColor(colors.black)
    text(245, 181, fields["receipt_no"], 10, True, width=153, height=28)
    widget = make_qr_widget(data)
    bounds = widget.getBounds()
    scale = 88 / (bounds[2] - bounds[0])
    drawing = Drawing(88, 88, transform=[scale, 0, 0, scale, 0, 0])
    drawing.add(widget)
    drawing.drawOn(pdf, 400, 842.25 - 266)
    text(105, 205, "RECEIVED FROM (Last Name, First Name Middle Name)", 7)
    # Fit rules to the actual wrapped text instead of reserving empty rows.
    name_height = text(105, 217, fields["payer"], 8, True, width=296, height=22)
    name_rule = 217 + name_height + 2
    line(name_rule, 105, 401)
    text(105, name_rule + 4, "ADDRESS (No. Street, Barangay, Municipality, Zip Code, Province)", 6.5)
    address_top = name_rule + 15
    address_height = text(105, address_top, fields["address"], 8, True, width=296, height=32)
    address_rule = address_top + address_height + 2
    line(address_rule, 105, 401)
    text(105, address_rule + 4, "TIN (Tax Identification Number)", 7, width=130)
    text(251, address_rule + 4, "LTO Client ID / LTO BUSINESS ID", 7, width=145)
    id_top = max(address_rule + 17, 270)  # Keep ID values below the QR code.
    tin_height = text(105, id_top, fields.get("payer_tin", ""), 8, width=130)
    client_height = text(251, id_top, fields.get("client_id", ""), 8, True, width=239)
    id_rule = id_top + max(tin_height, client_height, 10) + 2
    line(id_rule, 105, 490)
    # Move the full payment section up with the compact identity block.
    pdf.saveState()
    pdf.translate(0, 333 - (id_rule + 7))
    pdf.setFillColor(colors.HexColor("#505050"))
    pdf.rect(105, 842.25 - 349, 385, 16, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawCentredString(202.5, 842.25 - 345, "PAYMENT DETAILS")
    pdf.drawCentredString(395, 842.25 - 345, "BREAKDOWN OF PAYMENT")
    pdf.setStrokeColor(colors.white)
    pdf.setLineWidth(1)
    pdf.line(300, 842.25 - 333, 300, 842.25 - 349)
    pdf.setFillColor(colors.black)
    pdf.setStrokeColor(colors.gray)
    pdf.setLineWidth(0.5)
    detail_fields = [("transaction_no", "Transaction No"), ("plate_no", "Plate No"),
                     ("file_no", "File No"), ("classification", "Classification"),
                     ("vehicle_type", "Vehicle Type"), ("fuel_type", "Fuel Type"),
                     ("aircon_type", "Aircon Type"), ("color", "Color"), ("year_model", "Year Model")]
    y = 355
    for key, label in detail_fields:
        plate = key == "plate_no"
        size = 14 if plate else 8
        leading = 15 if plate else 9
        label_height = text(110, y, label + ":", size, width=63, height=22, align=2, leading=leading)
        value = fields.get(key, "")
        if key == "transaction_no" and "-" in value:
            prefix, suffix = value.rsplit("-", 1)
            value = prefix + "-\n" + suffix
        value_height = text(183, y, value, size, width=111, height=30, leading=leading)
        row_height = 18 if key == "transaction_no" else 17.5 if plate else 13.5
        y += max(row_height, label_height, value_height)
    notice = fields.get("validity", "")
    dates = re.fullmatch(r"This payment is valid until (\d{2}/\d{4}) and due for renewal on (\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})\.?", notice)
    if dates:
        month, start, end = dates.groups()
        notice = f"This payment is valid until\n{month} and due for\nrenewal on {start}-\n{end}."
    notice_height = text(183, y, notice, 8, width=111, height=45, leading=9)
    if y + notice_height > 550:
        raise ValueError("Payment details exceed the receipt box. Shorten vehicle details or the renewal notice.")
    payment_y = 355.0
    for charge in data.charges:
        description = charge.description
        if description.casefold() == "penalty late registration":
            description = "Penalty Late\nRegistration"
        description_height = text(308, payment_y, description, 8, width=95, height=27, leading=9)
        text(411, payment_y, "PHP", 8, width=23, leading=9)
        amount_height = text(440, payment_y, f"{charge.amount:,.2f}", 8, width=47, height=22, align=2, leading=9)
        payment_y += max(15, description_height + 1, amount_height + 1)
    if payment_y > 550:
        raise ValueError("Payment items exceed the receipt box. Shorten payment descriptions.")
    table_bottom = max(527, y + notice_height + 6, payment_y + 4)
    pdf.rect(105, 842.25 - table_bottom, 385, table_bottom - 351, fill=0, stroke=1)
    pdf.line(300, 842.25 - 351, 300, 842.25 - table_bottom)
    text(105, table_bottom + 10, "TOTAL AMOUNT PAID:", 10, True, width=150, leading=11)
    text(389, table_bottom + 10, "PHP", 10, True, width=26, leading=11)
    text(427, table_bottom + 10, f"{data.total:,.2f}", 10, True, width=63, align=2, leading=11)
    text(105, table_bottom + 28, "AMOUNT IN WORDS:", 10, True, width=120, leading=11)
    words_height = text(239, table_bottom + 28, amount_in_words(data.total), 10, True, width=251, height=44, align=2, leading=11)
    online = online_payment(fields)
    footer_fields = [("payment_mode", "MODE OF PAYMENT"), ("location", "LOCATION")]
    if not online:
        footer_fields.extend([("cashier", "CASHIER"), ("pos_machine", "POS MACHINE")])
    footer_top = max(table_bottom + 59, table_bottom + 28 + words_height + 10)
    for i, (key, label) in enumerate(footer_fields):
        text(106, footer_top + i * 15, label + ":", 8, width=90, leading=9)
        value = "-" if online and key == "location" else fields.get(key, "")
        text(199, footer_top + i * 15, value, 8, width=291, height=16, leading=9)
    notice_top = footer_top + len(footer_fields) * 15 + 12
    text(165, notice_top, "This is a system generated Official Receipt. No Signatures needed.",
         8, width=270, height=20, align=1, leading=9)
    # The frame supplies the quiet margin; keep the printed bars at the reference width.
    barcode = code128.Code128(barcode_payload(data), barHeight=36, barWidth=0.7, quiet=False)
    frame_top = notice_top + 18
    pdf.saveState()
    pdf.setStrokeColor(colors.HexColor("#AAAAAA"))
    pdf.setLineWidth(0.35)
    pdf.setDash(1.4, 1.2)
    pdf.rect(165, 842.25 - (frame_top + 60), 270, 60, fill=0, stroke=1)
    pdf.restoreState()
    pdf.saveState()
    pdf.translate(182, 842.25 - (frame_top + 45))
    pdf.scale(236 / barcode.width, 1)
    barcode.drawOn(pdf, 0, 0)
    pdf.restoreState()
    pdf.restoreState()
    pdf.showPage()
    pdf.save()
    return output.getvalue()
