import math
import os
import time
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

from officekit.engines.engine_calculators_extra import (
    MESSAGES,
    ExtendedCalculatorEngine as Engine,
)


def assert_value_error(test, message, function, *args, **kwargs):
    with test.assertRaises(ValueError) as caught:
        function(*args, **kwargs)
    test.assertEqual(str(caught.exception), message)


class WeightedAverageTests(unittest.TestCase):
    def test_unweighted_mean_of_three_values(self):
        result = Engine.calculate_weighted_average([1, 2, 3])
        self.assertEqual(result["mean"], 2.0)
        self.assertEqual(result["count_used"], 3)
        self.assertEqual(result["count_skipped"], 0)
        self.assertEqual(result["weight_total"], 3.0)
        self.assertFalse(result["weighted"])
        self.assertEqual(
            result["assumptions"],
            {"precision": "1e-10", "rounding": "half_up", "missing": "reject"},
        )

    def test_weighted_mean_uses_weights(self):
        result = Engine.calculate_weighted_average([80, 90], [1, 3])
        self.assertEqual(result["mean"], 87.5)
        self.assertEqual(result["weight_total"], 4.0)
        self.assertTrue(result["weighted"])

    def test_zero_weight_is_allowed_and_excludes_value(self):
        result = Engine.calculate_weighted_average([10, 20], [0, 5])
        self.assertEqual(result["mean"], 20.0)
        self.assertEqual(result["weight_total"], 5.0)

    def test_all_zero_weights_are_rejected(self):
        assert_value_error(self, MESSAGES["zero_weight_total"], Engine.calculate_weighted_average, [1, 2], [0, 0])

    def test_negative_weight_is_rejected(self):
        assert_value_error(self, MESSAGES["negative_weight"], Engine.calculate_weighted_average, [1, 2], [1, -1])

    def test_weight_count_mismatch_is_rejected(self):
        assert_value_error(self, MESSAGES["length_mismatch"], Engine.calculate_weighted_average, [1, 2], [1])

    def test_null_value_is_rejected_under_reject_policy(self):
        assert_value_error(self, MESSAGES["missing_value"], Engine.calculate_weighted_average, [1, None])

    def test_skip_policy_drops_null_values_and_counts_them(self):
        result = Engine.calculate_weighted_average([1, None, 3], missing="skip")
        self.assertEqual(result["mean"], 2.0)
        self.assertEqual(result["count_used"], 2)
        self.assertEqual(result["count_skipped"], 1)
        self.assertEqual(result["assumptions"]["missing"], "skip")

    def test_skip_policy_drops_value_with_null_weight(self):
        result = Engine.calculate_weighted_average([1, 5], [None, 2], missing="skip")
        self.assertEqual(result["mean"], 5.0)
        self.assertEqual(result["count_skipped"], 1)

    def test_null_weight_is_rejected_under_reject_policy(self):
        assert_value_error(self, MESSAGES["missing_value"], Engine.calculate_weighted_average, [1, 2], [None, 2])

    def test_skip_policy_with_nothing_left_is_rejected(self):
        assert_value_error(
            self, MESSAGES["no_values_after_skip"], Engine.calculate_weighted_average, [None], missing="skip"
        )

    def test_empty_list_is_rejected(self):
        assert_value_error(self, MESSAGES["value_count"], Engine.calculate_weighted_average, [])

    def test_more_than_ten_thousand_values_is_rejected(self):
        assert_value_error(self, MESSAGES["value_count"], Engine.calculate_weighted_average, [1] * 10001)

    def test_ten_thousand_values_are_accepted(self):
        self.assertEqual(Engine.calculate_weighted_average([1] * 10000)["mean"], 1.0)

    def test_value_bounds_are_inclusive_at_one_trillion(self):
        self.assertEqual(Engine.calculate_weighted_average([1e12])["mean"], 1e12)
        assert_value_error(self, MESSAGES["value_range"], Engine.calculate_weighted_average, [1e12 + 1])
        assert_value_error(self, MESSAGES["value_range"], Engine.calculate_weighted_average, [-1e12 - 1])

    def test_weight_bounds_are_inclusive_at_one_trillion(self):
        self.assertEqual(Engine.calculate_weighted_average([1, 2], [1e12, 1e12])["mean"], 1.5)
        assert_value_error(self, MESSAGES["weight_range"], Engine.calculate_weighted_average, [1], [1e12 + 1])

    def test_bool_string_nan_and_infinity_are_rejected(self):
        for bad in (True, "2", float("nan"), float("inf"), -float("inf")):
            with self.subTest(bad=bad):
                assert_value_error(self, MESSAGES["value_type"], Engine.calculate_weighted_average, [bad])

    def test_bool_weight_is_rejected(self):
        assert_value_error(self, MESSAGES["weight_type"], Engine.calculate_weighted_average, [1], [True])

    def test_tie_at_precision_quantum_rounds_half_up(self):
        # 2.5e-10 at the 1e-10 quantum: half-up gives 3e-10, half-even would give 2e-10.
        result = Engine.calculate_weighted_average([Decimal("0.00000000025")])
        self.assertEqual(result["mean"], 3e-10)
        below = Engine.calculate_weighted_average([Decimal("0.000000000149")])
        self.assertEqual(below["mean"], 1e-10)


class FractionTests(unittest.TestCase):
    def test_simplify_two_quarters_to_one_half(self):
        result = Engine.calculate_fraction("simplify", {"numerator": 2, "denominator": 4})
        self.assertEqual(result["numerator"], "1")
        self.assertEqual(result["denominator"], "2")
        self.assertEqual(result["decimal"], "0.5")
        self.assertFalse(result["is_integer"])
        self.assertEqual(result["assumptions"], {"exact": True})

    def test_add_one_third_and_one_sixth(self):
        result = Engine.calculate_fraction("add", {"numerator": 1, "denominator": 3}, {"numerator": 1, "denominator": 6})
        self.assertEqual((result["numerator"], result["denominator"]), ("1", "2"))

    def test_subtract_multiply_divide(self):
        left = {"numerator": 3, "denominator": 4}
        right = {"numerator": 1, "denominator": 2}
        self.assertEqual(Engine.calculate_fraction("subtract", left, right)["numerator"], "1")
        self.assertEqual(Engine.calculate_fraction("subtract", left, right)["denominator"], "4")
        product = Engine.calculate_fraction("multiply", left, right)
        self.assertEqual((product["numerator"], product["denominator"]), ("3", "8"))
        quotient = Engine.calculate_fraction("divide", left, right)
        self.assertEqual((quotient["numerator"], quotient["denominator"]), ("3", "2"))

    def test_sign_is_normalised_to_numerator(self):
        result = Engine.calculate_fraction("simplify", {"numerator": 1, "denominator": -2})
        self.assertEqual((result["numerator"], result["denominator"]), ("-1", "2"))
        self.assertEqual(result["decimal"], "-0.5")

    def test_zero_denominator_is_rejected(self):
        assert_value_error(
            self, MESSAGES["zero_denominator"], Engine.calculate_fraction, "simplify", {"numerator": 1, "denominator": 0}
        )

    def test_divide_by_zero_fraction_is_rejected(self):
        assert_value_error(
            self,
            MESSAGES["divide_by_zero"],
            Engine.calculate_fraction,
            "divide",
            {"numerator": 1, "denominator": 2},
            {"numerator": 0, "denominator": 5},
        )

    def test_right_operand_is_required_except_for_simplify(self):
        for operation in ("add", "subtract", "multiply", "divide"):
            with self.subTest(operation=operation):
                assert_value_error(
                    self,
                    MESSAGES["right_required"],
                    Engine.calculate_fraction,
                    operation,
                    {"numerator": 1, "denominator": 2},
                )

    def test_right_operand_is_rejected_for_simplify(self):
        assert_value_error(
            self,
            MESSAGES["right_forbidden"],
            Engine.calculate_fraction,
            "simplify",
            {"numerator": 1, "denominator": 2},
            {"numerator": 1, "denominator": 2},
        )

    def test_unknown_operation_is_rejected(self):
        assert_value_error(
            self, MESSAGES["operation"], Engine.calculate_fraction, "power", {"numerator": 1, "denominator": 2}
        )

    def test_large_values_stay_exact_as_strings(self):
        result = Engine.calculate_fraction(
            "multiply",
            {"numerator": 10**12, "denominator": 3},
            {"numerator": 10**12 - 1, "denominator": 10**12},
        )
        expected = (10**12) * (10**12 - 1)
        expected_denominator = 3 * 10**12
        divisor = math.gcd(expected, expected_denominator)
        self.assertEqual(result["numerator"], str(expected // divisor))
        self.assertEqual(result["denominator"], str(expected_denominator // divisor))

    def test_bound_of_one_trillion_is_accepted_and_beyond_is_rejected(self):
        result = Engine.calculate_fraction("simplify", {"numerator": 10**12, "denominator": 10**12})
        self.assertEqual((result["numerator"], result["denominator"]), ("1", "1"))
        self.assertTrue(result["is_integer"])
        assert_value_error(
            self,
            MESSAGES["fraction_range"],
            Engine.calculate_fraction,
            "simplify",
            {"numerator": 10**12 + 1, "denominator": 1},
        )
        assert_value_error(
            self,
            MESSAGES["fraction_range"],
            Engine.calculate_fraction,
            "simplify",
            {"numerator": 1, "denominator": -(10**12) - 1},
        )

    def test_mixed_number_for_improper_fraction(self):
        result = Engine.calculate_fraction("simplify", {"numerator": 7, "denominator": 3})
        self.assertEqual(result["mixed"], {"whole": "2", "numerator": "1", "denominator": "3"})

    def test_mixed_number_for_negative_proper_fraction_puts_sign_on_the_fraction(self):
        result = Engine.calculate_fraction("simplify", {"numerator": -1, "denominator": 2})
        self.assertEqual(result["mixed"], {"whole": "0", "numerator": "-1", "denominator": "2"})

    def test_mixed_number_for_negative_improper_fraction_puts_sign_on_the_whole(self):
        result = Engine.calculate_fraction("simplify", {"numerator": -7, "denominator": 2})
        self.assertEqual(result["mixed"], {"whole": "-3", "numerator": "1", "denominator": "2"})
        result = Engine.calculate_fraction("simplify", {"numerator": -7, "denominator": 3})
        self.assertEqual(result["mixed"], {"whole": "-2", "numerator": "1", "denominator": "3"})

    def test_negative_whole_number_has_no_remainder(self):
        result = Engine.calculate_fraction("simplify", {"numerator": -4, "denominator": 2})
        self.assertEqual(result["mixed"], {"whole": "-2", "numerator": "0", "denominator": "1"})

    def test_integer_result_is_flagged(self):
        result = Engine.calculate_fraction("simplify", {"numerator": 6, "denominator": 3})
        self.assertTrue(result["is_integer"])
        self.assertEqual(result["decimal"], "2")
        self.assertEqual(result["mixed"], {"whole": "2", "numerator": "0", "denominator": "1"})

    def test_decimal_has_twenty_significant_digits_rounded_half_up(self):
        result = Engine.calculate_fraction("simplify", {"numerator": 1, "denominator": 3})
        self.assertEqual(result["decimal"], "0.33333333333333333333")
        big = Engine.calculate_fraction("simplify", {"numerator": 10**12, "denominator": 7})
        self.assertEqual(big["decimal"], "142857142857.14285714")
        half = Engine.calculate_fraction("simplify", {"numerator": 2, "denominator": 3})
        self.assertEqual(half["decimal"], "0.66666666666666666667")

    def test_fraction_bool_and_float_parts_are_rejected(self):
        assert_value_error(
            self,
            MESSAGES["fraction_type"],
            Engine.calculate_fraction,
            "simplify",
            {"numerator": True, "denominator": 2},
        )
        assert_value_error(
            self,
            MESSAGES["fraction_type"],
            Engine.calculate_fraction,
            "simplify",
            {"numerator": 1.5, "denominator": 2},
        )


class RoiTests(unittest.TestCase):
    def test_return_of_120_on_100_is_twenty_percent(self):
        result = Engine.calculate_roi(100, 120)
        self.assertEqual(result["net_gain"], 20.0)
        self.assertEqual(result["roi_percent"], 20.0)
        self.assertEqual(result["total_cost"], 100.0)
        self.assertEqual(
            result["assumptions"],
            {"annualised": False, "fees": "added_to_cost", "currency_precision": "0.01", "percent_precision": "0.01"},
        )

    def test_fees_are_added_to_cost(self):
        result = Engine.calculate_roi(100, 120, 5)
        self.assertEqual(result["total_cost"], 105.0)
        self.assertEqual(result["net_gain"], 15.0)
        self.assertEqual(result["roi_percent"], 14.29)

    def test_returned_below_cost_is_negative_roi(self):
        result = Engine.calculate_roi(100, 50)
        self.assertEqual(result["net_gain"], -50.0)
        self.assertEqual(result["roi_percent"], -50.0)

    def test_zero_return_is_minus_one_hundred_percent(self):
        self.assertEqual(Engine.calculate_roi(100, 0)["roi_percent"], -100.0)

    def test_zero_invested_is_rejected(self):
        assert_value_error(self, MESSAGES["invested_range"], Engine.calculate_roi, 0, 10)

    def test_negative_invested_or_returned_or_fees_are_rejected(self):
        assert_value_error(self, MESSAGES["invested_range"], Engine.calculate_roi, -1, 10)
        assert_value_error(self, MESSAGES["returned_range"], Engine.calculate_roi, 10, -1)
        assert_value_error(self, MESSAGES["fees_range"], Engine.calculate_roi, 10, 10, -1)

    def test_bounds_are_inclusive_at_one_trillion(self):
        self.assertEqual(Engine.calculate_roi(1e12, 1e12)["roi_percent"], 0.0)
        assert_value_error(self, MESSAGES["invested_range"], Engine.calculate_roi, 1e12 + 1, 0)
        assert_value_error(self, MESSAGES["returned_range"], Engine.calculate_roi, 1, 1e12 + 1)
        assert_value_error(self, MESSAGES["fees_range"], Engine.calculate_roi, 1, 1, 1e12 + 1)

    def test_half_up_tie_at_percent_precision(self):
        result = Engine.calculate_roi(800, 801)
        self.assertEqual(result["roi_percent"], 0.13)

    def test_bool_string_and_non_finite_are_rejected(self):
        for bad in (True, "100", float("nan"), float("inf")):
            with self.subTest(bad=bad):
                assert_value_error(self, MESSAGES["value_type"], Engine.calculate_roi, bad, 10)
                assert_value_error(self, MESSAGES["value_type"], Engine.calculate_roi, 10, bad)
                assert_value_error(self, MESSAGES["value_type"], Engine.calculate_roi, 10, 10, bad)


class CagrTests(unittest.TestCase):
    def test_power_past_decimal_range_is_a_fixed_range_error_not_an_overflow(self):
        assert_value_error(self, MESSAGES["result_range"], Engine.calculate_cagr, 1, 1000000000000, Decimal("0.000001"))

    def test_hundred_to_one_twenty_one_over_two_years_is_ten_percent(self):
        result = Engine.calculate_cagr(100, 121, 2)
        self.assertEqual(result["cagr_percent"], 10.0)
        self.assertEqual(result["growth_multiple"], 1.21)
        self.assertEqual(result["assumptions"], {"compounding": "annual", "percent_precision": "0.01"})

    def test_fractional_years_match_independent_float_oracle(self):
        result = Engine.calculate_cagr(100, 121, 1.5)
        expected = (1.21 ** (1 / 1.5) - 1) * 100
        self.assertAlmostEqual(result["cagr_percent"], round(expected, 2), places=2)

    def test_end_of_zero_is_minus_one_hundred_percent(self):
        result = Engine.calculate_cagr(100, 0, 3)
        self.assertEqual(result["cagr_percent"], -100.0)
        self.assertEqual(result["growth_multiple"], 0.0)

    def test_decline_over_one_year(self):
        self.assertEqual(Engine.calculate_cagr(100, 50, 1)["cagr_percent"], -50.0)

    def test_start_must_be_positive(self):
        assert_value_error(self, MESSAGES["start_range"], Engine.calculate_cagr, 0, 10, 1)
        assert_value_error(self, MESSAGES["start_range"], Engine.calculate_cagr, -5, 10, 1)
        assert_value_error(self, MESSAGES["start_range"], Engine.calculate_cagr, 1e12 + 1, 10, 1)

    def test_end_must_not_be_negative(self):
        assert_value_error(self, MESSAGES["end_range"], Engine.calculate_cagr, 10, -1, 1)
        assert_value_error(self, MESSAGES["end_range"], Engine.calculate_cagr, 10, 1e12 + 1, 1)

    def test_years_must_be_positive_and_at_most_one_hundred(self):
        assert_value_error(self, MESSAGES["years_range"], Engine.calculate_cagr, 10, 10, 0)
        assert_value_error(self, MESSAGES["years_range"], Engine.calculate_cagr, 10, 10, -1)
        assert_value_error(self, MESSAGES["years_range"], Engine.calculate_cagr, 10, 10, 100.5)
        self.assertEqual(Engine.calculate_cagr(10, 10, 100)["cagr_percent"], 0.0)

    def test_bool_string_and_non_finite_are_rejected(self):
        for bad in (True, "2", float("nan"), float("inf")):
            with self.subTest(bad=bad):
                assert_value_error(self, MESSAGES["value_type"], Engine.calculate_cagr, bad, 10, 1)
                assert_value_error(self, MESSAGES["value_type"], Engine.calculate_cagr, 10, bad, 1)
                assert_value_error(self, MESSAGES["value_type"], Engine.calculate_cagr, 10, 10, bad)


@contextmanager
def pinned_local_zone(name):
    # The DST guard must not depend on the runner's zone, so the test pins the process zone and restores it after.
    previous = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = previous
        time.tzset()


@unittest.skipUnless(hasattr(time, "tzset"), "the zone can only be pinned where time.tzset exists")
class DateDifferenceTests(unittest.TestCase):
    def test_spans_across_dst_changes_are_whole_days_with_no_zone_drift(self):
        # C17: date-only inputs have no zone. Each span crosses a DST change in America/New_York
        # (spring forward 2026-03-08 02:00, fall back 2026-11-01 02:00), and each is still whole calendar days.
        with pinned_local_zone("America/New_York"):
            # An unknown zone falls back to UTC silently, so prove the pin took effect before relying on it.
            self.assertEqual(datetime(2026, 3, 8, 12).astimezone().utcoffset(), timedelta(hours=-4))
            spring = Engine.calculate_date_difference("2026-03-08", "2026-03-09")
            self.assertEqual((spring["days"], spring["weeks"], spring["week_days"]), (1, 0, 1))
            autumn = Engine.calculate_date_difference("2026-11-01", "2026-11-02")
            self.assertEqual((autumn["days"], autumn["weeks"], autumn["week_days"]), (1, 0, 1))
        full_year = Engine.calculate_date_difference("2026-03-01", "2027-03-01")
        self.assertEqual(full_year["days"], 365)
        self.assertEqual(full_year["assumptions"]["time_zone"], "none")

    def test_leap_span_is_395_days_one_year_one_month_one_day(self):
        result = Engine.calculate_date_difference("2024-01-31", "2025-03-01")
        self.assertEqual(result["days"], 395)
        self.assertEqual(result["direction"], "forward")
        self.assertEqual((result["years"], result["months"], result["rem_days"]), (1, 1, 1))
        self.assertEqual((result["weeks"], result["week_days"]), (56, 3))
        self.assertEqual(result["assumptions"], {"month_end": "clamp", "time_zone": "none"})

    def test_leap_february_to_march_is_two_days(self):
        result = Engine.calculate_date_difference("2024-02-28", "2024-03-01")
        self.assertEqual(result["days"], 2)
        self.assertEqual((result["years"], result["months"], result["rem_days"]), (0, 0, 2))

    def test_reversed_order_is_negative_and_backward(self):
        result = Engine.calculate_date_difference("2025-03-01", "2024-01-31")
        self.assertEqual(result["days"], -395)
        self.assertEqual(result["direction"], "backward")
        self.assertEqual((result["years"], result["months"], result["rem_days"]), (1, 1, 1))

    def test_inclusive_adds_one_day_in_the_direction_of_travel(self):
        self.assertEqual(Engine.calculate_date_difference("2024-01-01", "2024-01-03", True)["days"], 3)
        self.assertEqual(Engine.calculate_date_difference("2024-01-03", "2024-01-01", True)["days"], -3)

    def test_same_date_is_zero_and_same_direction(self):
        result = Engine.calculate_date_difference("2024-05-05", "2024-05-05")
        self.assertEqual((result["days"], result["direction"]), (0, "same"))
        inclusive = Engine.calculate_date_difference("2024-05-05", "2024-05-05", True)
        self.assertEqual((inclusive["days"], inclusive["direction"]), (1, "same"))

    def test_month_end_clamp_across_february(self):
        result = Engine.calculate_date_difference("2023-01-31", "2023-02-28")
        self.assertEqual((result["years"], result["months"], result["rem_days"]), (0, 1, 0))
        self.assertEqual(result["days"], 28)

    def test_range_boundaries_are_accepted(self):
        result = Engine.calculate_date_difference("1600-01-01", "2400-12-31")
        self.assertEqual(result["days"], (date(2400, 12, 31) - date(1600, 1, 1)).days)

    def test_invalid_and_out_of_range_dates_are_rejected(self):
        for bad in ("2024-1-5", "20240105", "2024-02-30", "1599-12-31", "2401-01-01", "2024-01-01\n", None, 20240101, True):
            with self.subTest(bad=bad):
                assert_value_error(self, MESSAGES["date"], Engine.calculate_date_difference, bad, "2024-01-01")

    def test_inclusive_must_be_a_boolean(self):
        assert_value_error(self, MESSAGES["inclusive_type"], Engine.calculate_date_difference, "2024-01-01", "2024-01-02", 1)


class AgeTests(unittest.TestCase):
    def test_leap_birthday_ages_on_february_28_in_common_years(self):
        self.assertEqual(Engine.calculate_age("2000-02-29", "2001-02-27")["years"], 0)
        on_feb_28 = Engine.calculate_age("2000-02-29", "2001-02-28")
        self.assertEqual((on_feb_28["years"], on_feb_28["months"], on_feb_28["days"]), (1, 0, 0))
        self.assertEqual(on_feb_28["total_days"], 365)

    def test_month_and_day_breakdown_before_first_birthday(self):
        result = Engine.calculate_age("2000-02-29", "2001-02-27")
        self.assertEqual((result["years"], result["months"], result["days"]), (0, 11, 29))
        self.assertEqual(result["total_days"], 364)
        self.assertEqual(result["next_birthday"], "2001-02-28")
        self.assertEqual(result["days_to_next_birthday"], 1)
        self.assertEqual(result["assumptions"], {"leap_birthday": "feb_28"})

    def test_day_after_first_birthday_in_common_year(self):
        result = Engine.calculate_age("2000-02-29", "2001-03-01")
        self.assertEqual((result["years"], result["months"], result["days"]), (1, 0, 1))
        self.assertEqual(result["next_birthday"], "2002-02-28")
        self.assertEqual(result["days_to_next_birthday"], 364)

    def test_next_birthday_on_feb_29_in_a_leap_year(self):
        result = Engine.calculate_age("2000-02-29", "2024-02-28")
        self.assertEqual(result["next_birthday"], "2024-02-29")
        self.assertEqual(result["days_to_next_birthday"], 1)

    def test_birthday_today_has_zero_days_to_next(self):
        result = Engine.calculate_age("1990-06-15", "2026-06-15")
        self.assertEqual((result["years"], result["months"], result["days"]), (36, 0, 0))
        self.assertEqual(result["next_birthday"], "2026-06-15")
        self.assertEqual(result["days_to_next_birthday"], 0)

    def test_birth_equal_to_as_of_is_zero(self):
        result = Engine.calculate_age("2026-10-22", "2026-10-22")
        self.assertEqual((result["years"], result["months"], result["days"], result["total_days"]), (0, 0, 0, 0))
        self.assertEqual(result["days_to_next_birthday"], 0)

    def test_birth_after_as_of_is_rejected(self):
        assert_value_error(self, MESSAGES["birth_after_as_of"], Engine.calculate_age, "2026-10-23", "2026-10-22")

    def test_invalid_dates_are_rejected(self):
        assert_value_error(self, MESSAGES["date"], Engine.calculate_age, "2001-02-29", "2026-10-22")
        assert_value_error(self, MESSAGES["date"], Engine.calculate_age, "1990-01-01", "2401-01-01")


class BusinessDaysTests(unittest.TestCase):
    MON = "2024-01-01"
    FRI = "2024-01-05"
    SUN = "2024-01-07"

    def test_monday_to_friday_inclusive_default_weekend(self):
        result = Engine.calculate_business_days(self.MON, self.FRI)
        self.assertEqual(result["business_days"], 5)
        self.assertEqual(result["calendar_days"], 5)
        self.assertEqual(result["weekend_days"], 0)
        self.assertEqual(result["assumptions"], {"holiday_source": "user_list"})

    def test_sunday_counts_as_weekend_in_default_week(self):
        result = Engine.calculate_business_days(self.MON, self.SUN)
        self.assertEqual((result["business_days"], result["calendar_days"], result["weekend_days"]), (5, 7, 2))

    def test_friday_saturday_weekend_variant(self):
        result = Engine.calculate_business_days(self.MON, self.SUN, weekend=(4, 5))
        self.assertEqual((result["business_days"], result["weekend_days"]), (5, 2))

    def test_no_weekend_days_counts_every_day(self):
        result = Engine.calculate_business_days(self.MON, self.SUN, weekend=())
        self.assertEqual((result["business_days"], result["weekend_days"]), (7, 0))

    def test_exclusive_range_excludes_end_date(self):
        result = Engine.calculate_business_days(self.MON, self.FRI, inclusive=False)
        self.assertEqual((result["business_days"], result["calendar_days"]), (4, 4))

    def test_empty_exclusive_range_is_zero(self):
        result = Engine.calculate_business_days(self.MON, self.MON, inclusive=False)
        self.assertEqual((result["business_days"], result["calendar_days"]), (0, 0))

    def test_single_weekday_inclusive_is_one(self):
        self.assertEqual(Engine.calculate_business_days(self.MON, self.MON)["business_days"], 1)

    def test_duplicate_holidays_are_counted_once_and_reported(self):
        result = Engine.calculate_business_days(self.MON, self.SUN, holidays=["2024-01-02", "2024-01-02"])
        self.assertEqual(result["business_days"], 4)
        self.assertEqual(result["holidays_excluded"], 1)
        self.assertEqual(result["duplicate_holidays"], 1)

    def test_holiday_on_weekend_is_not_subtracted_twice(self):
        result = Engine.calculate_business_days(self.MON, self.SUN, holidays=["2024-01-06"])
        self.assertEqual(result["business_days"], 5)
        self.assertEqual(result["holidays_on_weekend"], 1)
        self.assertEqual(result["holidays_excluded"], 0)

    def test_holiday_outside_range_is_reported_only(self):
        result = Engine.calculate_business_days(self.MON, self.SUN, holidays=["2023-12-25", "2024-01-08"])
        self.assertEqual(result["business_days"], 5)
        self.assertEqual(result["holidays_outside_range"], 2)

    def test_holiday_exactly_on_exclusive_end_is_outside_range(self):
        result = Engine.calculate_business_days(self.MON, self.FRI, inclusive=False, holidays=[self.FRI])
        self.assertEqual(result["holidays_outside_range"], 1)
        self.assertEqual(result["business_days"], 4)

    def test_mixed_holiday_categories_reconcile(self):
        result = Engine.calculate_business_days(
            self.MON, self.SUN, holidays=["2024-01-02", "2024-01-02", "2024-01-06", "2023-12-25"]
        )
        self.assertEqual(
            (result["holidays_excluded"], result["holidays_on_weekend"], result["holidays_outside_range"], result["duplicate_holidays"]),
            (1, 1, 1, 1),
        )
        self.assertEqual(result["business_days"], 4)

    def test_end_before_start_is_rejected(self):
        assert_value_error(self, MESSAGES["range_order"], Engine.calculate_business_days, self.FRI, self.MON)

    def test_seven_weekend_days_are_rejected(self):
        assert_value_error(
            self, MESSAGES["weekend_invalid"], Engine.calculate_business_days, self.MON, self.SUN, weekend=(0, 1, 2, 3, 4, 5, 6)
        )

    def test_duplicate_or_out_of_range_weekday_is_rejected(self):
        assert_value_error(self, MESSAGES["weekend_invalid"], Engine.calculate_business_days, self.MON, self.SUN, weekend=(5, 5))
        assert_value_error(self, MESSAGES["weekend_invalid"], Engine.calculate_business_days, self.MON, self.SUN, weekend=(7,))
        assert_value_error(self, MESSAGES["weekend_invalid"], Engine.calculate_business_days, self.MON, self.SUN, weekend=(True,))

    def test_range_length_limit_is_thirty_six_thousand_six_hundred_days(self):
        start = date(1600, 1, 1)
        at_limit = start + timedelta(days=36600)
        result = Engine.calculate_business_days(start.isoformat(), at_limit.isoformat(), inclusive=False)
        self.assertEqual(result["calendar_days"], 36600)
        over = start + timedelta(days=36601)
        assert_value_error(
            self, MESSAGES["range_length"], Engine.calculate_business_days, start.isoformat(), over.isoformat(), inclusive=False
        )

    def test_holiday_list_is_limited_to_one_thousand(self):
        holidays = [f"2024-01-{(index % 28) + 1:02d}" for index in range(1001)]
        assert_value_error(self, MESSAGES["holiday_count"], Engine.calculate_business_days, self.MON, self.SUN, holidays=holidays)

    def test_invalid_holiday_date_is_rejected(self):
        assert_value_error(self, MESSAGES["date"], Engine.calculate_business_days, self.MON, self.SUN, holidays=["2024-02-30"])

    def test_inclusive_must_be_a_boolean(self):
        assert_value_error(self, MESSAGES["inclusive_type"], Engine.calculate_business_days, self.MON, self.SUN, inclusive="yes")


class WorkHoursTests(unittest.TestCase):
    def test_overnight_shift_minus_break(self):
        result = Engine.calculate_work_hours([{"start": "22:00", "end": "06:00", "break_minutes": 30}])
        self.assertEqual(result["rows"], [{"index": 1, "worked_minutes": 450, "overnight": True, "dst_adjusted_minutes": 0}])
        self.assertEqual(result["total_minutes"], 450)
        self.assertEqual(result["total_hours"], 7.5)
        self.assertEqual(result["weeks"], [])
        self.assertEqual(result["assumptions"], {"dst": "not_applied", "overnight": "end_before_start"})

    def test_overnight_row_on_last_supported_date_with_zone_is_measured_not_rejected(self):
        rows = [{"date": "2400-12-31", "start": "22:00", "end": "06:00", "break_minutes": 0}]
        for zone in ("Europe/London", "Pacific/Kiritimati", "America/Adak"):
            with self.subTest(zone=zone):
                result = Engine.calculate_work_hours(rows, zone)
                self.assertEqual(result["rows"][0]["worked_minutes"], 480)
                self.assertEqual(result["weeks"], [{"iso_week": "2400-W52", "total_minutes": 480}])

    def test_daytime_shift_is_not_overnight(self):
        result = Engine.calculate_work_hours([{"start": "09:00", "end": "17:00", "break_minutes": 60}])
        self.assertEqual(result["rows"][0]["worked_minutes"], 420)
        self.assertFalse(result["rows"][0]["overnight"])

    def test_hours_round_half_up_to_hundredths(self):
        result = Engine.calculate_work_hours([{"start": "09:00", "end": "10:40", "break_minutes": 0}])
        self.assertEqual(result["total_hours"], 1.67)

    def test_equal_start_and_end_is_a_twenty_four_hour_shift(self):
        result = Engine.calculate_work_hours([{"start": "08:00", "end": "08:00", "break_minutes": 0}])
        self.assertEqual(result["rows"][0]["worked_minutes"], 1440)
        self.assertTrue(result["rows"][0]["overnight"])

    def test_break_equal_to_or_longer_than_shift_names_the_row(self):
        rows = [
            {"start": "09:00", "end": "10:00", "break_minutes": 0},
            {"start": "09:00", "end": "10:00", "break_minutes": 60},
        ]
        assert_value_error(self, MESSAGES["break_row"].format(row=2), Engine.calculate_work_hours, rows)

    def test_break_of_full_day_on_twenty_four_hour_shift_is_rejected(self):
        rows = [{"start": "08:00", "end": "08:00", "break_minutes": 1440}]
        assert_value_error(self, MESSAGES["break_row"].format(row=1), Engine.calculate_work_hours, rows)

    def test_break_bounds_are_zero_to_one_thousand_four_hundred_forty(self):
        self.assertEqual(
            Engine.calculate_work_hours([{"start": "00:00", "end": "23:59", "break_minutes": 1438}])["total_minutes"], 1
        )
        assert_value_error(
            self, MESSAGES["break_range"].format(row=1), Engine.calculate_work_hours, [{"start": "09:00", "end": "17:00", "break_minutes": -1}]
        )
        assert_value_error(
            self, MESSAGES["break_range"].format(row=1), Engine.calculate_work_hours, [{"start": "09:00", "end": "17:00", "break_minutes": 1441}]
        )

    def test_dst_spring_forward_overnight_is_seven_elapsed_hours_in_new_york(self):
        rows = [{"date": "2026-03-07", "start": "22:00", "end": "06:00", "break_minutes": 0}]
        result = Engine.calculate_work_hours(rows, "America/New_York")
        self.assertEqual(result["rows"][0]["worked_minutes"], 420)
        self.assertEqual(result["rows"][0]["dst_adjusted_minutes"], -60)
        self.assertEqual(result["assumptions"], {"dst": "zoneinfo", "overnight": "end_before_start"})

    def test_without_zone_the_same_shift_is_wall_clock(self):
        rows = [{"date": "2026-03-07", "start": "22:00", "end": "06:00", "break_minutes": 0}]
        result = Engine.calculate_work_hours(rows)
        self.assertEqual(result["rows"][0]["worked_minutes"], 480)
        self.assertEqual(result["rows"][0]["dst_adjusted_minutes"], 0)

    def test_zone_requires_a_date_on_every_row(self):
        rows = [
            {"date": "2026-03-07", "start": "09:00", "end": "10:00", "break_minutes": 0},
            {"start": "09:00", "end": "10:00", "break_minutes": 0},
        ]
        assert_value_error(self, MESSAGES["zone_requires_date"], Engine.calculate_work_hours, rows, "UTC")

    def test_nonexistent_local_time_in_zone_names_the_row(self):
        rows = [{"date": "2026-03-08", "start": "02:30", "end": "05:00", "break_minutes": 0}]
        assert_value_error(
            self, MESSAGES["nonexistent_row"].format(row=1), Engine.calculate_work_hours, rows, "America/New_York"
        )

    def test_unknown_zone_is_rejected(self):
        rows = [{"date": "2026-03-07", "start": "09:00", "end": "10:00", "break_minutes": 0}]
        assert_value_error(self, MESSAGES["zone_unknown"], Engine.calculate_work_hours, rows, "Mars/Olympus")

    def test_totals_reconcile_across_rows_and_iso_weeks(self):
        rows = [
            {"date": "2026-03-02", "start": "09:00", "end": "17:00", "break_minutes": 30},
            {"date": "2026-03-03", "start": "22:00", "end": "06:00", "break_minutes": 30},
            {"date": "2026-03-09", "start": "09:00", "end": "13:00", "break_minutes": 0},
            {"start": "10:00", "end": "11:00", "break_minutes": 0},
        ]
        result = Engine.calculate_work_hours(rows)
        self.assertEqual(result["total_minutes"], 450 + 450 + 240 + 60)
        self.assertEqual(result["weeks"], [{"iso_week": "2026-W10", "total_minutes": 900}, {"iso_week": "2026-W11", "total_minutes": 240}])
        self.assertEqual(sum(week["total_minutes"] for week in result["weeks"]), 900 + 240)
        self.assertEqual(sum(row["worked_minutes"] for row in result["rows"]), result["total_minutes"])

    def test_row_count_bounds(self):
        assert_value_error(self, MESSAGES["work_rows"], Engine.calculate_work_hours, [])
        assert_value_error(self, MESSAGES["work_rows"], Engine.calculate_work_hours, [{"start": "09:00", "end": "10:00", "break_minutes": 0}] * 401)
        self.assertEqual(len(Engine.calculate_work_hours([{"start": "09:00", "end": "10:00", "break_minutes": 0}] * 400)["rows"]), 400)

    def test_time_format_is_strict_twenty_four_hour_clock(self):
        for bad in ("24:00", "9:00", "09:60", "0900", "09:00 ", 900, None):
            with self.subTest(bad=bad):
                rows = [{"start": bad, "end": "10:00", "break_minutes": 0}]
                assert_value_error(self, MESSAGES["row_time_format"].format(row=1), Engine.calculate_work_hours, rows)


class TimeZoneConverterTests(unittest.TestCase):
    def test_ambiguous_time_without_choice_is_rejected(self):
        assert_value_error(
            self,
            MESSAGES["ambiguous_time"],
            Engine.convert_time_zone,
            "2026-11-01",
            "01:30",
            "America/New_York",
            ["UTC"],
        )

    def test_ambiguous_time_earlier_and_later_choices(self):
        earlier = Engine.convert_time_zone("2026-11-01", "01:30", "America/New_York", ["UTC"], "earlier")
        self.assertEqual(earlier["utc"], "2026-11-01T05:30:00Z")
        self.assertEqual(earlier["source"]["offset"], "-04:00")
        self.assertTrue(earlier["source"]["dst"])
        later = Engine.convert_time_zone("2026-11-01", "01:30", "America/New_York", ["UTC"], "later")
        self.assertEqual(later["utc"], "2026-11-01T06:30:00Z")
        self.assertEqual(later["source"]["offset"], "-05:00")
        self.assertEqual(later["source"]["abbreviation"], "EST")
        self.assertFalse(later["source"]["dst"])

    def test_unambiguous_time_ignores_fold(self):
        result = Engine.convert_time_zone("2026-07-01", "12:00", "America/New_York", ["UTC"], "later")
        self.assertEqual(result["utc"], "2026-07-01T16:00:00Z")

    def test_nonexistent_spring_forward_time_is_rejected(self):
        assert_value_error(
            self,
            MESSAGES["nonexistent_time"],
            Engine.convert_time_zone,
            "2026-03-08",
            "02:30",
            "America/New_York",
            ["UTC"],
        )
        assert_value_error(
            self,
            MESSAGES["nonexistent_time"],
            Engine.convert_time_zone,
            "2026-03-08",
            "02:30",
            "America/New_York",
            ["UTC"],
            "earlier",
        )

    def test_historical_date_uses_the_tz_database_rules_of_that_day(self):
        result = Engine.convert_time_zone("1990-07-01", "12:00", "Europe/London", ["America/New_York"])
        self.assertEqual(result["utc"], "1990-07-01T11:00:00Z")
        target = result["targets"][0]
        self.assertEqual(target["local"], "1990-07-01T07:00")
        self.assertEqual((target["offset"], target["abbreviation"], target["dst"]), ("-04:00", "EDT", True))
        self.assertEqual(target["day_shift"], 0)

    def test_utc_round_trip_returns_the_input(self):
        forward = Engine.convert_time_zone("2026-10-22", "12:00", "UTC", ["America/New_York"])
        local_target = forward["targets"][0]["local"]
        back = Engine.convert_time_zone(local_target[:10], local_target[11:], "America/New_York", ["UTC"])
        self.assertEqual(back["utc"], "2026-10-22T12:00:00Z")
        self.assertEqual(back["source"]["local"], "2026-10-22T08:00")

    def test_day_shift_across_midnight_in_both_directions(self):
        result = Engine.convert_time_zone("2026-01-01", "00:30", "Asia/Tokyo", ["America/Los_Angeles", "Asia/Kolkata"])
        self.assertEqual(result["utc"], "2025-12-31T15:30:00Z")
        self.assertEqual(result["targets"][0]["day_shift"], -1)
        self.assertEqual(result["targets"][0]["local"], "2025-12-31T07:30")
        self.assertEqual(result["targets"][1]["day_shift"], -1)
        self.assertEqual(result["targets"][1]["local"], "2025-12-31T21:00")
        self.assertEqual(result["targets"][1]["offset"], "+05:30")

    def test_target_count_is_one_to_ten(self):
        assert_value_error(self, MESSAGES["target_count"], Engine.convert_time_zone, "2026-01-01", "00:00", "UTC", [])
        assert_value_error(
            self, MESSAGES["target_count"], Engine.convert_time_zone, "2026-01-01", "00:00", "UTC", ["UTC"] * 11
        )
        self.assertEqual(len(Engine.convert_time_zone("2026-01-01", "00:00", "UTC", ["UTC"] * 10)["targets"]), 10)

    def test_years_outside_one_nine_hundred_to_two_thousand_one_hundred_are_rejected(self):
        assert_value_error(self, MESSAGES["conversion_year"], Engine.convert_time_zone, "1899-12-31", "00:00", "UTC", ["UTC"])
        assert_value_error(self, MESSAGES["conversion_year"], Engine.convert_time_zone, "2101-01-01", "00:00", "UTC", ["UTC"])

    def test_unknown_zones_are_rejected(self):
        assert_value_error(self, MESSAGES["zone_unknown"], Engine.convert_time_zone, "2026-01-01", "00:00", "Mars/Olympus", ["UTC"])
        assert_value_error(self, MESSAGES["zone_unknown"], Engine.convert_time_zone, "2026-01-01", "00:00", "UTC", ["Mars/Olympus"])

    def test_invalid_fold_and_time_are_rejected(self):
        assert_value_error(self, MESSAGES["fold_invalid"], Engine.convert_time_zone, "2026-11-01", "01:30", "America/New_York", ["UTC"], "middle")
        assert_value_error(self, MESSAGES["time_format"].format(row=1), Engine.convert_time_zone, "2026-01-01", "24:00", "UTC", ["UTC"])

    def test_list_time_zones_is_sorted_and_reports_the_database_version(self):
        result = Engine.list_time_zones()
        self.assertEqual(result["zones"], sorted(result["zones"]))
        self.assertIn("America/New_York", result["zones"])
        self.assertIsInstance(result["tzdata_version"], str)
        self.assertTrue(result["tzdata_version"])


def residual_of(a, b, c, root):
    """Independent |f(x)| for a root given as {real, imaginary} floats, using complex arithmetic."""
    x = complex(root["real"], root["imaginary"])
    return abs(a * x * x + b * x + c)


def independent_residual(a, b, c, root):
    """|f(x)| for a returned root, in 50-digit Decimal arithmetic (no root formula involved)."""
    with localcontext() as context:
        context.prec = 50
        a, b, c = (Decimal(repr(value)) for value in (a, b, c))
        re_part, im_part = Decimal(repr(root["real"])), Decimal(repr(root["imaginary"]))
        real_value = a * (re_part * re_part - im_part * im_part) + b * re_part + c
        imaginary_value = 2 * a * re_part * im_part + b * im_part
        return (real_value * real_value + imaginary_value * imaginary_value).sqrt()


def assert_max_residual_is_the_returned_roots_residual(test, a, b, c, result):
    """The reported max_residual must equal the residual of the roots the reader sees, to the 1e-10 quantum."""
    expected = max((independent_residual(a, b, c, root) for root in result["roots"]), default=Decimal(0))
    test.assertAlmostEqual(result["max_residual"], float(expected), delta=1e-10)


class QuadraticTests(unittest.TestCase):
    def test_two_real_roots_sorted(self):
        result = Engine.solve_quadratic(1, -3, 2)
        self.assertEqual(result["kind"], "two_real")
        self.assertEqual([root["real"] for root in result["roots"]], [1.0, 2.0])
        self.assertEqual(result["discriminant"], 1.0)
        assert_max_residual_is_the_returned_roots_residual(self, 1, -3, 2, result)
        self.assertEqual(result["assumptions"], {"precision": "1e-10", "method": "stable_quadratic"})

    def test_repeated_root_is_listed_once(self):
        result = Engine.solve_quadratic(1, -2, 1)
        self.assertEqual(result["kind"], "repeated_real")
        self.assertEqual(result["roots"], [{"real": 1.0, "imaginary": 0.0}])
        self.assertEqual(result["discriminant"], 0.0)
        assert_max_residual_is_the_returned_roots_residual(self, 1, -2, 1, result)

    def test_complex_pair_for_x_squared_plus_one(self):
        result = Engine.solve_quadratic(1, 0, 1)
        self.assertEqual(result["kind"], "complex_pair")
        self.assertEqual(result["discriminant"], -4.0)
        self.assertEqual(
            result["roots"],
            [{"real": 0.0, "imaginary": -1.0}, {"real": 0.0, "imaginary": 1.0}],
        )
        assert_max_residual_is_the_returned_roots_residual(self, 1, 0, 1, result)

    def test_irrational_roots_report_a_real_residual_not_zero(self):
        # Roots are rounded to 1e-10 for display; the residual of those rounded roots is about 7.6e-5 here.
        result = Engine.solve_quadratic(1000000, 0, -2000000)
        self.assertEqual([root["real"] for root in result["roots"]], [-1.4142135624, 1.4142135624])
        self.assertGreater(result["max_residual"], 1e-5)
        assert_max_residual_is_the_returned_roots_residual(self, 1000000, 0, -2000000, result)

    def test_complex_pair_with_negative_leading_coefficient_is_still_sorted(self):
        result = Engine.solve_quadratic(-1, 0, -1)
        self.assertEqual([root["imaginary"] for root in result["roots"]], [-1.0, 1.0])

    def test_linear_case_when_a_is_zero(self):
        result = Engine.solve_quadratic(0, 2, -4)
        self.assertEqual(result["kind"], "linear")
        self.assertEqual(result["roots"], [{"real": 2.0, "imaginary": 0.0}])
        assert_max_residual_is_the_returned_roots_residual(self, 0, 2, -4, result)
        self.assertIsNone(result["discriminant"])

    def test_degenerate_all_numbers_and_no_solution(self):
        all_numbers = Engine.solve_quadratic(0, 0, 0)
        self.assertEqual((all_numbers["kind"], all_numbers["roots"], all_numbers["max_residual"]), ("all_numbers", [], 0.0))
        self.assertIsNone(all_numbers["discriminant"])
        no_solution = Engine.solve_quadratic(0, 0, 5)
        self.assertEqual((no_solution["kind"], no_solution["roots"]), ("no_solution", []))
        self.assertIsNone(no_solution["discriminant"])

    def test_cancellation_case_keeps_the_small_root_accurate(self):
        result = Engine.solve_quadratic(1, 1e6, 1)
        small = min(result["roots"], key=lambda root: abs(root["real"]))
        self.assertAlmostEqual(small["real"], -1e-6, places=12)
        assert_max_residual_is_the_returned_roots_residual(self, 1, 1e6, 1, result)

    def test_residual_is_within_the_scale_tolerance_for_fractional_coefficients(self):
        a, b, c = 2.5, -3.5, 0.75
        result = Engine.solve_quadratic(a, b, c)
        scale = max(abs(a), abs(b), abs(c), 1)
        for root in result["roots"]:
            self.assertLessEqual(residual_of(a, b, c, root), 1e-9 * scale)
        assert_max_residual_is_the_returned_roots_residual(self, a, b, c, result)
        self.assertLessEqual(result["max_residual"], 1e-9 * scale)

    def test_coefficient_bounds_are_inclusive_at_one_trillion(self):
        self.assertEqual(Engine.solve_quadratic(1e12, 0, 0)["kind"], "repeated_real")
        for a, b, c in ((1e12 + 1, 0, 1), (1, 1e12 + 1, 1), (1, 1, -(1e12) - 1)):
            with self.subTest(a=a, b=b, c=c):
                assert_value_error(self, MESSAGES["coefficient_range"], Engine.solve_quadratic, a, b, c)

    def test_bool_string_and_non_finite_coefficients_are_rejected(self):
        for bad in (True, "1", float("nan"), float("inf")):
            with self.subTest(bad=bad):
                assert_value_error(self, MESSAGES["value_type"], Engine.solve_quadratic, bad, 1, 1)
                assert_value_error(self, MESSAGES["value_type"], Engine.solve_quadratic, 1, bad, 1)
                assert_value_error(self, MESSAGES["value_type"], Engine.solve_quadratic, 1, 1, bad)


class GcdLcmTests(unittest.TestCase):
    def test_gcd_and_lcm_of_pair(self):
        result = Engine.calculate_gcd_lcm([12, 18])
        self.assertEqual((result["gcd"], result["lcm"], result["count"]), ("6", "36", 2))
        self.assertEqual(result["assumptions"], {"sign": "absolute", "zero_policy": "gcd(0,0)=0; lcm with 0 = 0"})

    def test_zero_policy(self):
        self.assertEqual(Engine.calculate_gcd_lcm([0, 0])["gcd"], "0")
        self.assertEqual(Engine.calculate_gcd_lcm([0, 0])["lcm"], "0")
        self.assertEqual(Engine.calculate_gcd_lcm([0, 5])["gcd"], "5")
        self.assertEqual(Engine.calculate_gcd_lcm([0, 7, 3])["lcm"], "0")

    def test_negatives_give_non_negative_results(self):
        result = Engine.calculate_gcd_lcm([-12, 18])
        self.assertEqual((result["gcd"], result["lcm"]), ("6", "36"))
        result = Engine.calculate_gcd_lcm([-4, -6])
        self.assertEqual((result["gcd"], result["lcm"]), ("2", "12"))

    def test_exact_large_values_as_strings(self):
        big = 10**12
        result = Engine.calculate_gcd_lcm([big, big - 1])
        self.assertEqual(result["gcd"], "1")
        self.assertEqual(result["lcm"], str(big * (big - 1)))

    def test_count_bounds_two_to_one_hundred(self):
        assert_value_error(self, MESSAGES["integer_count"], Engine.calculate_gcd_lcm, [12])
        assert_value_error(self, MESSAGES["integer_count"], Engine.calculate_gcd_lcm, [1] * 101)
        self.assertEqual(Engine.calculate_gcd_lcm([6] * 100)["count"], 100)

    def test_non_integer_bool_and_string_items_are_rejected(self):
        for bad in (2.0, 2.5, True, "12"):
            with self.subTest(bad=bad):
                assert_value_error(self, MESSAGES["integer_type"], Engine.calculate_gcd_lcm, [12, bad])

    def test_magnitude_bound_is_one_trillion(self):
        self.assertEqual(Engine.calculate_gcd_lcm([10**12, 10**12])["gcd"], str(10**12))
        assert_value_error(self, MESSAGES["integer_range"], Engine.calculate_gcd_lcm, [10**12 + 1, 2])
        assert_value_error(self, MESSAGES["integer_range"], Engine.calculate_gcd_lcm, [2, -(10**12) - 1])


class StatisticsTests(unittest.TestCase):
    DATA = [2, 4, 4, 4, 5, 5, 7, 9]

    def test_population_statistics_for_reference_dataset(self):
        result = Engine.calculate_statistics(self.DATA, "population")
        self.assertEqual(result["count"], 8)
        self.assertEqual(result["sum"], 40.0)
        self.assertEqual(result["mean"], 5.0)
        self.assertEqual(result["median"], 4.5)
        self.assertEqual(result["modes"], [4.0])
        self.assertFalse(result["modes_truncated"])
        self.assertFalse(result["no_mode"])
        self.assertEqual((result["minimum"], result["maximum"], result["range"]), (2.0, 9.0, 7.0))
        self.assertEqual(result["variance"], 4.0)
        self.assertEqual(result["std_dev"], 2.0)
        self.assertIsNone(result["variance_unavailable_reason"])
        self.assertEqual(result["assumptions"], {"kind": "population", "precision": "1e-10"})

    def test_sample_variance_for_reference_dataset(self):
        result = Engine.calculate_statistics(self.DATA, "sample")
        self.assertEqual(result["variance"], 4.5714285714)
        self.assertAlmostEqual(result["std_dev"], 2.1380899353, places=9)
        self.assertEqual(result["assumptions"]["kind"], "sample")

    def test_singleton_population_has_zero_variance(self):
        result = Engine.calculate_statistics([3], "population")
        self.assertEqual((result["variance"], result["std_dev"], result["median"]), (0.0, 0.0, 3.0))
        self.assertTrue(result["no_mode"])

    def test_singleton_sample_variance_is_null_with_reason(self):
        result = Engine.calculate_statistics([3], "sample")
        self.assertIsNone(result["variance"])
        self.assertIsNone(result["std_dev"])
        self.assertEqual(result["variance_unavailable_reason"], MESSAGES["sample_needs_two"])

    def test_multimode_lists_every_mode(self):
        result = Engine.calculate_statistics([1, 1, 2, 2, 3], "population")
        self.assertEqual(result["modes"], [1.0, 2.0])
        self.assertFalse(result["no_mode"])

    def test_all_unique_values_have_no_mode(self):
        result = Engine.calculate_statistics([1, 2, 3], "population")
        self.assertEqual(result["modes"], [])
        self.assertTrue(result["no_mode"])

    def test_more_than_twenty_modes_are_truncated_smallest_first(self):
        result = Engine.calculate_statistics(list(range(21)) * 2, "population")
        self.assertEqual(len(result["modes"]), 20)
        self.assertEqual(result["modes"][0], 0.0)
        self.assertTrue(result["modes_truncated"])

    def test_median_of_odd_count_and_range_limits(self):
        self.assertEqual(Engine.calculate_statistics([1, 3, 2], "population")["median"], 2.0)
        self.assertEqual(Engine.calculate_statistics([10**12, -(10**12)], "population")["range"], 2e12)

    def test_empty_and_oversized_lists_are_rejected(self):
        assert_value_error(self, MESSAGES["value_count"], Engine.calculate_statistics, [], "sample")
        assert_value_error(self, MESSAGES["value_count"], Engine.calculate_statistics, [1] * 10001, "sample")

    def test_kind_must_be_sample_or_population(self):
        assert_value_error(self, MESSAGES["statistics_kind"], Engine.calculate_statistics, [1, 2], "other")

    def test_value_bounds_and_types(self):
        assert_value_error(self, MESSAGES["value_range"], Engine.calculate_statistics, [10**12 + 1], "population")
        for bad in (True, "2", float("nan")):
            with self.subTest(bad=bad):
                assert_value_error(self, MESSAGES["value_type"], Engine.calculate_statistics, [bad], "population")


class GeometryTests(unittest.TestCase):
    def measures(self, result):
        return {measure["name"]: measure for measure in result["measures"]}

    def test_circle_area_is_pi_and_unit_power_is_two(self):
        result = Engine.calculate_geometry("circle", "m", {"radius": 1})
        area = self.measures(result)["area"]
        self.assertAlmostEqual(area["value"], math.pi, places=6)
        self.assertEqual(area["unit_power"], 2)
        self.assertEqual(self.measures(result)["circumference"]["unit_power"], 1)
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["shape"], "circle")
        self.assertEqual(result["assumptions"], {"pi": "decimal_40", "precision": "1e-6"})

    def test_rectangle_area_and_perimeter(self):
        measures = self.measures(Engine.calculate_geometry("rectangle", "cm", {"width": 2, "height": 3}))
        self.assertEqual((measures["area"]["value"], measures["perimeter"]["value"]), (6.0, 10.0))

    def test_three_four_five_triangle_area_is_six(self):
        measures = self.measures(Engine.calculate_geometry("triangle", "ft", {"a": 3, "b": 4, "c": 5}))
        self.assertEqual(measures["area"]["value"], 6.0)
        self.assertEqual(measures["perimeter"]["value"], 12.0)

    def test_degenerate_or_violating_triangles_are_rejected(self):
        for sides in ({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 1, "c": 3}, {"a": 1, "b": 5, "c": 2}):
            with self.subTest(sides=sides):
                assert_value_error(self, MESSAGES["triangle_inequality"], Engine.calculate_geometry, "triangle", "m", sides)

    def test_sphere_surface_and_volume(self):
        measures = self.measures(Engine.calculate_geometry("sphere", "in", {"radius": 1}))
        self.assertAlmostEqual(measures["surface_area"]["value"], 4 * math.pi, places=6)
        self.assertAlmostEqual(measures["volume"]["value"], 4 / 3 * math.pi, places=6)
        self.assertEqual(measures["volume"]["unit_power"], 3)

    def test_cylinder_volume_is_two_pi_for_radius_one_height_two(self):
        measures = self.measures(Engine.calculate_geometry("cylinder", "mm", {"radius": 1, "height": 2}))
        self.assertAlmostEqual(measures["volume"]["value"], 2 * math.pi, places=6)
        self.assertEqual(measures["volume"]["unit_power"], 3)
        self.assertAlmostEqual(measures["surface_area"]["value"], 6 * math.pi, places=6)

    def test_cone_volume_slant_and_surfaces(self):
        measures = self.measures(Engine.calculate_geometry("cone", "km", {"radius": 3, "height": 4}))
        self.assertAlmostEqual(measures["volume"]["value"], 12 * math.pi, places=6)
        self.assertAlmostEqual(measures["slant_height"]["value"], 5.0, places=6)
        self.assertAlmostEqual(measures["lateral_area"]["value"], 15 * math.pi, places=6)
        self.assertAlmostEqual(measures["total_surface_area"]["value"], 24 * math.pi, places=6)

    def test_cuboid_volume_and_surface(self):
        measures = self.measures(Engine.calculate_geometry("cuboid", "yd", {"length": 2, "width": 3, "height": 4}))
        self.assertEqual((measures["volume"]["value"], measures["volume"]["unit_power"]), (24.0, 3))
        self.assertEqual((measures["surface_area"]["value"], measures["surface_area"]["unit_power"]), (52.0, 2))

    def test_every_measure_has_a_formula_and_unit_power(self):
        result = Engine.calculate_geometry("cylinder", "mi", {"radius": 1, "height": 2})
        for measure in result["measures"]:
            with self.subTest(measure=measure["name"]):
                self.assertTrue(measure["formula"])
                self.assertIn(measure["unit_power"], (1, 2, 3))

    def test_unit_must_be_one_of_eight_supported_units(self):
        for unit in ("parsec", "M", "", None):
            with self.subTest(unit=unit):
                assert_value_error(self, MESSAGES["unit_invalid"], Engine.calculate_geometry, "circle", unit, {"radius": 1})

    def test_unknown_shape_is_rejected(self):
        assert_value_error(self, MESSAGES["shape_invalid"], Engine.calculate_geometry, "pyramid", "m", {})

    def test_missing_dimension_is_rejected(self):
        assert_value_error(self, MESSAGES["dimension_missing"], Engine.calculate_geometry, "cylinder", "m", {"radius": 1})

    def test_dimension_bounds_are_zero_exclusive_and_one_million_inclusive(self):
        assert_value_error(self, MESSAGES["dimension_range"], Engine.calculate_geometry, "circle", "m", {"radius": 0})
        assert_value_error(self, MESSAGES["dimension_range"], Engine.calculate_geometry, "circle", "m", {"radius": 1e6 + 1})
        self.assertEqual(Engine.calculate_geometry("circle", "m", {"radius": 1e6})["unit"], "m")

    def test_bool_string_and_non_finite_dimensions_are_rejected(self):
        for bad in (True, "1", float("nan"), float("inf")):
            with self.subTest(bad=bad):
                assert_value_error(self, MESSAGES["value_type"], Engine.calculate_geometry, "circle", "m", {"radius": bad})


if __name__ == "__main__":
    unittest.main()
