# LTO Receipt Automation

For the local automatic staging QR flow and the separate database department handoff,
see [Automated receipt QR workflow](lto-automated-qr-workflow.md).

Automated mode now generates a staging JSON QR from the OR number and a SHA-256
test reference derived from the transaction number. No manual QR entry is required.
Manual mode retains custom QR options. This payload identifies test data; website
routing and payment verification require a separate backend integration.

## Current scope: generate from a short form

Open **LTO → Official Receipt**, which starts in **Automated** mode. The user enters
only these details (editable office defaults and current year are prefilled):

| Manual input | Description |
| --- | --- |
| Received From | Recipient's full name |
| Address | Recipient's address |
| Color | Motorcycle color |
| Year model | Motorcycle model year |
| Field Office | Issuing office name |
| Office Code | Issuing office code |
| Office Address | Issuing office address |
| LTO Client ID / LTO Business ID | User-provided client identifier |
| Mode of payment | Cash, GCash, Maya, bank transfer, card, or another method |

**Enter details → Generate fresh receipt → Preview / Export PDF.**

The app generates the OR number, transaction number, local plate, 15-digit MV file
number, payment date/time, and plate-based renewal notice. Brand-new registration
uses three-year validity. Existing private motorcycle, Gas, N/A aircon, office TIN,
and PHP 948.00 payment defaults populate automatically. Totals, amount in words,
QR, barcode, and the OR-number PDF filename are computed automatically.

Preview and export retain the generated numbers. **Generate fresh receipt** reserves
new numbers while keeping the user's form entries. An office-code change also
generates identifiers for that office. Random identifier reservations survive app
restarts so duplicates can be rejected; personal form data is not saved.
No OR/CR, registry records, imports, migration,
or provider setup is required. **Manual** mode remains available for detailed edits.

Identifier formats now match the samples in `assets`: a four-digit office code
and twelve-digit OR suffix (`1396-000000580412`),
`TX-MVIRS-YYYYMMDD-241123` transactions, exactly six-character plates such as
`Q1723B` or `681TZS`, and fifteen-digit MV file numbers. The generator randomly
chooses one letter/four digits/one letter or three digits/three letters. Each fresh
generation randomizes the OR suffix, transaction suffix, remaining plate characters,
and MV file suffix. The numeric section's final two digits match the date-based target;
trailing letters do not affect renewal. Manual entry still supports existing plate formats.
There is no advancing series and no `LOCAL-` prefix in this generator.

### Plate-based renewal calculation

The selected date plus three years sets the target. The generated plate is then
matched to the closest standard renewal window ending on or before that target:

- Last numeric digit: 1–9 means January–September; 0 means October.
- Second-to-last numeric digit: 1/2/3 means days 1–7; 4/5/6 means 8–14;
  7/8 means 15–21; 9/0 means 22 through month-end.
- Brand-new automated mode uses the editable receipt / first-registration date
  to establish a three-year maximum. Rather than accepting an unrelated random
  renewal month, the generator chooses plate endings for the closest complete
  window ending on or before that anniversary. Other plate characters remain random.
  The standard calendar has no November/December plate month, so those targets
  and early-January targets use the closest earlier available window.
  This is an explicit sample alignment policy, not an official validity determination.

The date defaults to generation time, is editable under **Payment**, and is preserved
after a manual edit, including during fresh generation. **Use current date and time**
restores the automatic default. Changing it recalculates validity and may reserve
a replacement plate. The OR remains unchanged. Transaction `YYYYMMDD` follows
the selected receipt date, retaining its random suffix where available; the sample
MV file's two-digit year also follows the selected year. Replacement references are
reserved locally; a collision causes a new random suffix rather than a duplicate.
For October 14, 2026, the cap is October 14, 2029. Generated plate endings are
`40`, `50`, or `60`, giving October 8–14, 2029 and validity until 10/2029.
The generator no longer chooses an unrelated May-ending plate for that date.

### Transaction and MV file sample conventions

The transaction reference uses the selected date, not the computer's current date:
`TX-MVIRS-20261014-572996` for October 14, 2026, with a random six-digit suffix.

The supplied MV examples can be grouped consistently as:

| Supplied value | Four-digit prefix | Two-digit group | Padded nine-digit suffix |
| --- | --- | --- | --- |
| `133626007554490` | `1336` | `26` | `007554490` |
| `130300001129304` | `1303` | `00` | `001129304` |
| `048000000059046` | `0480` | `00` | `000059046` |

For new generated samples, use the selected office prefix, selected two-digit year,
and a nine-digit zero-padded random suffix with up to seven significant digits.
This replaces the previous entirely random eleven-digit tail. The examples do not
prove that the two-digit group always encodes a year; this is an explicit sample
convention, not a verified LTO issuance specification. Manual entry preserves
existing full MV numbers, including zero-series examples.

For example, `AB12345` schedules May 8–14 in the calculated renewal year. These
are standard calendar windows containing the applicable working days; holiday
adjustments, extensions, and record-specific exceptions are not inferred.
Sources: [LTO Driver's Manual, volume 2, page 17](https://www.lto.gov.ph/wp-content/uploads/2023/10/FDM-vol.-2-2nd-Edition.pdf)
and [LTO AO AVT-2014-025](https://elibrary.judiciary.gov.ph/thebookshelf/showdocs/10/76962),
which confirms the second-to-last numeric digit for five-digit motorcycle plates.

Payment types are **Cash**, **E-wallet**, and **Online payment**. Choose GCash,
Maya, GrabPay, ShopeePay, bank transfer, card, or online banking, or type another
method. Non-cash receipts show the selected method and Location `-`, and omit
cashier/POS rows, matching the online sample.

PDFs display `SAMPLE - GENERATED DATA`. Generated identifiers do not represent
an official plate assignment or verified payment.

## Earlier provider-transition proposal (optional separate workspace)

The remainder documents the broader Registration Workspace. It is separate from
the short-form receipt generator and is not a prerequisite for using it.

## Implementation status

The local **Registration Workspace** is implemented. See [the operating and setup
guide](lto-workspace.md) for supported workflows, configuration/import schemas, and
remaining handover/deployment dependencies. Production ranges, official inventory,
fee formulas, external verification, and cutover data are not assumed from samples.

## Objective

Revamp the registration and receipt workflow for the transition from the outgoing
provider to the replacement system. This is an operational transaction-processing
workflow, rather than sample-data generation or a form that fills itself with random
identifiers.

The system should create and link records, perform assessments, record confirmed
payments, assign identifiers under the applicable allocation rules, and generate
receipts. Keep controlled manual correction available for exceptional transactions,
with the operator and reason recorded.

The existing receipt module is a presentation component of this proposed system.
Its editable sample amounts and validity defaults are not a production assessment
engine. Operational assessments need an approved, versioned rule configuration.

## Proposed workflow

**Find owner → Select motorcycle → Choose transaction → Review assessment → Record payment → Generate PDF**

| Step | Automated behavior |
| --- | --- |
| Find owner | Search by name or LTO client ID and populate address and TIN. |
| Select motorcycle | Search by plate or MV file number and populate vehicle specifications. |
| Choose transaction | Load registration history and calculate proposed renewal dates. |
| Assess payment | Suggest itemized charges using configurable fee rules. |
| Record payment | Save payment method, date, amount, and cashier. |
| Generate receipt | Populate the PDF, QR code, barcode, and export filename. |
| Retrieve later | Search, view, and reprint previously generated receipts. |

## Automated generation and assignment

The replacement system can generate or assign identifiers as part of processing a
transaction. Each identifier needs a defined owner, format, uniqueness scope, and
issuance point. Existing identifiers must be preserved during migration.

| Field or record | Proposed operational behavior | Required transition input |
| --- | --- | --- |
| Internal record ID | Automatically create a unique ID for each owner, vehicle, transaction, assessment, payment, and receipt. | Internal database design; map legacy record IDs separately. |
| Plate number | For a new registration, allocate from authorized plate inventory or an approved assignment mechanism. For existing vehicles, retrieve the assigned plate. | Available and reserved plate inventory, allocation rules, and existing vehicle-to-plate assignments. |
| MV file number | Assign at the permitted registration stage using the approved numbering scheme; retain the existing number for renewals and transfers. | Number format, issuing-office rules, allocation authority, and already issued/reserved numbers. |
| Transaction number | Generate when a transaction is created, following the agreed transaction-type, office, date, and sequence rules. | Approved format, sequence scope, and cutover starting values. |
| Official receipt number | Issue from the approved receipt series at the defined issuance stage after payment confirmation. | Assigned series, last issued number, reserved numbers, and void/cancellation rules. |
| LTO client ID | Retrieve an existing client identity or create one through the approved new-client process. | Client identity rules and migrated client records; do not create a new identity for every payment. |
| Registration validity and renewal notice | Calculate from the transaction, vehicle record, effective rules, plate schedule, and applicable exceptions. | Approved rules, effective dates, exemptions, and existing registration history. |
| Payment breakdown | Calculate from the assessed transaction and effective fee schedule. | Approved rates, formulas, rounding rules, exemptions, and assessment examples. |
| Office and cashier details | Populate from office configuration and the signed-in operator's assignment. | Office codes, office details, cashier accounts, and POS assignments. |
| Payment reference | Store the reference from the payment confirmation or cashier record and link it to one assessment. | Confirmation and reconciliation procedures, including duplicate-payment handling. |
| QR code | Encode the approved receipt identification or verification payload. | Payload specification, verification mechanism, and any required signing/key arrangements. |
| Barcode | Encode the saved transaction number, as required by the current receipt layout. | Confirmed barcode payload specification. |
| PDF filename | Use the issued official receipt number with a `.pdf` extension. | Receipt issuance result. |

Official plates and identifier formats must not be inferred solely from sample
receipts. Automatic assignment depends on the agreed allocation authority and
transition data. If the incoming provider is authorized to issue a series, the
system should implement that series directly with the required controls.

## Transaction lifecycle and controls

1. Find an existing owner and motorcycle, or register verified new records.
2. Create one transaction with its own identifier.
3. Validate the transaction's required information and supporting records.
4. Create an itemized assessment and save the rule version used.
5. Record and confirm payment against that assessment.
6. Complete the permitted registration and identifier-allocation steps in the
   order specified by the operational rules.
7. Issue and save the receipt with a snapshot of the data used for rendering.
8. Make the completed transaction searchable and support historical reprints.

Identifier reservations and issuance must be atomic and unique within their defined
scope, including when multiple operators work concurrently. Retrying an operation
must return its existing result instead of issuing another transaction, receipt,
or plate assignment. Record voided and cancelled identifiers rather than silently
reusing them. Historical reprints should use the saved receipt snapshot rather
than recomputing an old transaction with today's rates or owner details.

## Provider transition and migration

Obtain and reconcile the following handover information:

- Owner and vehicle records, their relationships, and legacy identifiers.
- Registration history, expiry dates, plate assignments, and relevant statuses.
- Open transactions, assessments, payments, reversals, and outstanding balances.
- Receipt history, receipt series, last issued numbers, reservations, and voids.
- Unassigned plate inventory and any existing reservations.
- Office, cashier, operator-role, and POS configuration.
- Approved fee/validity rules, effective dates, and exception handling.
- Import formats, field definitions, code lists, and any authorized interface specifications.

Run a migration rehearsal, report duplicates and missing relationships, reconcile
record counts and payment totals, and test representative transactions before
cutover. Define when the outgoing provider stops issuing identifiers and when the
replacement starts. Agree on handling in-flight payments and transactions, backup,
and rollback so both providers cannot issue overlapping identifiers.

## Local data storage

The current desktop application uses SQLite. It can support the local implementation
and migration prototypes. Confirm the production database and deployment design
against the expected operator concurrency, transaction volume, recovery needs, and
identifier-allocation requirements before deployment. Add records for these entities:

| Entity | Information to store |
| --- | --- |
| Owners | Name, address, TIN, and LTO client ID. |
| Motorcycles | Owner, plate number, MV file number, and vehicle specifications. |
| Registrations | Transaction type, registration date, validity, and renewal dates. |
| Payments | Itemized charges, payment method, amount, payment reference, and payment status. |
| Receipts | Receipt reference, transaction reference, generation date, and the data used to generate the document. |
| Office settings | Office details, cashier, POS station, and configurable fee schedules. |

## Ways to populate records

### 1. Saved records

Enter owner and motorcycle information once, then reuse it for subsequent transactions.

### 2. CSV import

Load multiple owners and motorcycles from a spreadsheet exported as CSV.

### 3. PDF or image import

Extract information from existing OR/CR documents. Show extracted values for correction
and review before saving them as records.

### 4. Authorized system integration

Import confirmed assessments and payment results from an existing system when documented,
authorized access is available. This is an optional future integration; it is not part
of the initial local-only implementation.

## Payment confirmation

Keep payment confirmation separate from selecting a payment method. Choosing GCash in
the current form labels the receipt; it does not verify that a payment occurred.

Support the following payment statuses:

- Pending
- Confirmed
- Failed
- Voided

Generate the final receipt from a confirmed payment record.

## Receipt references and codes

Local references can be generated automatically. Official receipt numbers and other
assigned identifiers can also be issued by the replacement system when the incoming
provider has the corresponding approved series and allocation authority. Otherwise,
retrieve them from the responsible authorized source.

A locally generated QR code can identify the saved local record. It should not be
represented as official LTO payment verification. Populate the existing barcode and
filename from the corresponding saved transaction and receipt references.

## Recommended next version

Implement these capabilities first, after confirming the handover and allocation rules:

1. Saved owners and motorcycles.
2. Registration history.
3. A transaction lifecycle with controlled identifier generation and assignment.
4. Configurable, versioned fee and validity assessments.
5. Payment recording with explicit confirmation status and reconciliation.
6. Receipt issuance from a confirmed payment, saved snapshots, and reprinting.
7. Migration imports, duplicate checks, operator permissions, and an audit history.

Preserve the current PySide6 interface and MVC separation: views in `pages/` and `ui/`,
non-visual operations in `services/`, and coordination in `app.py`. Keep the first
version local-only, with no network requests, telemetry, or cloud synchronization.

This document describes the broader transition proposal. The implementation guide
identifies which portions are available in the current local workspace and which
still require provider handover details or additional production integration work.
