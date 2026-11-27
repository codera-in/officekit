"""HTTP-level behavior for fixed-rate monthly loan amortization."""

from fastapi.testclient import TestClient

import app as officekit_app


client = TestClient(officekit_app.app)


def test_loan_emi_http_response_has_a_complete_reconciling_schedule():
    response = client.post(
        "/api/calculator/loan-emi",
        json={"principal": 100000, "annual_interest_rate": 10, "tenure_years": 5},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    schedule = result["schedule"]
    assert result["monthly_emi"] == 2124.70
    assert result["tenure_months"] == 60
    assert [row["month"] for row in schedule] == list(range(1, 61))
    assert round(sum(row["principal_paid"] for row in schedule), 2) == 100000.00
    assert round(sum(row["payment"] for row in schedule), 2) == result["total_payment"]
    assert round(sum(row["interest_paid"] for row in schedule), 2) == result["total_interest"]
    assert schedule[-1]["remaining_balance"] == 0


def test_loan_emi_http_zero_interest_and_smallest_supported_term():
    response = client.post(
        "/api/calculator/loan-emi",
        json={"principal": 1200, "annual_interest_rate": 0, "tenure_years": 1 / 12},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["tenure_months"] == 1
    assert result["monthly_emi"] == 1200.00
    assert result["total_interest"] == 0
    assert len(result["schedule"]) == 1
    assert result["schedule"][0]["remaining_balance"] == 0


def test_loan_emi_http_rejects_non_monthly_terms_and_invalid_json_numbers():
    valid = {"principal": 1000, "annual_interest_rate": 0, "tenure_years": 1}
    for payload in (
        {**valid, "tenure_years": 1.001},
        {**valid, "tenure_years": 1 / 24},
        {**valid, "principal": True},
        {**valid, "principal": "1000"},
        {**valid, "principal": 1e13},
        {**valid, "annual_interest_rate": 1001},
        {**valid, "unexpected": "field"},
    ):
        response = client.post("/api/calculator/loan-emi", json=payload)
        assert response.status_code == 422, payload

    nonfinite = client.post(
        "/api/calculator/loan-emi",
        content=b'{"principal":NaN,"annual_interest_rate":0,"tenure_years":1}',
        headers={"content-type": "application/json"},
    )
    assert nonfinite.status_code == 422

