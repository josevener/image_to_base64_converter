"""LTO receipt input form and local PDF preview; generation is controller-owned."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QBuffer, QDate, QDateTime, QIODevice, Qt, Signal
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLayout, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
    QSpinBox, QVBoxLayout, QWidget,
)

from ui.components.tool_page import ToolPage
from ui.pdf_preview import PdfPreview
from ui.registration_suggestions import RegistrationSuggestionsDialog
from ui.receipt_form import FormInteractions, FormSection, PaymentAmountDelegate, ReceiptNoticeEdit
from services.lto_receipt_service import LATE_REGISTRATION_CHARGE


class LtoOfficialReceiptPage(ToolPage):
    preview_requested = Signal()
    export_requested = Signal()
    payment_changed = Signal()
    suggestions_requested = Signal()
    validity_requested = Signal()
    reset_completed = Signal()
    fresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.inputs: dict[str, QLineEdit | ReceiptNoticeEdit] = {}
        self.setObjectName("receiptForm")
        self.setStyleSheet("""
            #receiptForm #formSectionTitle { font-size: 15px; font-weight: 700; }
            #receiptForm #formSectionToggle { font-size: 14px; font-weight: 600; text-align: left; padding: 0; }
            #receiptForm QLineEdit, #receiptForm QComboBox, #receiptForm QSpinBox,
            #receiptForm QDateEdit, #receiptForm QDateTimeEdit { min-height: 22px; }
            #receiptForm QLineEdit:focus, #receiptForm QComboBox:focus,
            #receiptForm QAbstractSpinBox:focus, #receiptForm QPlainTextEdit:focus,
            #receiptForm QTableWidget:focus { border: 2px solid #2F80ED; }
            #receiptForm QPushButton { min-height: 20px; }
            #receiptForm QTabBar::tab { min-height: 20px; padding: 7px 10px; }
            #receiptForm #previewTotal { color: #2F80ED; font-size: 17px; font-weight: 700; }
            #receiptForm QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
            #receiptForm QScrollBar::handle:vertical { background: #8190A2; min-height: 32px; border-radius: 4px; }
            #receiptForm QScrollBar::add-line:vertical, #receiptForm QScrollBar::sub-line:vertical { height: 0; }
            #receiptForm QScrollBar::add-page:vertical, #receiptForm QScrollBar::sub-page:vertical { background: transparent; }
            #receiptForm #formError { color: #D94F4F; padding: 8px; border: 1px solid #D94F4F; border-radius: 6px; }
            #receiptForm #receiptTotal { font-size: 20px; font-weight: 700; padding: 8px 0; }
        """)
        layout = QVBoxLayout(self)
        title = QLabel("Official Receipt")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        note = QLabel("Enter payer, motorcycle, and office details. Generate the receipt data, preview, then export.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.entry_mode = QComboBox()
        self.entry_mode.addItem("Automated — generate fresh receipt data", "automated")
        self.entry_mode.addItem("Manual — enter or edit all receipt fields", "manual")
        layout.addWidget(self.entry_mode)
        self.generated_identifiers: dict[str, str] = {}
        self.document_label = ""
        self.error_banner = QLabel()
        self.error_banner.setObjectName("formError")
        self.error_banner.setWordWrap(True)
        self.error_banner.hide()
        layout.addWidget(self.error_banner)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        editor = QWidget()
        editor.setMinimumWidth(330)
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        self.quick_inputs: dict[str, QLineEdit] = {}
        self.quick_scroll = QScrollArea()
        self.quick_scroll.setWidgetResizable(True)
        quick_body = QWidget()
        quick_layout = QFormLayout(quick_body)
        quick_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        quick_layout.setContentsMargins(0, 8, 0, 8)
        quick_layout.setVerticalSpacing(14)
        quick_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        payer_form = self._section(quick_layout, "Received from", "Only enter the details below. No existing OR/CR or registry records are needed.")
        for key, label in (("payer", "Received from *"), ("address", "Recipient address *"),
                           ("client_id", "LTO Client ID / LTO Business ID *")):
            self._quick_field(payer_form, key, label)
        motorcycle = self._section(quick_layout, "Motorcycle", "Brand-new sample: the selected date anchors 3-year validity. A random plate is matched to the closest renewal window within that limit. Private motorcycle without sidecar, Gas, N/A aircon.")
        color, year = self._columns(motorcycle)
        self._quick_field(color, "color", "Color *")
        self._quick_field(year, "year_model", "Year model *")
        payment_quick = self._section(quick_layout, "Payment", "Starts with your PHP 948.00 payment template. Use Manual to edit payment items or other defaults.")
        self.quick_date_overridden = False
        self.quick_date = QDateTimeEdit(QDateTime.currentDateTime())
        self.quick_date.setDisplayFormat("MM/dd/yyyy h:mm AP")
        self.quick_date.setCalendarPopup(True)
        self.quick_date.setDateRange(QDate(1900, 1, 1), QDate(2096, 12, 31))
        self.quick_date.setToolTip("Defaults to the generation date. Edit to change the receipt and first-registration date; validity follows this date. Scrolling does not change it.")
        payment_quick.addRow("Receipt / first-registration date", self.quick_date)
        self.today_button = QPushButton("Use current date and time")
        self.today_button.setObjectName("secondaryButton")
        self.today_button.clicked.connect(self._use_current_receipt_date)
        payment_quick.addRow(self.today_button)
        self.use_tx_format = QCheckBox("Use TX-MVIRS transaction format")
        self.use_tx_format.setToolTip("Unchecked: MAIRD-SAR-YYYYMMDD-######. Checked: TX-MVIRS-YYYYMMDD-######.")
        payment_quick.addRow(self.use_tx_format)
        self.quick_payment_type = QComboBox()
        for label, value in (("Cash", "cash"), ("E-wallet", "ewallet"), ("Online payment", "online")):
            self.quick_payment_type.addItem(label, value)
        payment_quick.addRow("Payment type", self.quick_payment_type)
        self.quick_mode = QComboBox()
        self.quick_mode.setEditable(True)
        self.quick_mode.lineEdit().setMaxLength(60)
        self.quick_mode.addItems(["Cash", "GCash", "Maya", "Bank transfer", "Card"])
        payment_quick.addRow("Mode of payment *", self.quick_mode)
        self.quick_late_penalty = QCheckBox("Penalty Late Registration (+ PHP 120.00)")
        payment_quick.addRow(self.quick_late_penalty)
        self.quick_mode.currentTextChanged.connect(self._quick_method_changed)
        self.quick_payment_type.currentIndexChanged.connect(self._quick_payment_type_changed)
        issuing = self._section(quick_layout, "Issuing office", "Prefilled office details remain editable.")
        for key, label in (("office", "Field office *"), ("office_code", "Office code *"),
                           ("office_address", "Office address *")):
            self._quick_field(issuing, key, label)
        self._section(quick_layout, "Automatic QR", "Generated automatically from this receipt's references. The test link does not confirm issuance or payment.")
        generated = self._section(quick_layout, "Generated receipt data", "Random plates have exactly 6 characters, such as Q1723B or 681TZS. Numeric endings align to the selected date's renewal window within 3 years. Date edits update the transaction date and sample MV year, and may replace the plate. PDFs are labeled as sample data.")
        generated.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self.generated_summary = QLabel("Ready to generate: OR number, transaction, plate, MV file, payment date, validity, QR code, and barcode.")
        self.generated_summary.setWordWrap(True)
        self.generated_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        generated.addRow(self.generated_summary)
        self.quick_scroll.setWidget(quick_body)
        editor_layout.addWidget(self.quick_scroll)
        self.tabs = tabs = QTabWidget()
        tabs.setUsesScrollButtons(True)
        editor_layout.addWidget(tabs)

        receipt_root = self._tab(tabs, "Receipt")
        receipt = self._section(receipt_root, "Receipt details", "Required fields are marked *. All details stay on this device.")
        self._field(receipt, "receipt_no", "Official receipt number *", "e.g. 1396-000000580411")
        self.date = QDateTimeEdit(QDateTime.currentDateTime())
        self.date.setDisplayFormat("MM/dd/yyyy h:mm AP")
        self.date.setCalendarPopup(True)
        receipt.addRow("Payment date and time", self.date)
        payer = self._section(receipt_root, "Paid by")
        self._field(payer, "payer", "Full name *", "Last name, First name Middle name")
        self._field(payer, "address", "Address *", "House / street, barangay, city, postal code, province")
        self._field(payer, "client_id", "LTO client / business ID", "Copy from the existing record")
        self._field(payer, "payer_tin", "Payer TIN (optional)")
        office = self._section(receipt_root, "Issuing office")
        self._field(office, "office", "Field office *", "e.g. VALENZUELA DISTRICT OFFICE")
        self._field(office, "office_address", "Office address")
        office_left, office_right = self._columns(office)
        self._field(office_left, "office_code", "Office code")
        self._field(office_right, "office_tin", "Office TIN")

        vehicle_root = self._tab(tabs, "Vehicle")
        vehicle = self._section(vehicle_root, "Vehicle identifiers", "Enter the plate if assigned. Otherwise, enter the MV file number.")
        for key, label in (("transaction_no", "Transaction number *"), ("plate_no", "Plate number"),
                           ("file_no", "MV file number")):
            self._field(vehicle, key, label)
        color_form, year_form = self._columns(vehicle)
        self._field(color_form, "color", "Color")
        self._field(year_form, "year_model", "Year model")
        specifications = self._section(vehicle_root, "Change vehicle specifications", "Defaults: private motorcycle without sidecar, Gas, N/A aircon.", collapsible=True)
        for key, label in (("classification", "Classification"), ("vehicle_type", "Vehicle type"),
                           ("fuel_type", "Fuel type"), ("aircon_type", "Aircon type")):
            self._field(specifications, key, label)

        registration_root = self._tab(tabs, "Validity")
        registration = self._section(registration_root, "What is this receipt for?", "This tab controls the validity and renewal sentence printed on the receipt.")
        self.registration_form = registration
        self.transaction = QComboBox()
        for label, value in (("Renew an existing registration", "renewal"), ("Register a brand-new motorcycle", "initial"),
                             ("Transfer an existing registration", "transfer")):
            self.transaction.addItem(label, value)
        registration.addRow("Registration task", self.transaction)
        self.registration_help = QLabel()
        self.registration_help.setWordWrap(True)
        self.registration_help.setObjectName("muted")
        registration.addRow(self.registration_help)
        self.auto_validity = QCheckBox("Calculate the receipt notice automatically")
        self.auto_validity.setChecked(True)
        registration.addRow(self.auto_validity)
        self.renewal_year = QSpinBox()
        self.renewal_year.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.renewal_year.setRange(1900, 2100)
        self.renewal_year.setValue(QDate.currentDate().year())
        registration.addRow("Year being renewed", self.renewal_year)
        self.year_help = QLabel()
        self.year_help.setWordWrap(True)
        self.year_help.setObjectName("muted")
        registration.addRow(self.year_help)

        self.initial_section = FormSection("Brand-new registration", "Starts with a 3-year validity period. Enter the first registration date; the first renewal year is calculated for you.")
        registration_root.addRow(self.initial_section)
        initial = self.initial_section.form
        self.initial_known = QCheckBox()
        self.initial_known.hide()
        self.initial_date = QDateEdit(QDate.currentDate())
        self.initial_date.setCalendarPopup(True)
        self.initial_date.setDisplayFormat("MM/dd/yyyy")
        initial.addRow("First registration date", self.initial_date)
        self.initial_years = QComboBox()
        for years in (3, 1, 5):
            self.initial_years.addItem("3 years (default)" if years == 3 else f"{years} year(s)", years)
        initial.addRow("Registration is valid for", self.initial_years)
        self.auto_initial_year = QCheckBox("Calculate the first renewal year for me")
        self.auto_initial_year.setChecked(True)
        initial.addRow(self.auto_initial_year)
        alignment_help = QLabel("The receipt uses the plate's renewal month and week in that year. If the OR/CR specifies different dates, use those confirmed dates instead.")
        alignment_help.setObjectName("muted")
        alignment_help.setWordWrap(True)
        initial.addRow(alignment_help)

        self.file_section = FormSection("No assigned plate yet?", "For an MV file-only record, copy the next renewal dates from OR/CR. The file digits do not determine this schedule.")
        registration_root.addRow(self.file_section)
        file_form = self.file_section.form
        self.file_dates_known = QCheckBox("I have the next renewal dates from OR/CR")
        file_form.addRow(self.file_dates_known)
        self.file_window_start = QDateEdit(QDate.currentDate())
        self.file_window_end = QDateEdit(QDate.currentDate())
        for label, control in (("Next renewal starts", self.file_window_start), ("Next renewal ends", self.file_window_end)):
            control.setCalendarPopup(True)
            control.setDisplayFormat("MM/dd/yyyy")
            control.setEnabled(False)
            self.file_dates_known.toggled.connect(control.setEnabled)
            file_form.addRow(label, control)

        self.previous_section = FormSection("Existing registration expiry", "Use the expiry printed on the current OR/CR.")
        registration_root.addRow(self.previous_section)
        previous = self.previous_section.form
        self.expiry_known = QCheckBox("I have the previous expiry date")
        previous.addRow(self.expiry_known)
        self.previous_expiry = QDateEdit(QDate.currentDate())
        self.previous_expiry.setCalendarPopup(True)
        self.previous_expiry.setDisplayFormat("MM/dd/yyyy")
        self.previous_expiry.setEnabled(False)
        self.expiry_known.toggled.connect(self.previous_expiry.setEnabled)
        previous.addRow("Current / previous expiry", self.previous_expiry)

        notice = self._section(registration_root, "Notice on your receipt", "Updates as you change the plate and registration inputs. Uncheck automatic calculation above to edit it yourself.")
        self._field(notice, "validity", "Validity and next renewal")
        self.inputs["validity"].setReadOnly(True)
        self.auto_validity.toggled.connect(lambda checked: self.inputs["validity"].setReadOnly(checked))
        self.validity_hint = QLabel()
        self.validity_hint.setWordWrap(True)
        self.validity_hint.setObjectName("muted")
        notice.addRow(self.validity_hint)

        self.estimate_section = FormSection("Optional: estimate registration fees", "Skip this if you already have assessed amounts. Your payment items stay unchanged until you review and apply an estimate.", collapsible=True)
        registration_root.addRow(self.estimate_section)
        estimates = self.estimate_section.form
        self.engine_cc = QSpinBox()
        self.engine_cc.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.engine_cc.setRange(0, 3000)
        self.engine_cc.setSpecialValueText("Enter engine displacement")
        self.engine_cc.setSuffix(" cc")
        estimates.addRow("Engine size (cc)", self.engine_cc)
        self.mvuc = QLineEdit("240.00")
        self.mvuc.setMaxLength(20)
        estimates.addRow("Annual MVUC rate (PHP)", self.mvuc)
        self.penalty_policy = QComboBox()
        for label, value in (("Leave late fees for manual assessment", "unconfirmed"),
                             ("Exemption / grace period confirmed", "exempt"),
                             ("50% rule confirmed; no exemption", "standard")):
            self.penalty_policy.addItem(label, value)
        estimates.addRow("How should late fees be estimated?", self.penalty_policy)
        assumptions = QLabel("For private motorcycles without sidecars. PHP 240 is an editable starting estimate. Confirm current rates and validity. Receipt date is used as payment date. Extensions and holidays need manual review.")
        assumptions.setWordWrap(True)
        estimates.addRow(assumptions)
        calculate = QPushButton("Review estimated fees")
        calculate.clicked.connect(lambda: self.suggestions_requested.emit())
        estimates.addRow(calculate)

        payment_root = self._tab(tabs, "Payment")
        payment = self._section(payment_root, "Payment method", "Online payments print the method and location '-'. Cash payments also include cashier and POS details.")
        self.payment_channel = QComboBox()
        self.payment_channel.addItem("Cash payment", "cash")
        self.payment_channel.addItem("Online payment", "online")
        self.mode = QComboBox()
        self.mode.setEditable(True)
        self.mode.addItems(["Cash", "GCash", "Maya", "Bank transfer", "Card"])
        channel_form, mode_form = self._columns(payment)
        channel_form.addRow("Payment type", self.payment_channel)
        mode_form.addRow("Payment method", self.mode)
        self.cash_section = FormSection("Cash collection details")
        payment_root.addRow(self.cash_section)
        for key, label in (("location", "Location"), ("cashier", "Cashier"), ("pos_machine", "POS machine")):
            self._field(self.cash_section.form, key, label)
        payment = self._section(payment_root, "Payment breakdown", "Double-click a description or amount to edit it. Up to 8 items; amounts are in PHP.")
        self.charges = QTableWidget(1, 2)
        self.charges.setHorizontalHeaderLabels(["Description", "Amount (PHP)"])
        self.charges.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.charges.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.charges.setMinimumHeight(220)
        self.charges.verticalHeader().setDefaultSectionSize(34)
        self.charges.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.charges.setAlternatingRowColors(True)
        self.charges.setItemDelegateForColumn(1, PaymentAmountDelegate(self.charges))
        self.charges.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        self.charges.setToolTip("Double-click a cell or press F2 to edit. Tab moves to the next cell.")
        payment.addRow(self.charges)
        self.late_penalty = QCheckBox("Penalty Late Registration (+ PHP 120.00)")
        payment.addRow(self.late_penalty)
        self.quick_late_penalty.toggled.connect(self._toggle_late_penalty)
        self.late_penalty.toggled.connect(self._toggle_late_penalty)
        rows = QHBoxLayout()
        rows.setSpacing(8)
        self.add_item_button = add = QPushButton("+ Add item")
        add.setObjectName("secondaryButton")
        add.clicked.connect(self.add_item)
        self.remove_item_button = remove = QPushButton("Remove selected row")
        remove.setObjectName("secondaryButton")
        remove.clicked.connect(self.remove_item)
        rows.addWidget(add)
        rows.addWidget(remove)
        payment.addRow(rows)
        self.total = QLabel("Total: PHP 0.00")
        self.total.setObjectName("receiptTotal")
        payment.addRow(self.total)
        self.charges.itemChanged.connect(self._update_total)
        self.charges.currentCellChanged.connect(self._update_payment_actions)

        codes_root = self._tab(tabs, "QR")
        codes = self._section(codes_root, "What should the QR code contain?", "Custom text with automatic sizing is the default. The barcode always uses the transaction number from Vehicle.")
        self.qr_mode = QComboBox()
        for label, value in (("Receipt number", "reference"), ("Receipt summary (JSON)", "summary"),
                             ("Custom text (default)", "text"), ("Existing URL", "url")):
            self.qr_mode.addItem(label, value)
        self.qr_mode.setCurrentIndex(self.qr_mode.findData("text"))
        codes.addRow("QR Code Model 2 payload", self.qr_mode)
        self.qr_text = QLineEdit()
        self.qr_text.setMaxLength(300)
        self.qr_text.setEnabled(True)
        self.qr_text.setPlaceholderText("Custom text or existing URL; max 300 UTF-8 bytes")
        codes.addRow("QR payload", self.qr_text)
        self.qr_mode.currentIndexChanged.connect(
            lambda: self.qr_text.setEnabled(self.qr_mode.currentData() in ("text", "url")))
        codes = self._section(codes_root, "Advanced QR settings", "Automatic sizing fits your data. Choose Version 8 only when you need the sample's 49 × 49 format.", collapsible=True)
        self.qr_level = QComboBox()
        self.qr_level.addItems(["L", "M", "Q", "H"])
        self.qr_level.setCurrentText("M")
        codes.addRow("QR error correction", self.qr_level)
        self.qr_version = QComboBox()
        self.qr_version.addItem("Version 8 - 49 x 49 modules (sample format)", "8")
        self.qr_version.addItem("Automatic sizing", "auto")
        self.qr_version.setCurrentIndex(self.qr_version.findData("auto"))
        codes.addRow("QR format", self.qr_version)
        code_note = QLabel("Version 8 matches the sample's module count. The black/white pattern depends on the payload and correction level. Summary includes receipt number, plate, and total only. URLs are never fetched. Code 128 encodes the transaction number. These settings do not create LTO verification data.")
        code_note.setWordWrap(True)
        codes.addRow(code_note)

        navigation = QHBoxLayout()
        self.back_button = QPushButton("Back")
        self.back_button.setObjectName("secondaryButton")
        self.back_button.clicked.connect(lambda: tabs.setCurrentIndex(max(0, tabs.currentIndex() - 1)))
        self.step_label = QLabel()
        self.step_label.setObjectName("muted")
        self.next_button = QPushButton()
        self.next_button.setObjectName("secondaryButton")
        self.next_button.clicked.connect(lambda: tabs.setCurrentIndex(min(tabs.count() - 1, tabs.currentIndex() + 1)))
        navigation.addWidget(self.back_button)
        navigation.addWidget(self.step_label, 1, Qt.AlignmentFlag.AlignCenter)
        navigation.addWidget(self.next_button)
        editor_layout.addLayout(navigation)
        self.navigation = navigation
        actions = QHBoxLayout()
        self.fresh_button = QPushButton("Generate fresh receipt")
        self.fresh_button.clicked.connect(lambda: self.fresh_requested.emit())
        editor_layout.addWidget(self.fresh_button)
        preview = QPushButton("Preview PDF")
        preview.setObjectName("secondaryButton")
        preview.clicked.connect(lambda: self.preview_requested.emit())
        export = QPushButton("Export PDF")
        export.clicked.connect(lambda: self.export_requested.emit())
        reset = QPushButton("Reset form")
        reset.setObjectName("secondaryButton")
        reset.clicked.connect(self.reset_form)
        for button in (preview, export, reset):
            actions.addWidget(button)
        editor_layout.addLayout(actions)
        splitter.addWidget(editor)
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_header = QHBoxLayout()
        preview_heading = QLabel("Receipt preview")
        preview_heading.setObjectName("formSectionTitle")
        preview_header.addWidget(preview_heading, 1)
        self.preview_total = QLabel("PHP 0.00")
        self.preview_total.setObjectName("previewTotal")
        self.preview_total.setToolTip("Total of the current payment items. Refresh Preview PDF after editing.")
        preview_header.addWidget(self.preview_total)
        preview_layout.addLayout(preview_header)
        self.preview_label = QLabel("PDF preview will appear here after you enter the required fields.")
        self.preview_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_label)
        self.document = QPdfDocument(self)
        self.pdf_view = PdfPreview()
        preview_layout.addWidget(self.pdf_view, 1)
        splitter.addWidget(preview_panel)
        splitter.setSizes([460, 480])
        layout.addWidget(splitter, 1)
        footer = QLabel("Local PDF export · Your entries are not saved after closing the app. Required fields are marked *.")
        footer.setObjectName("muted")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        for field in self.inputs.values():
            field.textChanged.connect(self._mark_stale)
        self.date.dateTimeChanged.connect(self._mark_stale)
        self.mode.currentTextChanged.connect(self._mark_stale)
        self.charges.itemChanged.connect(self._mark_stale)
        self.qr_mode.currentIndexChanged.connect(self._mark_stale)
        self.qr_text.textChanged.connect(self._mark_stale)
        self.qr_level.currentIndexChanged.connect(self._mark_stale)
        self.qr_version.currentIndexChanged.connect(self._mark_stale)
        self.inputs["plate_no"].textChanged.connect(lambda *_: self.validity_requested.emit())
        self.inputs["file_no"].textChanged.connect(lambda *_: self.validity_requested.emit())
        self.auto_validity.toggled.connect(lambda *_: self.validity_requested.emit())
        for control in (self.transaction, self.initial_years):
            control.currentIndexChanged.connect(lambda *_: self.validity_requested.emit())
        for control in (self.initial_date, self.previous_expiry, self.file_window_start, self.file_window_end):
            control.dateChanged.connect(lambda *_: self.validity_requested.emit())
        for control in (self.initial_known, self.expiry_known, self.file_dates_known):
            control.toggled.connect(lambda *_: self.validity_requested.emit())
        self.renewal_year.valueChanged.connect(lambda *_: self.validity_requested.emit())
        self.date.dateTimeChanged.connect(self._receipt_date_changed)
        self.payment_channel.currentIndexChanged.connect(self._payment_type_changed)
        self._payment_type_changed()
        self.transaction.currentIndexChanged.connect(self._registration_task_changed)
        self.inputs["plate_no"].textChanged.connect(self._refresh_registration)
        self.auto_validity.toggled.connect(self._refresh_registration)
        self.renewal_year.valueChanged.connect(self._refresh_registration)
        self.estimate_section.expanded_changed.connect(self._refresh_registration)
        tabs.currentChanged.connect(self._tab_changed)
        self._registration_task_changed()
        self._tab_changed()
        self._update_payment_actions()
        self._enhance_controls()
        self._interactions = FormInteractions(self)
        self.auto_initial_year.toggled.connect(self._refresh_registration)
        self.auto_initial_year.toggled.connect(lambda *_: self.validity_requested.emit())
        self.initial_years.currentIndexChanged.connect(self._refresh_registration)
        self.entry_mode.currentIndexChanged.connect(self._entry_mode_changed)
        self.quick_date.dateTimeChanged.connect(self._quick_date_changed)
        self.use_tx_format.toggled.connect(self._transaction_format_changed)
        self._entry_mode_changed()

    def _quick_field(self, form: QFormLayout, key: str, label: str) -> None:
        field = QLineEdit()
        field.setMaxLength(180 if key == "address" else 100)
        field.setClearButtonEnabled(True)
        field.setAccessibleName(label.replace("*", "").strip())
        field.textChanged.connect(self._mark_stale)
        self.quick_inputs[key] = field
        form.addRow(label, field)

    def automated(self) -> bool:
        return self.entry_mode.currentData() == "automated"

    def _transaction_format_changed(self) -> None:
        if self.automated():
            self.validity_requested.emit()
        self._mark_stale()

    def _entry_mode_changed(self) -> None:
        automatic = self.automated()
        if automatic:
            self.sync_automation_inputs()
        else:
            for key, field in self.quick_inputs.items():
                self.inputs[key].setText(field.text())
            online = self.quick_mode.currentText().strip().casefold() != "cash"
            self.payment_channel.setCurrentIndex(1 if online else 0)
            self.mode.setCurrentText(self.quick_mode.currentText())
            self.date.setDateTime(self.quick_date.dateTime())
        self.quick_scroll.setVisible(automatic)
        self.tabs.setVisible(not automatic)
        self.fresh_button.setVisible(automatic)
        for control in (self.back_button, self.step_label, self.next_button):
            control.setVisible(not automatic)
        if not automatic:
            self._tab_changed()
        self._mark_stale()

    def sync_automation_inputs(self) -> None:
        for key, field in self.quick_inputs.items():
            field.setText(self.inputs[key].text())
        method = self.mode.currentText()
        kind = "cash" if method.casefold() == "cash" else "ewallet" if method in ("GCash", "Maya", "GrabPay", "ShopeePay") else "online"
        self.quick_payment_type.setCurrentIndex(self.quick_payment_type.findData(kind))
        self.quick_mode.setCurrentText(method)
        self._quick_payment_type_changed(preserve=True)
        if self.quick_date.dateTime() != self.date.dateTime():
            self.quick_date_overridden = True
        self.quick_date.blockSignals(True)
        self.quick_date.setDateTime(self.date.dateTime())
        self.quick_date.blockSignals(False)

    def _quick_date_changed(self) -> None:
        self.quick_date_overridden = True
        if self.automated():
            self.date.setDateTime(self.quick_date.dateTime())
            self.initial_date.setDate(self.quick_date.date())
        self._mark_stale()

    def _use_current_receipt_date(self) -> None:
        self.quick_date.setDateTime(QDateTime.currentDateTime())
        self.quick_date_overridden = False

    def automation_datetime(self, fresh: bool) -> datetime:
        if fresh and not self.quick_date_overridden:
            self.quick_date.blockSignals(True)
            self.quick_date.setDateTime(QDateTime.currentDateTime())
            self.quick_date.blockSignals(False)
        return self.quick_date.dateTime().toPython()

    def _quick_payment_type_changed(self, *_args, preserve: bool = False) -> None:
        kind = self.quick_payment_type.currentData()
        choices = {"cash": ["Cash"], "ewallet": ["GCash", "Maya", "GrabPay", "ShopeePay"],
                   "online": ["Bank transfer", "Credit / debit card", "Online banking", "Other online payment"]}[kind]
        previous = self.quick_mode.currentText()
        self.quick_mode.blockSignals(True)
        try:
            self.quick_mode.clear()
            self.quick_mode.addItems(choices)
            if previous in choices or (preserve and kind != "cash"):
                self.quick_mode.setCurrentText(previous)
            self.quick_mode.setEnabled(kind != "cash")
        finally:
            self.quick_mode.blockSignals(False)
        self._mark_stale()

    def _quick_method_changed(self) -> None:
        method = self.quick_mode.currentText().strip()
        kind = ("cash" if method.casefold() == "cash" else "ewallet"
                if method in ("GCash", "Maya", "GrabPay", "ShopeePay")
                else "online" if self.quick_payment_type.currentData() == "cash"
                else self.quick_payment_type.currentData())
        changed = self.quick_payment_type.currentData() != kind
        self.quick_payment_type.blockSignals(True)
        self.quick_payment_type.setCurrentIndex(self.quick_payment_type.findData(kind))
        self.quick_payment_type.blockSignals(False)
        self.quick_mode.setEnabled(kind != "cash")
        if changed:
            self._quick_payment_type_changed(preserve=True)
        self._mark_stale()

    def automation_values(self) -> dict[str, str]:
        return {**{key: field.text().strip() for key, field in self.quick_inputs.items()},
                "payment_mode": self.quick_mode.currentText().strip()}

    def apply_automated_fields(self, fields: dict[str, str]) -> None:
        for key, value in fields.items():
            if key in self.inputs:
                self.inputs[key].setText(value)
        self.document_label = fields["document_label"]
        self.date.setDateTime(QDateTime.fromString(fields["date"], "MM/dd/yyyy hh:mm AP"))
        self.transaction.setCurrentIndex(self.transaction.findData("initial"))
        self.initial_date.setDate(self.date.date())
        self.initial_known.setChecked(True)
        self.initial_years.setCurrentIndex(self.initial_years.findData(3))
        self.auto_initial_year.setChecked(True)
        self.auto_validity.setChecked(True)
        self.payment_channel.setCurrentIndex(1 if fields["payment_channel"] == "online" else 0)
        self.mode.setCurrentText(fields["payment_mode"])

    def show_generated_summary(self) -> None:
        fields, _ = self.values()
        self.generated_summary.setText("\n".join((
            f"OR: {fields['receipt_no']}", f"Transaction: {fields['transaction_no']}",
            f"Plate: {fields['plate_no']}", f"MV file: {fields['file_no']}",
            f"Payment date: {fields['date']}", fields["validity"],
        )))
        # QFormLayout can retain the previous two-line row height inside a scroll area.
        self.generated_summary.setMinimumHeight(
            self.generated_summary.heightForWidth(max(200, self.generated_summary.width())))

    def _enhance_controls(self) -> None:
        hints = {
            "transaction_no": "e.g. MAIRD-SAR-20260423-023232",
            "plate_no": "e.g. Q1723B — leave blank if not assigned",
            "file_no": "15 digits, e.g. 133626007554490",
            "color": "e.g. WHITE or LIGHT GRAY", "year_model": "e.g. 2026",
            "office_code": "e.g. 1336", "office_address": "Street and city of the issuing office",
            "cashier": "Cashier name shown on the receipt", "location": "Cash collection office",
            "pos_machine": "Cashier station / POS identifier",
        }
        for key, widget in self.inputs.items():
            if isinstance(widget, QLineEdit):
                widget.setClearButtonEnabled(True)
            if key in hints:
                widget.setPlaceholderText(hints[key])
        for form in self.findChildren(QFormLayout):
            for row in range(form.rowCount()):
                label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                field_item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                label = label_item.widget() if label_item else None
                field = field_item.widget() if field_item else None
                if isinstance(label, QLabel) and field is not None:
                    label.setBuddy(field)
                    field.setAccessibleName(label.text().replace("*", "").strip())
        self.date.setToolTip("Type the payment date/time or choose a date from the calendar. Scrolling never changes this value.")
        self.renewal_year.setToolTip("Type the registration year. Use keyboard arrows to adjust deliberately; scrolling moves the form.")
        self.inputs["validity"].setToolTip("Calculated when automatic mode is on. Turn off automatic calculation above to edit this notice.")
        self.mode.lineEdit().setMaxLength(60)
        self.tabs.setTabToolTip(0, "Receipt number, payer, and issuing office")
        self.tabs.setTabToolTip(1, "Vehicle identifiers and specifications")
        self.tabs.setTabToolTip(2, "Registration validity and next renewal dates")
        self.tabs.setTabToolTip(3, "Payment method, itemized charges, and total")
        self.tabs.setTabToolTip(4, "QR content and advanced settings")

    def set_total(self, amount: str | None) -> None:
        self.total.setText(f"Total: PHP {amount}" if amount is not None else "Check payment amounts")
        self.preview_total.setText(f"PHP {amount}" if amount is not None else "Check amounts")

    def _payment_type_changed(self) -> None:
        online = self.payment_channel.currentData() == "online"
        self.mode.setEnabled(online)
        if not online:
            self.mode.setCurrentText("Cash")
        elif self.mode.currentText().strip().casefold() == "cash":
            self.mode.setCurrentText("GCash")
        for key in ("location", "cashier", "pos_machine"):
            self.inputs[key].setEnabled(not online)
        self.cash_section.setVisible(not online)
        self._mark_stale()

    def _registration_task_changed(self) -> None:
        task = self.transaction.currentData()
        if task == "initial" and not self.initial_known.isChecked():
            self.initial_date.setDate(self.date.date())
        self.initial_known.setChecked(task == "initial")
        if task == "transfer":
            self.expiry_known.setChecked(True)
        self._refresh_registration()
        self.validity_requested.emit()

    def show_initial_renewal_year(self, year: int) -> None:
        self.renewal_year.blockSignals(True)
        try:
            self.renewal_year.setValue(year)
        finally:
            self.renewal_year.blockSignals(False)
        self._refresh_registration()

    def _refresh_registration(self) -> None:
        task = self.transaction.currentData()
        automatic = self.auto_validity.isChecked()
        has_plate = bool(self.inputs["plate_no"].text().strip())
        descriptions = {
            "renewal": "For a motorcycle already registered. Change the year only if this receipt covers a different registration year.",
            "initial": "Brand-new motorcycle: enter its first registration date below. We use 3 years by default and calculate its first plate-based renewal.",
            "transfer": "Transfer: keep the expiry on the existing registration. Enter that expiry and the year of the next renewal.",
        }
        self.registration_help.setText(descriptions[task])
        automatic_year = task == "initial" and self.auto_initial_year.isChecked()
        self.renewal_year.setReadOnly(automatic_year)
        year_label = {"renewal": "Registration year covered by this payment", "initial": "First renewal year (calculated)" if automatic_year else "First renewal year (manual)", "transfer": "Next renewal year"}[task]
        self.registration_form.labelForField(self.renewal_year).setText(year_label)
        year = self.renewal_year.value()
        if task == "renewal":
            self.year_help.setText(f"Paying for {year} → next plate-based renewal in {year + 1}.")
        elif task == "initial":
            self.year_help.setText(f"{self.initial_years.currentData()}-year template → first renewal in {year}. The plate determines the month and week.")
        else:
            self.year_help.setText("Use the renewal year shown on the registration record.")
        estimating = self.estimate_section.expanded() and task != "transfer"
        self.registration_form.setRowVisible(self.renewal_year, (automatic or estimating) and has_plate)
        self.year_help.setVisible((automatic or estimating) and has_plate)
        self.initial_section.setVisible((automatic or estimating) and task == "initial")
        self.file_section.setVisible(automatic and not has_plate)
        self.previous_section.setVisible((automatic and task == "transfer") or (task == "renewal" and estimating))
        self.previous_section.form.setRowVisible(self.expiry_known, task != "transfer")
        self.estimate_section.setVisible(task != "transfer")
        self.estimate_section.form.setRowVisible(self.penalty_policy, task == "renewal")

    def _tab_changed(self) -> None:
        index = self.tabs.currentIndex()
        self.back_button.setEnabled(index > 0)
        self.next_button.setVisible(index < self.tabs.count() - 1)
        if index < self.tabs.count() - 1:
            self.next_button.setText("Next: " + self.tabs.tabText(index + 1))
        self.step_label.setText(f"{index + 1} / {self.tabs.count()}")

    @staticmethod
    def _section(parent: QFormLayout, title: str, description: str = "", collapsible: bool = False) -> QFormLayout:
        section = FormSection(title, description, collapsible)
        parent.addRow(section)
        return section.form

    @staticmethod
    def _columns(parent: QFormLayout) -> tuple[QFormLayout, QFormLayout]:
        pair = QWidget()
        pair.setObjectName("formSectionBody")
        row = QHBoxLayout(pair)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        forms = []
        for _ in range(2):
            column = QWidget()
            column.setObjectName("formSectionBody")
            form = QFormLayout(column)
            form.setContentsMargins(0, 0, 0, 0)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            row.addWidget(column, 1)
            forms.append(form)
        parent.addRow(pair)
        return forms[0], forms[1]

    def _tab(self, tabs: QTabWidget, name: str) -> QFormLayout:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(0, 8, 0, 8)
        form.setVerticalSpacing(14)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        scroll.setWidget(content)
        tabs.addTab(scroll, name)
        return form

    def _field(self, form: QFormLayout, key: str, label: str, placeholder: str = "") -> None:
        field = ReceiptNoticeEdit() if key == "validity" else QLineEdit()
        if isinstance(field, QLineEdit):
            field.setMaxLength(180 if key == "address" else 100)
        field.setPlaceholderText(placeholder)
        self.inputs[key] = field
        form.addRow(label, field)

    def values(self) -> tuple[dict[str, str], list[tuple[str, str]]]:
        fields = {key: field.text().strip() for key, field in self.inputs.items()}
        if self.document_label:
            fields["document_label"] = self.document_label
        fields["date"] = self.date.dateTime().toString("MM/dd/yyyy h:mm AP")
        fields["payment_mode"] = self.mode.currentText().strip()
        fields["payment_channel"] = self.payment_channel.currentData()
        if fields["payment_channel"] == "online":
            fields["location"] = "-"
            fields["cashier"] = ""
            fields["pos_machine"] = ""
        fields["qr_mode"] = self.qr_mode.currentData()
        fields["qr_payload"] = self.qr_text.text().strip()
        fields["qr_level"] = self.qr_level.currentText()
        fields["qr_version"] = self.qr_version.currentData()
        if self.automated():
            fields.update(qr_mode="automated", qr_payload="", qr_version="auto", qr_level="M")
        rows = []
        for row in range(self.charges.rowCount()):
            description = self.charges.item(row, 0)
            amount = self.charges.item(row, 1)
            rows.append((description.text().strip() if description else "",
                         amount.text().strip() if amount else ""))
        return fields, rows

    def add_item(self) -> None:
        if self.charges.rowCount() < 8:
            row = self.charges.rowCount()
            self.charges.insertRow(row)
            self.charges.setItem(row, 0, QTableWidgetItem(""))
            self.charges.setItem(row, 1, QTableWidgetItem(""))
            self.charges.setCurrentCell(row, 0)
            self.charges.editItem(self.charges.item(row, 0))
            self._mark_stale()
            self._update_payment_actions()

    def remove_item(self) -> None:
        row = self.charges.currentRow()
        if row >= 0:
            self.charges.removeRow(row)
            self._update_total()
            self._mark_stale()
            self._update_payment_actions()

    def _update_payment_actions(self) -> None:
        self._sync_late_penalty()
        self.add_item_button.setEnabled(self.charges.rowCount() < 8)
        self.remove_item_button.setEnabled(self.charges.currentRow() >= 0)

    def _update_total(self) -> None:
        self._sync_late_penalty()
        self.payment_changed.emit()

    def _late_penalty_rows(self) -> list[int]:
        return [row for row in range(self.charges.rowCount())
                if self.charges.item(row, 0) is not None
                and self.charges.item(row, 0).text().strip().casefold()
                == LATE_REGISTRATION_CHARGE.description.casefold()]

    def _sync_late_penalty(self) -> None:
        present = bool(self._late_penalty_rows())
        for checkbox in (self.quick_late_penalty, self.late_penalty):
            blocked = checkbox.blockSignals(True)
            checkbox.setChecked(present)
            checkbox.blockSignals(blocked)

    def _toggle_late_penalty(self, enabled: bool) -> None:
        rows = self._late_penalty_rows()
        if enabled and not rows and self.charges.rowCount() >= 8:
            self._sync_late_penalty()
            self.show_error("Remove a payment item before adding the late-registration penalty (maximum 8 items).")
            return
        blocked = self.charges.blockSignals(True)
        try:
            if enabled and not rows:
                # Place the optional penalty immediately after MVUC in the default breakdown.
                row = next((i + 1 for i in range(self.charges.rowCount())
                            if self.charges.item(i, 0) is not None
                            and self.charges.item(i, 0).text().strip().casefold() == "mvuc"),
                           self.charges.rowCount())
                self.charges.insertRow(row)
                self.charges.setItem(row, 0, QTableWidgetItem(LATE_REGISTRATION_CHARGE.description))
                self.charges.setItem(row, 1, QTableWidgetItem(f"{LATE_REGISTRATION_CHARGE.amount:.2f}"))
            elif not enabled:
                for row in reversed(rows):
                    self.charges.removeRow(row)
        finally:
            self.charges.blockSignals(blocked)
        self._update_payment_actions()
        self._update_total()
        self._mark_stale()

    def _mark_stale(self) -> None:
        self.preview_label.setText("Input changed. Select Preview PDF to refresh the receipt.")
        self.error_banner.hide()

    def display_preview(self, content: bytes, total: str) -> None:
        self.pdf_view.set_document(None)
        self.document.close()
        if hasattr(self, "_preview_buffer"):
            self._preview_buffer.close()
            self._preview_buffer.deleteLater()
        self._preview_buffer = QBuffer(self)
        self._preview_buffer.setData(content)
        self._preview_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.document.load(self._preview_buffer)
        if self.document.error() != QPdfDocument.Error.None_:
            raise ValueError("Qt could not load the PDF preview.")
        self.pdf_view.set_document(self.document)
        self.set_total(total)
        self.preview_label.setText("Current receipt preview • A4 • 1 page")

    def export_path(self, suggested_name: str = "official_receipt.pdf") -> str:
        path, _ = QFileDialog.getSaveFileName(self, "Export Official Receipt", suggested_name, "PDF files (*.pdf)")
        if path and not path.lower().endswith(".pdf"):
            path += ".pdf"
        return path

    def show_error(self, message: str) -> None:
        self.error_banner.setText(message)
        self.error_banner.show()
        if self.automated():
            return
        for prefix, key, tab in (("Receipt number", "receipt_no", 0), ("Received from", "payer", 0),
                                 ("Address", "address", 0), ("Field office", "office", 0),
                                 ("Transaction number", "transaction_no", 1)):
            if message.startswith(prefix):
                self.tabs.setCurrentIndex(tab)
                self.inputs[key].setFocus()
                break

    def reset_form(self) -> None:
        if QMessageBox.question(self, "Reset receipt", "Clear all entered receipt details?") != QMessageBox.StandardButton.Yes:
            return
        for field in self.inputs.values():
            field.clear()
        self.generated_identifiers.clear()
        self.use_tx_format.setChecked(False)
        self.document_label = ""
        self.date.setDateTime(QDateTime.currentDateTime())
        self.mode.setCurrentIndex(0)
        self.payment_channel.setCurrentIndex(0)
        self.charges.clearContents()
        self.charges.setRowCount(1)
        self.pdf_view.set_document(None)
        self.document.close()
        self.set_total("0.00")
        self.preview_label.setText("Enter receipt details to generate a new preview.")
        self.transaction.setCurrentIndex(0)
        self.engine_cc.setValue(0)
        self.initial_known.setChecked(False)
        self.expiry_known.setChecked(False)
        self.initial_date.setDate(QDate.currentDate())
        self.previous_expiry.setDate(QDate.currentDate())
        self.renewal_year.setValue(QDate.currentDate().year())
        self.initial_years.setCurrentIndex(0)
        self.auto_initial_year.setChecked(True)
        self.mvuc.setText("240.00")
        self.penalty_policy.setCurrentIndex(0)
        self.qr_mode.setCurrentIndex(self.qr_mode.findData("text"))
        self.qr_level.setCurrentText("M")
        self.qr_text.clear()
        self.qr_version.setCurrentIndex(self.qr_version.findData("auto"))
        self.file_dates_known.setChecked(False)
        self.file_window_start.setDate(QDate.currentDate())
        self.file_window_end.setDate(QDate.currentDate())
        self.auto_validity.setChecked(True)
        self.estimate_section.toggle.setChecked(False)
        self._refresh_registration()
        self.tabs.setCurrentIndex(0)
        self.reset_completed.emit()
        if self.automated():
            self._entry_mode_changed()
        self.generated_summary.setText("Ready to generate fresh receipt data.")
        self._update_payment_actions()
        self.preview_label.setText("Enter receipt details to generate a new preview.")

    def _receipt_date_changed(self) -> None:
        if self.transaction.currentData() == "renewal":
            self.renewal_year.setValue(self.date.date().year())
        self.validity_requested.emit()

    def load_defaults(self, fields: dict[str, str], charges: list[tuple[str, str]]) -> None:
        for key, value in fields.items():
            self.inputs[key].setText(value)
        self.charges.blockSignals(True)
        try:
            self.charges.setRowCount(len(charges))
            for row, (label, amount) in enumerate(charges):
                self.charges.setItem(row, 0, QTableWidgetItem(label))
                self.charges.setItem(row, 1, QTableWidgetItem(amount))
        finally:
            self.charges.blockSignals(False)
        self.payment_changed.emit()
        self._update_payment_actions()

    def registration_values(self) -> dict:
        return {
            "transaction": self.transaction.currentData(), "plate": self.inputs["plate_no"].text().strip(),
            "engine_cc": self.engine_cc.value(),
            "initial_date": self.initial_date.date().toPython() if self.initial_known.isChecked() else None,
            "previous_expiry": self.previous_expiry.date().toPython() if self.expiry_known.isChecked() else None,
            "payment_date": self.date.date().toPython(), "renewal_year": self.renewal_year.value(),
            "initial_validity_years": self.initial_years.currentData(), "annual_mvuc": self.mvuc.text().strip(),
            "auto_initial_renewal_year": self.auto_initial_year.isChecked(),
            "cap_initial_term": self.automated(),
            "penalty_policy": self.penalty_policy.currentData(),
            "file_no": self.inputs["file_no"].text().strip(),
            "confirmed_window_start": self.file_window_start.date().toPython() if self.file_dates_known.isChecked() else None,
            "confirmed_window_end": self.file_window_end.date().toPython() if self.file_dates_known.isChecked() else None,
        }

    def review_suggestions(self, validity: str, charges: list[tuple[str, str]], explanation: str) -> bool:
        dialog = RegistrationSuggestionsDialog(validity, charges, explanation, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        applied = False
        if dialog.apply_validity.isChecked():
            self.inputs["validity"].setText(validity)
            applied = True
        if dialog.apply_charges.isChecked() and charges:
            self.charges.blockSignals(True)
            try:
                self.charges.clearContents()
                self.charges.setRowCount(len(charges))
                for row, (label, amount) in enumerate(charges):
                    self.charges.setItem(row, 0, QTableWidgetItem(label))
                    self.charges.setItem(row, 1, QTableWidgetItem(amount))
            finally:
                self.charges.blockSignals(False)
            self.payment_changed.emit()
            self._update_payment_actions()
            self._mark_stale()
            applied = True
        return applied
