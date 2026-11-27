"""
TDD Tests for Module 6: High-Traffic Financial & Business Calculators
- Loan EMI & Full Amortization
- Compound Interest & Wealth Growth
- VAT & Sales Tax (Forward & Reverse Inclusive)
- Freelance & Agency Rate Calculator
- Profit Margin & Markup Calculator
- Break-Even Analysis Calculator
- Straight Line Depreciation
"""

import unittest
from officekit.engines.engine_calculators import CalculatorEngine

class TestModule6CalculatorsEngine(unittest.TestCase):

    def test_loan_emi_and_amortization(self):
        res = CalculatorEngine.calculate_loan_emi(principal=100000, annual_interest_rate=10.0, tenure_years=5.0)
        self.assertEqual(res["monthly_emi"], 2124.70)
        self.assertGreater(res["total_payment"], 120000)
        self.assertEqual(len(res["preview_schedule"]), 12)
        self.assertEqual(len(res["schedule"]), 60)
        self.assertEqual(res["schedule"][-1]["remaining_balance"], 0.0)
        self.assertAlmostEqual(sum(row["principal_paid"] for row in res["schedule"]), 100000.0, places=2)
        self.assertAlmostEqual(sum(row["payment"] for row in res["schedule"]), res["total_payment"], places=2)
        self.assertAlmostEqual(sum(row["interest_paid"] for row in res["schedule"]), res["total_interest"], places=2)
        previous_balance = 100000.0
        for row in res["schedule"]:
            self.assertAlmostEqual(
                row["payment"], row["principal_paid"] + row["interest_paid"], places=2
            )
            self.assertAlmostEqual(
                row["remaining_balance"], previous_balance - row["principal_paid"], places=2
            )
            previous_balance = row["remaining_balance"]

    def test_loan_schedule_adjusts_last_payment_for_zero_rate_rounding(self):
        result = CalculatorEngine.calculate_loan_emi(
            principal=1000, annual_interest_rate=0, tenure_years=1
        )
        self.assertEqual(len(result["schedule"]), 12)
        self.assertEqual(result["schedule"][-1]["remaining_balance"], 0.0)
        self.assertEqual(sum(row["principal_paid"] for row in result["schedule"]), 1000.0)
        self.assertEqual(result["total_payment"], 1000.0)
        self.assertEqual(result["total_interest"], 0.0)

    def test_zero_principal_produces_a_zero_payment_schedule(self):
        result = CalculatorEngine.calculate_loan_emi(
            principal=0, annual_interest_rate=12.5, tenure_years=1
        )

        self.assertEqual(result["monthly_emi"], 0.0)
        self.assertEqual(result["total_interest"], 0.0)
        self.assertEqual(result["total_payment"], 0.0)
        self.assertEqual(len(result["schedule"]), 12)
        self.assertTrue(all(row["payment"] == 0.0 for row in result["schedule"]))
        self.assertTrue(all(row["remaining_balance"] == 0.0 for row in result["schedule"]))

    def test_loan_calculator_rejects_nonfinite_and_out_of_range_inputs(self):
        for args in (
            {"principal": -1, "annual_interest_rate": 10, "tenure_years": 1},
            {"principal": float("nan"), "annual_interest_rate": 10, "tenure_years": 1},
            {"principal": 1000, "annual_interest_rate": -1, "tenure_years": 1},
            {"principal": 1000, "annual_interest_rate": 1001, "tenure_years": 1},
            {"principal": 1000, "annual_interest_rate": 10, "tenure_years": 0},
            {"principal": 1000, "annual_interest_rate": 10, "tenure_years": 100.1},
            {"principal": 1000, "annual_interest_rate": 10, "tenure_years": 1.001},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                CalculatorEngine.calculate_loan_emi(**args)

    def test_compound_interest(self):
        res = CalculatorEngine.calculate_compound_interest(principal=10000, annual_rate=8.0, years=5.0, monthly_contribution=100)
        self.assertGreater(res["future_value"], 20000)
        self.assertEqual(len(res["growth_history"]), 5)

    def test_compound_interest_honors_compounding_frequency(self):
        annual = CalculatorEngine.calculate_compound_interest(
            principal=1000, annual_rate=12, years=1, compound_freq=1
        )
        monthly = CalculatorEngine.calculate_compound_interest(
            principal=1000, annual_rate=12, years=1, compound_freq=12
        )

        self.assertAlmostEqual(annual["future_value"], 1120.00, places=2)
        self.assertAlmostEqual(monthly["future_value"], 1126.83, places=2)

        daily = CalculatorEngine.calculate_compound_interest(
            principal=1000, annual_rate=8, years=1, compound_freq=365
        )
        self.assertAlmostEqual(daily["future_value"], 1083.28, places=2)

    def test_compound_interest_contributions_are_end_of_month_and_reconcile(self):
        result = CalculatorEngine.calculate_compound_interest(
            principal=1000, annual_rate=12, years=1, compound_freq=12,
            monthly_contribution=100,
        )
        monthly_factor = 1 + 0.12 / 12
        expected = 1000 * monthly_factor ** 12 + 100 * (monthly_factor ** 12 - 1) / (monthly_factor - 1)

        self.assertAlmostEqual(result["future_value"], expected, places=2)
        self.assertEqual(result["total_invested"], 2200.00)
        self.assertAlmostEqual(
            result["future_value"],
            result["total_invested"] + result["total_interest_earned"],
            places=2,
        )

    def test_compound_interest_handles_fractional_years_and_incomplete_months(self):
        result = CalculatorEngine.calculate_compound_interest(
            principal=1000, annual_rate=12, years=1.1, compound_freq=4,
            monthly_contribution=100,
        )
        monthly_factor = (1 + 0.12 / 4) ** (4 / 12)
        expected = 1000
        for _ in range(13):
            expected = expected * monthly_factor + 100
        expected *= monthly_factor ** 0.2

        self.assertAlmostEqual(result["future_value"], expected, places=2)
        self.assertEqual(result["total_invested"], 2300.00)
        self.assertEqual([row["year"] for row in result["growth_history"]], [1, 1.1])
        self.assertAlmostEqual(result["growth_history"][-1]["total_balance"], expected, places=2)
        self.assertEqual(result["assumptions"]["contribution_timing"], "end_of_month")
        self.assertEqual(result["assumptions"]["fractional_month"], "interest_only")

    def test_compound_interest_zero_rate_only_accumulates_completed_month_contributions(self):
        result = CalculatorEngine.calculate_compound_interest(
            principal=100, annual_rate=0, years=1.25, monthly_contribution=10
        )
        self.assertEqual(result["future_value"], 250.00)
        self.assertEqual(result["total_invested"], 250.00)
        self.assertEqual(result["total_interest_earned"], 0.00)
        self.assertEqual([row["year"] for row in result["growth_history"]], [1, 1.25])

    def test_compound_interest_validates_finite_domain_and_zero_duration(self):
        zero = CalculatorEngine.calculate_compound_interest(principal=100, annual_rate=5, years=0)
        self.assertEqual(zero["future_value"], 100.00)
        self.assertEqual(zero["total_invested"], 100.00)
        self.assertEqual(zero["growth_history"], [])

        invalid = [
            {"principal": -1}, {"principal": float("nan")},
            {"annual_rate": float("inf")}, {"years": -0.1},
            {"years": 101}, {"annual_rate": -100}, {"annual_rate": 1001},
            {"years": float("nan")}, {"compound_freq": 0},
            {"compound_freq": True}, {"compound_freq": 1.5},
            {"monthly_contribution": -1}, {"monthly_contribution": 1e13},
            {"principal": 1e13}, {"principal": "100"},
        ]
        for override in invalid:
            args = {"principal": 100, "annual_rate": 5, "years": 1,
                    "compound_freq": 12, "monthly_contribution": 0}
            args.update(override)
            with self.subTest(override=override), self.assertRaises(ValueError):
                CalculatorEngine.calculate_compound_interest(**args)

    def test_vat_and_sales_tax(self):
        # Forward tax: $100 + 20% = $120
        res_ex = CalculatorEngine.calculate_vat_salestax(amount=100.0, tax_rate_percent=20.0, is_inclusive=False)
        self.assertEqual(res_ex["gross_amount"], 120.0)
        self.assertEqual(res_ex["tax_amount"], 20.0)

        # Reverse tax: $120 gross inclusive of 20% = $100 net
        res_inc = CalculatorEngine.calculate_vat_salestax(amount=120.0, tax_rate_percent=20.0, is_inclusive=True)
        self.assertAlmostEqual(res_inc["net_amount"], 100.0, places=2)
        self.assertAlmostEqual(res_inc["tax_amount"], 20.0, places=2)

    def test_vat_rounds_currency_amounts_half_up_and_keeps_totals_consistent(self):
        exclusive = CalculatorEngine.calculate_vat_salestax(
            amount=0.05, tax_rate_percent=10, is_inclusive=False
        )
        inclusive = CalculatorEngine.calculate_vat_salestax(
            amount=0.05, tax_rate_percent=10, is_inclusive=True
        )
        self.assertEqual(exclusive["tax_amount"], 0.01)
        self.assertEqual(exclusive["gross_amount"], 0.06)
        self.assertEqual(inclusive["net_amount"] + inclusive["tax_amount"], inclusive["gross_amount"])
        self.assertEqual(inclusive["net_amount"], 0.05)
        self.assertEqual(inclusive["tax_amount"], 0.00)

    def test_vat_rejects_invalid_amounts_rates_and_mode(self):
        for args in (
            {"amount": -1, "tax_rate_percent": 20},
            {"amount": float("nan"), "tax_rate_percent": 20},
            {"amount": 100, "tax_rate_percent": -1},
            {"amount": 100, "tax_rate_percent": 1001},
            {"amount": 100, "tax_rate_percent": float("inf")},
            {"amount": 1e13, "tax_rate_percent": 20},
            {"amount": True, "tax_rate_percent": 20},
            {"amount": 100, "tax_rate_percent": 20, "is_inclusive": 1},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                CalculatorEngine.calculate_vat_salestax(**args)

    def test_freelance_hourly_rate(self):
        res = CalculatorEngine.calculate_freelance_invoice_rate(
            target_annual_take_home=80000,
            billable_hours_per_week=25,
            vacation_weeks=4,
            business_expenses_annual=5000,
            tax_rate_percent=25.0
        )
        self.assertGreater(res["recommended_hourly_rate"], 80)
        self.assertGreater(res["recommended_day_rate"], 400)

    def test_freelance_rate_rejects_zero_work_and_invalid_tax_or_time_inputs(self):
        for args in (
            {"billable_hours_per_week": 0},
            {"billable_hours_per_week": 169},
            {"vacation_weeks": 52},
            {"vacation_weeks": -1},
            {"tax_rate_percent": 100},
            {"tax_rate_percent": -1},
            {"tax_rate_percent": float("nan")},
            {"business_expenses_annual": -1},
            {"target_annual_take_home": float("inf")},
        ):
            values = {"target_annual_take_home": 80000}
            values.update(args)
            with self.subTest(args=args), self.assertRaises(ValueError):
                CalculatorEngine.calculate_freelance_invoice_rate(**values)

    def test_freelance_rate_reports_its_tax_and_day_rate_assumptions(self):
        result = CalculatorEngine.calculate_freelance_invoice_rate(
            target_annual_take_home=0, billable_hours_per_week=40,
            vacation_weeks=2, business_expenses_annual=0, tax_rate_percent=0,
        )
        self.assertEqual(result["recommended_hourly_rate"], 0)
        self.assertEqual(result["recommended_day_rate"], 0)
        self.assertEqual(result["assumptions"]["working_days_per_week"], 5)

    def test_margin_and_markup(self):
        res = CalculatorEngine.calculate_margin_markup(cost=80.0, revenue=100.0)
        self.assertEqual(res["profit"], 20.0)
        self.assertEqual(res["gross_margin_percent"], 20.0)
        self.assertEqual(res["markup_percent"], 25.0)

    def test_margin_and_markup_mark_zero_denominators_undefined(self):
        no_revenue = CalculatorEngine.calculate_margin_markup(cost=10, revenue=0)
        no_cost = CalculatorEngine.calculate_margin_markup(cost=0, revenue=10)
        self.assertIsNone(no_revenue["gross_margin_percent"])
        self.assertIsNone(no_cost["markup_percent"])
        self.assertEqual(no_revenue["profit"], -10.0)
        self.assertEqual(no_cost["profit"], 10.0)

    def test_margin_and_markup_round_currency_half_up_at_half_cent_ties(self):
        positive = CalculatorEngine.calculate_margin_markup(cost=0, revenue=1.125)
        negative = CalculatorEngine.calculate_margin_markup(cost=1.25, revenue=1.125)

        self.assertEqual(positive["profit"], 1.13)
        self.assertEqual(positive["gross_margin_percent"], 100.0)
        self.assertEqual(negative["profit"], -0.13)
        self.assertEqual(negative["gross_margin_percent"], -11.11)
        self.assertEqual(negative["markup_percent"], -10.0)

    def test_margin_and_markup_rejects_percentages_that_overflow_finite_output(self):
        with self.assertRaises(ValueError):
            CalculatorEngine.calculate_margin_markup(cost=1e12, revenue=1e-320)

    def test_margin_and_markup_validate_amounts_and_keep_losses(self):
        loss = CalculatorEngine.calculate_margin_markup(cost=120, revenue=100)
        self.assertEqual(loss["gross_margin_percent"], -20.0)
        self.assertEqual(loss["markup_percent"], -16.67)
        for args in (
            {"cost": -1, "revenue": 10}, {"cost": 10, "revenue": -1},
            {"cost": float("nan"), "revenue": 10},
            {"cost": 10, "revenue": float("inf")},
            {"cost": 1e13, "revenue": 10}, {"cost": True, "revenue": 10},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                CalculatorEngine.calculate_margin_markup(**args)

    def test_break_even(self):
        # Fixed costs $10,000, price $50, unit cost $25 -> Break even 400 units ($20,000)
        res = CalculatorEngine.calculate_break_even(fixed_costs=10000, price_per_unit=50, cost_per_unit=25)
        self.assertEqual(res["break_even_units"], 400)
        self.assertEqual(res["break_even_revenue"], 20000.0)

    def test_break_even_rounds_up_to_the_first_profitable_whole_unit(self):
        result = CalculatorEngine.calculate_break_even(
            fixed_costs=1000, price_per_unit=50, cost_per_unit=20
        )
        self.assertEqual(result["break_even_units"], 34)
        self.assertEqual(result["break_even_revenue"], 1700.0)
        self.assertGreaterEqual(34 * result["contribution_margin"], 1000)
        self.assertLess(33 * result["contribution_margin"], 1000)

    def test_break_even_accepts_zero_fixed_costs_and_rejects_invalid_amounts(self):
        zero = CalculatorEngine.calculate_break_even(
            fixed_costs=0, price_per_unit=50, cost_per_unit=20
        )
        self.assertEqual(zero["break_even_units"], 0)
        self.assertEqual(zero["break_even_revenue"], 0.0)

        invalid_cases = [
            {"fixed_costs": -1}, {"price_per_unit": -1},
            {"cost_per_unit": -1}, {"fixed_costs": float("nan")},
            {"price_per_unit": float("inf")}, {"fixed_costs": 1e13},
            {"price_per_unit": 10, "cost_per_unit": 10},
        ]
        for override in invalid_cases:
            args = {"fixed_costs": 100, "price_per_unit": 50, "cost_per_unit": 20}
            args.update(override)
            with self.subTest(override=override), self.assertRaises(ValueError):
                CalculatorEngine.calculate_break_even(**args)

    def test_depreciation(self):
        res = CalculatorEngine.calculate_depreciation(asset_cost=50000, salvage_value=5000, useful_life_years=5)
        self.assertEqual(res["annual_depreciation"], 9000.0)
        self.assertEqual(len(res["schedule"]), 5)

    def test_depreciation_cent_rounding_reconciles_to_salvage_value(self):
        result = CalculatorEngine.calculate_depreciation(
            asset_cost=10, salvage_value=0, useful_life_years=3
        )

        self.assertEqual([row["depreciation"] for row in result["schedule"]], [3.33, 3.33, 3.34])
        self.assertEqual([row["book_value"] for row in result["schedule"]], [6.67, 3.34, 0.0])
        self.assertEqual(sum(row["depreciation"] for row in result["schedule"]), result["total_depreciable"])
        self.assertEqual(result["schedule"][-1]["book_value"], 0.0)

    def test_depreciation_supports_fully_salvaged_and_zero_cost_assets(self):
        no_depreciation = CalculatorEngine.calculate_depreciation(
            asset_cost=25, salvage_value=25, useful_life_years=1
        )
        zero_asset = CalculatorEngine.calculate_depreciation(
            asset_cost=0, salvage_value=0, useful_life_years=5
        )

        self.assertEqual(no_depreciation["total_depreciable"], 0.0)
        self.assertEqual(no_depreciation["schedule"], [{"year": 1, "depreciation": 0.0, "book_value": 25.0}])
        self.assertEqual(zero_asset["schedule"][-1]["book_value"], 0.0)

    def test_depreciation_rejects_invalid_money_and_life_inputs(self):
        valid = {"asset_cost": 100, "salvage_value": 10, "useful_life_years": 5}
        invalid_cases = (
            {"asset_cost": True}, {"asset_cost": "100"},
            {"asset_cost": float("nan")}, {"salvage_value": float("inf")},
            {"asset_cost": -1}, {"asset_cost": 1e13},
            {"salvage_value": -1}, {"salvage_value": 101},
            {"useful_life_years": 0}, {"useful_life_years": -1},
            {"useful_life_years": 1.5}, {"useful_life_years": True},
            {"useful_life_years": 101},
        )

        for override in invalid_cases:
            args = {**valid, **override}
            with self.subTest(override=override), self.assertRaises(ValueError):
                CalculatorEngine.calculate_depreciation(**args)

    def test_simple_interest_supports_years_and_months_with_explicit_totals(self):
        years = CalculatorEngine.calculate_simple_interest(
            principal=1000, annual_rate_percent=10, time_value=2, time_unit="years"
        )
        months = CalculatorEngine.calculate_simple_interest(
            principal=1000, annual_rate_percent=10, time_value=24, time_unit="months"
        )

        self.assertEqual(years["interest_amount"], 200.0)
        self.assertEqual(years["total_amount"], 1200.0)
        self.assertEqual(years["time_in_years"], 2.0)
        self.assertEqual(months["interest_amount"], years["interest_amount"])
        self.assertEqual(months["assumptions"]["rate_basis"], "nominal_annual")

    def test_simple_interest_rounds_half_up_and_accepts_zero_rate(self):
        half_cent = CalculatorEngine.calculate_simple_interest(
            principal=0.01, annual_rate_percent=50, time_value=1, time_unit="years"
        )
        zero_rate = CalculatorEngine.calculate_simple_interest(
            principal=123.45, annual_rate_percent=0, time_value=12, time_unit="months"
        )

        self.assertEqual(half_cent["interest_amount"], 0.01)
        self.assertEqual(zero_rate["interest_amount"], 0.0)
        self.assertEqual(zero_rate["total_amount"], 123.45)

    def test_simple_interest_rejects_invalid_amounts_rates_and_durations(self):
        valid = {"principal": 100, "annual_rate_percent": 5, "time_value": 1, "time_unit": "years"}
        invalid_cases = (
            {"principal": True}, {"principal": -1}, {"principal": float("inf")},
            {"principal": 1e13}, {"annual_rate_percent": -1},
            {"annual_rate_percent": 1001}, {"annual_rate_percent": float("nan")},
            {"time_value": 0}, {"time_value": -1}, {"time_value": float("inf")},
            {"time_value": 1201, "time_unit": "months"},
            {"time_value": 101, "time_unit": "years"}, {"time_unit": "days"},
            {"time_unit": []},
        )

        for override in invalid_cases:
            args = {**valid, **override}
            with self.subTest(override=override), self.assertRaises(ValueError):
                CalculatorEngine.calculate_simple_interest(**args)

if __name__ == "__main__":
    unittest.main()
