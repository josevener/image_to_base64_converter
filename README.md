# Developer Toolbox

A scalable Windows desktop image-utilities application built with **PySide6 (Qt)**.
Its first production-ready tool, **Image to Base64**, encodes image files to Base64 or
Data URI text. The collapsible Qt sidebar animates smoothly and completely hides to
give the active tool the full window width.

Developed by [Zentrix Solutions](https://zentrix-solutions.vercel.app).

## Architecture

The code follows MVC boundaries:

- `app.py` is the controller and coordinates navigation.
- `ui/` contains the reusable Qt shell: header, sidebar, status bar, and window.
- `pages/` contains individual tool views.
- `services/` owns image and Base64 operations, without visual-widget dependencies.

Future contributors must follow the Qt UI rule in [AGENTS.md](AGENTS.md).

## Input Activity Monitor

The **Input Activity Monitor** is a transparent, consent-based utility for your own
device or an organization-managed device with written user consent. It is inactive
on startup. The user must acknowledge the authorization confirmation checkbox before
**Start Monitoring** is available.

It keeps all processing on the local device and records only aggregate counts: total
keyboard events, events per minute, active duration, and broad key categories. It
never saves typed text, passwords, key names, clipboard data, or personal content. An
on-screen audit panel identifies the local Windows user and records visible start,
pause, stop, and reset timestamps. Use **Export Summary** to save a timestamped
aggregate-only CSV file in the repository's `exports` folder. Those local reports are
excluded from Git by default.

Optional periodic screen captures are disabled by default. When the authorized user
explicitly enables them, captures occur only while monitoring is visibly active and
are saved directly as timestamped PNG files in `exports/screenshots`; they are never
sent over a network.

## LTO Official Receipt

### Generate a receipt from a short form

Open **LTO → Official Receipt**. **Automated** mode is selected initially. Enter
Received From, recipient address, LTO Client ID / Business ID, motorcycle color,
year model, field office, office code, office address, and mode of payment.
Office details and the current model year are prefilled and editable.

Select **Generate fresh receipt** to generate an OR number, transaction number,
plate, 15-digit MV file number, payment timestamp, and plate-based renewal notice.
Brand-new registration defaults to three years. QR, Code 128 barcode, totals, and
amount in words are included automatically. **Preview PDF** and **Export PDF**
keep the same identifiers; **Generate fresh receipt** creates a new set.
The export filename is the generated OR number plus `.pdf`.

The automated form includes an editable **Receipt / first-registration date**.
It defaults to generation time. Once edited, the selected date is preserved on
preview, export, and fresh generation. **Use current date and time** restores the
automatic default. The selected date (not the model year) anchors the sample's
three-year maximum. Generated sample plates are randomized with their final two
digits constrained to the closest available renewal window ending on or before
the anniversary. October 14, 2026 therefore gives October 8–14, 2029 and validity
until 10/2029, rather than an unrelated random plate shortening it to May.
The standard plate calendar has January–October months only; November/December
and early-January targets use the closest earlier available window. This is the sample
generator's alignment policy, not a determination of an official registration expiry.
Changing the receipt date keeps the OR number. It updates the transaction's
`YYYYMMDD` and the sample MV file's `YY`, retaining their random suffixes where
available. It replaces the plate when renewal digits no longer match the target.

No existing OR/CR, records, imports, or office configuration files are required.
Choose **Cash**, **E-wallet**, or **Online payment**. E-wallet methods include GCash,
Maya, GrabPay, and ShopeePay; online methods include bank transfer, card, and online
banking. Other methods can be typed. E-wallet/online receipts print the method and
Location `-`, with no cashier/POS rows.
Switch to **Manual** to edit all fields, vehicle defaults, or the PHP 948.00 payment
template. Generated numbers follow the asset formats: `1396-000000580412`,
`MAIRD-SAR-YYYYMMDD-241123`, a six-character plate such as `Q1723B` or `681TZS`,
and a 15-digit MV file number. Plate formats are one letter/four digits/one letter
or three digits/three letters. Digit-first generated plates always start with 1–9,
never 0. Renewal uses the numeric section's last two digits, including when letters
appear at the end. The full manual editor still accepts existing formats.
Values are randomized on each fresh generation, with no `LOCAL-` prefix; plate
renewal digits are constrained by the selected date.
The app reserves identifiers locally and retries collisions; it does not advance
the old counter. Preview/export reuse the same random values. Generated PDFs
display `SAMPLE - GENERATED DATA`; these are not official LTO-issued identifiers.

Transaction format defaults to `MAIRD-SAR-<selected YYYYMMDD>-<random six digits>`;
the optional checkbox selects the `TX-MVIRS-` prefix instead.
The sample MV convention is `<office:4><selected YY:2><zero-padded random suffix:9>`,
for example `1336 | 26 | 007554490`. The random suffix uses up to seven significant
digits, preserving the leading zeros seen in the reference. Other supplied examples
split as `1303 | 00 | 001129304` and `0480 | 00 | 000059046`.
The selected-year convention is inferred for this generator, not a verified LTO
allocation rule. Existing MV numbers, including `00` series, remain editable in Manual.
Only generated identifier reservations (no payer details) are persisted at
`%LOCALAPPDATA%\DeveloperToolbox\lto_receipt_numbers.db`; payer entries are not stored.

### Automated Registration Workspace

Open **LTO → Registration Workspace** for saved owners/motorcycles, controlled
identifier allocation, versioned assessments, pending/confirmed payments, receipt
issuance, exact PDF reprints, migration preview/import, local roles, and audit history.
The first Windows account opening a new registry becomes its administrator. The
workspace starts with editable local defaults from your sample: Valenzuela office,
TIN 000865491001, three-year validity, and the PHP 948.00 payment template. Local
identifiers and plates are generated automatically. Open **Defaults** to edit these
values and select **Save defaults**; no import or migration is needed to start.
Starter PDFs are labeled LOCAL STARTER PROFILE. Existing configured offices and
counters are preserved. Technical configuration, migration, roles, and audit are
available only after enabling **Advanced tools**.

See [the workspace guide](docs/lto-workspace.md) for setup, configuration and import
schemas, operating steps, and transition boundaries. Start from
[the filled local configuration template](docs/lto-office-config-template.json).

The workspace uses a separate local SQLite registry at
`%LOCALAPPDATA%\DeveloperToolbox\lto_registry.db`. It does not contact payment providers
or LTMS. Payment confirmation is explicitly recorded by an assigned cashier.
The full manual Official Receipt editor remains available through its mode selector.

Open **LTO → Official Receipt** in the sidebar. Enter the receipt, field office,
payer, and vehicle details across the Receipt and Vehicle tabs. On the Payment
tab, choose Cash, GCash, or another payment method and add up to eight payment
items. Select **Preview PDF** to calculate the total and amount in words and view
the A4 receipt, then **Export PDF** to choose a local file. **Reset** clears the form.

On Payment, choose **Cash payment** or **Online payment**. Online defaults to GCash;
select or enter another method as needed. The online PDF shows the method and
Location "-", omits Cashier/POS rows, and moves the notice and barcode up. The
barcode has a light dashed frame with clear padding for both payment layouts.
The default export filename is the official receipt number plus `.pdf`; characters
Windows cannot use in filenames are replaced with underscores.

The layout is based on `assets/official_receipt_cash_payment.pdf`. No sample personal
data is prefilled or embedded in generated documents. Input stays in memory until
you export; there are no network calls. Code 128 encodes the required transaction number. The
**QR** tab offers QR Code Model 2 with receipt number, JSON summary
(receipt number, plate, total), custom text, or an existing HTTP/HTTPS URL. QR defaults
to custom text with Automatic sizing. Version 8 (49 x 49 modules) remains available.
Error correction is selectable. The actual pattern changes with the encoded data.
URLs are encoded without being
opened or fetched; payloads are limited to 300 UTF-8 bytes for print readability.
These settings do not create LTO payment verification data.
Automated transaction numbers default to `MAIRD-SAR-YYYYMMDD-######`, with a
six-digit random suffix. Check **Use TX-MVIRS transaction format** to generate
`TX-MVIRS-YYYYMMDD-######` instead. The selection applies to fresh generation
and date changes. Changing the format updates the transaction, QR, and barcode;
preview/export alone preserve the current references. Reset clears the checkbox.

Automated mode requires no QR input. It builds a link to the configured test
endpoint in `services/lto_receipt_service.py`, using the OR number as `P200_OR`
and uppercase SHA-256 of the saved UTF-8 transaction number as `P200_HASH`.
QR sizing is automatic; the barcode continues to encode the transaction number.
Preview/export preserve references; date changes and fresh generation update the
QR when the transaction changes. Manual QR settings survive mode switches.
The endpoint and hash algorithm have not been verified against an authoritative
service. A reproducible digest does not authenticate issuance or payment. Generated
PDFs remain marked as sample data; the app never opens or fetches this link.
The notice above the barcode reads: "This is a system generated Official Receipt.
No Signatures needed."
The module formats your data; it does not issue or validate an LTO receipt.

The form starts with Private - (PVT), Motorcycle Without Sidecar, Gas, N/A aircon,
and office TIN 000865491001. Default editable payment rows are Cost of plate
120.00, MVUC 720.00, Science Tax 40.50, Science Tax Penalty 7.50, Transfer Fee
50.00, and Legal Research Fee 10.00 (total PHP 948.00). Penalty Late Registration
is excluded by default. In Automated Payment or the Manual Payment breakdown,
check **Penalty Late Registration (+ PHP 120.00)** to include it (total PHP
1,068.00); uncheck it to remove it. These are the requested template amounts,
separate from the optional fee estimator. Reset restores these defaults.

The notice automatically updates to "This payment is valid until MM/YYYY and due
for renewal on MM/DD/YYYY - MM/DD/YYYY." For regular annual renewal, the selected
renewal year + 1 and plate digits determine the next nominal window. Changing the
receipt date sets the regular renewal year to its calendar year; you may override
the year on Validity. Initial and transfer transactions use their confirmed
validity inputs. Disable automatic computation on Validity to enter a manual notice.

For a record with only an MV file number, enter the 15-digit file number and enable
**I have the next renewal dates from OR/CR** on Validity. Enter the
actual next renewal start/end dates. The supplied plate-digit guidelines do not
define an MV file-digit formula, so file digits are not treated as plate digits.
An assigned plate takes priority when present.

### Understanding the Validity tab

The former Registration tab is now **Validity**. It controls the sentence about
registration validity and next renewal printed on the receipt. For ordinary annual
renewal, leave **Renew an existing registration** selected and confirm the registration
year covered by the payment. For example, paying for 2026 produces the plate-based
renewal window in 2027. The full notice is shown in a readable text box and updates
automatically. Engine size and fee estimates are not needed for this step.

Choose **Register a brand-new motorcycle** and enter its first registration date.
The form defaults to the requested **3-year** template and automatically calculates
the first renewal year (registration year + validity years). The notice uses the
plate's month/week in that year, even if that month falls before the anniversary
of the original registration date. For example, April 23, 2026 with plate Q1723B
and 3 years produces March 1–7, 2029, with validity shown as 03/2029. Check the
result against OR/CR. The period stays editable, and unchecking **Calculate the
first renewal year for me** enables a manual year override.

Choose **Transfer an existing
registration** to retain the existing expiry and specify the next renewal year.
Only relevant date fields are shown. If there is no assigned plate, the OR/CR date
section appears instead. Uncheck automatic calculation to write the notice manually.

Use **Back** and **Next** to move through Receipt, Vehicle, Validity, Payment, and QR.
Vehicle specifications and advanced QR settings are collapsed initially. Cash
collection fields are hidden for online payments and retained if you switch back.
Validation errors appear above the form so you can correct inputs without a popup.

Mouse-wheel and trackpad scrolling move the form without changing dropdown, date,
or number values, including focused fields. Change values by typing, clicking, or
using the keyboard. Clickable controls use a pointer cursor; text fields use a text
cursor, and focus outlines show the active field. Short related fields share a row.
The preview header shows the current payment total; refresh the PDF after edits.

### Optional fee estimates

Enter the plate on **Vehicle**, then open **Validity**. Select annual renewal,
initial registration, or transfer; enter engine displacement, known registration
dates, and renewal year. The receipt date is the payment date. For initial
registration, review the default 3-year period and automatically calculated first renewal year. Confirm
the editable annual MVUC (PHP 240 starting estimate) for your private motorcycle
without sidecar before applying estimates.

Expand **Optional: estimate registration fees** and select **Review estimated fees**
to review dates, estimated MVUC, and assumptions. Annual renewal estimates also need
the previous official expiry; this section appears when the fee estimator is open.
Apply the validity notice and separately opt to replace existing payment items.
Payment replacement is unchecked by default. Annual renewal suggests the following
year's plate window. Initial registration uses your confirmed validity period;
transfer retains the existing expiry and does not invent transfer fees.

Late charges are omitted while the policy is unconfirmed. A 50% MVUC estimate is
offered only for a confirmed standard policy and delay of less than one year.
Confirmed exemptions omit the penalty. Arrears of one year or more require manual
assessment. Science tax, legal research, CTPL, inspection, and other charges are
excluded; enter assessed amounts on **Payment**. Calendar windows do not adjust for
holidays or special extensions. No rules are downloaded at runtime: review current
issuances before using estimates. Calculation inputs are not saved.

Rule references:

- [LTO registration schedule](https://www.lto.gov.ph/wp-content/uploads/2023/10/FDM-vol.-2-2nd-Edition.pdf)
- [LTO November 2023 late registration memorandum](https://lto.gov.ph/wp-content/uploads/2023/11/Memo_11092023.pdf)
- [LTO NCR advisories and extensions](https://www.ltoncr.com/announcements/)
- [2026 initial-validity policy announcement](https://pia.gov.ph/news/new-5-year-lto-vehicle-registration-curbs-fixers-reduces-long-lines/)

## Persistent data

The application uses Python's built-in SQLite support; no separate database server or
package is required. Persistent data is stored locally in
`%LOCALAPPDATA%\DeveloperToolbox\developer_toolbox.db`, including theme settings, recent
files, and API history. Existing Image Toolkit Pro data is copied there automatically
on the next launch, while the original remains as a backup.

## Requirements

- Python 3.12
- Windows (for native file opening and drag/drop)

## Run

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Use **Browse Image** or drop a supported file anywhere in the window. The app accepts JPG, PNG, BMP, GIF, and WebP files up to 50 MB. Conversion occurs on a background thread. To use the monitor, open **Utilities → Input Activity Monitor**, review the privacy notice, then click **Start Monitoring**.

## Shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+O | Browse image |
| Ctrl+C | Copy raw Base64 |
| Ctrl+S | Save output |
| Ctrl+L | Clear |
| Ctrl+V | Load an image from the clipboard |

## Package

The project includes a minimal `assets/icon.ico`; replace it with your own branding if desired.

### Create the application bundle

Install PyInstaller, then build using the included spec file:

```powershell
pip install pyinstaller
pyinstaller app.spec
```

This creates `dist\DeveloperToolbox\DeveloperToolbox.exe` and its required Qt files.

### Create the Windows installer

Open `installer.iss` in Inno Setup Compiler and select **Build → Compile**. The
installer is written to `installer_output\DeveloperToolbox-Setup-1.0.0.exe`.
