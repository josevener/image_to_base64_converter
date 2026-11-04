"""Transactional guarantees for the local provider-transition workspace."""

import copy
import json
import sqlite3
import unittest
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services.lto_workflow_service import LtoWorkflowService


def office_fixture() -> dict:
    return {
        'authority_reference': 'TEST FIXTURE ONLY',
        'office': {'code': '9999', 'name': 'TEST OFFICE', 'address': 'Example office address', 'tin': '000000000000', 'pos_machine': 'TEST POS'},
        'rules': {'version': 'TEST-v1', 'effective_from': '2020-01-01', 'effective_until': '2099-12-31',
                  'initial_years': 3, 'validity_mode': 'plate_schedule', 'fees': {
                      'initial': [{'description': 'MVUC', 'amount': '240.00', 'basis': 'per_validity_year'}, {'description': 'Legal Research Fee', 'amount': '10.00', 'basis': 'fixed'}],
                      'renewal': [{'description': 'MVUC', 'amount': '240.00', 'basis': 'fixed'}],
                      'transfer': [{'description': 'Transfer Fee', 'amount': '50.00', 'basis': 'fixed'}]}},
        'series': [{'kind': kind, 'prefix': prefix, 'width': width, 'first': 1, 'last': 99}
                   for kind, prefix, width in (('transaction','TEST-{office}-{type}-{date}-',6),
                                              ('receipt','TEST-OR-',6), ('mv_file','9999',11), ('client','TEST-CLIENT-',6))],
    }


def vehicle_fixture(chassis: str = 'TEST-CHASSIS-1') -> dict:
    return {'chassis': chassis, 'engine_no': 'TEST-ENGINE-' + chassis, 'engine_cc': '125', 'color': 'WHITE',
            'year_model': '2026', 'classification': 'Private - (PVT)', 'vehicle_type': 'Motorcycle Without Sidecar',
            'fuel_type': 'Gas', 'aircon_type': 'N/A', 'plate': '', 'mv_file': '', 'expiry': ''}


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / 'registry.db'
        self.service = LtoWorkflowService(self.path, 'test-admin')
        self.config = office_fixture()
        self.service.configure(self.config)
        self.owner = self.service.create_owner({'name': 'EXAMPLE, TEST', 'address': 'Example Street'})
        self.vehicle = self.service.create_vehicle(self.owner, vehicle_fixture())
        self.service.add_plate_stock('9999', ['TEST12345', 'TEST12346'], 'TEST STOCK ONLY')

    def tearDown(self) -> None:
        self.directory.cleanup()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def draft(self, **changes) -> str:
        values = {'office_code': '9999', 'vehicle_id': self.vehicle, 'kind': 'initial', 'new_owner_id': None,
                  'date': '2026-04-23', 'expiry': '', 'renewal_start': '', 'renewal_end': '', 'date_reason': ''}
        values.update(changes)
        return self.service.create_transaction(values, 'test-request-' + values['vehicle_id'])

    def paid(self) -> str:
        record = self.draft()
        self.service.assess(record)
        payment = self.service.record_payment(record, 'GCash', 'TEST-PAY-1', '730.00')
        self.service.confirm_payment(payment, 'TEST settlement checked')
        return record

    def test_end_to_end_confirmed_payment_and_immutable_reprint(self) -> None:
        record = self.draft()
        self.assertEqual(self.service.detail(record)['state'], 'Draft')
        vehicle = self.service.vehicles()[0]
        self.assertEqual(vehicle['plate'], 'TEST12345')
        self.assertEqual(vehicle['mv_file'], '999900000000001')
        self.service.assess(record)
        self.assertEqual(self.service.detail(record)['assessment'][0]['total_cents'], 73000)
        with self.assertRaisesRegex(ValueError, 'confirmed payment'):
            self.service.issue(record)
        with self.assertRaisesRegex(ValueError, 'equal'):
            self.service.record_payment(record, 'GCash', 'TEST-PAY-1', '1.00')
        payment = self.service.record_payment(record, 'GCash', 'TEST-PAY-1', '730.00')
        with self.assertRaises(ValueError):
            self.service.issue(record)
        self.service.confirm_payment(payment, 'TEST settlement evidence')
        number = self.service.issue(record)
        self.assertEqual(number, 'TEST-OR-000001')
        saved_number, content = self.service.receipt_pdf(record)
        self.assertTrue(content.startswith(b'%PDF'))
        self.assertEqual(saved_number, number)
        with self.connection() as db:
            db.execute("UPDATE owners SET name='CHANGED AFTER ISSUE' WHERE id=?", (self.owner,))
        self.assertEqual(self.service.receipt_pdf(record)[1], content)
        target = Path(self.directory.name) / (number + '.pdf')
        self.service.export_receipt(record, str(target))
        self.assertEqual(target.read_bytes(), content)
        with self.connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE receipts SET number='CHANGED'")

    def test_duplicate_retries_and_concurrent_issuance(self) -> None:
        record = self.paid()
        self.assertEqual(self.draft(), record)
        with ThreadPoolExecutor(max_workers=4) as executor:
            numbers = list(executor.map(lambda _: self.service.issue(record), range(4)))
        self.assertEqual(set(numbers), {'TEST-OR-000001'})
        self.assertEqual(self.service.summary()['counts']['receipts'], 1)
        counters = {row['kind']: row['next_no'] for row in self.service.summary()['series']}
        self.assertEqual(counters['receipt'], 2)
        self.assertEqual(counters['transaction'], 2)

    def test_failure_rolls_back_all_allocations(self) -> None:
        with self.connection() as db:
            db.execute('DELETE FROM plate_stock')
        with self.assertRaisesRegex(ValueError, 'No unassigned plates'):
            self.draft()
        self.assertEqual(self.service.summary()['counts']['transactions'], 0)
        self.assertTrue(all(row['next_no'] == 1 for row in self.service.summary()['series']))
        self.assertIsNone(self.service.vehicles()[0]['mv_file'])

    def test_roles_are_enforced_in_service(self) -> None:
        self.service.set_operator('test-viewer', 'viewer', 'TEST role assignment')
        viewer = LtoWorkflowService(self.path, 'test-viewer')
        self.assertEqual(viewer.summary()['role'], 'viewer')
        with self.assertRaises(ValueError):
            viewer.create_owner({'name': 'X', 'address': 'X'})
        with self.assertRaises(ValueError):
            viewer.configure(self.config)
        with self.assertRaisesRegex(ValueError, 'administrator'):
            self.service.set_operator('test-admin', 'viewer', 'TEST last administrator')

    def test_configuration_does_not_reset_counters_or_reassess_old_drafts(self) -> None:
        record = self.draft()
        self.service.configure(self.config)
        changed = copy.deepcopy(self.config)
        changed['rules']['version'] = 'TEST-v2'
        changed['rules']['fees']['initial'][0]['amount'] = '500.00'
        self.service.configure(changed)
        self.service.assess(record)
        self.assertEqual(self.service.detail(record)['assessment'][0]['total_cents'], 73000)
        self.assertEqual(next(row for row in self.service.summary()['series'] if row['kind']=='transaction')['next_no'], 2)
        overlapping = copy.deepcopy(changed)
        overlapping['rules']['version'] = 'TEST-v3'
        overlapping['series'][0]['first'] = 2
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            self.service.configure(overlapping)

    def test_failed_payment_retry_and_duplicate_reference(self) -> None:
        record = self.draft()
        self.service.assess(record)
        payment = self.service.record_payment(record, 'GCash', 'TEST-FAIL', '730.00')
        self.service.fail_payment(payment, 'TEST failure')
        self.assertEqual(self.service.detail(record)['state'], 'Assessed')
        with self.assertRaises(ValueError):
            self.service.confirm_payment(payment, 'TEST disallowed retry')
        next_payment = self.service.record_payment(record, 'GCash', 'TEST-RETRY', '730.00')
        self.assertNotEqual(next_payment, payment)
        self.service.confirm_payment(next_payment, 'TEST confirmation')
        self.assertEqual(self.service.detail(record)['state'], 'Payment Confirmed')

    def test_migration_preview_apply_idempotency_and_conflicts(self) -> None:
        vehicle = vehicle_fixture('LEGACY-CHASSIS')
        vehicle.update(legacy_id='vehicle-old', owner_legacy_id='owner-old', plate='OLD12345', mv_file='111100000000001', expiry='2027-05-14')
        bundle = {'owners': [{'legacy_id':'owner-old','name':'LEGACY EXAMPLE','address':'Legacy Street','client_id':'LEGACY-CLIENT'}],
                  'vehicles': [vehicle], 'history': [{'legacy_id':'history-old','vehicle_legacy_id':'vehicle-old',
                      'registration_date':'2026-05-14','expiry':'2027-05-14','status':'Confirmed','paid_amount':'240.00',
                      'receipt_no':'LEGACY-OR-1','transaction_no':'LEGACY-TX-1'}]}
        report = self.service.migrate(bundle)
        self.assertEqual(report['confirmed_paid_cents'], 24000)
        self.assertEqual(len(self.service.owners()), 1)
        self.service.migrate(bundle, report['digest'])
        self.assertEqual(len(self.service.owners()), 2)
        self.assertTrue(self.service.migrate(bundle, report['digest'])['already_imported'])
        changed = copy.deepcopy(bundle)
        changed['owners'][0]['name'] = 'CONFLICT'
        with self.assertRaises(ValueError):
            self.service.migrate(changed, report['digest'])
        with self.assertRaisesRegex(ValueError, 'conflict'):
            self.service.migrate(changed)

    def test_void_retains_numbers_and_backup_restores(self) -> None:
        record = self.draft()
        number = self.service.detail(record)['number']
        self.service.void(record, 'TEST cancellation')
        self.assertEqual(self.service.detail(record)['state'], 'Voided')
        self.assertEqual(self.service.vehicles()[0]['plate'], 'TEST12345')
        with self.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM identifiers WHERE value=?", (number,)).fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM audit')
        target = Path(self.directory.name) / 'backup.db'
        self.service.backup(target)
        restored = LtoWorkflowService(target, 'test-admin')
        self.assertEqual(restored.detail(record)['state'], 'Voided')

    def test_receipt_render_failure_does_not_consume_number(self) -> None:
        record = self.paid()
        with patch('services.lto_workflow_service.generate_receipt', side_effect=ValueError('TEST render failure')):
            with self.assertRaisesRegex(ValueError, 'render failure'):
                self.service.issue(record)
        self.assertEqual(self.service.detail(record)['state'], 'Payment Confirmed')
        self.assertEqual(self.service.summary()['counts']['receipts'], 0)
        self.assertEqual(self.service.issue(record), 'TEST-OR-000001')

    def test_transfer_completes_ownership_only_on_issuance(self) -> None:
        initial = self.paid()
        self.service.issue(initial)
        original_pdf = self.service.receipt_pdf(initial)[1]
        recipient = self.service.create_owner({'name':'NEW EXAMPLE OWNER','address':'Another Street'})
        values = {'office_code':'9999','vehicle_id':self.vehicle,'kind':'transfer','new_owner_id':recipient,'date':'2026-04-24'}
        transfer = self.service.create_transaction(values, 'test-transfer-request')
        self.service.assess(transfer)
        self.assertEqual(self.service.vehicles()[0]['owner_id'], self.owner)
        payment = self.service.record_payment(transfer, 'Cash', 'TEST-TRANSFER-PAY', '50.00')
        self.service.confirm_payment(payment, 'TEST cash reconciled')
        self.service.issue(transfer)
        self.assertEqual(self.service.vehicles()[0]['owner_id'], recipient)
        self.assertEqual(self.service.receipt_pdf(initial)[1], original_pdf)

    def test_contact_corrections_are_reasoned_and_lock_open_records(self) -> None:
        owner = self.service.owners()[0]
        values = {key:owner[key] or '' for key in ('name','address','tin','client_id','legacy_id')}
        values['address'] = 'Corrected Street'
        self.service.correct_record('owner', self.owner, values, 'TEST source correction')
        self.assertEqual(self.service.owners()[0]['address'], 'Corrected Street')
        self.draft()
        with self.assertRaisesRegex(ValueError, 'open transaction'):
            self.service.correct_record('owner', self.owner, values, 'TEST blocked edit')

    def test_confirmed_date_requirements_rollback_draft_reservations(self) -> None:
        configured = copy.deepcopy(self.config)
        configured['rules']['version'] = 'TEST-confirmed-dates'
        configured['rules']['validity_mode'] = 'confirmed_dates'
        self.service.configure(configured)
        with self.assertRaisesRegex(ValueError, 'confirmed OR/CR dates'):
            self.draft()
        self.assertEqual(self.service.summary()['counts']['transactions'], 0)
        record = self.draft(expiry='2029-05-14', renewal_start='2029-05-08', renewal_end='2029-05-14', date_reason='TEST OR/CR')
        self.assertEqual(self.service.detail(record)['state'], 'Draft')

    def test_imported_identifiers_cannot_be_reissued(self) -> None:
        record = self.paid()
        bundle = {'issued_identifiers':[{'kind':'receipt','value':'TEST-OR-000001'}]}
        report = self.service.migrate(bundle)
        self.service.migrate(bundle, report['digest'])
        with self.assertRaisesRegex(ValueError, 'already assigned'):
            self.service.issue(record)
        self.assertEqual(self.service.detail(record)['state'], 'Payment Confirmed')
        new_range = copy.deepcopy(self.config)
        new_range['rules']['version'] = 'TEST-new-receipt-range'
        new_range['series'][1].update(first=100,last=199)
        self.service.configure(new_range)
        self.assertEqual(self.service.issue(record), 'TEST-OR-000100')

    def test_renewal_window_and_late_assessment_are_explicit(self) -> None:
        values = vehicle_fixture('RENEWAL-CHASSIS')
        values.update(plate='OLD12345', mv_file='111100000000002', expiry='2026-05-14')
        vehicle = self.service.create_vehicle(self.owner, values)
        request = {'office_code':'9999','vehicle_id':vehicle,'kind':'renewal','date':'2026-05-01'}
        with self.assertRaisesRegex(ValueError, 'earlier than'):
            self.service.create_transaction(request, 'test-early')
        configured = copy.deepcopy(self.config)
        configured['rules'].update(version='TEST-early-renewal', renewal_early_days=60)
        self.service.configure(configured)
        early = self.service.create_transaction(request, 'test-early')
        self.service.assess(early)
        self.service.void(early, 'TEST switch to late-renewal scenario')
        request['date'] = '2026-05-15'
        late = self.service.create_transaction(request, 'test-late')
        with self.assertRaisesRegex(ValueError, 'reasoned manual assessment'):
            self.service.assess(late)
        self.service.assess(late, [('MVUC','240.00'),('Assessed penalty','120.00')], 'TEST assessed penalty')
        self.assertEqual(self.service.detail(late)['assessment'][0]['total_cents'], 36000)

    def test_payment_preflight_and_settled_fund_void_guard(self) -> None:
        record = self.draft()
        self.service.assess(record)
        with patch('services.lto_workflow_service.generate_receipt', side_effect=ValueError('TEST invalid layout')):
            with self.assertRaisesRegex(ValueError, 'invalid layout'):
                self.service.record_payment(record, 'Cash', 'TEST-PREFLIGHT', '730.00')
        detail = self.service.detail(record)
        self.assertEqual(detail['state'], 'Assessed')
        self.assertFalse(detail['payments'])
        payment = self.service.record_payment(record, 'Cash', 'TEST-PREFLIGHT', '730.00')
        self.service.confirm_payment(payment, 'TEST settled cash')
        with self.assertRaisesRegex(ValueError, 'reversal/refund'):
            self.service.void(record, 'TEST disallowed silent reversal')
        self.assertEqual(self.service.detail(record)['state'], 'Payment Confirmed')

    def test_starter_defaults_work_without_files_and_remain_editable(self) -> None:
        service = LtoWorkflowService(Path(self.directory.name) / 'starter.db', 'starter-admin')
        service.ensure_starter_defaults()
        state = service.summary()
        self.assertEqual(len(state['offices']), 1)
        config = json.loads(state['offices'][0]['payload'])
        self.assertEqual(config['office']['tin'], '000865491001')
        self.assertEqual(config['rules']['initial_years'], 3)
        owner = service.create_owner({'name':'STARTER OWNER','address':'Example Street'})
        vehicle = service.create_vehicle(owner, vehicle_fixture())
        record = service.create_transaction({'office_code':'1396','vehicle_id':vehicle,'kind':'initial','date':'2026-04-23'}, 'starter-request')
        self.assertEqual(service.vehicles()[0]['plate'], 'LOCAL1001')
        service.assess(record)
        self.assertEqual(service.detail(record)['assessment'][0]['total_cents'], 94800)
        payment = service.record_payment(record, 'GCash', 'STARTER PAYMENT', '948.00')
        service.confirm_payment(payment, 'Starter confirmation')
        service.issue(record)
        snapshot = json.loads(service.detail(record)['receipt'][0]['snapshot'])
        self.assertEqual(snapshot['fields']['document_label'], 'LOCAL STARTER PROFILE')
        fees = copy.deepcopy(config['rules']['fees'])
        fees['initial'][0]['amount'] = '121.00'
        service.save_editable_defaults({'config_id':state['offices'][0]['id'], 'office':config['office'],
                                       'initial_years':3,'fees':fees,'series':config['series']})
        service.ensure_starter_defaults()
        changed = service.summary()
        self.assertEqual(len(changed['offices']), 1)
        self.assertEqual(next(row for row in changed['series'] if row['kind']=='transaction')['next_no'], 2)
        self.assertEqual(json.loads(changed['offices'][0]['payload'])['rules']['fees']['initial'][0]['amount'], '121.00')
        self.assertEqual(service.detail(record)['assessment'][0]['total_cents'], 94800)
        self.service.ensure_starter_defaults()
        self.assertEqual(len(self.service.summary()['offices']), 1)
        self.assertEqual(self.service.summary()['offices'][0]['code'], '9999')
