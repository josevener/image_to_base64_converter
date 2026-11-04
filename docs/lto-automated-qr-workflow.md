# Automated receipt QR workflow and database handoff

Status: local automatic QR URL generation is implemented. Website lookup and
database integration remain separate, unverified work.

## Available now

Automated mode has no editable QR field. It builds an APEX-style link to
`https://portal-lto-gov-phi.vercel.app/ords/` with `P200_OR` set to the saved OR
number and `P200_HASH` set to uppercase SHA-256 of the saved UTF-8 transaction
number. This user-supplied test endpoint is not established as an official service.
The digest convention is locally defined; its compatibility with the destination
has not been confirmed. No payer details are included. The app makes no network
request and keeps sample labels on generated PDFs. QR sizing is automatic.
Manual mode retains its independent QR options across mode switches.

## Goal

In the Python application's Automated mode, generate the QR payload from the receipt
and transaction references. The operator should not type or paste a QR URL. Database
integration belongs to the department responsible for the verification service and
can be developed separately from the local receipt preview.

Keep the existing manual QR options in Manual mode. Preserve the Code 128 barcode:
its payload remains the transaction number.

## QR service

`services/lto_receipt_service.py` supports automated URL, receipt-reference, summary, custom
text, and URL QR payloads. It does not authenticate receipts or fetch verification URLs.
It already supports automatic QR sizing, a four-module quiet zone, and a payload
limit of 300 UTF-8 bytes. Any proposed URL must fit that limit or explicitly revisit
and verify the print-size constraint.

## Proposed end-to-end operator experience

1. Enter the usual payer, vehicle, office, payment method, and editable date details.
2. Generate a fresh receipt. The application creates the OR and transaction references.
3. Automatically derive the QR reference and build the configured staging URL.
4. Preview or export the same receipt snapshot, including the same QR payload.
5. Scan the QR to test routing and reference display on the staging website.

Automated mode hides the editable QR payload field. An optional read-only disclosure
can show the generated destination and reference for troubleshooting. Configure the
staging destination once; do not require an operator to enter it for every receipt.
Use automatic QR sizing and retain the quiet zone.

Previewing, exporting, or reopening the same snapshot must not generate new numbers.
Generating a fresh transaction must regenerate its dependent QR reference. If a date
edit changes the transaction number, rebuild the QR before the next preview/export.
The finalized snapshot is the source of all printed references.

## Parameters and digest convention

The existing APEX-style parameter names can be retained as a compatibility contract:

| Parameter | Meaning |
| --- | --- |
| `P200_OR` | OR number, from `receipt_no` |
| `P200_HASH` | Test digest or future authenticated token, according to the agreed contract |

The OR number is not itself the hash. In a packed APEX query, the values appear after
the parameter-name list, separated by a comma.

For a local test reference only, the proposed deterministic convention is SHA-256
of the finalized transaction number, encoded as UTF-8, rendered as 64 uppercase
hexadecimal characters. Normalize the reference once when creating the receipt;
hash exactly the saved value, without independently changing case or whitespace
in the website. Do not hash the OR number, current clock time, or a different
transaction value by accident.

This yields a 256-bit digest, but it is publicly reproducible. Digest length and
format do not prove payment, issuance authority, or authenticity. This test digest
is a reference for exercising the workflow, not a production authentication scheme.

Build URLs with a URL library and test the complete encode/decode round trip. Do not
assume an APEX-style packed query will parse like ordinary separate query parameters.
Reject malformed input and duplicate or ambiguous parameters at the service boundary.

## Staging before database integration

The full local workflow can be tested without a production database:

- Generate the QR locally; the desktop app makes no network request.
- Opening the QR in a browser is a separate, user-initiated action.
- Display a persistent **STAGING - TEST DATA** indicator on the destination.
- Without an authoritative lookup, display **Reference received - verification unavailable**.
- A small fixture store may return **Matched staging record** for an exact saved test pair.
- Unknown or incorrect pairs return **No matching staging record**; a well-formed
  hash alone must never produce an official-verification result.
- Keep staging output clearly identified as test output, including exported samples.

The department can replace the fixture adapter with its database lookup later,
without changing the receipt form. This makes routing, QR scanning, URL parsing,
and snapshot consistency testable now without asserting that payment was verified.

## Department responsibilities

| Python application | Verification service / database department |
| --- | --- |
| Generate local test identifiers and immutable receipt snapshots | Define authoritative identifiers, record ownership, and issuance rules |
| Build the QR from the finalized snapshot | Parse the link and look up the corresponding saved record |
| Preserve matching PDF, QR, and barcode references | Confirm payment and receipt state, including voided/revoked records |
| Export test fixtures for handoff | Import fixtures into an isolated test store and implement production persistence |
| Keep staging configuration separate from production | Provide authenticated issuance, token management, and deployment configuration |

## Proposed handoff record

Agree on this minimal record before connecting the systems. These are proposed
fields, not an existing API or confirmed database schema.

| Field | Purpose |
| --- | --- |
| `schema_version` | Version of the handoff contract |
| `environment` | Explicitly `staging` for test records |
| `receipt_no` | Unique receipt reference in its environment |
| `transaction_no` | Exact saved transaction reference used by the QR workflow |
| `test_digest` | SHA-256 reference for staging fixtures only |
| `payment_at` | Selected payment timestamp, with agreed timezone/offset |
| `created_at` | Actual snapshot creation timestamp, distinct from editable payment date |
| `amount_minor` | Integer payment amount in centavos |
| `currency` | `PHP` |
| `receipt_state` | For example `test`, `issued`, or `voided`, with agreed transitions |

Use fictional payer data in fixtures. Do not put payer names, addresses, client IDs,
or payment credentials into the public QR URL. The minimal lookup record does not
need those details. The database team should define duplicate handling and reject
conflicting reuse of a receipt reference. An imported test record is not evidence
that a production payment was confirmed.

## Production transition

Before enabling actual receipt verification, the backend must issue a signed token
or a securely generated opaque token bound to the saved receipt and its transaction.
A plain transaction-number digest is insufficient. Signing secrets must remain on
the backend, outside the desktop app and browser bundle.

The service must check the token against the authoritative record and current
receipt/payment state. Token format, expiration/revocation rules, API authentication,
and the production domain require an agreed backend contract. Version the token
contract so staging digests cannot be interpreted as production credentials.

This document does not request a production database, provider migration import, or
additional per-receipt setup from the operator. Those integrations remain a separate
department handoff.

## Acceptance checks for the eventual implementation

- Automated mode requires no QR typing; Manual mode retains custom QR options.
- The same finalized transaction always produces the same staging digest.
- A changed transaction updates the QR; preview/export alone leave it unchanged.
- Parsing the generated URL recovers the exact OR and digest values.
- The printed QR scans successfully at the actual PDF size and automatic version.
- Barcode decoding still returns the exact transaction number.
- A wrong digest, unknown OR, or malformed URL never displays a successful match.
- Database unavailability displays verification unavailable rather than a success.
- Staging records and links remain distinct from production verification.

The local implementation is covered by the LTO test suite, including deterministic
digest generation, reference changes after date edits/fresh generation, stable
preview/export references, and Manual-mode custom QR preservation. Website matching,
URL parsing, database status, and physical scanner checks remain integration acceptance
tasks; passing local tests does not demonstrate those capabilities.
