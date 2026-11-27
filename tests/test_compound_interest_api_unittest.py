"""Independent HTTP vectors for frequency-aware compound growth."""

import math
import unittest

from fastapi.testclient import TestClient

from app import app


def reference_growth(principal, annual_rate, years, compound_freq, monthly_contribution):
    """Use direct exponentiation and a transparent month-by-month recurrence."""
    factor = math.pow(1 + (annual_rate / 100) / compound_freq, compound_freq / 12)
    exact_months = years * 12
    whole_months = math.floor(exact_months)
    fraction = exact_months - whole_months
    balance = float(principal)
    invested = float(principal)
    history = []
    for month in range(1, whole_months + 1):
        balance = balance * factor + monthly_contribution
        invested += monthly_contribution
        if month % 12 == 0:
            history.append({
                "year": month / 12,
                "total_balance": round(balance, 2),
                "total_invested": round(invested, 2),
                "total_interest": round(balance - invested, 2),
            })
    if fraction:
        balance *= math.pow(factor, fraction)
    if years > 0 and (not history or history[-1]["year"] != years):
        history.append({
            "year": years,
            "total_balance": round(balance, 2),
            "total_invested": round(invested, 2),
            "total_interest": round(balance - invested, 2),
        })
    return {
        "future_value": round(balance, 2),
        "total_invested": round(invested, 2),
        "total_interest_earned": round(balance - invested, 2),
        "growth_history": history,
    }


class CompoundInterestApiTests(unittest.TestCase):
    def test_http_annual_compounding_known_values_and_year_history(self):
        client = TestClient(app)
        expected = {
            10: (1210.0, 210.0, [1100.0, 1210.0]),
            20: (1440.0, 440.0, [1200.0, 1440.0]),
        }

        for rate, (future_value, interest, yearly_balances) in expected.items():
            with self.subTest(rate=rate):
                response = client.post("/api/calculator/compound-interest", json={
                    "principal": 1000,
                    "annual_rate": rate,
                    "years": 2,
                    "compound_freq": 1,
                    "monthly_contribution": 0,
                })
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual(result["future_value"], future_value)
                self.assertEqual(result["total_invested"], 1000.0)
                self.assertEqual(result["total_interest_earned"], interest)
                self.assertEqual([row["total_balance"] for row in result["growth_history"]], yearly_balances)
                self.assertEqual([row["year"] for row in result["growth_history"]], [1, 2])

    def test_http_schedule_matches_independent_annual_quarterly_monthly_and_daily_vectors(self):
        vectors = (
            {"principal": 1000, "annual_rate": 12, "years": 1, "compound_freq": 1, "monthly_contribution": 100},
            {"principal": 9876.54, "annual_rate": 8.25, "years": 2.375, "compound_freq": 4, "monthly_contribution": 125.50},
            {"principal": 2500, "annual_rate": 0, "years": 1.25, "compound_freq": 12, "monthly_contribution": 50},
            {"principal": 100, "annual_rate": 8, "years": 1, "compound_freq": 365, "monthly_contribution": 0},
            {"principal": 500, "annual_rate": 5, "years": 0, "compound_freq": 12, "monthly_contribution": 100},
        )
        client = TestClient(app)

        for vector in vectors:
            with self.subTest(vector=vector):
                response = client.post("/api/calculator/compound-interest", json=vector)
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                expected = reference_growth(**{
                    "principal": vector["principal"],
                    "annual_rate": vector["annual_rate"],
                    "years": vector["years"],
                    "compound_freq": vector["compound_freq"],
                    "monthly_contribution": vector["monthly_contribution"],
                })
                for field in ("future_value", "total_invested", "total_interest_earned"):
                    self.assertEqual(result[field], expected[field])
                self.assertEqual(result["growth_history"], expected["growth_history"])
                self.assertAlmostEqual(
                    result["future_value"],
                    result["total_invested"] + result["total_interest_earned"],
                    places=2,
                )
                self.assertEqual(result["assumptions"], {
                    "rate_basis": "nominal_annual",
                    "monthly_accrual": "equivalent_effective_monthly_rate",
                    "contribution_timing": "end_of_month",
                    "fractional_month": "interest_only",
                })

    def test_http_rejects_unknown_fields_fractional_frequency_and_oversized_range(self):
        client = TestClient(app)
        valid = {"principal": 100, "annual_rate": 5, "years": 1}
        invalid = (
            {**valid, "compound_freq": 1.5},
            {**valid, "compound_freq": True},
            {**valid, "years": 100.01},
            {**valid, "unknown": "ignored must be rejected"},
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                response = client.post("/api/calculator/compound-interest", json=payload)
                self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
