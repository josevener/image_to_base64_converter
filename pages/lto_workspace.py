"""Qt views for local registration records and the payment-to-receipt workflow."""

from __future__ import annotations

import json
from PySide6.QtCore import QBuffer, QDate, QIODevice, Qt, Signal
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)
from ui.components.tool_page import ToolPage
from ui.pdf_preview import PdfPreview
from ui.receipt_form import FormInteractions, FormSection, PaymentAmountDelegate


class LtoWorkspacePage(ToolPage):
    action_requested = Signal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self.current_transaction: str | None = None
        self._loaded = False
        self._detail: dict = {}
        self._role = 'viewer'
        self._owner_rows: dict[str, dict] = {}
        self._vehicle_rows: dict[str, dict] = {}
        self.editing_owner: str | None = None
        self.editing_vehicle: str | None = None
        self._quick_configs: dict[str, dict] = {}
        self._quick_config_id: str | None = None
        self._quick_fees: dict[str, list[dict]] = {}
        self._quick_fee_kind: str | None = None
        self.setObjectName('ltoWorkspace')
        self.setStyleSheet('#ltoWorkspace QLabel#workspaceTitle {font-size:24px;font-weight:700;} '
                           '#ltoWorkspace #formSectionTitle {font-size:15px;font-weight:700;}'
                           '#ltoWorkspace QLabel#workspaceMessage {color:#2F80ED;padding:8px;}'
                           '#ltoWorkspace QLabel#workspaceError {color:#D94F4F;padding:8px;}'
                           '#ltoWorkspace QLineEdit:focus, #ltoWorkspace QPlainTextEdit:focus {border:2px solid #2F80ED;}')
        root = QVBoxLayout(self)
        title = QLabel('Registration Workspace')
        title.setObjectName('workspaceTitle')
        header = QHBoxLayout()
        header.addWidget(title, 1)
        self.advanced_toggle = self.button('Advanced tools', lambda: None)
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        header.addWidget(self.advanced_toggle)
        root.addLayout(header)
        self.identity = QLabel('Loading local registry…')
        self.identity.setObjectName('muted')
        self.identity.setTextFormat(Qt.TextFormat.PlainText)
        self.identity.setWordWrap(True)
        root.addWidget(self.identity)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setObjectName('workspaceError')
        self.message.hide()
        root.addWidget(self.message)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_transactions()
        self._build_records()
        self._build_setup()
        self._build_migration()
        self._build_audit()
        root.addWidget(self.save_quick)
        self.tabs.currentChanged.connect(lambda index: self.save_quick.setVisible(index == 2))
        self.save_quick.hide()
        self._toggle_advanced(False)
        self._interactions = FormInteractions(self)

    def showEvent(self, event: object) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self.request('refresh')

    def request(self, action: str, payload: object = None) -> None:
        self.action_requested.emit(action, payload)

    def button(self, label: str, callback, primary: bool = False) -> QPushButton:
        button = QPushButton(label)
        if not primary:
            button.setObjectName('secondaryButton')
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        return button

    def tab(self, label: str) -> QVBoxLayout:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(12)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, label)
        return layout

    @staticmethod
    def field(form: QFormLayout, label: str, default: str = '', hint: str = '') -> QLineEdit:
        field = QLineEdit(default)
        field.setMaxLength(180 if 'address' in label.lower() or 'reason' in label.lower() else 100)
        field.setPlaceholderText(hint)
        field.setAccessibleName(label)
        field.setClearButtonEnabled(True)
        form.addRow(label, field)
        return field

    @staticmethod
    def table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(190)
        return table

    @staticmethod
    def fill_table(table: QTableWidget, rows: list[dict], keys: list[str]) -> None:
        table.blockSignals(True)
        try:
            table.setRowCount(len(rows))
            for row_no, record in enumerate(rows):
                for column, key in enumerate(keys):
                    item = QTableWidgetItem(str(record.get(key) or ''))
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, record.get('id'))
                    table.setItem(row_no, column, item)
        finally:
            table.blockSignals(False)

    def _build_transactions(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Owner, plate, transaction, or receipt number')
        self.search.returnPressed.connect(lambda: self.request('refresh'))
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.button('Search / refresh', lambda: self.request('refresh')))
        self.new_button = self.button('New transaction', lambda: self.request('new_transaction'), True)
        toolbar.addWidget(self.new_button)
        layout.addLayout(toolbar)
        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        self.transaction_table = self.table(['Transaction', 'Owner', 'Plate', 'Status', 'Receipt'])
        self.transaction_table.setMinimumHeight(120)
        self.transaction_table.setMaximumHeight(230)
        self.transaction_table.currentCellChanged.connect(self._select_transaction)
        split.addWidget(self.transaction_table)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        details = QVBoxLayout(body)
        details.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.draft_section = FormSection('Start a registration transaction', 'Save an owner and motorcycle under Records first. New identifiers are reserved from the configured office series and plate stock.')
        draft = self.draft_section.form
        self.office_combo = QComboBox()
        self.vehicle_combo = QComboBox()
        self.kind_combo = QComboBox()
        for label, kind in (('Brand-new registration', 'initial'), ('Annual renewal', 'renewal'), ('Transfer of ownership', 'transfer')):
            self.kind_combo.addItem(label, kind)
        self.transfer_combo = QComboBox()
        self.transaction_date = QDateEdit(QDate.currentDate())
        self.transaction_date.setCalendarPopup(True)
        self.transaction_date.setMaximumDate(QDate.currentDate())
        self.transaction_date.setDisplayFormat('yyyy-MM-dd')
        for label, widget in (('Issuing office', self.office_combo), ('Motorcycle', self.vehicle_combo), ('Transaction type', self.kind_combo),
                              ('New owner (transfer only)', self.transfer_combo), ('Registration / transaction date', self.transaction_date)):
            draft.addRow(label, widget)
        self.kind_combo.currentIndexChanged.connect(lambda: self.transfer_combo.setEnabled(self.kind_combo.currentData() == 'transfer'))
        self.transfer_combo.setEnabled(False)
        self.confirmed_dates = FormSection('Confirmed dates from OR/CR', 'Required when the office uses confirmed-date rules, for file-only records, or exceptions. All three dates use YYYY-MM-DD.', True)
        self.date_inputs = {key: self.field(self.confirmed_dates.form, label, hint='YYYY-MM-DD')
                            for key, label in (('expiry', 'Validity expiry'), ('renewal_start', 'Next renewal starts'), ('renewal_end', 'Next renewal ends'))}
        self.date_inputs['date_reason'] = self.field(self.confirmed_dates.form, 'Source / reason', hint='OR/CR or assessment reference')
        draft.addRow(self.confirmed_dates)
        self.create_button = self.button('Create draft and reserve identifiers', self._create_draft, True)
        draft.addRow(self.create_button)
        details.addWidget(self.draft_section)
        self.detail_section = FormSection('Transaction details')
        self.detail_heading = QLabel()
        self.detail_heading.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_heading.setWordWrap(True)
        self.detail_section.form.addRow(self.detail_heading)
        self.assessment_table = self.table(['Assessed item', 'Amount (PHP)'])
        self.assessment_table.setMinimumHeight(120)
        self.assessment_table.setItemDelegateForColumn(1, PaymentAmountDelegate(self.assessment_table))
        self.detail_section.form.addRow(self.assessment_table)
        self.payment_summary = QLabel()
        self.payment_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.payment_summary.setWordWrap(True)
        self.detail_section.form.addRow(self.payment_summary)
        self.action_bar = QWidget()
        action_layout = QVBoxLayout(self.action_bar)
        action_layout.setContentsMargins(0, 0, 0, 0)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.actions: dict[str, QPushButton] = {}
        for action, label in (('assess', 'Assess'), ('manual_assessment', 'Manual assessment'), ('record_payment', 'Record payment')):
            button = self.button(label, lambda checked=False, a=action: self.request(a, self.current_transaction))
            actions.addWidget(button)
            self.actions[action] = button
        action_layout.addLayout(actions)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        for action, label in (('confirm_payment', 'Confirm payment'), ('issue', 'Issue receipt'), ('view_receipt', 'View PDF'), ('export', 'Export'), ('void', 'Void')):
            button = self.button(label, lambda checked=False, a=action: self.request(a, self.current_transaction), action == 'issue')
            actions.addWidget(button)
            self.actions[action] = button
        action_layout.addLayout(actions)
        self.fail_button = self.button('Mark pending payment failed', lambda: self.request('fail_payment', self.current_transaction))
        action_layout.addWidget(self.fail_button)
        self.detail_section.hide()
        details.addWidget(self.detail_section)
        scroll.setWidget(body)
        split.addWidget(scroll)
        split.setSizes([200, 430])
        layout.addWidget(split, 1)
        layout.addWidget(self.action_bar)
        self.action_bar.hide()
        self.tabs.addTab(page, 'Transactions')

    def _create_draft(self) -> None:
        self.request('create_transaction', {
            'office_code': self.office_combo.currentData(), 'vehicle_id': self.vehicle_combo.currentData(),
            'kind': self.kind_combo.currentData(), 'new_owner_id': self.transfer_combo.currentData(),
            'date': self.transaction_date.date().toString('yyyy-MM-dd'),
            **{key: widget.text().strip() for key, widget in self.date_inputs.items()},
        })

    def _select_transaction(self) -> None:
        row = self.transaction_table.currentRow()
        item = self.transaction_table.item(row, 0) if row >= 0 else None
        if item:
            self.request('select_transaction', item.data(Qt.ItemDataRole.UserRole))

    def _build_records(self) -> None:
        layout = self.tab('Records')
        records = QTabWidget()
        layout.addWidget(records)
        for title, kind in (('Owners', 'owner'), ('Motorcycles', 'vehicle')):
            body = QWidget()
            contents = QVBoxLayout(body)
            section = FormSection('Add ' + kind, 'Existing identifiers are retained. Leave identifiers blank only for a new motorcycle awaiting assignment.')
            fields: dict[str, QLineEdit] = {}
            if kind == 'owner':
                keys = [('name', 'Full name *'), ('address', 'Address *'), ('tin', 'TIN'), ('client_id', 'Existing client ID'), ('legacy_id', 'Legacy owner ID (optional)')]
            else:
                self.vehicle_owner_combo = QComboBox()
                section.form.addRow('Saved owner *', self.vehicle_owner_combo)
                keys = [('chassis', 'Chassis number *'), ('engine_no', 'Engine number *'), ('engine_cc', 'Engine size in cc *'),
                        ('plate', 'Existing plate (if assigned)'), ('mv_file', 'Existing MV file number'),
                        ('expiry', 'Existing official expiry (YYYY-MM-DD)'), ('color', 'Color *'), ('year_model', 'Year model *'),
                        ('classification', 'Classification *'), ('vehicle_type', 'Vehicle type *'), ('fuel_type', 'Fuel type *'),
                        ('aircon_type', 'Aircon type *'), ('legacy_id', 'Legacy vehicle ID (optional)')]
            defaults = {'classification': 'Private - (PVT)', 'vehicle_type': 'Motorcycle Without Sidecar', 'fuel_type': 'Gas', 'aircon_type': 'N/A'}
            for key, label in keys:
                fields[key] = self.field(section.form, label, defaults.get(key, ''))
            if kind == 'owner':
                self.owner_inputs = fields
                self.save_owner = self.button('Save owner', lambda: self._save_record('owner'), True)
                section.form.addRow(self.save_owner)
                section.form.addRow(self.button('New owner / clear selection', lambda: self.clear_record('owner')))
                self.owner_table = self.table(['Name', 'Client ID', 'Address'])
                self.owner_table.currentCellChanged.connect(lambda: self._select_record('owner'))
                table = self.owner_table
            else:
                self.vehicle_inputs = fields
                self.save_vehicle = self.button('Save motorcycle', lambda: self._save_record('vehicle'), True)
                section.form.addRow(self.save_vehicle)
                section.form.addRow(self.button('New motorcycle / clear selection', lambda: self.clear_record('vehicle')))
                self.vehicle_table = self.table(['Owner', 'Plate', 'MV file', 'Chassis', 'Expiry'])
                self.vehicle_table.currentCellChanged.connect(lambda: self._select_record('vehicle'))
                table = self.vehicle_table
            contents.addWidget(section)
            contents.addWidget(table)
            records.addTab(body, title)

    def clear_record(self, kind: str) -> None:
        fields = self.owner_inputs if kind == 'owner' else self.vehicle_inputs
        if kind == 'owner':
            self.editing_owner = None
            self.save_owner.setText('Save owner')
        else:
            self.editing_vehicle = None
            self.save_vehicle.setText('Save motorcycle')
            self.vehicle_owner_combo.setEnabled(True)
        defaults = {'classification':'Private - (PVT)', 'vehicle_type':'Motorcycle Without Sidecar', 'fuel_type':'Gas', 'aircon_type':'N/A'}
        for key, field in fields.items():
            field.setReadOnly(False)
            field.setText(defaults.get(key, ''))

    def _select_record(self, kind: str) -> None:
        table = self.owner_table if kind == 'owner' else self.vehicle_table
        item = table.item(table.currentRow(), 0) if table.currentRow() >= 0 else None
        if item is None:
            return
        record_id = item.data(Qt.ItemDataRole.UserRole)
        fields = self.owner_inputs if kind == 'owner' else self.vehicle_inputs
        record = (self._owner_rows if kind == 'owner' else self._vehicle_rows).get(record_id)
        if record is None:
            return
        values = {**record, **(json.loads(record['specs']) if kind == 'vehicle' else {})}
        protected = ('client_id','legacy_id') if kind=='owner' else ('chassis','engine_no','plate','mv_file','expiry','legacy_id')
        for key, field in fields.items():
            field.setText(str(values.get(key) or ''))
            field.setReadOnly(key in protected)
        if kind == 'owner':
            self.editing_owner = record_id
            self.save_owner.setText('Save contact correction')
        else:
            self.editing_vehicle = record_id
            self.vehicle_owner_combo.setCurrentIndex(self.vehicle_owner_combo.findData(record['owner_id']))
            self.vehicle_owner_combo.setEnabled(False)
            self.save_vehicle.setText('Save specification correction')

    def _save_record(self, kind: str) -> None:
        fields = self.owner_inputs if kind == 'owner' else self.vehicle_inputs
        values = {key: field.text().strip() for key, field in fields.items()}
        record_id = self.editing_owner if kind == 'owner' else self.editing_vehicle
        if record_id:
            reason = self.prompt('Record correction', 'Reason / source for this contact or specification correction:')
            if reason is not None:
                self.request('correct_record', {'kind': kind, 'record_id': record_id, 'values': values, 'reason': reason})
        elif kind == 'owner':
            self.request('create_owner', values)
        else:
            self.request('create_vehicle', {'owner_id': self.vehicle_owner_combo.currentData(), 'values': values})

    def _build_setup(self) -> None:
        layout = self.tab('Defaults')
        self.quick_choice = QComboBox()
        self.quick_choice.currentIndexChanged.connect(lambda: self.select_quick_profile(self.quick_choice.currentData()))
        layout.addWidget(self.quick_choice)
        office = FormSection('Office details', 'These values start from your sample receipt. Edit them here—no file or import is needed.')
        office.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.quick_office = {key:self.field(office.form, label) for key,label in (
            ('name','Office name'), ('code','Office code'), ('address','Office address'),
            ('tin','Office TIN'), ('pos_machine','POS / cashier station'))}
        self.quick_years = QSpinBox()
        self.quick_years.setRange(1,10)
        self.quick_years.setValue(3)
        self.quick_years.setSuffix(' years')
        office.form.addRow('Brand-new registration validity', self.quick_years)
        layout.addWidget(office)
        fees = FormSection('Default payment items', 'The starting template totals PHP 948.00. Edit the amounts before using them for your assessments.')
        self.quick_fee_choice = QComboBox()
        for label, kind in (('Brand-new registration','initial'),('Annual renewal','renewal'),('Transfer of ownership','transfer')):
            self.quick_fee_choice.addItem(label, kind)
        self.quick_fee_choice.currentIndexChanged.connect(self._switch_quick_fees)
        fees.form.addRow('Payment template for', self.quick_fee_choice)
        self.quick_fee_table = QTableWidget(0,2)
        self.quick_fee_table.setHorizontalHeaderLabels(['Description','Amount (PHP)'])
        self.quick_fee_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.quick_fee_table.setItemDelegateForColumn(1, PaymentAmountDelegate(self.quick_fee_table))
        self.quick_fee_table.setMinimumHeight(210)
        fees.form.addRow(self.quick_fee_table)
        fee_buttons = QHBoxLayout()
        fee_buttons.setSpacing(8)
        fee_buttons.addWidget(self.button('+ Add item', lambda: self.quick_fee_table.insertRow(self.quick_fee_table.rowCount()) if self.quick_fee_table.rowCount()<8 else None))
        fee_buttons.addWidget(self.button('Remove selected', lambda: self.quick_fee_table.removeRow(self.quick_fee_table.currentRow()) if self.quick_fee_table.currentRow()>=0 else None))
        fees.form.addRow(fee_buttons)
        layout.addWidget(fees)
        numbering = FormSection('Numbering defaults', 'Starter numbers are marked LOCAL. Existing counters continue when you edit other defaults. Assigned numbering and plate inventory are available in Advanced tools.', True)
        self.quick_series = QTableWidget(0,5)
        self.quick_series.setHorizontalHeaderLabels(['Identifier','Prefix','Digits','First','Last'])
        self.quick_series.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.quick_series.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.quick_series.setMinimumHeight(210)
        numbering.form.addRow(self.quick_series)
        layout.addWidget(numbering)
        self.save_quick = self.button('Save defaults', self._save_quick_defaults, True)
        self.advanced_setup = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_setup)
        advanced_layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.advanced_setup)
        layout = advanced_layout
        layout.addWidget(self.button('Open a different local registry', lambda: self.request('open_registry')))
        intro = QLabel('Optional tools for assigned ranges, plate stock, operator roles, and existing records. You do not need these to use the starter defaults.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.setup_summary = QPlainTextEdit()
        self.setup_summary.setReadOnly(True)
        self.setup_summary.setMaximumHeight(160)
        layout.addWidget(self.setup_summary)
        config = FormSection('Office configuration JSON', 'Use the documented schema in docs/lto-workspace.md. Re-importing an unchanged range keeps its current counter.')
        self.config_json = QPlainTextEdit()
        self.config_json.setMinimumHeight(220)
        config.form.addRow(self.config_json)
        buttons = QHBoxLayout()
        buttons.addWidget(self.button('Load JSON', lambda: self._choose_json('load_config')))
        self.save_config = self.button('Save configuration', lambda: self.request('configure', self.config_json.toPlainText()), True)
        buttons.addWidget(self.save_config)
        config.form.addRow(buttons)
        layout.addWidget(config)
        stock = FormSection('Assigned plate inventory', 'Paste actual unassigned plates, one per line. They will be reserved by new-registration drafts.')
        self.stock_office = QComboBox()
        stock.form.addRow('Office', self.stock_office)
        self.stock_authority = self.field(stock.form, 'Stock authority / batch reference')
        self.stock_plates = QPlainTextEdit()
        self.stock_plates.setMaximumHeight(120)
        stock.form.addRow('Plates', self.stock_plates)
        self.save_stock = self.button('Import assigned stock', lambda: self.request('add_stock', {'office': self.stock_office.currentData(), 'authority': self.stock_authority.text(), 'plates': self.stock_plates.toPlainText()}))
        stock.form.addRow(self.save_stock)
        layout.addWidget(stock)
        operators = FormSection('Windows operator roles', 'First launch assigns this Windows account as administrator. Permissions apply to this local application; protect the database using Windows access controls.')
        self.operator_name = self.field(operators.form, 'Windows username')
        self.operator_role = QComboBox()
        self.operator_role.addItems(['viewer', 'operator', 'cashier', 'admin'])
        operators.form.addRow('Role', self.operator_role)
        self.operator_reason = self.field(operators.form, 'Role-change reason')
        self.save_operator = self.button('Assign role', lambda: self.request('set_operator', {'username': self.operator_name.text(), 'role': self.operator_role.currentText(), 'reason': self.operator_reason.text()}))
        operators.form.addRow(self.save_operator)
        self.backup_button = self.button('Back up local registry', lambda: self.request('backup'))
        operators.form.addRow(self.backup_button)
        layout.addWidget(operators)

    def _toggle_advanced(self, checked: bool) -> None:
        if not hasattr(self, 'advanced_setup'):
            return
        self.advanced_setup.setVisible(checked)
        for index in (3,4):
            self.tabs.setTabVisible(index, checked)

    def _store_quick_fees(self) -> None:
        if self._quick_fee_kind is None:
            return
        rows = []
        for row in range(self.quick_fee_table.rowCount()):
            label = self.quick_fee_table.item(row,0)
            amount = self.quick_fee_table.item(row,1)
            rows.append({'description':label.text().strip() if label else '', 'amount':amount.text().strip() if amount else '',
                         'basis':label.data(Qt.ItemDataRole.UserRole) or 'fixed' if label else 'fixed'})
        self._quick_fees[self._quick_fee_kind] = rows

    def _switch_quick_fees(self) -> None:
        self._store_quick_fees()
        self._quick_fee_kind = self.quick_fee_choice.currentData()
        lines = self._quick_fees.get(self._quick_fee_kind, [])
        self.quick_fee_table.setRowCount(len(lines))
        for row,line in enumerate(lines):
            label = QTableWidgetItem(line['description'])
            label.setData(Qt.ItemDataRole.UserRole,line.get('basis','fixed'))
            self.quick_fee_table.setItem(row,0,label)
            self.quick_fee_table.setItem(row,1,QTableWidgetItem(str(line['amount'])))

    def select_quick_profile(self, config_id: str | None) -> None:
        if config_id not in self._quick_configs:
            return
        self._quick_config_id = config_id
        self.quick_choice.blockSignals(True)
        self.quick_choice.setCurrentIndex(self.quick_choice.findData(config_id))
        self.quick_choice.blockSignals(False)
        data = self._quick_configs[config_id]
        for key,field in self.quick_office.items():
            field.setText(str(data['office'].get(key) or ''))
        self.quick_years.setValue(data['rules']['initial_years'])
        self._quick_fee_kind = None
        self._quick_fees = json.loads(json.dumps(data['rules']['fees']))
        self._switch_quick_fees()
        series = data.get('series',[])
        self.quick_series.setRowCount(len(series))
        for row,item in enumerate(series):
            for column,key in enumerate(('kind','prefix','width','first','last')):
                cell = QTableWidgetItem(str(item.get(key,'')))
                if column==0:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.quick_series.setItem(row,column,cell)

    def _save_quick_defaults(self) -> None:
        self._store_quick_fees()
        try:
            series=[]
            for row in range(self.quick_series.rowCount()):
                values = [self.quick_series.item(row,col).text().strip() for col in range(5)]
                series.append({'kind':values[0], 'prefix':values[1], 'width':int(values[2]), 'first':int(values[3]), 'last':int(values[4])})
        except (ValueError, AttributeError):
            self.notify('Digits, First, and Last must be whole numbers.', error=True)
            return
        self.request('save_quick_defaults', {'config_id':self._quick_config_id,
            'office':{key:field.text().strip() for key,field in self.quick_office.items()},
            'initial_years':self.quick_years.value(), 'fees':self._quick_fees, 'series':series})

    def _build_migration(self) -> None:
        layout = self.tab('Migration')
        note = QLabel('Import a JSON handover bundle. Preview validates the entire bundle without saving. Apply imports exactly the reviewed content in one transaction. Pending legacy history is retained for reconciliation, not resumed as a new payment.')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(self.button('Load handover JSON', lambda: self._choose_json('load_migration')))
        self.migration_json = QPlainTextEdit()
        self.migration_json.setPlaceholderText('{"owners": [], "vehicles": [], "history": [], "issued_identifiers": []}')
        self.migration_json.setMinimumHeight(180)
        layout.addWidget(self.migration_json)
        self.migration_report = QPlainTextEdit()
        self.migration_report.setReadOnly(True)
        layout.addWidget(self.migration_report)
        buttons = QHBoxLayout()
        self.preview_migration = self.button('Preview / validate', lambda: self.request('preview_migration', self.migration_json.toPlainText()))
        self.apply_migration = self.button('Apply reviewed import', lambda: self.request('apply_migration', {'text': self.migration_json.toPlainText(), 'digest': self.reviewed_digest}), True)
        self.apply_migration.setEnabled(False)
        self.reviewed_digest: str | None = None
        self.migration_json.textChanged.connect(self._invalidate_import)
        buttons.addWidget(self.preview_migration)
        buttons.addWidget(self.apply_migration)
        layout.addLayout(buttons)
        self.history_table = self.table(['Legacy record', 'Plate', 'MV file', 'Paid cents (historical)'])
        layout.addWidget(self.history_table)

    def _invalidate_import(self) -> None:
        self.reviewed_digest = None
        self.apply_migration.setEnabled(False)
        self.migration_report.setPlainText('Preview required before applying this content.')

    def _choose_json(self, action: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, 'Load JSON', '', 'JSON files (*.json)')
        if path:
            self.request(action, path)

    def _build_audit(self) -> None:
        layout = self.tab('Audit')
        layout.addWidget(QLabel('Most recent 1,000 audit events. Timestamps use UTC.'))
        layout.addWidget(self.button('Refresh audit', lambda: self.request('refresh')))
        self.audit_table = self.table(['UTC time', 'Windows user', 'Action', 'Record', 'Details'])
        layout.addWidget(self.audit_table, 1)

    @staticmethod
    def _choices(combo: QComboBox, rows: list[tuple[str, str]]) -> None:
        selected = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for label, record_id in rows:
            combo.addItem(label, record_id)
        index = combo.findData(selected)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def render(self, state: dict, owners: list[dict], vehicles: list[dict], transactions: list[dict], audit: list[dict], history: list[dict]) -> None:
        self._role = state['role']
        previous_id = self._quick_config_id
        self._quick_configs = {row['id']:json.loads(row['payload']) for row in state['offices']}
        self._choices(self.quick_choice, [(data['office']['name'],key) for key,data in self._quick_configs.items()])
        if previous_id not in self._quick_configs:
            self.select_quick_profile(self.quick_choice.currentData())
        self._owner_rows = {row['id']: row for row in owners}
        self._vehicle_rows = {row['id']: row for row in vehicles}
        self.identity.setText(f"{state['actor']} · {state['role']}   |   Owners {state['counts']['owners']} · Motorcycles {state['counts']['vehicles']} · Transactions {state['counts']['transactions']}")
        self.identity.setToolTip(f"Local registry: {state['database']}\nNo network or payment-provider requests. Confirmation is recorded manually by an assigned cashier.")
        self._choices(self.office_combo, [(json.loads(row['payload'])['office']['name'] + ' (' + row['code'] + ')', row['code']) for row in state['offices']])
        self._choices(self.stock_office, [(row['code'], row['code']) for row in state['offices']])
        owner_choices = [(row['name'] + ' · ' + (row['client_id'] or row['id'][:8]), row['id']) for row in owners]
        self._choices(self.vehicle_owner_combo, owner_choices)
        self._choices(self.transfer_combo, owner_choices)
        self._choices(self.vehicle_combo, [(f"{row['owner_name']} · {row['plate'] or row['mv_file'] or row['chassis']}", row['id']) for row in vehicles])
        self.fill_table(self.owner_table, owners, ['name', 'client_id', 'address'])
        self.fill_table(self.vehicle_table, vehicles, ['owner_name', 'plate', 'mv_file', 'chassis', 'expiry'])
        self.fill_table(self.transaction_table, transactions, ['number', 'name', 'plate', 'state', 'receipt_no'])
        self.fill_table(self.audit_table, audit, ['at', 'actor', 'action', 'record_id', 'details'])
        self.fill_table(self.history_table, history, ['legacy_id', 'plate', 'mv_file', 'paid_cents'])
        self.setup_summary.setPlainText(json.dumps({key: state[key] for key in ('counts', 'series', 'stock', 'operators')}, indent=2))
        can_edit = state['role'] in ('admin', 'operator')
        self.save_owner.setEnabled(can_edit)
        self.save_vehicle.setEnabled(can_edit and bool(owners))
        self.new_button.setEnabled(can_edit)
        self.create_button.setEnabled(can_edit and bool(vehicles) and bool(state['offices']))
        for button in (self.save_quick, self.save_config, self.save_stock, self.save_operator, self.backup_button, self.preview_migration):
            button.setEnabled(state['role'] == 'admin')
        if not state['offices']:
            self.notify('Choose an office profile on Defaults or ask your registry administrator to save one.')

    def show_draft(self) -> None:
        self.current_transaction = None
        self.draft_section.show()
        self.detail_section.hide()
        self.action_bar.hide()
        self.tabs.setCurrentIndex(0)

    def show_detail(self, detail: dict) -> None:
        self._detail = detail
        self.current_transaction = detail['id']
        self.draft_section.hide()
        self.detail_section.show()
        self.action_bar.show()
        self.detail_heading.setText(f"{detail['number']}\n{detail['kind'].title()} · {detail['state']}")
        assessment = detail['assessment'][0] if detail['assessment'] else None
        lines = json.loads(assessment['lines']) if assessment else []
        self.fill_table(self.assessment_table, lines, ['description', 'amount'])
        self.assessment_table.setMaximumHeight(max(120, min(270, len(lines) * 31 + 40)))
        payments = detail['payments']
        summary = []
        if assessment:
            summary.extend([f"Total: PHP {assessment['total_cents'] / 100:,.2f} · Rule version: {assessment['rule_version']}", assessment['validity']])
        summary.extend(f"{p['method']} · {p['reference']} · {p['status']}" for p in payments)
        self.payment_summary.setText('\n'.join(summary) if summary else 'Create an assessment to calculate fees and validity.')
        state = detail['state']
        edit = self._role in ('admin', 'operator')
        cashier = self._role in ('admin', 'cashier')
        allowed = {'assess': edit and state == 'Draft', 'manual_assessment': edit and state in ('Draft','Assessed'),
                   'record_payment': cashier and state == 'Assessed', 'confirm_payment': cashier and state == 'Payment Pending',
                   'issue': cashier and state == 'Payment Confirmed', 'view_receipt': state == 'Issued',
                   'export': state == 'Issued', 'void': self._role == 'admin' and state in ('Draft','Assessed','Payment Pending')}
        for key, button in self.actions.items():
            button.setEnabled(allowed[key])
            button.setVisible(allowed[key])
        self.fail_button.setEnabled(cashier and state == 'Payment Pending')
        self.fail_button.setVisible(cashier and state == 'Payment Pending')

    def notify(self, message: str, error: bool = False) -> None:
        self.message.setObjectName('workspaceError' if error else 'workspaceMessage')
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.message.setText(message)
        self.message.show()
        self.status_changed.emit(message)

    def payment_dialog(self, total: str) -> dict | None:
        dialog = QDialog(self)
        dialog.setWindowTitle('Record pending payment')
        layout = QVBoxLayout(dialog)
        info = QLabel('This creates a Pending payment. A cashier must separately confirm it against payment evidence; no provider lookup is performed.')
        info.setWordWrap(True)
        layout.addWidget(info)
        form = QFormLayout()
        method = QComboBox()
        method.setEditable(True)
        method.addItems(['Cash', 'GCash', 'Maya', 'Bank transfer', 'Card'])
        form.addRow('Payment method', method)
        reference = self.field(form, 'Payment / cashier reference')
        amount = self.field(form, 'Assessed amount (PHP)', total)
        amount.setReadOnly(True)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        interactions = FormInteractions(dialog)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return {'method': method.currentText(), 'reference': reference.text(), 'amount': amount.text()}

    def manual_assessment_dialog(self) -> dict | None:
        dialog = QDialog(self)
        dialog.setWindowTitle('Reasoned manual assessment')
        dialog.resize(560, 410)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Enter assessed charges; the saved rule version and reason remain in history.'))
        lines = json.loads(self._detail['assessment'][0]['lines']) if self._detail.get('assessment') else [{'description': '', 'amount': ''}]
        table = QTableWidget(len(lines), 2)
        table.setHorizontalHeaderLabels(['Description', 'Amount (PHP)'])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setItemDelegateForColumn(1, PaymentAmountDelegate(table))
        for row, item in enumerate(lines):
            table.setItem(row, 0, QTableWidgetItem(item['description']))
            table.setItem(row, 1, QTableWidgetItem(item['amount']))
        layout.addWidget(table)
        actions = QHBoxLayout()
        actions.addWidget(self.button('Add item', lambda: table.insertRow(table.rowCount()) if table.rowCount() < 8 else None))
        actions.addWidget(self.button('Remove selected', lambda: table.removeRow(table.currentRow()) if table.currentRow() >= 0 else None))
        layout.addLayout(actions)
        reason = QLineEdit()
        reason.setPlaceholderText('Assessment authority / correction reason (required)')
        layout.addWidget(reason)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        interactions = FormInteractions(dialog)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return {'lines': [(table.item(row,0).text() if table.item(row,0) else '', table.item(row,1).text() if table.item(row,1) else '') for row in range(table.rowCount())], 'reason': reason.text()}

    def prompt(self, title: str, text: str) -> str | None:
        value, accepted = QInputDialog.getText(self, title, text)
        return value if accepted else None

    def save_path(self, name: str, file_filter: str = 'PDF files (*.pdf)') -> str:
        return QFileDialog.getSaveFileName(self, 'Save local file', name, file_filter)[0]

    def choose_registry(self) -> str:
        return QFileDialog.getOpenFileName(self, 'Open an existing local registry', '', 'SQLite registry (*.db)')[0]

    def show_receipt(self, number: str, content: bytes) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle('Issued receipt ' + number)
        dialog.resize(700, 650)
        layout = QVBoxLayout(dialog)
        document = QPdfDocument(dialog)
        buffer = QBuffer(dialog)
        buffer.setData(content)
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        document.load(buffer)
        preview = PdfPreview()
        preview.set_document(document)
        layout.addWidget(preview)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()
        document.close()
