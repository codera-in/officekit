from copy import deepcopy
from datetime import date
from decimal import Decimal
import io

import pytest

from officekit.invoices.domain import calculate_totals, InvoiceService, InvoiceError, next_occurrence, report_csv
from officekit.invoices import models as m
from officekit.invoices import domain
from officekit.invoices.models import Currency, TaxProfile, Line, Discount


class Repository:
    def __init__(self):
        self.state = {"schema_version": 1, "library_id": m.new_id(), "revision": 0, **{name: {} for name in ("businesses", "clients", "items", "documents", "payments", "schedules", "conversions")}}
        self.archives = {}

    def read(self):
        return deepcopy(self.state)

    def transaction(self, expected, callback, event=None):
        if expected != self.state["revision"]:
            raise InvoiceError("REVISION_CONFLICT", "changed", 409)
        state = self.read()
        result = callback(state)
        state["revision"] += 1
        self.state = state
        result["library_revision"] = state["revision"]
        return result

    def archive_document(self, identifier, issued, data):
        self.archives[identifier] = (issued, data)


class Libraries:
    def __init__(self):
        self.repo = Repository()

    def get(self, key):
        return self.repo


@pytest.fixture
def world():
    libraries = Libraries()
    service = InvoiceService(libraries, today=lambda: date(2026, 10, 25), now=lambda: "2026-10-25T00:00:00+00:00")
    business = service.save("library", "businesses", m.BusinessWrite(name="Studio", expected_revision=0))
    client = service.save("library", "clients", m.ClientWrite(business_id=business["id"], name="Client", expected_revision=1))
    return service, libraries.repo, business, client


def save_draft(world, **overrides):
    service, repo, business, client = world
    return service.save("library", "documents", m.DraftWrite(expected_revision=repo.state["revision"], business_id=business["id"], client_id=client["id"], issue_date="2026-10-25", due_date=overrides.pop("due_date", "2026-11-08"), lines=overrides.pop("lines", [{"description": "Consulting", "quantity": "2", "rate": "50"}]), **overrides))


def transition(world, document, action="issue", **overrides):
    service, repo, _, _ = world
    return service.transition("library", document["id"], m.Transition(expected_revision=repo.state["revision"], action=action, **overrides))


def test_totals_use_decimal_and_reconcile_inclusive_compound_taxes():
    currency = Currency()
    taxes = TaxProfile(rows=[{"label": "VAT", "rate": "10"}, {"label": "Duty", "rate": "5", "mode": "compound"}])
    result = calculate_totals([Line(description="Item", quantity="3", rate="0.1")], currency, taxes, Discount())
    assert result["subtotal"] == "0.30"
    assert result["total"] == "0.35"
    inclusive = taxes.model_copy(update={"inclusive": True})
    result = calculate_totals([Line(description="Item", rate="115.5")], currency, inclusive, Discount())
    assert result["net"] == "100.00"
    assert [row["amount"] for row in result["taxes"]] == ["10.00", "5.50"]
    assert result["total"] == "115.50"


def test_discount_allocation_exemptions_precision_and_amount_bounds():
    lines = [Line(description="A", rate="10.01"), Line(description="B", rate="4.99", tax_exempt=True)]
    result = calculate_totals(lines, Currency(), TaxProfile(rows=[{"label": "Tax", "rate": "10"}]), Discount(kind="fixed", value="3"))
    assert result["subtotal"] == "15.00" and result["discount"] == "3.00"
    assert result["lines"][1]["taxes"] == ["0.00"]
    assert sum(Decimal(row["discount"]) for row in result["lines"]) == Decimal("3")
    assert calculate_totals(lines, Currency(precision=0), TaxProfile(), Discount(kind="percent", value="10"))["total"] == "13"
    assert calculate_totals([Line(description="Free", rate="0")], Currency(), TaxProfile(), Discount())["total"] == "0.00"
    with pytest.raises(InvoiceError, match="discount exceeds"):
        calculate_totals(lines, Currency(), TaxProfile(), Discount(kind="fixed", value="16"))
    with pytest.raises(InvoiceError, match="exceeds"):
        calculate_totals([Line(description="Large", rate="1000000000000", quantity="1000000000000")], Currency(), TaxProfile(), Discount())
    with pytest.raises(InvoiceError, match="exceeds"):
        calculate_totals([Line(description="Large", rate="1000000000000", quantity="1000") for _ in range(2)], Currency(), TaxProfile(), Discount())


def test_profiles_catalogue_edits_and_issued_snapshot_are_independent(world):
    service, repo, business, client = world
    item = service.save("library", "items", m.ItemWrite(expected_revision=2, business_id=business["id"], private_name="Design", description="Reusable", rate="20"))
    draft = save_draft(world, lines=[{"description": "Invoice-only extra details", "item_id": item["id"], "rate": "25"}])
    assert service.record("library", "items", item["id"])["description"] == "Reusable"
    issued = transition(world, draft)
    assert issued["number"] == "INV-001" and issued["archive_status"] == "ready"
    assert repo.archives[issued["id"]][1].startswith(b"%PDF")
    updated = service.save("library", "businesses", m.BusinessWrite(expected_revision=repo.state["revision"], name="New name"), business["id"])
    assert updated["name"] == "New name"
    assert service.record("library", "documents", issued["id"])["business"]["name"] == "Studio"
    with pytest.raises(InvoiceError, match="cannot be edited"):
        service.save("library", "documents", m.DraftWrite(expected_revision=repo.state["revision"], **draft["draft"]), draft["id"])
    other = service.save("library", "businesses", m.BusinessWrite(expected_revision=repo.state["revision"], name="Other", currencies=[{"code": "INR", "symbol": "₹"}]))
    assert other["currencies"][0]["code"] == "INR" and business["currencies"][0]["code"] == "USD"
    with pytest.raises(InvoiceError, match="another business"):
        service.save("library", "documents", m.DraftWrite(expected_revision=repo.state["revision"], **{**draft["draft"], "business_id": other["id"]}))


def test_draft_updates_configuration_and_profile_mismatch_guards(world):
    service, repo, business, client = world
    draft = save_draft(world)
    changed = service.save("library", "documents", m.DraftWrite(expected_revision=repo.state["revision"], **{**draft["draft"], "notes": "More detail"}), draft["id"])
    assert changed["draft"]["notes"] == "More detail"
    bad = m.new_id()
    for field in ("currency_id", "tax_profile_id", "template_id"):
        with pytest.raises(InvoiceError, match="configuration"):
            save_draft(world, **{field: bad})
    with pytest.raises(InvoiceError, match="payment methods"):
        save_draft(world, payment_method_ids=[bad])
    with pytest.raises(InvoiceError, match="unavailable"):
        service.record("library", "items", bad)
    other = service.save("library", "businesses", m.BusinessWrite(name="Other", expected_revision=repo.state["revision"]))
    item = service.save("library", "items", m.ItemWrite(business_id=other["id"], private_name="Other", expected_revision=repo.state["revision"]))
    with pytest.raises(InvoiceError, match="item belongs"):
        save_draft(world, lines=[{"description": "Wrong profile", "item_id": item["id"]}])
    with pytest.raises(InvoiceError, match="cannot move"):
        service.save("library", "clients", m.ClientWrite(name="Client", business_id=other["id"], expected_revision=repo.state["revision"]), client["id"])
    with pytest.raises(InvoiceError, match="configuration"):
        service.save("library", "clients", m.ClientWrite(name="Client", business_id=business["id"], tax_profile_id=bad, expected_revision=repo.state["revision"]))


def test_invoice_numbering_transition_conflict_void_and_overdue(world):
    service, repo, business, client = world
    draft = save_draft(world)
    with pytest.raises(InvoiceError, match="does not permit"):
        transition(world, draft, "accept")
    issued = transition(world, draft)
    second = transition(world, save_draft(world))
    assert second["number"] == "INV-002"
    with pytest.raises(InvoiceError, match="already used"):
        transition(world, save_draft(world), number="INV-001")
    void = transition(world, second, "void", reason="Cancelled")
    assert void["status"] == "Void"
    overdue = transition(world, save_draft(world, due_date="2026-10-25"))
    service.today = lambda: date(2026, 10, 26)
    assert service.record("library", "documents", overdue["id"])["status"] == "Overdue"
    quote = transition(world, save_draft(world, kind="quote", valid_until="2026-10-25"))
    assert service.record("library", "documents", quote["id"])["status"] == "Expired"
    assert transition(world, quote, "decline")["status"] == "Declined"


def test_partial_full_payments_idempotence_corrections_and_report(world):
    service, repo, business, client = world
    document = transition(world, save_draft(world))
    payload = dict(amount="40", date="2026-10-25", idempotency_key=m.new_id(), method="Bank", reference="Paid")
    result = service.payment("library", document["id"], m.Payment(expected_revision=repo.state["revision"], **payload))
    assert result["document"]["status"] == "Partially paid" and result["document"]["balance"] == "60.00"
    repeat = service.payment("library", document["id"], m.Payment(expected_revision=repo.state["revision"], **payload))
    assert len(repeat["payments"]) == 1
    with pytest.raises(InvoiceError, match="another payment"):
        service.payment("library", document["id"], m.Payment(expected_revision=repo.state["revision"], **{**payload, "amount": "41"}))
    with pytest.raises(InvoiceError, match="Correct recorded payments"):
        transition(world, document, "void")
    with pytest.raises(InvoiceError, match="exceeds the balance"):
        service.payment("library", document["id"], m.Payment(expected_revision=repo.state["revision"], **{**payload, "idempotency_key": m.new_id(), "amount": "61"}))
    with pytest.raises(InvoiceError, match="decimal places"):
        service.payment("library", document["id"], m.Payment(expected_revision=repo.state["revision"], **{**payload, "idempotency_key": m.new_id(), "amount": "0.001"}))
    report = service.report("library", business["id"], business["default_currency_id"], date(2026, 10, 1), date(2026, 10, 31))
    assert report["received"] == "40.00" and report["outstanding"] == "60.00"
    corrected = service.payment("library", document["id"], m.PaymentCorrection(expected_revision=repo.state["revision"], payment_id=result["payments"][0]["id"], reason="Wrong amount", replacement=m.Payment(expected_revision=0, **{**payload, "amount": "100", "idempotency_key": m.new_id()})), correction=True)
    assert corrected["document"]["status"] == "Paid"
    assert sum(Decimal(entry["amount"]) for entry in corrected["payments"]) == Decimal(100)
    with pytest.raises(InvoiceError, match="already been corrected"):
        service.payment("library", document["id"], m.PaymentCorrection(expected_revision=repo.state["revision"], payment_id=result["payments"][0]["id"], reason="Again"), correction=True)
    assert len(service.payments("library", document["id"])["items"]) == 3


def test_quote_deposit_balance_idempotence_and_invalid_conversion(world):
    service, repo, business, client = world
    quote = save_draft(world, kind="quote")
    key = m.new_id()
    def convert(kind="deposit", amount="30", token=key):
        return service.convert("library", m.Conversion(expected_revision=repo.state["revision"], source_quote_id=quote["id"], kind=kind, amount=amount, idempotency_key=token))
    with pytest.raises(InvoiceError, match="Accept the quote"):
        convert()
    quote = transition(world, quote)
    quote = transition(world, quote, "accept")
    deposit = convert()["documents"][0]
    assert deposit["totals"]["total"] == "30.00"
    assert convert()["documents"][0]["id"] == deposit["id"]
    with pytest.raises(InvoiceError, match="another conversion"):
        convert(amount="31")
    with pytest.raises(InvoiceError, match="unallocated"):
        convert(kind="full", token=m.new_id())
    with pytest.raises(InvoiceError, match="precision"):
        convert(amount="0.001", token=m.new_id())
    balance = convert(kind="balance", amount=None, token=m.new_id())["documents"][0]
    assert balance["totals"]["total"] == "70.00"
    with pytest.raises(InvoiceError, match="unallocated"):
        convert(token=m.new_id())


def test_recurring_dates_deduplication_pause_approval_and_catchup(world):
    service, repo, business, client = world
    draft = save_draft(world)
    schedule = service.save("library", "schedules", m.ScheduleWrite(expected_revision=repo.state["revision"], business_id=business["id"], draft=draft["draft"], frequency="monthly", anchor_date="2026-08-31", catch_up="ask"))
    result = service.recurring("library", m.RecurringBatch(expected_revision=repo.state["revision"]))
    assert result["approval_required"] == [schedule["id"]]
    result = service.recurring("library", m.RecurringBatch(expected_revision=repo.state["revision"], approved_schedule_ids=[schedule["id"]]))
    assert len(result["created_document_ids"]) == 2
    dates = [repo.state["documents"][key]["draft"]["issue_date"] for key in result["created_document_ids"]]
    assert dates == ["2026-08-31", "2026-09-30"]
    assert service.recurring("library", m.RecurringBatch(expected_revision=repo.state["revision"]))["existing_count"] == 2
    assert next_occurrence(date(2024, 2, 29), "yearly", 1) == date(2025, 2, 28)
    assert next_occurrence(date(2026, 1, 31), "quarterly", 1) == date(2026, 4, 30)
    assert next_occurrence(date(2026, 1, 1), "weekly", 2) == date(2026, 1, 15)
    service.save("library", "schedules", m.ScheduleWrite(expected_revision=repo.state["revision"], business_id=business["id"], draft=draft["draft"], anchor_date="2026-01-01", paused=True))
    assert service.recurring("library", m.RecurringBatch(expected_revision=repo.state["revision"]))["created_document_ids"] == []


def test_preview_filters_report_period_and_csv_formula_protection(world):
    service, repo, business, client = world
    draft = save_draft(world)
    assert service.preview("library", m.Preview(expected_revision=repo.state["revision"], document_id=draft["id"]))["id"] == draft["id"]
    assert service.preview("library", m.Preview(expected_revision=repo.state["revision"], draft=draft["draft"]))["state"] == "draft"
    with pytest.raises(InvoiceError, match="changed"):
        service.preview("library", m.Preview(expected_revision=0, document_id=draft["id"]))
    transition(world, draft)
    save_draft(world, kind="quote")
    page = service.page("library", "documents", business["id"], search="Consulting", status="Issued", kind="invoice", start="2026-10-01", end="2026-10-31", sort="amount", order="asc", limit=1)
    assert len(page["items"]) == 1
    assert service.page("library", "documents", limit=1)["next_cursor"] == "1"
    assert len(service.page("library", "documents", cursor="1")["items"]) == 1
    for cursor in ("bad", "-1"):
        with pytest.raises(InvoiceError, match="cursor"):
            service.page("library", "documents", cursor=cursor)
    for start, end in ((date(2026, 2, 1), date(2026, 1, 1)), (date(2000, 1, 1), date(2026, 1, 1))):
        with pytest.raises(InvoiceError, match="period"):
            service.report("library", business["id"], business["default_currency_id"], start, end)
    report = service.report("library", business["id"], business["default_currency_id"], date(2026, 10, 1), date(2026, 10, 31))
    report["clients"][0]["name"] = "=FORMULA()"
    assert b"'=FORMULA()" in report_csv(report)
    report["clients"][0]["name"] = "Safe client"
    assert b"Safe client" in report_csv(report)


def test_archive_failure_preserves_issued_identity_and_retry_is_explicit(world, monkeypatch):
    service, repo, _, _ = world
    draft = save_draft(world)
    with pytest.raises(InvoiceError, match="Issue the document"):
        service.archive("library", draft["id"], repo.state["revision"])
    with pytest.raises(InvoiceError, match="changed"):
        service.archive("library", draft["id"], 0)
    original = repo.archive_document
    def denied(*args):
        raise OSError("full")
    monkeypatch.setattr(repo, "archive_document", denied)
    issued = transition(world, draft)
    assert issued["state"] == "issued" and issued["archive_status"] == "pending"
    assert service.record("library", "documents", issued["id"])["number"] == "INV-001"
    monkeypatch.setattr(repo, "archive_document", original)
    archived = service.archive("library", issued["id"], repo.state["revision"])
    assert archived["archive_status"] == "ready"
    current = repo.state["revision"]
    assert service.archive("library", issued["id"], current)["id"] == issued["id"]
    assert repo.state["revision"] == current


def test_taxed_deposit_reconciliation_and_recurring_batch_cap(world):
    service, repo, business, client = world
    quote = save_draft(world, kind="quote", tax_override={"name": "VAT", "inclusive": True, "rows": [{"label": "VAT", "rate": "10"}, {"label": "Local", "rate": "5"}]})
    transition(world, quote)
    transition(world, quote, "accept")
    deposit = service.convert("library", m.Conversion(expected_revision=repo.state["revision"], source_quote_id=quote["id"], kind="deposit", amount="30", idempotency_key=m.new_id()))["documents"][0]
    assert Decimal(deposit["totals"]["net"]) + sum(Decimal(row["amount"]) for row in deposit["totals"]["taxes"]) == Decimal("30")
    draft = save_draft(world)
    service.save("library", "schedules", m.ScheduleWrite(expected_revision=repo.state["revision"], business_id=business["id"], draft=draft["draft"], frequency="weekly", anchor_date="2024-01-01", end_count=105))
    batch = service.recurring("library", m.RecurringBatch(expected_revision=repo.state["revision"]))
    assert len(batch["created_document_ids"]) == 100 and batch["remaining_count"] == 5
    assert len(service.recurring("library", m.RecurringBatch(expected_revision=repo.state["revision"]))["created_document_ids"]) == 5


def test_reports_respect_date_filters_unrelated_payments_and_overdue(world, monkeypatch):
    service, repo, business, client = world
    first = transition(world, save_draft(world, due_date="2026-10-25"))
    second = transition(world, save_draft(world))
    service.payment("library", first["id"], m.Payment(expected_revision=repo.state["revision"], amount="10", date="2026-10-25", idempotency_key=m.new_id()))
    service.today = lambda: date(2026, 10, 26)
    before = service.report("library", business["id"], business["default_currency_id"], date(2026, 9, 1), date(2026, 9, 30))
    assert before["invoiced"] == before["outstanding"] == "0.00"
    after = service.report("library", business["id"], business["default_currency_id"], date(2026, 10, 26), date(2026, 10, 31))
    assert after["overdue"] == "90.00" and after["received"] == "0.00"
    assert service.report("library", business["id"], business["default_currency_id"], date(2026, 10, 1), date(2026, 10, 31), m.new_id())["clients"] == []
    monkeypatch.setattr(domain, "MAX_CSV_BYTES", 10)
    with pytest.raises(InvoiceError, match="CSV report exceeds"):
        report_csv(after)
