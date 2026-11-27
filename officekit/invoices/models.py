"""Explicit bounded invoice DTOs; money crosses boundaries as decimal strings."""

import re
import uuid
from datetime import date as CalendarDate
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator


def new_id():
    return str(uuid.uuid4())


def decimal_input(value):
    if not re.fullmatch(r"\d{1,13}(?:\.\d{1,8})?", value) or Decimal(value) > Decimal("1000000000000"):
        raise ValueError("Use a nonnegative decimal with at most eight decimal places and magnitude 10^12.")
    return value


Money = Annotated[StrictStr, AfterValidator(decimal_input)]
Identifier = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
Name = Annotated[StrictStr, Field(min_length=1, max_length=160)]
Text = Annotated[StrictStr, Field(max_length=8000)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    @field_validator("*", mode="before")
    @classmethod
    def text_controls(cls, value):
        if isinstance(value, str) and any(ord(char) < 32 and char not in "\n\r\t" for char in value):
            raise ValueError("Control characters are not supported.")
        return value


class Revision(Model):
    expected_revision: Annotated[StrictInt, Field(ge=0)]


class Currency(Model):
    id: Identifier = Field(default_factory=new_id)
    code: Annotated[StrictStr, Field(pattern=r"^[A-Z0-9]{2,12}$")] = "USD"
    name: Annotated[StrictStr, Field(max_length=80)] = "US dollar"
    symbol: Annotated[StrictStr, Field(max_length=12)] = "$"
    precision: Annotated[StrictInt, Field(ge=0, le=8)] = 2
    placement: Literal["before", "after", "code"] = "before"
    grouping: Literal["western", "indian", "none"] = "western"
    decimal_separator: Literal[".", ","] = "."
    grouping_separator: Literal[",", ".", " ", ""] = ","

    @model_validator(mode="after")
    def distinct_separators(self):
        if self.decimal_separator == self.grouping_separator:
            raise ValueError("Decimal and grouping separators must differ.")
        return self


class TaxRow(Model):
    label: Annotated[StrictStr, Field(min_length=1, max_length=80)]
    rate: Money = "0"
    registration_label: Annotated[StrictStr, Field(max_length=80)] = ""
    registration_number: Annotated[StrictStr, Field(max_length=160)] = ""
    mode: Literal["additive", "compound"] = "additive"

    @field_validator("rate")
    @classmethod
    def percentage(cls, value):
        if Decimal(value) > 100 or -Decimal(value).as_tuple().exponent > 6:
            raise ValueError("Tax rate must be 0–100 with at most six decimal places.")
        return value


class TaxProfile(Model):
    id: Identifier = Field(default_factory=new_id)
    name: Name = "No tax"
    inclusive: StrictBool = False
    rows: list[TaxRow] = Field(default_factory=list, max_length=6)


class PaymentField(Model):
    label: Annotated[StrictStr, Field(min_length=1, max_length=80)]
    value: Annotated[StrictStr, Field(max_length=512)] = ""
    visible: StrictBool = True


class PaymentMethod(Model):
    id: Identifier = Field(default_factory=new_id)
    type: Literal["bank", "link", "local", "cash-cheque", "custom"] = "bank"
    label: Annotated[StrictStr, Field(min_length=1, max_length=80)] = "Bank transfer"
    enabled: StrictBool = True
    fields: list[PaymentField] = Field(default_factory=list, max_length=20)
    link: Annotated[StrictStr, Field(max_length=2048)] = ""
    qr_payload: Annotated[StrictStr, Field(max_length=2048)] = ""
    instructions: Text = ""

    @field_validator("link")
    @classmethod
    def safe_link(cls, value):
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if value and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password):
            raise ValueError("Payment links must use HTTPS without credentials.")
        return value


class Template(Model):
    id: Identifier = Field(default_factory=new_id)
    name: Name = "Default"
    layout: Literal["Classic", "Compact", "Bold"] = "Classic"
    paper: Literal["A4", "Letter"] = "A4"
    logo_id: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    logo_size: Literal["small", "medium", "large"] = "medium"
    logo_placement: Literal["left", "center", "right"] = "left"
    accent: Annotated[StrictStr, Field(pattern=r"^#[0-9a-fA-F]{6}$")] = "#16749a"
    locale: Annotated[StrictStr, Field(max_length=80)] = "en-US"
    labels: dict[Annotated[StrictStr, Field(max_length=80)], Annotated[StrictStr, Field(max_length=160)]] = Field(default_factory=dict, max_length=20)
    columns: list[Literal["description", "quantity", "rate", "amount", "date", "unit"]] = Field(default_factory=lambda: ["description", "quantity", "rate", "amount"], min_length=1, max_length=6)
    footer: Text = ""


class Numbering(Model):
    invoice_prefix: Annotated[StrictStr, Field(pattern=r"^[\w .-]{0,40}$")] = "INV-"
    quote_prefix: Annotated[StrictStr, Field(pattern=r"^[\w .-]{0,40}$")] = "QUO-"
    estimate_prefix: Annotated[StrictStr, Field(pattern=r"^[\w .-]{0,40}$")] = "EST-"
    next_counter: Annotated[StrictInt, Field(ge=1, le=999999999)] = 1
    padding: Annotated[StrictInt, Field(ge=1, le=9)] = 3
    reset: Literal["never", "yearly"] = "never"


class Business(Model):
    name: Name
    profile_name: Annotated[StrictStr, Field(max_length=160)] = ""
    address: Annotated[StrictStr, Field(max_length=4000)] = ""
    contact: Annotated[StrictStr, Field(max_length=512)] = ""
    registrations: list[PaymentField] = Field(default_factory=list, max_length=20)
    currencies: list[Currency] = Field(default_factory=lambda: [Currency()], min_length=1, max_length=100)
    default_currency_id: Identifier | None = None
    tax_profiles: list[TaxProfile] = Field(default_factory=lambda: [TaxProfile()], min_length=1, max_length=50)
    default_tax_profile_id: Identifier | None = None
    templates: list[Template] = Field(default_factory=lambda: [Template()], min_length=1, max_length=20)
    default_template_id: Identifier | None = None
    payment_methods: list[PaymentMethod] = Field(default_factory=list, max_length=20)
    numbering: Numbering = Field(default_factory=Numbering)

    @model_validator(mode="after")
    def defaults(self):
        for collection, field in ((self.currencies, "default_currency_id"), (self.tax_profiles, "default_tax_profile_id"), (self.templates, "default_template_id")):
            ids = [item.id for item in collection]
            if len(ids) != len(set(ids)):
                raise ValueError("Saved configuration IDs must be unique.")
            selected = getattr(self, field)
            if selected is not None and selected not in ids:
                raise ValueError("Default configuration must belong to this profile.")
            setattr(self, field, selected or ids[0])
        codes = [item.code for item in self.currencies]
        if len(codes) != len(set(codes)):
            raise ValueError("Currency codes must be unique within a profile.")
        return self


class BusinessWrite(Business, Revision):
    pass


class Client(Model):
    business_id: Identifier
    name: Name
    address: Annotated[StrictStr, Field(max_length=4000)] = ""
    contact: Annotated[StrictStr, Field(max_length=512)] = ""
    email: Annotated[StrictStr, Field(max_length=512)] = ""
    customer_reference: Annotated[StrictStr, Field(max_length=512)] = ""
    tax_profile_id: Identifier | None = None
    terms_days: Annotated[StrictInt, Field(ge=0, le=3650)] = 14
    archived: StrictBool = False


class ClientWrite(Client, Revision):
    pass


class Item(Model):
    business_id: Identifier
    private_name: Name
    description: Annotated[StrictStr, Field(max_length=4000)] = ""
    unit: Annotated[StrictStr, Field(max_length=40)] = ""
    quantity: Money = "1"
    rate: Money = "0"
    tax_exempt: StrictBool = False
    archived: StrictBool = False


class ItemWrite(Item, Revision):
    pass


class Line(Model):
    description: Annotated[StrictStr, Field(min_length=1, max_length=4000)]
    item_id: Identifier | None = None
    unit: Annotated[StrictStr, Field(max_length=40)] = ""
    date: CalendarDate | None = None
    quantity: Money = "1"
    rate: Money = "0"
    tax_exempt: StrictBool = False
    section: Annotated[StrictStr, Field(max_length=160)] = ""

    @field_validator("quantity")
    @classmethod
    def positive(cls, value):
        if Decimal(value) == 0:
            raise ValueError("Quantity must be positive.")
        return value


class Discount(Model):
    kind: Literal["none", "percent", "fixed"] = "none"
    value: Money = "0"

    @model_validator(mode="after")
    def bounded_percent(self):
        if self.kind == "percent" and Decimal(self.value) > 100:
            raise ValueError("Discount percentage cannot exceed 100.")
        return self


class Draft(Model):
    business_id: Identifier
    kind: Literal["invoice", "quote", "estimate"] = "invoice"
    client_id: Identifier
    issue_date: CalendarDate
    due_date: CalendarDate | None = None
    valid_until: CalendarDate | None = None
    currency_id: Identifier | None = None
    tax_profile_id: Identifier | None = None
    template_id: Identifier | None = None
    currency_override: Currency | None = None
    tax_override: TaxProfile | None = None
    template_override: Template | None = None
    lines: list[Line] = Field(min_length=1, max_length=200)
    discount: Discount = Field(default_factory=Discount)
    notes: Text = ""
    terms: Text = ""
    payment_method_ids: list[Identifier] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def dates_ordered(self):
        if (self.due_date and self.due_date < self.issue_date) or (self.valid_until and self.valid_until < self.issue_date):
            raise ValueError("Due and validity dates cannot precede the issue date.")
        return self


class DraftWrite(Draft, Revision):
    source_draft_id: Identifier | None = None


class Transition(Revision):
    action: Literal["issue", "accept", "decline", "void"]
    number: Annotated[StrictStr, Field(min_length=1, max_length=80, pattern=r"^[\w .-]+$")] | None = None
    reason: Annotated[StrictStr, Field(max_length=1000)] = ""


class Conversion(Revision):
    source_quote_id: Identifier
    kind: Literal["full", "deposit", "balance"] = "full"
    amount: Money | None = None
    idempotency_key: Identifier


class Payment(Revision):
    amount: Money
    date: CalendarDate
    method: Annotated[StrictStr, Field(max_length=80)] = ""
    reference: Annotated[StrictStr, Field(max_length=512)] = ""
    idempotency_key: Identifier

    @field_validator("amount")
    @classmethod
    def positive(cls, value):
        if Decimal(value) == 0:
            raise ValueError("Payment must be positive.")
        return value


class PaymentCorrection(Revision):
    payment_id: Identifier
    reason: Annotated[StrictStr, Field(min_length=1, max_length=1000)]
    replacement: Payment | None = None


class Schedule(Model):
    business_id: Identifier
    draft: Draft
    frequency: Literal["weekly", "monthly", "quarterly", "yearly"] = "monthly"
    anchor_date: CalendarDate
    end_date: CalendarDate | None = None
    end_count: Annotated[StrictInt, Field(ge=1, le=10000)] | None = None
    paused: StrictBool = False
    catch_up: Literal["each", "ask"] = "each"

    @model_validator(mode="after")
    def valid_schedule(self):
        if self.business_id != self.draft.business_id or (self.end_date and self.end_date < self.anchor_date):
            raise ValueError("Schedule profile/date range is invalid.")
        return self


class ScheduleWrite(Schedule, Revision):
    pass


class RecurringBatch(Revision):
    approved_schedule_ids: list[Identifier] = Field(default_factory=list, max_length=500)


class Attachment(Model):
    selection_id: Identifier


class AssetWrite(Revision, Attachment):
    pass


class Preview(Revision):
    document_id: Identifier | None = None
    draft: Draft | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.document_id is None) == (self.draft is None):
            raise ValueError("Choose one saved document or draft.")
        return self


class LibraryState(Model):
    id: str
    library_id: str | None = None
    label: str
    status: str
    revision: int = 0
    businesses: list[dict] = Field(default_factory=list)
    capabilities: dict = Field(default_factory=dict)


class RecordMeta(Model):
    id: Identifier
    library_revision: int
    created_at: str
    updated_at: str


class BusinessRecord(Business, RecordMeta):
    pass


class ClientRecord(Client, RecordMeta):
    pass


class ItemRecord(Item, RecordMeta):
    pass


class DocumentRecord(RecordMeta):
    business_id: Identifier
    kind: str
    state: str
    status: str
    number: str
    draft: Draft
    business: Business
    client: Client
    currency: Currency
    tax_profile: TaxProfile
    template: Template
    payment_methods: list[PaymentMethod]
    totals: dict
    paid: str
    balance: str
    source_quote_id: str | None = None
    allocation_kind: str | None = None
    recurrence_key: str | None = None
    reason: str = ""
    archive_status: Literal["none", "pending", "ready"] = "none"
    archive_message: str = ""


class ScheduleRecord(Schedule, RecordMeta):
    pass


class Page(Model):
    items: list[BusinessRecord | ClientRecord | ItemRecord | DocumentRecord | ScheduleRecord | LibraryState]
    next_cursor: str | None = None


class PaymentRecord(RecordMeta):
    document_id: Identifier
    amount: str
    date: str
    method: str
    reference: str
    idempotency_key: str
    reversal_of: str | None = None
    reason: str = ""


class PaymentPage(Model):
    items: list[PaymentRecord]
    next_cursor: str | None = None


class PaymentResult(Model):
    document: DocumentRecord
    payments: list[PaymentRecord]
    library_revision: int


class ConversionResult(Model):
    documents: list[DocumentRecord]
    library_revision: int


class RecurringResult(Model):
    created_document_ids: list[str]
    existing_count: int
    remaining_count: int
    approval_required: list[str]
    library_revision: int


class InvoiceReport(Model):
    business_id: str
    currency: Currency
    start: str
    end: str
    invoiced: str
    received: str
    outstanding: str
    overdue: str
    clients: list[dict]


class AssetRecord(Model):
    id: str
    width: int
    height: int
    mime: Literal["image/png"] = "image/png"
    bytes: int
    library_revision: int
