"""Independent vectors and hostile-boundary coverage for everyday percentages."""

import unittest

from fastapi.testclient import TestClient

from app import app
from officekit.engines.engine_calculators import CalculatorEngine


class EverydayPercentageEngineTests(unittest.TestCase):
    def test_percent_of_uses_decimal_half_up_rounding_and_supports_zero_and_over_one_hundred(self):
        self.assertEqual(CalculatorEngine.calculate_percent_of(15, 240)["result"], 36.0)
        self.assertEqual(CalculatorEngine.calculate_percent_of(0, 42)["result"], 0.0)
        self.assertEqual(CalculatorEngine.calculate_percent_of(125, 8)["result"], 10.0)
        self.assertEqual(CalculatorEngine.calculate_percent_of(12.5, 1)["result"], 0.13)

    def test_percentage_change_handles_increase_decrease_zero_final_and_half_up(self):
        increase = CalculatorEngine.calculate_percentage_change(80, 100)
        decrease = CalculatorEngine.calculate_percentage_change(100, 80)
        zero = CalculatorEngine.calculate_percentage_change(100, 0)
        self.assertEqual((increase["change_value"], increase["change_percent"], increase["direction"]), (20.0, 25.0, "increase"))
        self.assertEqual((decrease["change_value"], decrease["change_percent"], decrease["direction"]), (-20.0, -20.0, "decrease"))
        self.assertEqual((zero["change_value"], zero["change_percent"], zero["direction"]), (-100.0, -100.0, "decrease"))
        self.assertEqual(CalculatorEngine.calculate_percentage_change(8, 9)["change_percent"], 12.5)
        self.assertEqual(CalculatorEngine.calculate_percentage_change(100, 100)["direction"], "no_change")
        self.assertEqual(CalculatorEngine.calculate_percentage_change(1, 0.995)["change_value"], -0.01)

    def test_discount_reconciles_savings_and_final_price_at_zero_and_full_discount(self):
        normal = CalculatorEngine.calculate_discount(100, 20)
        free = CalculatorEngine.calculate_discount(42.25, 100)
        unchanged = CalculatorEngine.calculate_discount(42.25, 0)
        self.assertEqual((normal["savings"], normal["discounted_price"]), (20.0, 80.0))
        self.assertEqual((free["savings"], free["discounted_price"]), (42.25, 0.0))
        self.assertEqual((unchanged["savings"], unchanged["discounted_price"]), (0.0, 42.25))
        tie = CalculatorEngine.calculate_discount(1, 0.5)
        self.assertEqual((tie["savings"], tie["discounted_price"]), (0.01, 0.99))

    def test_engine_rejects_boolean_nonfinite_negative_zero_denominator_and_out_of_range_inputs(self):
        bad_percent_values = ((True, 10), (float("nan"), 1), (15, float("inf")), (-1, 1), (1_000_001, 1), (1, -1))
        for percent, value in bad_percent_values:
            with self.subTest(percent=percent, value=value), self.assertRaises(ValueError):
                CalculatorEngine.calculate_percent_of(percent, value)
        for original, new in ((0, 1), (True, 1), (1, float("nan")), (-1, 1), (1, 1e12 + 1), (1e-12, 1e12)):
            with self.subTest(original=original, new=new), self.assertRaises(ValueError):
                CalculatorEngine.calculate_percentage_change(original, new)
        for price, percent in ((-1, 5), (10, -1), (10, 100.01), (True, 5), (10, float("inf"))):
            with self.subTest(price=price, percent=percent), self.assertRaises(ValueError):
                CalculatorEngine.calculate_discount(price, percent)


class EverydayPercentageApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_http_routes_match_independent_percent_change_and_discount_vectors(self):
        vectors = (
            ("/api/calculator/percent-of", {"percent": 15, "value": 240}, "result", 36.0),
            ("/api/calculator/percentage-change", {"original_value": 80, "new_value": 100}, "change_percent", 25.0),
            ("/api/calculator/discount", {"price": 100, "discount_percent": 20}, "discounted_price", 80.0),
        )
        for route, request, result_key, expected in vectors:
            with self.subTest(route=route):
                response = self.client.post(route, json=request)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()[result_key], expected)
                self.assertEqual(response.json()["assumptions"], {
                    "rounding": "half_up",
                    "precision": "0.01",
                    "currency": "not_inferred",
                    "taxes": "excluded",
                })

    def test_http_rejects_missing_extra_coerced_nonfinite_and_out_of_range_inputs(self):
        invalid = (
            ("/api/calculator/percent-of", {"percent": 15}),
            ("/api/calculator/percent-of", {"percent": True, "value": 240}),
            ("/api/calculator/percent-of", {"percent": 15, "value": 240, "unit": "USD"}),
            ("/api/calculator/percent-of", {"percent": 1_000_001, "value": 1}),
            ("/api/calculator/percentage-change", {"original_value": 0, "new_value": 1}),
            ("/api/calculator/percentage-change", {"original_value": 100, "new_value": "80"}),
            ("/api/calculator/discount", {"price": 100, "discount_percent": 100.01}),
        )
        for route, payload in invalid:
            with self.subTest(route=route, payload=payload):
                self.assertEqual(self.client.post(route, json=payload).status_code, 422)
        non_finite = self.client.post(
            "/api/calculator/discount",
            content='{"price":Infinity,"discount_percent":10}',
            headers={"content-type": "application/json"},
        )
        self.assertEqual(non_finite.status_code, 422)


if __name__ == "__main__":
    unittest.main()
