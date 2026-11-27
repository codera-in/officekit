"""Input and domain-validation regressions for unit conversions."""

import math
import unittest

from officekit.engines.engine_units import UnitConverterEngine


class UnitConverterValidationTests(unittest.TestCase):
    def test_same_unit_conversion_still_validates_category_and_units(self):
        self.assertEqual(UnitConverterEngine.convert(12, "length", "meter", "meter"), 12.0)
        for category, unit in (("unknown", "x"), ("length", "not-a-unit"), ("temperature", "m") ):
            with self.subTest(category=category, unit=unit), self.assertRaises(ValueError):
                UnitConverterEngine.convert(12, category, unit, unit)

    def test_rejects_non_numeric_boolean_nonfinite_and_oversized_values(self):
        for value in (True, "12", math.inf, -math.inf, math.nan, 1e101):
            with self.subTest(value=value), self.assertRaises(ValueError):
                UnitConverterEngine.convert(value, "length", "meter", "foot")

    def test_rejects_invalid_categories_and_unit_types(self):
        for category, source, target in (
            (None, "meter", "foot"),
            ("length", None, "foot"),
            ("length", "meter", []),
            ("unknown", "meter", "foot"),
        ):
            with self.subTest(category=category, source=source, target=target), self.assertRaises(ValueError):
                UnitConverterEngine.convert(1, category, source, target)

    def test_rejects_nonfinite_conversion_results(self):
        with self.assertRaises(ValueError):
            UnitConverterEngine.convert(1e100, "digital_storage", "tb", "bytes")

    def test_rejects_nonfinite_temperature_results(self):
        with self.assertRaises(ValueError):
            UnitConverterEngine.convert(1e100, "temperature", "celsius", "fahrenheit")

    def test_temperature_conversions_enforce_absolute_zero_before_same_unit_return(self):
        self.assertAlmostEqual(
            UnitConverterEngine.convert(-273.15, "temperature", "celsius", "kelvin"),
            0.0,
            places=10,
        )
        self.assertEqual(UnitConverterEngine.convert(0, "temperature", "kelvin", "kelvin"), 0.0)
        for value, unit in ((-273.150001, "celsius"), (-459.671, "fahrenheit"), (-0.001, "kelvin")):
            with self.subTest(value=value, unit=unit), self.assertRaisesRegex(ValueError, "absolute zero"):
                UnitConverterEngine.convert(value, "temperature", unit, unit)

    def test_core_area_volume_speed_and_fixed_duration_time_conversions(self):
        cases = (
            (1, "area", "square_meter", "square_centimeter", 10000.0),
            (1, "area", "acre", "square_foot", 43560.0),
            (1, "area", "hectare", "square_meter", 10000.0),
            (1, "volume", "gallon_us", "liter", 3.785411784),
            (1, "volume", "gallon_imperial", "liter", 4.54609),
            (1, "volume", "tablespoon_us", "milliliter", 14.78676478125),
            (36, "speed", "km/h", "m/s", 10.0),
            (100, "speed", "kilometer_per_hour", "meter_per_second", 100 / 3.6),
            (60, "speed", "mile_per_hour", "knot", 52.13857451403887),
            (90, "time", "minute", "hour", 1.5),
            (1, "time", "day", "hour", 24.0),
            (1, "time", "year_365d", "day", 365.0),
            (1, "time", "millisecond", "microsecond", 1000.0),
        )
        for value, category, source, target, expected in cases:
            with self.subTest(category=category, source=source, target=target):
                self.assertAlmostEqual(
                    UnitConverterEngine.convert(value, category, source, target),
                    expected,
                    places=10,
                )

    def test_every_canonical_factor_is_positive_finite_and_round_trips(self):
        for category, tree in UnitConverterEngine.CONVERSION_TREES.items():
            units = tree["units"]
            for unit, factor in units.items():
                with self.subTest(category=category, unit=unit):
                    self.assertTrue(math.isfinite(factor) and factor > 0)
                    base_value = UnitConverterEngine.convert(1, category, unit, tree["base"])
                    round_trip = UnitConverterEngine.convert(base_value, category, tree["base"], unit)
                    self.assertAlmostEqual(round_trip, 1.0, places=10)

    def test_fixed_unit_aliases_and_same_unit_conversion(self):
        self.assertEqual(UnitConverterEngine.convert(12, "volume", "L", "liter"), 12.0)
        self.assertEqual(UnitConverterEngine.convert(8, "speed", "kph", "km/h"), 8.0)
        self.assertEqual(UnitConverterEngine.convert(3, "time", "yr365", "year_365d"), 3.0)
        with self.assertRaisesRegex(ValueError, "Unknown source unit"):
            UnitConverterEngine.convert(1, "time", "month", "day")

    def test_units_are_rejected_under_other_categories(self):
        for category, source, target in (
            ("area", "acre", "liter"),
            ("volume", "gallon_us", "square_meter"),
            ("speed", "mph", "second"),
            ("time", "day", "kilometer"),
        ):
            with self.subTest(category=category, source=source, target=target), self.assertRaises(ValueError):
                UnitConverterEngine.convert(1, category, source, target)

    def test_digital_storage_symbols_keep_bit_and_byte_case_distinctions(self):
        cases = (
            (8, "bit", "byte", 1.0),
            (1, "B", "bit", 8.0),
            (1, "KB", "byte", 1000.0),
            (1, "kb", "byte", 125.0),
            (1, "MB", "byte", 1_000_000.0),
            (1, "Mb", "byte", 125_000.0),
            (1, "KiB", "byte", 1024.0),
            (1, "Kib", "byte", 128.0),
            (1, "MiB", "byte", 1_048_576.0),
            (1, "Mib", "byte", 131_072.0),
            (1, "Kilobytes", "byte", 1000.0),
            (1, "kilobits", "byte", 125.0),
        )
        for value, source, target, expected in cases:
            with self.subTest(source=source, target=target):
                self.assertEqual(
                    UnitConverterEngine.convert(value, "digital_storage", source, target),
                    expected,
                )

    def test_energy_power_pressure_force_frequency_and_angle_reference_vectors(self):
        cases = (
            (1, "energy", "kilowatt_hour", "megajoule", 3.6),
            (1, "energy", "calorie", "joule", 4.184),
            (1, "energy", "calorie_15c", "joule", 4.1855),
            (1, "energy", "calorie_it", "joule", 4.1868),
            (1, "energy", "btu_it", "joule", 1055.05585262),
            (1, "energy", "btu_th", "joule", 1054.35026444),
            (1, "power", "kilowatt", "watt", 1000.0),
            (1, "power", "mechanical_horsepower", "watt", 745.6998715822702),
            (1, "power", "metric_horsepower", "watt", 735.49875),
            (1, "power", "watt", "btu_per_hour", 3.412141633127942),
            (1, "pressure", "atmosphere", "pascal", 101325.0),
            (1, "pressure", "atmosphere", "torr", 760.0),
            (1, "pressure", "bar", "kilopascal", 100.0),
            (1, "pressure", "psi", "pascal", 6894.757293168),
            (1, "force", "pound_force", "newton", 4.4482216152605),
            (1, "force", "kilogram_force", "newton", 9.80665),
            (1, "force", "kilonewton", "newton", 1000.0),
            (60, "frequency", "rpm", "hertz", 1.0),
            (1, "frequency", "gigahertz", "hertz", 1_000_000_000.0),
            (1, "frequency", "millihertz", "hertz", 0.001),
            (180, "angle", "degree", "radian", math.pi),
            (200, "angle", "gradian", "radian", math.pi),
            (1, "angle", "turn", "radian", 2 * math.pi),
        )
        for value, category, source, target, expected in cases:
            with self.subTest(category=category, source=source, target=target):
                self.assertAlmostEqual(
                    UnitConverterEngine.convert(value, category, source, target),
                    expected,
                    places=9,
                )

    def test_engineering_categories_do_not_accept_units_from_other_dimensions(self):
        for category, source, target in (
            ("energy", "kilowatt_hour", "watt"),
            ("power", "watt", "joule"),
            ("pressure", "psi", "newton"),
            ("force", "newton", "pascal"),
            ("frequency", "hertz", "radian"),
            ("angle", "degree", "hertz"),
        ):
            with self.subTest(category=category, source=source, target=target), self.assertRaises(ValueError):
                UnitConverterEngine.convert(1, category, source, target)

    def test_engineering_unit_aliases_and_identity_conversions(self):
        aliases = (
            (1, "energy", "kWh", "kilowatt_hour", 1.0),
            (1, "power", "hp", "mechanical_horsepower", 1.0),
            (1, "pressure", "atm", "atmosphere", 1.0),
            (1, "force", "lbf", "pound_force", 1.0),
            (60, "frequency", "RPM", "hertz", 1.0),
            (1, "frequency", "MHz", "hertz", 1_000_000.0),
            (1, "frequency", "mHz", "hertz", 0.001),
            (360, "angle", "degrees", "degree", 360.0),
            (1, "energy", "MJ", "joule", 1_000_000.0),
            (1, "energy", "mJ", "joule", 0.001),
            (1, "power", "MW", "watt", 1_000_000.0),
            (1, "power", "mW", "watt", 0.001),
            (1, "pressure", "MPa", "pascal", 1_000_000.0),
            (1, "pressure", "mPa", "pascal", 0.001),
            (1, "force", "MN", "newton", 1_000_000.0),
            (1, "force", "mN", "newton", 0.001),
        )
        for value, category, source, target, expected in aliases:
            with self.subTest(category=category, source=source):
                self.assertAlmostEqual(
                    UnitConverterEngine.convert(value, category, source, target),
                    expected,
                    places=9,
                )

    def test_case_sensitive_engineering_prefixes_reject_ambiguous_wrong_case(self):
        for category, source, target in (
            ("energy", "mj", "joule"),
            ("power", "Mw", "watt"),
            ("pressure", "MPA", "pascal"),
            ("force", "Mn", "newton"),
            ("frequency", "mhz", "hertz"),
        ):
            with self.subTest(category=category, source=source), self.assertRaises(ValueError):
                UnitConverterEngine.convert(1, category, source, target)


if __name__ == "__main__":
    unittest.main()
