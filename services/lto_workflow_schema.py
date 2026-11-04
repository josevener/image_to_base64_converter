"""Version-one schema for the local LTO transaction workspace."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS operators(username TEXT PRIMARY KEY, role TEXT NOT NULL
 CHECK(role IN ('admin','operator','cashier','viewer')));
CREATE TABLE IF NOT EXISTS office_configs(
 id TEXT PRIMARY KEY, code TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS active_office ON office_configs(code) WHERE active=1;
CREATE TABLE IF NOT EXISTS series(
 id TEXT PRIMARY KEY, office_code TEXT NOT NULL, kind TEXT NOT NULL,
 prefix TEXT NOT NULL, width INTEGER NOT NULL, first_no INTEGER NOT NULL,
 last_no INTEGER NOT NULL, next_no INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 authority TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS active_series ON series(office_code,kind) WHERE active=1;
CREATE TABLE IF NOT EXISTS identifiers(
 kind TEXT NOT NULL, value TEXT NOT NULL, record_id TEXT NOT NULL,
 origin TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(kind,value));
CREATE TABLE IF NOT EXISTS owners(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL, tin TEXT NOT NULL DEFAULT '',
 client_id TEXT UNIQUE, legacy_id TEXT UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vehicles(
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES owners(id),
 plate TEXT UNIQUE, mv_file TEXT UNIQUE, chassis TEXT NOT NULL UNIQUE,
 engine_no TEXT NOT NULL, specs TEXT NOT NULL, expiry TEXT,
 state TEXT NOT NULL DEFAULT 'new', legacy_id TEXT UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plate_stock(
 plate TEXT PRIMARY KEY, office_code TEXT NOT NULL, authority TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'available' CHECK(state IN ('available','reserved','issued')),
 vehicle_id TEXT UNIQUE REFERENCES vehicles(id));
CREATE TABLE IF NOT EXISTS transactions(
 id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE, request_digest TEXT NOT NULL,
 number TEXT NOT NULL UNIQUE, vehicle_id TEXT NOT NULL REFERENCES vehicles(id),
 payer_id TEXT NOT NULL REFERENCES owners(id), config_id TEXT NOT NULL REFERENCES office_configs(id),
 kind TEXT NOT NULL CHECK(kind IN ('initial','renewal','transfer')), state TEXT NOT NULL,
 inputs TEXT NOT NULL, assessment_id TEXT, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_vehicle_transaction ON transactions(vehicle_id)
 WHERE state IN ('Draft','Assessed','Payment Pending','Payment Confirmed');
CREATE TABLE IF NOT EXISTS assessments(
 id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL REFERENCES transactions(id),
 lines TEXT NOT NULL, total_cents INTEGER NOT NULL CHECK(total_cents>0),
 validity TEXT NOT NULL, expiry TEXT NOT NULL, renewal_start TEXT NOT NULL, renewal_end TEXT NOT NULL,
 rule_version TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payments(
 id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL REFERENCES transactions(id),
 assessment_id TEXT NOT NULL REFERENCES assessments(id), method TEXT NOT NULL,
 reference TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 status TEXT NOT NULL CHECK(status IN ('Pending','Confirmed','Failed','Voided')),
 evidence TEXT NOT NULL DEFAULT '', recorded_by TEXT NOT NULL, confirmed_by TEXT,
 created_at TEXT NOT NULL, UNIQUE(method,reference));
CREATE UNIQUE INDEX IF NOT EXISTS one_live_payment ON payments(transaction_id)
 WHERE status IN ('Pending','Confirmed');
CREATE TABLE IF NOT EXISTS receipts(
 id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL UNIQUE REFERENCES transactions(id),
 number TEXT NOT NULL UNIQUE, payment_id TEXT NOT NULL UNIQUE REFERENCES payments(id),
 snapshot TEXT NOT NULL, pdf BLOB NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS legacy_history(
 legacy_id TEXT PRIMARY KEY, vehicle_id TEXT NOT NULL REFERENCES vehicles(id),
 payload TEXT NOT NULL, paid_cents INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS migration_batches(digest TEXT PRIMARY KEY,report TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
 id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL,
 action TEXT NOT NULL, record_id TEXT NOT NULL, details TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
 BEGIN SELECT RAISE(ABORT,'Audit entries are immutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
 BEGIN SELECT RAISE(ABORT,'Audit entries are immutable'); END;
CREATE TRIGGER IF NOT EXISTS receipt_no_update BEFORE UPDATE ON receipts
 BEGIN SELECT RAISE(ABORT,'Issued receipt snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS receipt_no_delete BEFORE DELETE ON receipts
 BEGIN SELECT RAISE(ABORT,'Issued receipt snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS assessment_no_update BEFORE UPDATE ON assessments
 BEGIN SELECT RAISE(ABORT,'Assessment versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS assessment_no_delete BEFORE DELETE ON assessments
 BEGIN SELECT RAISE(ABORT,'Assessment versions are immutable'); END;
"""
