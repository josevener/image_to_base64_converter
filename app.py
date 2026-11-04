"""Application controller: connects Qt views to image services."""

from __future__ import annotations

from decimal import Decimal
import json
import sqlite3
from datetime import date
from pathlib import Path
from uuid import uuid4
from theme import save_settings

from PySide6.QtGui import QAction, QKeySequence

from pages.base64_to_image import Base64ToImagePage
from pages.api_client import ApiClientPage
from pages.about import AboutPage
from pages.background_remover import BackgroundRemoverPage
from pages.compress import CompressPage
from pages.crop import CropPage
from pages.favicon_generator import FaviconGeneratorPage
from pages.format_converter import FormatConverterPage
from pages.ico_generator import IcoGeneratorPage
from pages.image_to_base64 import ImageToBase64Page
from pages.input_activity_monitor import InputActivityMonitorPage
from pages.metadata import MetadataPage
from pages.lto_official_receipt import LtoOfficialReceiptPage
from pages.lto_workspace import LtoWorkspacePage
from services.lto_workflow_service import LtoWorkflowService, configuration_template, read_json_file
from services.lto_receipt_service import (
    Charge, ReceiptData, generate_receipt, parse_amount, save_receipt,
    DEFAULT_RECEIPT_FIELDS, DEFAULT_RECEIPT_CHARGES,
    receipt_filename,
)
from services.lto_registration_service import RegistrationInput, automatic_validity, calculate_suggestions, initial_renewal_year
from services.lto_receipt_automation import OFFICE_DEFAULTS, automated_fields, fresh_identifiers, validate_inputs, align_generated_plate, align_generated_references
from pages.qr_generator import QrGeneratorPage
from pages.qr_reader import QrReaderPage
from pages.resize import ResizePage
from pages.rotate import RotatePage
from pages.settings import SettingsPage
from pages.wifi_connections import WifiConnectionsPage
from ui.main_window import MainWindow


class ApplicationController:
    """Owns page navigation and is the MVC controller for the application."""

    def __init__(self) -> None:
        self._lto_workflow: LtoWorkflowService | None = None
        self._lto_request_key = str(uuid4())
        self.window = MainWindow()
        self._pages = {
            "Image to Base64": ImageToBase64Page(),
            "Base64 to Image": Base64ToImagePage(),
            "API Client": ApiClientPage(),
            "Format Converter": FormatConverterPage(),
            "ICO Generator": IcoGeneratorPage(),
            "Favicon Generator": FaviconGeneratorPage(),
            "Resize Image": ResizePage(),
            "Compress Image": CompressPage(),
            "Crop Image": CropPage(),
            "Rotate & Flip": RotatePage(),
            "Background Remover": BackgroundRemoverPage(),
            "Image Metadata": MetadataPage(),
            "QR Code Reader": QrReaderPage(),
            "QR Code Generator": QrGeneratorPage(),
            "Settings": SettingsPage(),
            "About": AboutPage(),
            "Wi-Fi Connections": WifiConnectionsPage(),
            "Input Activity Monitor": InputActivityMonitorPage(),
            "Official Receipt": LtoOfficialReceiptPage(),
            "Registration Workspace": LtoWorkspacePage(),
        }
        for name, page in self._pages.items():
            page.status_changed.connect(self.window.set_status)
            self.window.add_page(name, page)
        self.window.tool_requested.connect(self.show_tool)
        workspace = self._pages["Registration Workspace"]
        workspace.config_json.setPlainText(json.dumps(configuration_template(), indent=2))
        workspace.action_requested.connect(self.workspace_action)
        receipt = self._pages["Official Receipt"]
        receipt.preview_requested.connect(self.preview_receipt)
        receipt.export_requested.connect(self.export_receipt)
        receipt.payment_changed.connect(self.update_receipt_total)
        receipt.suggestions_requested.connect(self.calculate_registration)
        receipt.validity_requested.connect(self.update_automatic_validity)
        receipt.reset_completed.connect(self.initialize_receipt)
        receipt.fresh_requested.connect(self.generate_fresh_receipt)
        self.initialize_receipt()
        self._add_shortcuts()
        self.show_tool("Image to Base64")

    def _workflow(self) -> LtoWorkflowService:
        if self._lto_workflow is None:
            selected = self.window.settings.get('lto_registry_path')
            self._lto_workflow = LtoWorkflowService(Path(selected), allow_create=False) if selected else LtoWorkflowService()
        return self._lto_workflow

    def _refresh_workspace(self) -> None:
        service = self._workflow()
        service.ensure_starter_defaults()
        page = self._pages["Registration Workspace"]
        page.render(service.summary(), service.owners(), service.vehicles(),
                    service.transactions(page.search.text().strip()), service.audit(), service.history())
        if page.current_transaction:
            page.show_detail(service.detail(page.current_transaction))

    def workspace_action(self, action: str, payload: object = None) -> None:
        """Coordinate local registry operations; views never access the database."""
        page = self._pages["Registration Workspace"]
        try:
            if action == 'open_registry':
                path = page.choose_registry()
                if not path:
                    return
                candidate = LtoWorkflowService(Path(path), allow_create=False)
                candidate.summary()  # Verify this Windows account is assigned before switching.
                self._lto_workflow = candidate
                self.window.settings['lto_registry_path'] = path
                save_settings(self.window.settings)
                self._lto_request_key = str(uuid4())
                page.show_draft()
                self._refresh_workspace()
                page.notify('Opened local registry for this Windows account.')
                return
            service = self._workflow()
            message = ''
            if action == 'refresh':
                self._refresh_workspace()
                return
            if action == 'new_transaction':
                self._lto_request_key = str(uuid4())
                for field in page.date_inputs.values():
                    field.clear()
                page.show_draft()
                return
            if action == 'select_transaction':
                page.show_detail(service.detail(str(payload)))
                return
            if action == 'create_owner':
                record = service.create_owner(payload)
                self._refresh_workspace()
                page.vehicle_owner_combo.setCurrentIndex(page.vehicle_owner_combo.findData(record))
                page.clear_record('owner')
                message = 'Owner saved. Select the owner when adding a motorcycle.'
            elif action == 'create_vehicle':
                record = service.create_vehicle(payload['owner_id'], payload['values'])
                self._refresh_workspace()
                page.vehicle_combo.setCurrentIndex(page.vehicle_combo.findData(record))
                page.clear_record('vehicle')
                message = 'Motorcycle saved. Create its registration transaction on Transactions.'
            elif action == 'save_quick_defaults':
                config_id = service.save_editable_defaults(payload)
                self._refresh_workspace()
                page.select_quick_profile(config_id)
                message = 'Defaults saved. New transactions will use these values.'
            elif action == 'correct_record':
                service.correct_record(**payload)
                message = 'Record correction saved with the operator, reason, and previous values.'
            elif action == 'configure':
                service.configure(json.loads(str(payload)))
                code = json.loads(str(payload))['office']['code']
                self._refresh_workspace()
                for combo in (page.office_combo, page.stock_office):
                    combo.setCurrentIndex(combo.findData(code))
                message = 'Office configuration saved. Existing series counters were retained.'
            elif action == 'load_config':
                page.config_json.setPlainText(json.dumps(read_json_file(str(payload)), indent=2))
                page.tabs.setCurrentIndex(2)
                return
            elif action == 'add_stock':
                plates = [value.strip() for value in payload['plates'].replace(',', '\n').splitlines() if value.strip()]
                count = service.add_plate_stock(payload['office'], plates, payload['authority'])
                page.stock_plates.clear()
                message = f'Imported {count} unassigned plates.'
            elif action == 'set_operator':
                service.set_operator(**payload)
                message = 'Windows operator role updated.'
            elif action == 'create_transaction':
                record = service.create_transaction(payload, self._lto_request_key)
                page.current_transaction = record
                message = 'Draft created. Identifiers are reserved; registration is completed after receipt issuance.'
            elif action == 'assess':
                service.assess(str(payload))
                message = 'Assessment saved with the configured rule version.'
            elif action == 'manual_assessment':
                values = page.manual_assessment_dialog()
                if values is None:
                    return
                service.assess(str(payload), values['lines'], values['reason'])
                message = 'Manual assessment saved with its reason; prior assessment versions were retained.'
            elif action == 'record_payment':
                detail = service.detail(str(payload))
                if not detail['assessment']:
                    raise ValueError('Assess the transaction first.')
                total = Decimal(detail['assessment'][0]['total_cents']) / 100
                values = page.payment_dialog(f'{total:.2f}')
                if values is None:
                    return
                service.record_payment(str(payload), **values)
                message = 'Payment recorded as Pending. Confirm against evidence before issuing a receipt.'
            elif action in ('confirm_payment', 'fail_payment'):
                detail = service.detail(str(payload))
                payment = next((p for p in detail['payments'] if p['status']=='Pending'), None)
                if payment is None:
                    raise ValueError('There is no pending payment for this transaction.')
                prompt = 'Evidence / reconciliation reference. This records manual confirmation; no payment-provider lookup is performed.' if action=='confirm_payment' else 'Reason this pending payment failed:'
                reason = page.prompt('Confirm payment' if action=='confirm_payment' else 'Payment failure', prompt)
                if reason is None:
                    return
                if action == 'confirm_payment':
                    service.confirm_payment(payment['id'], reason)
                else:
                    service.fail_payment(payment['id'], reason)
                message = 'Payment status updated.'
            elif action == 'issue':
                number = service.issue(str(payload))
                message = f'Receipt {number} issued and saved. View or export its immutable PDF.'
            elif action == 'view_receipt':
                number, content = service.receipt_pdf(str(payload))
                page.show_receipt(number, content)
                return
            elif action == 'export':
                number, _ = service.receipt_pdf(str(payload))
                path = page.save_path(receipt_filename(number))
                if not path:
                    return
                if not path.lower().endswith('.pdf'):
                    path += '.pdf'
                service.export_receipt(str(payload), path)
                message = f'Saved issued receipt to {path}'
            elif action == 'void':
                reason = page.prompt('Void transaction', 'Reason for voiding this transaction. Reserved identifiers will be retained:')
                if reason is None:
                    return
                service.void(str(payload), reason)
                message = 'Transaction voided. Its identifiers and audit history were retained.'
            elif action == 'backup':
                path = page.save_path(f'lto_registry_backup_{date.today():%Y%m%d}.db', 'SQLite registry (*.db)')
                if not path:
                    return
                service.backup(Path(path))
                message = f'Local registry backup saved to {path}'
            elif action == 'load_migration':
                page.migration_json.setPlainText(json.dumps(read_json_file(str(payload)), indent=2))
                return
            elif action == 'preview_migration':
                report = service.migrate(json.loads(str(payload)))
                page.reviewed_digest = report['digest']
                page.migration_report.setPlainText(json.dumps(report, indent=2) + '\n\nPreview only: no records have been saved by this validation run.')
                page.apply_migration.setEnabled(True)
                return
            elif action == 'apply_migration':
                if not payload['digest']:
                    raise ValueError('Preview this handover bundle before importing it.')
                report = service.migrate(json.loads(payload['text']), payload['digest'])
                page.migration_report.setPlainText(json.dumps(report, indent=2) + '\n\nImport complete.')
                page.apply_migration.setEnabled(False)
                message = 'Reviewed handover bundle imported atomically.'
            else:
                raise ValueError('Unknown workspace action.')
            self._refresh_workspace()
            if message:
                page.notify(message)
        except (ValueError, OSError, sqlite3.Error) as error:
            page.notify(str(error), error=True)

    def _receipt_pdf(self) -> tuple[bytes, str]:
        self._prepare_automated_receipt()
        self.update_automatic_validity(strict=True)
        page = self._pages["Official Receipt"]
        fields, rows = page.values()
        data = ReceiptData(fields, [Charge(label, parse_amount(amount)) for label, amount in rows])
        content = generate_receipt(data)
        if page.automated():
            page.show_generated_summary()
        return content, f"{data.total:,.2f}"

    def _prepare_automated_receipt(self, fresh: bool = False) -> None:
        page = self._pages["Official Receipt"]
        if not page.automated():
            return
        values = validate_inputs(page.automation_values())
        identifiers = page.generated_identifiers
        new_receipt = fresh or not identifiers or not identifiers["receipt_no"].startswith(f"{values['office_code']}-")
        payment_date = page.automation_datetime(new_receipt)
        if new_receipt:
            identifiers = fresh_identifiers(values["office_code"], registration_date=payment_date.date(),
                                            use_tx_format=page.use_tx_format.isChecked())
        else:
            identifiers = align_generated_plate(identifiers, payment_date.date())
            identifiers = align_generated_references(identifiers, payment_date.date(),
                                                     use_tx_format=page.use_tx_format.isChecked())
        page.generated_identifiers = identifiers
        fields = automated_fields(values, identifiers, payment_date)
        for key in DEFAULT_RECEIPT_FIELDS:
            fields[key] = page.inputs[key].text().strip()
        page.apply_automated_fields(fields)

    def generate_fresh_receipt(self) -> None:
        page = self._pages["Official Receipt"]
        try:
            self._prepare_automated_receipt(fresh=True)
            self.preview_receipt()
        except (ValueError, OSError, sqlite3.Error) as error:
            page.show_error(str(error))

    def initialize_receipt(self) -> None:
        page = self._pages["Official Receipt"]
        page.load_defaults({**DEFAULT_RECEIPT_FIELDS, **OFFICE_DEFAULTS},
                           [(item.description, f"{item.amount:.2f}") for item in DEFAULT_RECEIPT_CHARGES])
        if page.automated():
            page.inputs["year_model"].setText(str(date.today().year))
            page.sync_automation_inputs()
            page.quick_date_overridden = False
        self.update_automatic_validity()

    def update_automatic_validity(self, strict: bool = False) -> None:
        page = self._pages["Official Receipt"]
        if not page.auto_validity.isChecked():
            page.validity_hint.setText("Manual notice enabled.")
            return
        try:
            if page.automated() and page.generated_identifiers:
                identifiers = align_generated_plate(page.generated_identifiers, page.quick_date.date().toPython())
                identifiers = align_generated_references(identifiers, page.quick_date.date().toPython(),
                                                         use_tx_format=page.use_tx_format.isChecked())
                page.generated_identifiers = identifiers
                for key in ("plate_no", "transaction_no", "file_no"):
                    control = page.inputs[key]
                    blocked = control.blockSignals(True)
                    control.setText(identifiers[key])
                    control.blockSignals(blocked)
            values = page.registration_values()
            values["annual_mvuc"] = Decimal("0")  # Dates do not depend on the fee-estimation input.
            if values["transaction"] == "initial" and values["auto_initial_renewal_year"]:
                year = initial_renewal_year(RegistrationInput(**values))
                page.show_initial_renewal_year(year)
                values["renewal_year"] = year
            notice = automatic_validity(RegistrationInput(**values))
            page.inputs["validity"].setText(notice)
            page.validity_hint.setText("Computed from plate schedule and renewal year." if values["plate"]
                                       else "Using confirmed OR/CR dates for the MV file-only record.")
            if page.automated() and page.generated_identifiers:
                page.show_generated_summary()
        except (ValueError, OSError, sqlite3.Error) as error:
            page.inputs["validity"].clear()
            page.validity_hint.setText(str(error))
            if strict:
                raise

    def update_receipt_total(self) -> None:
        page = self._pages["Official Receipt"]
        _, rows = page.values()
        try:
            total = sum((parse_amount(amount) for _, amount in rows if amount), Decimal("0.00"))
            page.set_total(f"{total:,.2f}")
        except ValueError:
            page.set_total(None)

    def calculate_registration(self) -> None:
        page = self._pages["Official Receipt"]
        try:
            values = page.registration_values()
            values["annual_mvuc"] = parse_amount(values["annual_mvuc"])
            suggestion = calculate_suggestions(RegistrationInput(**values))
            charges = [(item.description, f"{item.amount:.2f}") for item in suggestion.charges]
            if page.review_suggestions(suggestion.validity, charges, suggestion.explanation):
                self.window.set_status("Registration suggestions applied; review before exporting")
        except ValueError as error:
            page.show_error(str(error))

    def preview_receipt(self) -> None:
        page = self._pages["Official Receipt"]
        try:
            content, total = self._receipt_pdf()
            page.display_preview(content, total)
            self.window.set_status("Official Receipt preview updated")
        except (ValueError, OSError, sqlite3.Error) as error:
            page.show_error(str(error))

    def export_receipt(self) -> None:
        page = self._pages["Official Receipt"]
        try:
            content, total = self._receipt_pdf()
            fields, _ = page.values()
            path = page.export_path(receipt_filename(fields["receipt_no"]))
            if not path:
                return
            save_receipt(path, content)
            page.display_preview(content, total)
            self.window.set_status(f"Receipt PDF saved to {path}")
        except (ValueError, OSError, sqlite3.Error) as error:
            page.show_error(str(error))

    def _add_shortcuts(self) -> None:
        page = self._pages["Image to Base64"]
        for key, callback in (
            ("Ctrl+O", page.browse_image), ("Ctrl+C", lambda: page.copy_output(False)),
            ("Ctrl+S", page.save_output), ("Ctrl+L", page.clear),
            ("Ctrl+V", page.paste_image),
        ):
            action = QAction(self.window)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(callback)
            self.window.addAction(action)

    def show_tool(self, name: str) -> None:
        """Show an available page or the application's standard future-tool page."""
        if name.startswith("recent:") or name.startswith("drop:"):
            path = name.split(":", 1)[1]
            page = self._pages["Image to Base64"]
            self.window.show_page("Image to Base64")
            page.load_image(path)  # type: ignore[attr-defined]
            return
        if name in self._pages:
            self.window.show_page(name)
        else:
            self.window.show_placeholder(name)

    def show(self) -> None:
        self.window.showMaximized()

    def shutdown(self) -> None:
        """Release services that own system resources before Qt exits."""
        monitor = self._pages.get("Input Activity Monitor")
        if isinstance(monitor, InputActivityMonitorPage):
            monitor.shutdown()
