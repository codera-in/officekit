"""Resource and numeric-safety regressions for the expression evaluator."""

import unittest

from officekit.engines.engine_units import MathEvaluator


class MathEvaluatorBoundsTests(unittest.TestCase):
    def test_accepts_precedence_unary_and_bounded_power(self):
        self.assertEqual(MathEvaluator.evaluate("2 + 3 * 4"), 14)
        self.assertEqual(MathEvaluator.evaluate("-(10 - 2) / 4"), -2.0)
        self.assertEqual(MathEvaluator.evaluate("2 ^ 3"), 8)
        self.assertEqual(MathEvaluator.evaluate("2 ^ 3 ^ 2"), 512)
        self.assertEqual(MathEvaluator.evaluate("-2 ^ 2"), -4)
        self.assertEqual(MathEvaluator.evaluate("2 ** 332"), 2 ** 332)

    def test_rejects_boolean_nonfinite_and_complex_numbers(self):
        for expression in ("True + 1", "1e309", "(-1) ** 0.5"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                MathEvaluator.evaluate(expression)

    def test_rejects_oversized_expressions_ast_nodes_and_nesting(self):
        def balanced_sum(count):
            if count == 1:
                return "1"
            middle = count // 2
            return f"({balanced_sum(middle)} + {balanced_sum(count - middle)})"

        expressions = (
            "1" * 513,
            balanced_sum(70),
            "1 + " * 33 + "1",
        )
        for expression in expressions:
            with self.subTest(length=len(expression)), self.assertRaises(ValueError):
                MathEvaluator.evaluate(expression)

    def test_rejects_arithmetic_that_exceeds_bounded_result_range(self):
        for expression in ("2 ** 334", "2 ** 1025", "10 ** 101", "0.01 ** -101"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                MathEvaluator.evaluate(expression)

    def test_rejects_empty_input_and_division_by_zero(self):
        for expression in ("", "   ", "1 / 0"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                MathEvaluator.evaluate(expression)

    def test_evaluates_scientific_constants_and_common_functions(self):
        self.assertAlmostEqual(MathEvaluator.evaluate("2 * pi"), 2 * 3.141592653589793)
        self.assertEqual(MathEvaluator.evaluate("tau / 2"), MathEvaluator.evaluate("pi"))
        self.assertEqual(MathEvaluator.evaluate("sqrt(81) + abs(-3)"), 12)
        self.assertEqual(MathEvaluator.evaluate("sin(pi / 2) + cos(0) + tan(0)"), 2)
        self.assertAlmostEqual(MathEvaluator.evaluate("asin(1) + acos(1) + atan(0)"), 1.5707963267948966)
        self.assertAlmostEqual(MathEvaluator.evaluate("atan2(1, 0)"), 1.5707963267948966)
        self.assertEqual(MathEvaluator.evaluate("log(8, 2) + log2(8) + log10(100) + log(e) + ln(e)"), 10)
        self.assertEqual(MathEvaluator.evaluate("floor(2.9) + ceil(1.1) + round(1.25, 1)"), 5.2)
        self.assertEqual(MathEvaluator.evaluate("factorial(5) + hypot(3, 4)"), 125)
        self.assertEqual(MathEvaluator.evaluate("factorial(0) + min(2, 1) + max(3, 4)"), 6)
        self.assertEqual(MathEvaluator.evaluate("sinh(0) + cosh(0) + tanh(0)"), 1)
        self.assertAlmostEqual(MathEvaluator.evaluate("degrees(pi) + radians(180)"), 183.1415926535898)

    def test_trigonometry_supports_explicit_radian_and_degree_modes(self):
        self.assertAlmostEqual(MathEvaluator.evaluate("sin(pi / 2)"), 1)
        self.assertAlmostEqual(MathEvaluator.evaluate("sin(90)", angle_mode="degrees"), 1)
        self.assertAlmostEqual(MathEvaluator.evaluate("asin(1)", angle_mode="degrees"), 90)
        self.assertAlmostEqual(MathEvaluator.evaluate("atan2(1, 0)", angle_mode="degrees"), 90)
        with self.assertRaises(ValueError):
            MathEvaluator.evaluate("sin(90)", angle_mode="gradians")

    def test_scientific_functions_remain_bounded_and_sandboxed(self):
        for expression in (
            "unknown_constant + 1",
            "unknown_function(1)",
            "sqrt()",
            "sqrt(1, 2)",
            "log(10, 2, 3)",
            "sin(x=1)",
            "(1).__class__",
            "__import__('os')",
            "factorial(5.5)",
            "factorial(-1)",
            "factorial(70)",
            "round(1.2, 13)",
            "round(1.2, True)",
            "sqrt(-1)",
            "log(0)",
            "tan(pi / 2) ** 20",
            "1 @ 2",
            "~1",
        ):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                MathEvaluator.evaluate(expression)

    def test_internal_numeric_guards_reject_unsupported_runtime_values(self):
        with self.assertRaises(ValueError):
            MathEvaluator.evaluate(42)
        with self.assertRaises(ValueError):
            MathEvaluator._validate_number(1 << 1024)
        with self.assertRaises(ValueError):
            MathEvaluator._validate_number(1e101)
        with self.assertRaises(ValueError):
            MathEvaluator._integer_argument("5", "test argument")
        self.assertEqual(MathEvaluator.evaluate("0.5 ** -2"), 4.0)


if __name__ == "__main__":
    unittest.main()
