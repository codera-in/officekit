import pytest

from officekit.invoices.models import BusinessWrite, Currency, DraftWrite, Line, PaymentMethod
from officekit.invoices import models as m


def test_currency_and_business_configuration_is_strict():
    business = BusinessWrite(name="International", expected_revision=0)
    assert business.currencies[0].code == "USD"
    assert business.address == ""
    assert Currency(code="CUSTOM", precision=8).precision == 8
    for payload in ({"code": "usd"}, {"precision": 9}, {"decimal_separator": ",", "grouping_separator": ","}):
        with pytest.raises(ValueError):
            Currency(**payload)
    with pytest.raises(ValueError):
        BusinessWrite(name="Test", expected_revision=0, path="/tmp")


def test_money_input_and_payment_links_reject_unsafe_values():
    for value in (True, 2.5, "NaN", "-1", "1e8", "1.000000001"):
        with pytest.raises(ValueError):
            Line(description="Work", rate=value)
    with pytest.raises(ValueError):
        Line(description="Work", quantity="0")
    with pytest.raises(ValueError):
        PaymentMethod(link="http://example.com")
    with pytest.raises(ValueError):
        PaymentMethod(label="bad\x00label")


def test_configuration_references_percentages_and_dates_are_validated():
    currency = Currency()
    with pytest.raises(ValueError, match="unique"):
        BusinessWrite(name="Profile", expected_revision=0, currencies=[currency, currency])
    with pytest.raises(ValueError, match="belong"):
        BusinessWrite(name="Profile", expected_revision=0, default_currency_id=m.new_id())
    with pytest.raises(ValueError, match="codes must be unique"):
        BusinessWrite(name="Profile", expected_revision=0, currencies=[Currency(), Currency()])
    for value in ("101", "0.1234567"):
        with pytest.raises(ValueError, match="Tax rate"):
            m.TaxRow(label="Tax", rate=value)
    with pytest.raises(ValueError, match="cannot exceed"):
        m.Discount(kind="percent", value="101")
    business_id, client_id = m.new_id(), m.new_id()
    draft = dict(business_id=business_id, client_id=client_id, issue_date="2026-10-25", lines=[{"description": "Work"}])
    for dates in ({"due_date": "2026-10-24"}, {"valid_until": "2026-10-24"}):
        with pytest.raises(ValueError, match="cannot precede"):
            m.Draft(**draft, **dates)
    with pytest.raises(ValueError, match="positive"):
        m.Payment(expected_revision=0, amount="0", date="2026-10-25", idempotency_key=m.new_id())
    with pytest.raises(ValueError, match="profile/date"):
        m.Schedule(business_id=m.new_id(), draft=draft, anchor_date="2026-10-25")
    with pytest.raises(ValueError, match="profile/date"):
        m.Schedule(business_id=business_id, draft=draft, anchor_date="2026-10-25", end_date="2026-10-24")
    for payload in ({}, {"document_id": m.new_id(), "draft": draft}):
        with pytest.raises(ValueError, match="Choose one"):
            m.Preview(expected_revision=0, **payload)
    assert PaymentMethod(link="https://example.com/pay").link.endswith("/pay")
