"""Local transaction processing, allocation, payment records, and immutable receipts.

Fresh workspaces can use an explicitly local, editable starter profile.
The Windows account identifies the operator; database/filesystem access is the
security boundary of this local desktop implementation.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import re
import sqlite3
import string
import os
import tempfile
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from services import database_service
from services.lto_receipt_service import Charge, ReceiptData, DEFAULT_RECEIPT_CHARGES, generate_receipt, parse_amount, save_receipt
from services.lto_registration_service import renewal_window, validity_notice
from services.lto_workflow_schema import SCHEMA


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _required(value: Any, label: str, maximum: int = 100) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f'{label} is required (up to {maximum} characters).')
    return value.strip()


def _date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{label} must be a date in YYYY-MM-DD format.') from error


def _optional(value: Any, label: str, maximum: int = 100) -> str:
    if value is None:
        return ''
    if not isinstance(value, str) or len(value.strip()) > maximum:
        raise ValueError(f'{label} must be text, up to {maximum} characters.')
    return value.strip()


def _cents(value: str) -> int:
    return int(parse_amount(value) * 100)


def _identifier(kind: str, value: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f'{kind.replace("_", " ").title()} identifiers must be strings, preserving leading zeros.')
    value = value.strip()
    if kind == 'plate':
        value = re.sub(r'[\s-]', '', value.upper())
        valid = bool(re.fullmatch(r'[A-Z0-9]{2,12}', value))
    elif kind == 'mv_file':
        value = re.sub(r'[\s-]', '', value)
        valid = bool(re.fullmatch(r'[0-9]{15}', value))
    else:
        maximum = {'transaction': 60, 'receipt': 40, 'client': 100}.get(kind)
        valid = maximum is not None and 0 < len(value) <= maximum and value.isascii() and value.isprintable()
    if not valid:
        raise ValueError(f'Invalid {kind.replace("_", " ")} identifier: {value[:60]}')
    return value


class LtoWorkflowService:
    def __init__(self, path: Path | None = None, actor: str | None = None, allow_create: bool = True) -> None:
        self.path = Path(path) if path else database_service.DATA_DIRECTORY / 'lto_registry.db'
        self.actor = actor or getpass.getuser()
        if not allow_create and not self.path.is_file():
            raise ValueError('Select an existing local registry database.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            if not allow_create:
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'operators', 'transactions', 'receipts', 'office_configs'}.issubset(tables):
                    raise ValueError('The selected file is not an LTO workspace registry.')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 1:
                raise ValueError('This registry was created by a newer application version.')
            db.executescript(SCHEMA)
            db.execute('PRAGMA user_version=1')
            db.commit()
        with self._write() as db:
            if not db.execute('SELECT 1 FROM operators LIMIT 1').fetchone():
                db.execute('INSERT INTO operators VALUES(?,?)', (self.actor, 'admin'))
                self._audit(db, 'bootstrap_admin', self.actor, {'role': 'admin'})

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        return db

    @contextmanager
    def _write(self, dry_run: bool = False) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.rollback() if dry_run else db.commit()
        except sqlite3.IntegrityError as error:
            db.rollback()
            raise ValueError(f'Duplicate or conflicting record; nothing was saved. {error}') from error
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _audit(self, db: sqlite3.Connection, action: str, record_id: str, details: Any) -> None:
        db.execute('INSERT INTO audit(at,actor,action,record_id,details) VALUES(?,?,?,?,?)',
                   (_now(), self.actor, action, record_id, _json(details)))

    def _allow(self, db: sqlite3.Connection, *roles: str) -> str:
        row = db.execute('SELECT role FROM operators WHERE username=?', (self.actor,)).fetchone()
        if row is None or row['role'] not in roles:
            raise ValueError(f'Your Windows account ({self.actor}) is not assigned the required role.')
        return row['role']

    def _read(self, query: str, args: tuple = ()) -> list[dict]:
        db = self._connect()
        try:
            self._allow(db, 'admin', 'operator', 'cashier', 'viewer')
            return [dict(row) for row in db.execute(query, args)]
        finally:
            db.close()

    def _reserve(self, db: sqlite3.Connection, kind: str, value: str, record_id: str, origin: str) -> str:
        value = _identifier(kind, value)
        existing = db.execute('SELECT record_id FROM identifiers WHERE kind=? AND value=?', (kind, value)).fetchone()
        if existing:
            if existing['record_id'] == record_id:
                return value
            raise ValueError(f'{kind.replace("_", " ").title()} {value} is already assigned or retained in history.')
        db.execute('INSERT INTO identifiers VALUES(?,?,?,?,?)', (kind, value, record_id, origin, _now()))
        return value

    def _allocate(self, db: sqlite3.Connection, kind: str, office: str, record_id: str, day: date, task: str) -> str:
        row, value = self._next_identifier(db, kind, office, day, task)
        value = self._reserve(db, kind, value, record_id, 'allocated')
        db.execute('UPDATE series SET next_no=next_no+1 WHERE id=?', (row['id'],))
        self._audit(db, 'allocate_identifier', record_id, {'kind': kind, 'value': value, 'series_id': row['id']})
        return value

    def _next_identifier(self, db: sqlite3.Connection, kind: str, office: str, day: date, task: str) -> tuple[sqlite3.Row, str]:
        row = db.execute('SELECT * FROM series WHERE kind=? AND office_code=? AND active=1', (kind, office)).fetchone()
        if row is None:
            raise ValueError(f'Configure an assigned {kind.replace("_", " ")} series for office {office} first.')
        if row['next_no'] > row['last_no']:
            raise ValueError(f'The assigned {kind} series is exhausted. Import a new authorized range.')
        prefix = row['prefix'].format(office=office, date=day.strftime('%Y%m%d'), type=task.upper())
        value = prefix + str(row['next_no']).zfill(row['width'])
        return row, _identifier(kind, value)

    def summary(self) -> dict:
        role = self._read('SELECT role FROM operators WHERE username=?', (self.actor,))[0]['role']
        counts = {table: self._read(f'SELECT COUNT(*) AS n FROM {table}')[0]['n']
                  for table in ('owners', 'vehicles', 'transactions', 'receipts')}
        return {'actor': self.actor, 'role': role, 'database': str(self.path), 'counts': counts,
                'offices': self._read('SELECT id,code,payload FROM office_configs WHERE active=1 ORDER BY code'),
                'operators': self._read('SELECT * FROM operators ORDER BY username'),
                'series': self._read('SELECT office_code,kind,prefix,width,first_no,next_no,last_no,authority FROM series WHERE active=1'),
                'stock': self._read('SELECT office_code,state,COUNT(*) AS quantity FROM plate_stock GROUP BY office_code,state')}

    def configure(self, payload: dict) -> str:
        if not isinstance(payload, dict):
            raise ValueError('Office configuration must be a JSON object.')
        office = payload.get('office', {})
        if not isinstance(office, dict):
            raise ValueError('Office must be a JSON object.')
        code = _required(office.get('code'), 'Office code', 8)
        if not re.fullmatch(r'[A-Z0-9]+', code):
            raise ValueError('Office code must use uppercase letters and digits.')
        _required(office.get('name'), 'Office name')
        _required(office.get('address'), 'Office address')
        _required(office.get('tin'), 'Office TIN')
        authority = _required(payload.get('authority_reference'), 'Allocation / rule authority reference', 180)
        rules = payload.get('rules', {})
        if not isinstance(rules, dict):
            raise ValueError('Rules must be a JSON object.')
        _required(rules.get('version'), 'Rule version')
        first = _date(rules.get('effective_from'), 'Rules effective from')
        last = _date(rules['effective_until'], 'Rules effective until') if rules.get('effective_until') else None
        if last and last < first:
            raise ValueError('Rules effective-until date is before effective-from.')
        if rules.get('validity_mode') not in ('confirmed_dates', 'plate_schedule'):
            raise ValueError('Rules validity_mode must be confirmed_dates or plate_schedule.')
        if type(rules.get('initial_years')) is not int or not 1 <= rules['initial_years'] <= 10:
            raise ValueError('Configure initial_years between 1 and 10.')
        if type(rules.get('renewal_early_days', 0)) is not int or not 0 <= rules.get('renewal_early_days', 0) <= 365:
            raise ValueError('renewal_early_days must be an approved integer between 0 and 365.')
        fees = rules.get('fees', {})
        if not isinstance(fees, dict) or set(fees) - {'initial', 'renewal', 'transfer'}:
            raise ValueError('Fees must map initial, renewal, and/or transfer to fee line lists.')
        for task, lines in fees.items():
            if not isinstance(lines, list) or not 1 <= len(lines) <= 8:
                raise ValueError(f'Configure 1 to 8 fee lines for {task}, or omit that transaction type.')
            for line in lines:
                if not isinstance(line, dict):
                    raise ValueError('Each fee line must be a JSON object.')
                _required(line.get('description'), 'Fee description', 60)
                _cents(str(line.get('amount', '')))
                if line.get('basis') not in ('fixed', 'per_validity_year'):
                    raise ValueError('Fee basis must be fixed or per_validity_year.')
        allocations = payload.get('series', [])
        allowed_kinds = ('transaction','receipt','mv_file','client','plate') if payload.get('profile_type') == 'local_starter' else ('transaction','receipt','mv_file','client')
        if (not isinstance(allocations, list) or any(not isinstance(x, dict) or x.get('kind') not in allowed_kinds for x in allocations)
                or len({x.get('kind') for x in allocations}) != len(allocations)):
            raise ValueError('Configure no more than one series per identifier kind.')
        for item in allocations:
            if item.get('kind') not in allowed_kinds:
                raise ValueError('Series kind must be transaction, receipt, mv_file, or client.')
            prefix = item.get('prefix', '')
            if not isinstance(prefix, str) or not prefix.isascii() or (prefix and not prefix.isprintable()) or len(prefix) > 40:
                raise ValueError('Series prefix must be printable ASCII, up to 40 characters.')
            try:
                tokens = list(string.Formatter().parse(prefix))
            except ValueError as error:
                raise ValueError('Invalid series prefix placeholders.') from error
            if any(token is not None and (token not in ('office', 'date', 'type') or spec or conversion)
                   for _, token, spec, conversion in tokens):
                raise ValueError('Series prefixes support only {office}, {date}, and {type}.')
            if any(type(item.get(key)) is not int for key in ('width', 'first', 'last')):
                raise ValueError('Series width, first, and last must be integers.')
            if not 1 <= item['width'] <= 15 or not 0 <= item['first'] <= item['last'] < 10 ** item['width']:
                raise ValueError('Invalid series width or assigned numeric range.')
            _identifier(item['kind'], prefix.format(office=code, date='20000101', type='TRANSFER') + str(item['last']).zfill(item['width']))
            if item['kind'] == 'plate' and not prefix.startswith('LOCAL'):
                raise ValueError('Automatic starter plates use a LOCAL prefix. Assigned plates use the stock list in Advanced tools.')
        digest = _digest(payload)
        with self._write() as db:
            self._allow(db, 'admin')
            prior = db.execute('SELECT id,active FROM office_configs WHERE digest=?', (digest,)).fetchone()
            if prior and prior['active']:
                return prior['id']
            if prior:
                raise ValueError('This is an inactive historical configuration. Submit a new rule version instead.')
            for item in allocations:
                same = db.execute('SELECT * FROM series WHERE office_code=? AND kind=? AND prefix=? AND width=? AND first_no=? AND last_no=?',
                                  (code, item['kind'], item.get('prefix', ''), item['width'], item['first'], item['last'])).fetchone()
                if same:
                    if not same['active']:
                        raise ValueError('An old identifier range cannot be reactivated.')
                    continue
                overlap = db.execute('SELECT 1 FROM series WHERE kind=? AND office_code=? AND prefix=? AND width=? AND first_no<=? AND last_no>=?',
                                     (item['kind'], code, item.get('prefix', ''), item['width'], item['last'], item['first'])).fetchone()
                if overlap:
                    raise ValueError(f'Overlapping {item["kind"]} range. Existing counters cannot be reset.')
                db.execute('UPDATE series SET active=0 WHERE office_code=? AND kind=?', (code, item['kind']))
                db.execute('INSERT INTO series VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (str(uuid4()), code, item['kind'], item.get('prefix', ''), item['width'], item['first'], item['last'], item['first'], 1, authority))
            db.execute('UPDATE office_configs SET active=0 WHERE code=?', (code,))
            record = str(uuid4())
            db.execute('INSERT INTO office_configs VALUES(?,?,?,?,1,?)', (record, code, _json(payload), digest, _now()))
            self._audit(db, 'configure_office', record, {'code': code, 'rule_version': rules['version'], 'authority': authority, 'digest': digest})
            return record

    def ensure_starter_defaults(self) -> None:
        """Make a fresh workspace usable without replacing any existing configuration."""
        state = self.summary()
        if state['offices'] or state['role'] != 'admin':
            return
        self.configure(starter_configuration())

    def save_editable_defaults(self, values: dict) -> str:
        office = values.get('office', {})
        prior = self._read('SELECT payload FROM office_configs WHERE id=?', (values.get('config_id'),))
        payload = json.loads(prior[0]['payload']) if prior else starter_configuration()
        payload['office'] = office
        payload['authority_reference'] = values.get('authority_reference') or payload['authority_reference']
        payload['rules']['initial_years'] = values['initial_years']
        payload['rules']['fees'] = values['fees']
        payload['series'] = values['series']
        if not prior or payload != json.loads(prior[0]['payload']):
            payload['rules']['version'] = 'editable-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:6]
        return self.configure(payload)

    def set_operator(self, username: str, role: str, reason: str) -> None:
        username = _required(username, 'Windows username')
        reason = _required(reason, 'Role-change reason', 180)
        if role not in ('admin', 'operator', 'cashier', 'viewer'):
            raise ValueError('Unknown operator role.')
        with self._write() as db:
            self._allow(db, 'admin')
            old = db.execute('SELECT role FROM operators WHERE username=?', (username,)).fetchone()
            if old and old['role'] == 'admin' and role != 'admin' and db.execute("SELECT COUNT(*) FROM operators WHERE role='admin'").fetchone()[0] <= 1:
                raise ValueError('At least one administrator must remain assigned.')
            db.execute('INSERT INTO operators VALUES(?,?) ON CONFLICT(username) DO UPDATE SET role=excluded.role', (username, role))
            self._audit(db, 'set_operator_role', username, {'previous': old['role'] if old else None, 'role': role, 'reason': reason})

    def create_owner(self, values: dict) -> str:
        with self._write() as db:
            self._allow(db, 'admin', 'operator')
            return self._owner(db, values)

    def _owner(self, db: sqlite3.Connection, values: dict) -> str:
        name = _required(values.get('name'), 'Owner name')
        address = _required(values.get('address'), 'Owner address', 180)
        client = _optional(values.get('client_id'), 'Client ID') or None
        tin = _optional(values.get('tin'), 'Owner TIN')
        if len(tin) > 100:
            raise ValueError('Owner TIN is too long.')
        record = str(uuid4())
        if client:
            client = self._reserve(db, 'client', client, record, 'entered')
        db.execute('INSERT INTO owners VALUES(?,?,?,?,?,?,?)', (record, name, address, tin, client, values.get('legacy_id') or None, _now()))
        self._audit(db, 'create_owner', record, {'legacy_id': values.get('legacy_id')})
        return record

    def create_vehicle(self, owner_id: str, values: dict) -> str:
        with self._write() as db:
            self._allow(db, 'admin', 'operator')
            return self._vehicle(db, owner_id, values)

    def correct_record(self, kind: str, record_id: str, values: dict, reason: str) -> None:
        """Reasoned contact/specification corrections; assigned identifiers stay immutable."""
        reason = _required(reason, 'Correction reason', 180)
        if kind not in ('owner', 'vehicle'):
            raise ValueError('Unknown record type.')
        with self._write() as db:
            self._allow(db, 'admin', 'operator')
            table = 'owners' if kind == 'owner' else 'vehicles'
            old = db.execute(f'SELECT * FROM {table} WHERE id=?', (record_id,)).fetchone()
            if not old:
                raise ValueError('Select a saved record.')
            column = 'payer_id' if kind == 'owner' else 'vehicle_id'
            if db.execute(f"SELECT 1 FROM transactions WHERE {column}=? AND state IN ('Draft','Assessed','Payment Pending','Payment Confirmed')", (record_id,)).fetchone():
                raise ValueError('This record is used by an open transaction. Complete or void it before correcting the record.')
            if kind == 'owner':
                for key in ('client_id', 'legacy_id'):
                    if (values.get(key) or '') != (old[key] or ''):
                        raise ValueError('Assigned and legacy identifiers cannot be changed by a contact correction.')
                name = _required(values.get('name'), 'Owner name')
                address = _required(values.get('address'), 'Owner address', 180)
                tin = str(values.get('tin') or '').strip()
                if len(tin) > 100:
                    raise ValueError('Owner TIN is too long.')
                after = {'name': name, 'address': address, 'tin': tin}
                db.execute('UPDATE owners SET name=?,address=?,tin=? WHERE id=?', (name, address, tin, record_id))
                before = {key: old[key] for key in after}
            else:
                for key in ('chassis', 'engine_no', 'plate', 'mv_file', 'expiry', 'legacy_id'):
                    if (values.get(key) or '') != (old[key] or ''):
                        raise ValueError('Physical identifiers, registration expiry, and legacy IDs require a registration/handover process, not a specification correction.')
                before = json.loads(old['specs'])
                after = {key: _required(str(values.get(key) or ''), key.replace('_', ' ')) for key in before}
                if not after['engine_cc'].isdigit() or not 1 <= int(after['engine_cc']) <= 3000 or not re.fullmatch(r'[0-9]{4}', after['year_model']):
                    raise ValueError('Check the engine size (1–3000 cc) and four-digit year model.')
                db.execute('UPDATE vehicles SET specs=? WHERE id=?', (_json(after), record_id))
            self._audit(db, 'correct_' + kind, record_id, {'before': before, 'after': after, 'reason': reason})

    def _vehicle(self, db: sqlite3.Connection, owner_id: str, values: dict) -> str:
        if not db.execute('SELECT 1 FROM owners WHERE id=?', (owner_id,)).fetchone():
            raise ValueError('Select a saved owner first.')
        specs = {key: str(values.get(key) or '').strip() for key in ('classification', 'vehicle_type', 'fuel_type', 'aircon_type', 'color', 'year_model', 'engine_cc')}
        for key, value in specs.items():
            _required(value, key.replace('_', ' ').title())
        if not specs['engine_cc'].isdigit() or not 1 <= int(specs['engine_cc']) <= 3000:
            raise ValueError('Engine displacement must be between 1 and 3000 cc.')
        if not re.fullmatch(r'[0-9]{4}', specs['year_model']):
            raise ValueError('Year model must contain four digits.')
        chassis = _required(values.get('chassis'), 'Chassis number').upper()
        engine = _required(values.get('engine_no'), 'Engine number')
        expiry = _optional(values.get('expiry'), 'Existing expiry') or None
        if expiry:
            _date(expiry, 'Existing expiry')
        record = str(uuid4())
        plate = self._reserve(db, 'plate', values['plate'], record, 'entered') if values.get('plate') else None
        mv_file = self._reserve(db, 'mv_file', values['mv_file'], record, 'entered') if values.get('mv_file') else None
        db.execute('INSERT INTO vehicles VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (record, owner_id, plate, mv_file, chassis, engine, _json(specs), expiry,
                    'registered' if expiry else 'new', values.get('legacy_id') or None, _now()))
        if plate:
            stock = db.execute('SELECT state FROM plate_stock WHERE plate=?', (plate,)).fetchone()
            if stock:
                if stock['state'] != 'available':
                    raise ValueError('Plate is already reserved in stock.')
                db.execute("UPDATE plate_stock SET state='issued',vehicle_id=? WHERE plate=?", (record, plate))
        self._audit(db, 'create_vehicle', record, {'owner_id': owner_id, 'legacy_id': values.get('legacy_id')})
        return record

    def owners(self, search: str = '') -> list[dict]:
        return self._read('SELECT * FROM owners WHERE name LIKE ? OR COALESCE(client_id,\'\') LIKE ? ORDER BY name',
                          ('%' + search + '%', '%' + search + '%'))

    def vehicles(self, search: str = '') -> list[dict]:
        term = '%' + search + '%'
        return self._read('SELECT v.*,o.name AS owner_name FROM vehicles v JOIN owners o ON o.id=v.owner_id '
                          'WHERE o.name LIKE ? OR COALESCE(plate,\'\') LIKE ? OR COALESCE(mv_file,\'\') LIKE ? OR chassis LIKE ? ORDER BY v.created_at DESC',
                          (term, term, term, term))

    def add_plate_stock(self, office_code: str, plates: list[str], authority: str) -> int:
        authority = _required(authority, 'Plate stock authority reference', 180)
        if not plates:
            raise ValueError('Enter at least one assigned plate from inventory.')
        with self._write() as db:
            self._allow(db, 'admin')
            if not db.execute('SELECT 1 FROM office_configs WHERE code=? AND active=1', (office_code,)).fetchone():
                raise ValueError('Select a configured office.')
            count = 0
            for plate in plates:
                value = _identifier('plate', plate)
                existing = db.execute('SELECT office_code FROM plate_stock WHERE plate=?', (value,)).fetchone()
                if existing:
                    if existing['office_code'] != office_code:
                        raise ValueError(f'Plate {value} belongs to another office stock list.')
                    continue
                if db.execute("SELECT 1 FROM identifiers WHERE kind='plate' AND value=?", (value,)).fetchone():
                    raise ValueError(f'Plate {value} is already assigned or retained in history.')
                db.execute('INSERT INTO plate_stock(plate,office_code,authority) VALUES(?,?,?)', (value, office_code, authority))
                count += 1
            self._audit(db, 'import_plate_stock', office_code, {'count': count, 'authority': authority})
            return count

    def create_transaction(self, values: dict, request_key: str) -> str:
        request_key = _required(request_key, 'Request key')
        fingerprint = _digest(values)
        task = values.get('kind')
        if task not in ('initial', 'renewal', 'transfer'):
            raise ValueError('Select initial, renewal, or transfer.')
        day = _date(values.get('date'), 'Transaction date')
        if day > date.today():
            raise ValueError('The registration / transaction date cannot be in the future.')
        with self._write() as db:
            self._allow(db, 'admin', 'operator')
            retry = db.execute('SELECT id,request_digest FROM transactions WHERE request_key=?', (request_key,)).fetchone()
            if retry:
                if retry['request_digest'] != fingerprint:
                    raise ValueError('This request key was already used with different inputs. Start a new transaction.')
                return retry['id']
            vehicle = db.execute('SELECT * FROM vehicles WHERE id=?', (values.get('vehicle_id'),)).fetchone()
            if vehicle is None:
                raise ValueError('Select a saved motorcycle.')
            if db.execute("SELECT 1 FROM transactions WHERE vehicle_id=? AND state IN ('Draft','Assessed','Payment Pending','Payment Confirmed')", (vehicle['id'],)).fetchone():
                raise ValueError('This motorcycle already has an open transaction. Resume or void it first.')
            config = db.execute('SELECT * FROM office_configs WHERE code=? AND active=1', (values.get('office_code'),)).fetchone()
            if config is None:
                raise ValueError('Import the assigned office configuration before creating transactions.')
            payload = json.loads(config['payload'])
            rules = payload['rules']
            if day < _date(rules['effective_from'], 'Effective from') or (rules.get('effective_until') and day > _date(rules['effective_until'], 'Effective until')):
                raise ValueError('The configured rule version does not cover the transaction date.')
            if task == 'initial' and vehicle['state'] != 'new':
                raise ValueError('This motorcycle already has registration history. Choose renewal or transfer.')
            if task != 'initial' and not vehicle['expiry']:
                raise ValueError('The existing official expiry is required for renewal or transfer. Import the registration record first.')
            payer_id = values.get('new_owner_id') if task == 'transfer' else vehicle['owner_id']
            payer = db.execute('SELECT * FROM owners WHERE id=?', (payer_id,)).fetchone()
            if payer is None or (task == 'transfer' and payer_id == vehicle['owner_id']):
                raise ValueError('Choose a different saved owner as the transfer recipient.')
            record = str(uuid4())
            number = self._allocate(db, 'transaction', config['code'], record, day, task)
            if task == 'initial':
                mv_file = vehicle['mv_file'] or self._allocate(db, 'mv_file', config['code'], vehicle['id'], day, task)
                plate = vehicle['plate']
                if not plate:
                    stock = db.execute("SELECT plate FROM plate_stock WHERE office_code=? AND state='available' ORDER BY plate LIMIT 1", (config['code'],)).fetchone()
                    if stock is None:
                        if payload.get('profile_type') != 'local_starter':
                            raise ValueError('No unassigned plates in this office inventory. Add your assigned plates in Advanced tools.')
                        plate = self._allocate(db, 'plate', config['code'], vehicle['id'], day, task)
                        db.execute("INSERT INTO plate_stock VALUES(?,?,?,'reserved',?)", (plate, config['code'], 'Local starter numbering', vehicle['id']))
                    else:
                        plate = self._reserve(db, 'plate', stock['plate'], vehicle['id'], 'stock_reservation')
                    db.execute("UPDATE plate_stock SET state='reserved',vehicle_id=? WHERE plate=?", (vehicle['id'], plate))
                db.execute("UPDATE vehicles SET plate=?,mv_file=?,state='pending' WHERE id=?", (plate, mv_file, vehicle['id']))
                if not payer['client_id'] and db.execute("SELECT 1 FROM series WHERE office_code=? AND kind='client' AND active=1", (config['code'],)).fetchone():
                    client = self._allocate(db, 'client', config['code'], payer_id, day, task)
                    db.execute('UPDATE owners SET client_id=? WHERE id=?', (client, payer_id))
            db.execute('INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (record, request_key, fingerprint, number, vehicle['id'], payer_id, config['id'], task, 'Draft', _json(values), None, _now()))
            # Validate schedule inputs before any reservation is committed, so a
            # missing OR/CR date can be corrected without consuming identifiers.
            saved_tx = db.execute('SELECT * FROM transactions WHERE id=?', (record,)).fetchone()
            saved_vehicle = db.execute('SELECT * FROM vehicles WHERE id=?', (vehicle['id'],)).fetchone()
            self._dates(saved_tx, saved_vehicle, rules)
            self._audit(db, 'create_transaction', record, {'number': number, 'kind': task, 'vehicle_id': vehicle['id'], 'config_id': config['id']})
            return record

    def _dates(self, transaction: sqlite3.Row, vehicle: sqlite3.Row, rules: dict) -> tuple[str, str, str, str]:
        inputs = json.loads(transaction['inputs'])
        supplied = [_optional(inputs.get(key), 'Confirmed date') for key in ('expiry', 'renewal_start', 'renewal_end')]
        if any(supplied):
            if not all(supplied):
                raise ValueError('Provide all three confirmed dates: validity expiry, renewal start, and renewal end.')
            _required(inputs.get('date_reason'), 'Confirmed-date source / reason', 180)
            expiry, start, end = [_date(item, 'Confirmed date') for item in supplied]
            if start > end or (end - start).days > 366 or expiry > end:
                raise ValueError('The confirmed dates are inconsistent. Check validity and the renewal window.')
        elif rules['validity_mode'] == 'confirmed_dates':
            raise ValueError('This office requires confirmed OR/CR dates. Provide validity expiry and the next renewal window when creating the draft.')
        else:
            task = transaction['kind']
            if task == 'initial':
                day = _date(inputs['date'], 'Registration date')
                year = day.year + rules['initial_years']
            elif task == 'renewal':
                prior = _date(vehicle['expiry'], 'Previous expiry')
                day = _date(inputs['date'], 'Transaction date')
                if day < prior - timedelta(days=rules.get('renewal_early_days', 0)):
                    raise ValueError('This renewal is earlier than the configured office renewal window. Confirm the allowed early-renewal period.')
                try:
                    anniversary = prior.replace(year=prior.year + 1)
                except ValueError:
                    anniversary = prior.replace(year=prior.year + 1, day=28)
                if day >= anniversary:
                    raise ValueError('Multi-year arrears need confirmed assessed dates; void this draft and enter the assessed dates and reason.')
                year = prior.year + 1
            else:
                year = _date(vehicle['expiry'], 'Existing expiry').year
            if not vehicle['plate']:
                raise ValueError('No plate schedule is available. Provide confirmed OR/CR dates.')
            start, end = renewal_window(vehicle['plate'], year)
            expiry = _date(vehicle['expiry'], 'Existing expiry') if task == 'transfer' else end
        return validity_notice(expiry, start, end), expiry.isoformat(), start.isoformat(), end.isoformat()

    def assess(self, transaction_id: str, manual_lines: list[tuple[str, str]] | None = None, reason: str = '') -> str:
        with self._write() as db:
            self._allow(db, 'admin', 'operator')
            tx = db.execute('SELECT * FROM transactions WHERE id=?', (transaction_id,)).fetchone()
            if tx is None or tx['state'] not in ('Draft', 'Assessed'):
                raise ValueError('Only draft/assessed transactions without a pending payment can be assessed.')
            if tx['assessment_id'] and manual_lines is None:
                return tx['assessment_id']
            vehicle = db.execute('SELECT * FROM vehicles WHERE id=?', (tx['vehicle_id'],)).fetchone()
            config = json.loads(db.execute('SELECT payload FROM office_configs WHERE id=?', (tx['config_id'],)).fetchone()[0])
            rules = config['rules']
            if manual_lines is not None:
                reason = _required(reason, 'Manual assessment reason', 180)
                lines = [{'description': _required(label, 'Fee description', 60), 'amount': f'{parse_amount(amount):.2f}'} for label, amount in manual_lines]
            else:
                if config.get('profile_type') != 'local_starter' and tx['kind'] == 'renewal' and _date(json.loads(tx['inputs'])['date'], 'Transaction date') > _date(vehicle['expiry'], 'Previous expiry'):
                    raise ValueError('Late renewal needs a reasoned manual assessment of penalties or a confirmed exemption. Use Manual assessment.')
                configured = rules['fees'].get(tx['kind'])
                if not configured:
                    raise ValueError('No fee schedule is configured for this transaction type. Configure a new rule version or enter a reasoned manual assessment.')
                years = rules['initial_years'] if tx['kind'] == 'initial' else 1
                lines = [{'description': line['description'], 'amount': f"{parse_amount(str(line['amount'])) * (years if line['basis']=='per_validity_year' else 1):.2f}"} for line in configured]
            if not 1 <= len(lines) <= 8:
                raise ValueError('An assessment must have 1 to 8 payment items.')
            total = sum(_cents(item['amount']) for item in lines)
            if total > 99999999999:
                raise ValueError('Assessment exceeds the supported receipt amount.')
            validity, expiry, start, end = self._dates(tx, vehicle, rules)
            record = str(uuid4())
            db.execute('INSERT INTO assessments VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (record, transaction_id, _json(lines), total, validity, expiry, start, end, rules['version'], reason, _now()))
            db.execute("UPDATE transactions SET state='Assessed',assessment_id=? WHERE id=?", (record, transaction_id))
            self._audit(db, 'assess_transaction', transaction_id, {'assessment_id': record, 'total_cents': total, 'rule_version': rules['version'], 'reason': reason})
            return record

    def record_payment(self, transaction_id: str, method: str, reference: str, amount: str) -> str:
        method = _required(method, 'Payment method', 60)
        method = {'cash':'Cash','gcash':'GCash','maya':'Maya','bank transfer':'Bank transfer','card':'Card'}.get(method.casefold(), method)
        reference = _required(reference, 'Payment / cashier reference', 100)
        amount_cents = _cents(amount)
        with self._write() as db:
            self._allow(db, 'admin', 'cashier')
            retry = db.execute('SELECT * FROM payments WHERE method=? AND reference=?', (method, reference)).fetchone()
            if retry:
                if retry['transaction_id'] == transaction_id and retry['amount_cents'] == amount_cents:
                    return retry['id']
                raise ValueError('This payment reference is already linked to a different transaction or amount.')
            tx = db.execute('SELECT * FROM transactions WHERE id=?', (transaction_id,)).fetchone()
            if tx is None or tx['state'] != 'Assessed':
                raise ValueError('Create an assessment before recording a payment.')
            assessment = db.execute('SELECT * FROM assessments WHERE id=?', (tx['assessment_id'],)).fetchone()
            if amount_cents != assessment['total_cents']:
                raise ValueError('Payment amount must equal the current assessed amount. Partial payments are not supported.')
            config = json.loads(db.execute('SELECT payload FROM office_configs WHERE id=?', (tx['config_id'],)).fetchone()[0])
            _, candidate = self._next_identifier(db, 'receipt', config['office']['code'], date.today(), tx['kind'])
            if db.execute("SELECT 1 FROM identifiers WHERE kind='receipt' AND value=?", (candidate,)).fetchone():
                raise ValueError('The next receipt number is already retained in history. Configure an unused assigned range before recording payment.')
            # Preflight the exact layout without issuing or storing a receipt number.
            self._render_receipt(db, tx, assessment, {'method':method, 'confirmed_by':self.actor, 'created_at':_now()}, candidate)
            record = str(uuid4())
            db.execute('INSERT INTO payments VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (record, transaction_id, assessment['id'], method, reference, amount_cents, 'Pending', '', self.actor, None, _now()))
            db.execute("UPDATE transactions SET state='Payment Pending' WHERE id=?", (transaction_id,))
            self._audit(db, 'record_pending_payment', transaction_id, {'payment_id': record, 'reference': reference, 'amount_cents': amount_cents})
            return record

    def confirm_payment(self, payment_id: str, evidence: str) -> None:
        evidence = _required(evidence, 'Confirmation evidence / reconciliation reference', 180)
        with self._write() as db:
            self._allow(db, 'admin', 'cashier')
            payment = db.execute('SELECT * FROM payments WHERE id=?', (payment_id,)).fetchone()
            if payment is None:
                raise ValueError('Select a pending payment.')
            if payment['status'] == 'Confirmed':
                return
            if payment['status'] != 'Pending':
                raise ValueError('Only pending payments can be confirmed.')
            db.execute("UPDATE payments SET status='Confirmed',evidence=?,confirmed_by=? WHERE id=?", (evidence, self.actor, payment_id))
            db.execute("UPDATE transactions SET state='Payment Confirmed' WHERE id=?", (payment['transaction_id'],))
            self._audit(db, 'confirm_payment', payment['transaction_id'], {'payment_id': payment_id, 'evidence': evidence})

    def fail_payment(self, payment_id: str, reason: str) -> None:
        reason = _required(reason, 'Failure reason', 180)
        with self._write() as db:
            self._allow(db, 'admin', 'cashier')
            payment = db.execute("SELECT * FROM payments WHERE id=? AND status='Pending'", (payment_id,)).fetchone()
            if not payment:
                raise ValueError('Only pending payments can be marked failed.')
            db.execute("UPDATE payments SET status='Failed',evidence=? WHERE id=?", (reason, payment_id))
            db.execute("UPDATE transactions SET state='Assessed' WHERE id=?", (payment['transaction_id'],))
            self._audit(db, 'fail_payment', payment['transaction_id'], {'payment_id': payment_id, 'reason': reason})

    def _render_receipt(self, db: sqlite3.Connection, tx: sqlite3.Row, assessment: sqlite3.Row,
                        payment: dict | sqlite3.Row, number: str) -> tuple[dict, bytes]:
        owner = db.execute('SELECT * FROM owners WHERE id=?', (tx['payer_id'],)).fetchone()
        vehicle = db.execute('SELECT * FROM vehicles WHERE id=?', (tx['vehicle_id'],)).fetchone()
        config = json.loads(db.execute('SELECT payload FROM office_configs WHERE id=?', (tx['config_id'],)).fetchone()[0])
        office = config['office']
        fields = {**json.loads(vehicle['specs']), 'receipt_no': number, 'transaction_no': tx['number'],
                  'payer': owner['name'], 'address': owner['address'], 'payer_tin': owner['tin'],
                  'client_id': owner['client_id'] or '', 'plate_no': vehicle['plate'] or '', 'file_no': vehicle['mv_file'] or '',
                  'office': office['name'], 'office_code': office['code'], 'office_address': office['address'],
                  'office_tin': office['tin'], 'date': datetime.fromisoformat(payment['created_at']).astimezone().strftime('%m/%d/%Y %I:%M %p'), 'validity': assessment['validity'],
                  'payment_mode': payment['method'], 'payment_channel': 'cash' if payment['method']=='Cash' else 'online',
                  'location': office['name'] if payment['method']=='Cash' else '-',
                  'cashier': payment['confirmed_by'] or '', 'pos_machine': office.get('pos_machine') or '',
                  'qr_mode': 'reference', 'qr_level': 'M', 'qr_version': '8'}
        fields.pop('engine_cc', None)
        if config.get('profile_type') == 'local_starter':
            fields['document_label'] = 'LOCAL STARTER PROFILE'
        lines = json.loads(assessment['lines'])
        content = generate_receipt(ReceiptData(fields, [Charge(item['description'], Decimal(item['amount'])) for item in lines]))
        snapshot = {'fields': fields, 'charges': lines, 'assessment_id': assessment['id'],
                    'config_id': tx['config_id'], 'rule_version': assessment['rule_version']}
        return snapshot, content

    def issue(self, transaction_id: str) -> str:
        with self._write() as db:
            self._allow(db, 'admin', 'cashier')
            tx = db.execute('SELECT * FROM transactions WHERE id=?', (transaction_id,)).fetchone()
            if tx is None or tx['state'] not in ('Payment Confirmed', 'Issued'):
                raise ValueError('A confirmed payment is required before receipt issuance.')
            prior = db.execute('SELECT number FROM receipts WHERE transaction_id=?', (transaction_id,)).fetchone()
            if prior:
                return prior['number']
            payment = db.execute("SELECT * FROM payments WHERE transaction_id=? AND status='Confirmed'", (transaction_id,)).fetchone()
            assessment = db.execute('SELECT * FROM assessments WHERE id=?', (tx['assessment_id'],)).fetchone()
            if not payment or payment['assessment_id'] != assessment['id'] or payment['amount_cents'] != assessment['total_cents']:
                raise ValueError('Payment and assessment do not reconcile.')
            vehicle = db.execute('SELECT * FROM vehicles WHERE id=?', (tx['vehicle_id'],)).fetchone()
            config = json.loads(db.execute('SELECT payload FROM office_configs WHERE id=?', (tx['config_id'],)).fetchone()[0])
            office = config['office']
            record = str(uuid4())
            number = self._allocate(db, 'receipt', office['code'], record, date.today(), tx['kind'])
            snapshot, content = self._render_receipt(db, tx, assessment, payment, number)
            snapshot['payment_id'] = payment['id']
            db.execute('INSERT INTO receipts VALUES(?,?,?,?,?,?,?,?)',
                       (record, transaction_id, number, payment['id'], _json(snapshot), content, hashlib.sha256(content).hexdigest(), _now()))
            db.execute("UPDATE transactions SET state='Issued' WHERE id=?", (transaction_id,))
            db.execute("UPDATE vehicles SET owner_id=?,expiry=?,state='registered' WHERE id=?", (tx['payer_id'], assessment['expiry'], vehicle['id']))
            db.execute("UPDATE plate_stock SET state='issued' WHERE vehicle_id=?", (vehicle['id'],))
            self._audit(db, 'issue_receipt', transaction_id, {'receipt_id': record, 'number': number, 'sha256': hashlib.sha256(content).hexdigest()})
            return number

    def void(self, transaction_id: str, reason: str) -> None:
        reason = _required(reason, 'Void reason', 180)
        with self._write() as db:
            self._allow(db, 'admin')
            tx = db.execute('SELECT * FROM transactions WHERE id=?', (transaction_id,)).fetchone()
            if not tx:
                raise ValueError('Select a transaction.')
            if tx['state'] == 'Voided':
                return
            if tx['state'] == 'Issued':
                raise ValueError('Issued registrations require an approved reversal process. This version supports voiding before issuance only.')
            if tx['state'] == 'Payment Confirmed':
                raise ValueError('Confirmed payments require an approved reversal/refund process; settled funds cannot be voided by this workflow.')
            db.execute("UPDATE transactions SET state='Voided' WHERE id=?", (transaction_id,))
            db.execute("UPDATE payments SET status='Voided' WHERE transaction_id=? AND status IN ('Pending','Confirmed')", (transaction_id,))
            if tx['kind'] == 'initial':
                db.execute("UPDATE vehicles SET state='new' WHERE id=?", (tx['vehicle_id'],))
            self._audit(db, 'void_transaction', transaction_id, {'reason': reason, 'retained_identifiers': True})

    def transactions(self, search: str = '') -> list[dict]:
        term = '%' + search + '%'
        return self._read('SELECT t.id,t.number,t.kind,t.state,t.created_at,o.name,v.plate,v.mv_file,r.number AS receipt_no '
                          'FROM transactions t JOIN owners o ON o.id=t.payer_id JOIN vehicles v ON v.id=t.vehicle_id '
                          'LEFT JOIN receipts r ON r.transaction_id=t.id WHERE t.number LIKE ? OR o.name LIKE ? '
                          'OR COALESCE(v.plate,\'\') LIKE ? OR COALESCE(r.number,\'\') LIKE ? ORDER BY t.created_at DESC', (term, term, term, term))

    def detail(self, transaction_id: str) -> dict:
        rows = self._read('SELECT * FROM transactions WHERE id=?', (transaction_id,))
        if not rows:
            raise ValueError('Transaction not found.')
        result = rows[0]
        result['assessment'] = self._read('SELECT * FROM assessments WHERE id=?', (result['assessment_id'],))
        result['payments'] = self._read('SELECT * FROM payments WHERE transaction_id=? ORDER BY created_at,id', (transaction_id,))
        result['receipt'] = self._read('SELECT id,number,snapshot,sha256,created_at FROM receipts WHERE transaction_id=?', (transaction_id,))
        result['audit'] = self._read('SELECT * FROM audit WHERE record_id=? ORDER BY id', (transaction_id,))
        return result

    def receipt_pdf(self, transaction_id: str) -> tuple[str, bytes]:
        rows = self._read("SELECT r.number,r.pdf,r.sha256 FROM receipts r JOIN transactions t ON t.id=r.transaction_id WHERE t.id=? AND t.state='Issued'", (transaction_id,))
        if not rows:
            raise ValueError('There is no issued receipt for this transaction.')
        row = rows[0]
        content = bytes(row['pdf'])
        if hashlib.sha256(content).hexdigest() != row['sha256']:
            raise ValueError('Receipt integrity check failed. Restore from a verified backup.')
        return row['number'], content

    def export_receipt(self, transaction_id: str, path: str) -> None:
        _, content = self.receipt_pdf(transaction_id)
        save_receipt(path, content)
        with self._write() as db:
            self._audit(db, 'export_receipt', transaction_id, {'sha256': hashlib.sha256(content).hexdigest()})

    def backup(self, destination: Path) -> None:
        if destination.resolve() == self.path.resolve():
            raise ValueError('Choose a different path for the registry backup.')
        db = self._connect()
        temporary: str | None = None
        try:
            self._allow(db, 'admin')
            with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.db', delete=False) as stream:
                temporary = stream.name
            with closing(sqlite3.connect(temporary)) as target:
                db.backup(target)
                target.commit()
            os.replace(temporary, destination)
        finally:
            db.close()
            if temporary and Path(temporary).exists():
                Path(temporary).unlink()
        with self._write() as db:
            self._audit(db, 'backup_registry', '', {'completed': True})

    def audit(self) -> list[dict]:
        return self._read('SELECT * FROM audit ORDER BY id DESC LIMIT 1000')

    def history(self) -> list[dict]:
        return self._read('SELECT h.*,v.plate,v.mv_file FROM legacy_history h JOIN vehicles v ON v.id=h.vehicle_id ORDER BY h.created_at DESC')

    def migrate(self, payload: dict, expected_digest: str | None = None) -> dict:
        """Preview by rolling back a full validation run; apply the identical reviewed payload atomically."""
        if not isinstance(payload, dict):
            raise ValueError('Migration bundle must be a JSON object.')
        digest = _digest(payload)
        if expected_digest is not None and expected_digest != digest:
            raise ValueError('Migration inputs changed after preview. Preview the bundle again.')
        for key in ('owners', 'vehicles', 'history', 'issued_identifiers'):
            rows = payload.get(key, [])
            if not isinstance(rows, list) or len(rows) > 5000 or any(not isinstance(row, dict) for row in rows):
                raise ValueError(f'{key} must be a list of up to 5,000 records per bundle.')
        with self._write(dry_run=expected_digest is None) as db:
            self._allow(db, 'admin')
            previous = db.execute('SELECT report FROM migration_batches WHERE digest=?', (digest,)).fetchone()
            if previous:
                return {**json.loads(previous['report']), 'already_imported': True}
            report = {'digest': digest, 'owners_created': 0, 'vehicles_created': 0, 'history_created': 0,
                      'records_unchanged': 0, 'identifiers_retained': 0, 'confirmed_paid_cents': 0}
            owner_map = {row['legacy_id']: row['id'] for row in db.execute('SELECT id,legacy_id FROM owners WHERE legacy_id IS NOT NULL')}
            vehicle_map = {row['legacy_id']: row['id'] for row in db.execute('SELECT id,legacy_id FROM vehicles WHERE legacy_id IS NOT NULL')}
            for values in payload.get('owners', []):
                legacy = _required(values.get('legacy_id'), 'Owner legacy_id')
                if legacy in owner_map:
                    old = db.execute('SELECT * FROM owners WHERE id=?', (owner_map[legacy],)).fetchone()
                    new = (_required(values.get('name'), 'Owner name'), _required(values.get('address'), 'Owner address', 180),
                           _optional(values.get('tin'), 'Owner TIN'), _optional(values.get('client_id'), 'Client ID') or None)
                    if new != (old['name'], old['address'], old['tin'], old['client_id']):
                        raise ValueError(f'Owner migration conflict for legacy ID {legacy}. No changes were applied.')
                    report['records_unchanged'] += 1
                else:
                    owner_map[legacy] = self._owner(db, values)
                    report['owners_created'] += 1
            for values in payload.get('vehicles', []):
                legacy = _required(values.get('legacy_id'), 'Vehicle legacy_id')
                owner_id = owner_map.get(values.get('owner_legacy_id'))
                if not owner_id:
                    raise ValueError(f'Owner legacy ID for vehicle {legacy} was not found.')
                if legacy in vehicle_map:
                    old = db.execute('SELECT * FROM vehicles WHERE id=?', (vehicle_map[legacy],)).fetchone()
                    specs = {key: str(values.get(key, '')).strip() for key in json.loads(old['specs'])}
                    normalized_plate = _identifier('plate', values['plate']) if values.get('plate') else None
                    normalized_mv = _identifier('mv_file', values['mv_file']) if values.get('mv_file') else None
                    if (old['owner_id'], old['plate'], old['mv_file'], old['chassis'], old['engine_no'], old['expiry'], old['specs']) != (
                        owner_id, normalized_plate, normalized_mv, values.get('chassis', '').strip().upper(), values.get('engine_no', '').strip(), values.get('expiry') or None, _json(specs)):
                        raise ValueError(f'Vehicle migration conflict for legacy ID {legacy}.')
                    report['records_unchanged'] += 1
                else:
                    vehicle_map[legacy] = self._vehicle(db, owner_id, values)
                    report['vehicles_created'] += 1
            for values in payload.get('history', []):
                legacy = _required(values.get('legacy_id'), 'History legacy_id')
                vehicle_id = vehicle_map.get(values.get('vehicle_legacy_id'))
                if not vehicle_id:
                    raise ValueError(f'Vehicle legacy ID for history {legacy} was not found.')
                old = db.execute('SELECT * FROM legacy_history WHERE legacy_id=?', (legacy,)).fetchone()
                if old:
                    if old['payload'] != _json(values):
                        raise ValueError(f'History migration conflict for {legacy}.')
                    report['records_unchanged'] += 1
                    continue
                if values.get('status') not in ('Confirmed', 'Voided', 'Pending', 'Failed'):
                    raise ValueError('Historical payment status must be Confirmed, Voided, Pending, or Failed.')
                _date(values.get('registration_date'), 'Historical registration date')
                _date(values.get('expiry'), 'Historical expiry')
                paid = _cents(str(values.get('paid_amount', ''))) if str(values.get('paid_amount', '')) not in ('0', '0.00') else 0
                if values['status'] == 'Confirmed' and paid == 0:
                    raise ValueError('Confirmed historical payments need a positive paid_amount.')
                for kind, key in (('receipt', 'receipt_no'), ('transaction', 'transaction_no')):
                    if values.get(key):
                        self._reserve(db, kind, values[key], 'history:' + legacy, 'migration')
                db.execute('INSERT INTO legacy_history VALUES(?,?,?,?,?)', (legacy, vehicle_id, _json(values), paid, _now()))
                report['history_created'] += 1
                if values['status'] == 'Confirmed':
                    report['confirmed_paid_cents'] += paid
            for values in payload.get('issued_identifiers', []):
                kind = values.get('kind')
                if kind not in ('receipt', 'transaction', 'client', 'mv_file', 'plate'):
                    raise ValueError('Unknown handed-over identifier kind.')
                identifier = _identifier(kind, values.get('value', ''))
                existing = db.execute('SELECT origin FROM identifiers WHERE kind=? AND value=?', (kind, identifier)).fetchone()
                if existing:
                    if existing['origin'] == 'allocated':
                        raise ValueError(f'{identifier} was allocated by this system and conflicts with the handover list.')
                    continue
                if kind == 'plate' and db.execute('SELECT 1 FROM plate_stock WHERE plate=?', (identifier,)).fetchone():
                    raise ValueError(f'Historical plate {identifier} conflicts with unassigned stock. Reconcile stock before importing.')
                self._reserve(db, kind, identifier, 'handover:' + identifier, 'migration')
                report['identifiers_retained'] += 1
            self._audit(db, 'migration_import', digest, report)
            db.execute('INSERT INTO migration_batches VALUES(?,?,?)', (digest, _json(report), _now()))
            return report


def configuration_template() -> dict:
    """The editable local starter profile shown by advanced configuration tools."""
    return starter_configuration()


def starter_configuration() -> dict:
    """Editable values from the provided receipt; number defaults stay explicitly local."""
    fees = [{'description': item.description, 'amount': f'{item.amount:.2f}', 'basis': 'fixed'} for item in DEFAULT_RECEIPT_CHARGES]
    return {
        'profile_type': 'local_starter', 'authority_reference': 'Local starter configuration',
        'office': {'code':'1396', 'name':'VALENZUELA DISTRICT OFFICE',
                   'address':'CRISTOBAL ST. GEN. T. DE LEON VALENZUELA', 'tin':'000865491001',
                   'pos_machine':'VALENZUELA MV - CASHIER'},
        'rules': {'version':'starter-1', 'effective_from':'2020-01-01', 'effective_until':'',
                  'initial_years':3, 'renewal_early_days':60, 'validity_mode':'plate_schedule',
                  'fees':{kind:[dict(line) for line in fees] for kind in ('initial','renewal','transfer')}},
        'series': [{'kind':kind,'prefix':prefix,'width':width,'first':first,'last':last}
                   for kind,prefix,width,first,last in (
                       ('transaction','LOCAL-{office}-{type}-{date}-',6,1,999999),
                       ('receipt','LOCAL-{office}-',6,1,999999),
                       ('mv_file','0000',11,1,99999999999),
                       ('client','LOCAL-CLIENT-',6,1,999999),
                       ('plate','LOCAL',4,1001,9999))],
    }


def read_json_file(path: str) -> dict:
    source = Path(path)
    if source.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('JSON input exceeds 20 MB. Split the handover into smaller bundles.')
    try:
        value = json.loads(source.read_text(encoding='utf-8-sig'))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f'Invalid UTF-8 JSON: {error}') from error
    if not isinstance(value, dict):
        raise ValueError('The JSON file must contain an object.')
    return value
