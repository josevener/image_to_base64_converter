# Local Registration Workspace

Open **LTO → Registration Workspace**. The existing **Official Receipt** page remains
the manual document editor; the workspace is the saved transaction workflow.

## Start without setup files

A new workspace opens ready to use with editable defaults from the provided receipt:

- Valenzuela District Office, code 1396, office TIN 000865491001, and cashier station.
- Three-year initial registration validity and plate-based renewal dates.
- The six requested payment items totaling PHP 948.00.
- LOCAL transaction, receipt, client, and plate numbering; MV file numbers use a
  local `0000` prefix. Plates are generated locally as needed, without a stock import.

Add an owner and motorcycle on **Records**, then create a transaction. No JSON,
migration, or import is required. Open **Defaults** to edit the office, validity,
payment items per transaction type, and numbering. Select **Save defaults** once.
Saved assessments/receipts and number counters are preserved when defaults change.

The initial profile is explicitly local. Its PDFs display **LOCAL STARTER PROFILE**;
its fee values are the requested sample template, not a verified production tariff.
Existing configured registries are not overwritten with starter values.

**Advanced tools** reveals optional registry switching, assigned inventory/ranges,
operator administration, migration, and audit. These are outside the everyday flow.
The app opens maximized while retaining Windows title-bar controls.

## What is implemented

- Persistent owners and motorcycles, with chassis-based duplicate checks.
- Office/rule configuration versions and assigned numeric ranges.
- Plate inventory import and draft-time reservations.
- Draft → Assessed → Payment Pending → Payment Confirmed → Issued transactions.
- Automatic transaction, MV file, optional client, and receipt number assignment.
- Manual assessments with a mandatory reason and retained assessment versions.
- Reasoned owner-contact and vehicle-specification corrections, with open-record locks.
- Explicit manual payment confirmation, failed-payment retry, and pre-issuance voids.
- Immutable receipt snapshots and stored PDF bytes for exact historical reprints.
- Atomic migration preview/apply, conflict detection, historical records, and retained identifiers.
- Local Windows-account roles, audit history, and consistent SQLite backups.

The starter values are clearly local rather than official assignments. Public
statistics and sample receipts cannot establish which identifiers belong to the
incoming provider. Assigned operational ranges can be configured in Advanced tools.

## Optional assigned-office setup

1. The first Windows account opening a new local registry is assigned `admin`.
2. Enable **Advanced tools** and open **Defaults**. Load or edit an assigned office configuration using the schema below.
3. Enter the handed-over authority reference, office, rule version, effective dates,
   assessed fee schedule, and assigned number ranges. Save the configuration.
4. Import the actual unassigned plate inventory, one plate per line, with its batch
   or authority reference. Re-importing the same stock list preserves reservations.
5. Assign Windows usernames to roles. This application does not collect passwords.
6. Import reviewed legacy records on **Migration**, if available.

The default registry is `%LOCALAPPDATA%\DeveloperToolbox\lto_registry.db`. It is separate
from application settings. **Open local registry** selects an existing registry and
remembers its path. The Windows account must already be assigned a role in it.

For several Windows accounts on the same computer, use one local registry file
accessible under the agreed Windows filesystem permissions. Each account must open
that same registry. Do not place a live SQLite database on a network share or use
separate copies as if they shared a numbering series.

## Roles

| Role | Operations |
| --- | --- |
| Viewer | Read records, transactions, history, audit, and issued receipts; export issued receipts. |
| Operator | Viewer functions, create owners/vehicles, create drafts, and assess fees. |
| Cashier | Viewer functions, record/confirm/fail payments, and issue receipts. |
| Admin | All functions, configuration, stock import, migration, role assignment, backup, and pre-issuance voiding. |

Permissions are enforced in the service, not just by disabled buttons. At least one
admin must remain. This local design trusts Windows identity and filesystem access;
it is not centralized authentication or tamper-proof storage against someone with
direct write access to the database. Enterprise identity and deployment controls
remain production deployment decisions.

## Office configuration schema

`docs/lto-office-config-template.json` contains the filled local starter profile.
For an assigned operational office, use the schema below with its handover values,
omit `profile_type: local_starter`, and remove the local automatic `plate` series.

```json
{
  "authority_reference": "HANDOVER OR APPROVAL REFERENCE",
  "office": {
    "code": "ASSIGNED_CODE",
    "name": "ASSIGNED OFFICE NAME",
    "address": "ASSIGNED OFFICE ADDRESS",
    "tin": "ASSIGNED OFFICE TIN",
    "pos_machine": "ASSIGNED POS OR CASHIER STATION"
  },
  "rules": {
    "version": "APPROVED_RULE_VERSION",
    "effective_from": "YYYY-MM-DD",
    "effective_until": "",
    "initial_years": 3,
    "validity_mode": "confirmed_dates",
    "fees": {}
  },
  "series": []
}
```

The capitalized strings and date above are placeholders. Replace them before import.
Office codes contain 1–8 uppercase letters/digits.

### Identifier series

Each entry in `series` has these properties:

| Property | Meaning |
| --- | --- |
| `kind` | `transaction`, `receipt`, `mv_file`, or optional `client`. |
| `prefix` | Assigned literal prefix, optionally containing `{office}`, `{date}`, or `{type}`. |
| `width` | Number of zero-padded sequence digits, from 1 to 15. |
| `first` | First available number handed over for this range; integer. |
| `last` | Last permitted number in this range; integer. |

`{date}` is `YYYYMMDD`. `{type}` is `INITIAL`, `RENEWAL`, or `TRANSFER`.
The final value is the expanded prefix followed by the padded number. There is no
implicit daily/yearly reset. Final MV file numbers must contain exactly 15 digits;
transaction numbers permit up to 60 printable ASCII characters, and receipt numbers
permit up to 40. Client IDs permit up to 100.

Transaction series are required to create a draft; receipt series are required to
issue a receipt. New motorcycles without an MV file number also need an `mv_file`
series. If a client series is configured, a new initial-registration payer without
a client ID is assigned one. Existing client identities are reused.

Re-importing an unchanged range keeps its current counter. Overlapping ranges and
reactivating historical ranges are rejected. When a range is exhausted, import a
new assigned non-overlapping range. Already issued/reserved identifiers are checked
again at allocation, including identifiers retained from migration.

### Fee rules

`rules.fees` maps any supported transaction kind (`initial`, `renewal`, `transfer`)
to 1–8 entries. Each entry contains:

- `description`: the assessed fee label, at most 60 characters.
- `amount`: a positive decimal string with at most two decimal places.
- `basis`: `fixed` or `per_validity_year`.

`per_validity_year` multiplies the amount by `initial_years` for initial registration;
renewal and transfer use one year. Omit zero/free items. There are no implicit late
penalties, science-tax formulas, or sample PHP 948 totals in the workspace.

Unsupported/exceptional assessments can be entered through **Manual assessment**
with a reason. A new assessment version is saved; a pending or confirmed payment
locks the assessment from changes. Office configuration is captured when the draft
is created, so later fee changes do not rewrite an open transaction's rule version.

This first fee engine supports fixed and per-validity-year charges. More complex
statutory formulas, exemptions, arrears, and proration need approved extensions to
the rule engine or a reasoned manual assessment.

### Validity rules

- `confirmed_dates` requires validity expiry, next-renewal start, next-renewal end,
  and the OR/CR/source reference on the new transaction form.
- `plate_schedule` uses the existing plate-month/week calculator. Initial registration
  uses the registration year plus configured `initial_years`; annual renewal uses
  the previous expiry year plus one. Transfer retains the existing expiry.
- `renewal_early_days` optionally specifies the approved early-renewal window (0–365
  days). When omitted it is zero, so the system does not assume an early-renewal
  allowance. Late renewal requires a reasoned manual assessment of penalties or an
  exemption; the fixed renewal schedule is not silently used as the final amount.
- Supplied confirmed dates override the calculated schedule and require a reason.
- Plate-less records and multi-year arrears need confirmed assessed dates.

The three-year default in the template is an editable configuration value. Saving
it is not verification of the rule's current applicability. Confirm rule versions
and exception dates against the provider handover and official records.

## Daily workflow

1. On **Records**, save the owner and motorcycle. Chassis number, engine number,
   engine size, color, year, and specifications are required. Existing registrations
   need their official expiry date. Existing plate/MV/client numbers are preserved.
2. On **Transactions**, select **New transaction**, office, saved motorcycle, type,
   and registration/transaction date. A transfer also needs the new saved owner.
3. Enter confirmed dates when required by the configured rules. Create the draft.
4. The draft reserves its transaction number. New-registration drafts reserve an
   MV file number and a plate from inventory when those identifiers are missing.
5. Select **Assess**, or enter a reasoned **Manual assessment**.
6. A cashier records the exact assessed amount and a payment/cashier reference.
   The payment starts as **Pending**. Partial payments are not supported.
7. Select **Confirm payment** and enter the evidence/reconciliation reference.
   Selecting GCash or entering a reference does not perform a provider lookup.
8. Select **Issue receipt**. A receipt number is allocated, registration/ownership
   is completed, and the snapshot plus generated PDF is saved atomically.
9. **View PDF** or **Export** retrieves the stored artifact. The export filename is
   the issued receipt number. Owner/rate changes do not alter historical reprints.

Select a saved owner/motorcycle row on **Records** to correct contact information
or vehicle specifications. Saving a correction requires a reason. Assigned IDs,
physical identifiers, ownership, and existing expiry cannot be changed through this
correction form. Records used by open transactions must be completed or voided first.
Select **New owner / clear selection** or **New motorcycle / clear selection** to
start another record rather than edit the selected one.

The printed payment date comes from the payment recording timestamp. Audit and
storage timestamps use UTC; printed payment timestamps use the device's local zone.
The barcode uses the transaction number. The QR uses the issued receipt number;
external verification URLs/signatures are not invented or integrated.

Pending payments can be marked **Failed** with a reason, then retried using a new
payment reference. A reference cannot be reused for a different transaction/amount.
Admins can void a transaction before issuance. Its numbers remain reserved and its
audit/history remain intact. Confirmed payments cannot be voided through this workflow.
Confirmed-payment and issued-registration reversals/refunds require a separate
approved process and are not implemented as a destructive undo.

## Migration bundle

UTF-8 JSON files are limited to 20 MB. Each array supports at most 5,000 records per
bundle. Import related records together or refer to legacy IDs imported previously.

```json
{
  "owners": [],
  "vehicles": [],
  "history": [],
  "issued_identifiers": []
}
```

| Array | Record fields |
| --- | --- |
| `owners` | `legacy_id`, `name`, `address`; optional `tin`, `client_id`. |
| `vehicles` | `legacy_id`, `owner_legacy_id`, `chassis`, `engine_no`, `engine_cc`, `color`, `year_model`, `classification`, `vehicle_type`, `fuel_type`, `aircon_type`; optional existing `plate`, `mv_file`, `expiry`. |
| `history` | `legacy_id`, `vehicle_legacy_id`, `registration_date`, `expiry`, `status`, `paid_amount`; optional `receipt_no`, `transaction_no`, and additional source metadata. |
| `issued_identifiers` | `kind` and `value`, for assigned identifiers outside the detailed records being imported. |

Dates use `YYYY-MM-DD`. Identifiers use strings so leading zeros are preserved.
History status is `Confirmed`, `Voided`, `Pending`, or `Failed`. Confirmed historical
payments require a positive paid amount. The full history payload is retained.

**Preview / validate** executes validation in a rolled-back database transaction.
Review counts, unchanged records, and the confirmed paid total (integer cents).
**Apply reviewed import** accepts only the same content digest and saves all rows
or none. Repeating the same import is idempotent. Changed legacy records, broken
relationships, and conflicting identifiers cause the import to fail without changes.

Legacy history is read-only reconciliation data. It does not become a live payment
confirmation or permit new receipts to be issued for old payments. Historical PDF
import, legacy PDF reprinting, and resuming in-flight legacy transactions require
an agreed source mapping and are not implemented by guessing from a summary export.

## Backups and transition boundaries

Use **Back up local registry** for a consistent SQLite backup, including stored PDFs,
roles, counters, history, and audit events. Copying only the `.db` file while WAL is
active is not a substitute for this backup action. Protect backups as registry data.

This implementation is local-only and does not connect to LTMS, GCash, Maya, FOI,
cloud services, or the outgoing provider. It does not parse Citizen's Charter PDFs
into verified fee rules. Assigned ranges, actual inventory, migration mappings,
production concurrency/deployment review, external confirmation contracts, and
cutover/rollback reconciliation still need the provider handover.

## Verification

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Workflow fixtures use explicitly synthetic `TEST` identifiers and rates only in
isolated test databases. They are not loaded into an operator's registry.
