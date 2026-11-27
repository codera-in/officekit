"""
OfficeKit - Canonical Unit Converter & Safe Math Evaluator (Pillars 3 & 4)
Supports:
- AST-based sandboxed arithmetic evaluator (zero unsafe eval())
- Canonical Base-Unit conversions (Length, Area, Mass, Storage, Temperature, Typography)
- Clear distinction between Decimal SI (KB/MB) and Binary IEC (KiB/MiB)
"""

import math
from typing import Dict, Any
from officekit.engines.engine_math import MathEvaluator


class UnitConverterEngine:
    """Canonical base-unit conversion tree."""

    MAX_ABSOLUTE_VALUE = 1e100
    ABSOLUTE_ZERO_CELSIUS = -273.15
    TEMPERATURE_ROUNDING_TOLERANCE_CELSIUS = 1e-10
    CASE_SENSITIVE_UNIT_CATEGORIES = {
        "digital_storage", "energy", "power", "pressure", "force", "frequency"
    }

    @classmethod
    def catalog(cls) -> dict[str, list[dict[str, Any]]]:
        """Return stable, deduplicated UI choices that the converter accepts."""
        categories = []
        for category, tree in cls.CONVERSION_TREES.items():
            seen_factors = set()
            units = []
            for unit, factor in tree["units"].items():
                if factor in seen_factors:
                    continue
                seen_factors.add(factor)
                label = unit.replace("_", " ").title() if "_" in unit else unit
                units.append({"id": unit, "label": label})
            categories.append({
                "id": category,
                "label": category.replace("_", " ").title(),
                "units": units,
            })
        categories.append({
            "id": "temperature",
            "label": "Temperature",
            "units": [
                {"id": "celsius", "label": "Celsius (°C)"},
                {"id": "fahrenheit", "label": "Fahrenheit (°F)"},
                {"id": "kelvin", "label": "Kelvin (K)"},
            ],
        })
        return {"categories": categories}

    # Multiplication factors relative to category base unit
    CONVERSION_TREES = {
        "length": {
            "base": "meter",
            "units": {
                "meter": 1.0,
                "m": 1.0,
                "millimeter": 0.001,
                "mm": 0.001,
                "centimeter": 0.01,
                "cm": 0.01,
                "kilometer": 1000.0,
                "km": 1000.0,
                "inch": 0.0254,
                "in": 0.0254,
                "foot": 0.3048,
                "ft": 0.3048,
                "yard": 0.9144,
                "yd": 0.9144,
                "mile": 1609.344,
                "mi": 1609.344,
                "nautical_mile": 1852.0
            }
        },
        "area": {
            "base": "square_meter",
            "units": {
                "square_meter": 1.0,
                "m2": 1.0,
                "sq_m": 1.0,
                "square_kilometer": 1_000_000.0,
                "km2": 1_000_000.0,
                "sq_km": 1_000_000.0,
                "square_centimeter": 0.0001,
                "cm2": 0.0001,
                "sq_cm": 0.0001,
                "square_millimeter": 0.000001,
                "mm2": 0.000001,
                "sq_mm": 0.000001,
                "hectare": 10_000.0,
                "ha": 10_000.0,
                "acre": 4046.8564224,
                "square_foot": 0.09290304,
                "ft2": 0.09290304,
                "sq_ft": 0.09290304,
                "square_yard": 0.83612736,
                "yd2": 0.83612736,
                "sq_yd": 0.83612736,
                "square_mile": 2_589_988.110336,
                "mi2": 2_589_988.110336,
                "sq_mi": 2_589_988.110336,
            }
        },
        "volume": {
            "base": "milliliter",
            "units": {
                "milliliter": 1.0,
                "millilitre": 1.0,
                "ml": 1.0,
                "liter": 1000.0,
                "litre": 1000.0,
                "l": 1000.0,
                "cubic_centimeter": 1.0,
                "cm3": 1.0,
                "cubic_meter": 1_000_000.0,
                "m3": 1_000_000.0,
                "teaspoon_us": 4.92892159375,
                "tsp_us": 4.92892159375,
                "tablespoon_us": 14.78676478125,
                "tbsp_us": 14.78676478125,
                "fluid_ounce_us": 29.5735295625,
                "floz_us": 29.5735295625,
                "cup_us": 236.5882365,
                "pint_us": 473.176473,
                "pt_us": 473.176473,
                "quart_us": 946.352946,
                "qt_us": 946.352946,
                "gallon_us": 3785.411784,
                "gal_us": 3785.411784,
                "fluid_ounce_imperial": 28.4130625,
                "floz_imperial": 28.4130625,
                "pint_imperial": 568.26125,
                "pt_imperial": 568.26125,
                "quart_imperial": 1136.5225,
                "qt_imperial": 1136.5225,
                "gallon_imperial": 4546.09,
                "gal_imperial": 4546.09,
            }
        },
        "mass": {
            "base": "gram",
            "units": {
                "gram": 1.0,
                "g": 1.0,
                "milligram": 0.001,
                "mg": 0.001,
                "kilogram": 1000.0,
                "kg": 1000.0,
                "ounce": 28.349523125,
                "oz": 28.349523125,
                "pound": 453.59237,
                "lb": 453.59237,
                "tonne": 1000000.0
            }
        },
        "digital_storage": {
            "base": "bytes",
            "units": {
                # SI symbols are case-sensitive: lowercase b is bit, uppercase B is byte.
                "bit": 0.125,
                "bits": 0.125,
                "b": 0.125,
                "byte": 1.0,
                "bytes": 1.0,
                "B": 1.0,
                # Decimal SI byte and bit symbols, plus unambiguous word aliases.
                "kB": 1000.0,
                "KB": 1000.0,
                "kilobyte": 1000.0,
                "kilobytes": 1000.0,
                "kb": 125.0,
                "kilobit": 125.0,
                "kilobits": 125.0,
                "MB": 1_000_000.0,
                "megabyte": 1_000_000.0,
                "megabytes": 1_000_000.0,
                "Mb": 125_000.0,
                "megabit": 125_000.0,
                "megabits": 125_000.0,
                "GB": 1_000_000_000.0,
                "gigabyte": 1_000_000_000.0,
                "gigabytes": 1_000_000_000.0,
                "Gb": 125_000_000.0,
                "gigabit": 125_000_000.0,
                "gigabits": 125_000_000.0,
                "TB": 1_000_000_000_000.0,
                "terabyte": 1_000_000_000_000.0,
                "terabytes": 1_000_000_000_000.0,
                "Tb": 125_000_000_000.0,
                "terabit": 125_000_000_000.0,
                "terabits": 125_000_000_000.0,
                # Binary IEC byte and bit symbols and full-word aliases.
                "KiB": 1024.0,
                "kibibyte": 1024.0,
                "kibibytes": 1024.0,
                "Kib": 128.0,
                "kibibit": 128.0,
                "kibibits": 128.0,
                "MiB": 1_048_576.0,
                "mebibyte": 1_048_576.0,
                "mebibytes": 1_048_576.0,
                "Mib": 131_072.0,
                "mebibit": 131_072.0,
                "mebibits": 131_072.0,
                "GiB": 1_073_741_824.0,
                "gibibyte": 1_073_741_824.0,
                "gibibytes": 1_073_741_824.0,
                "Gib": 134_217_728.0,
                "gibibit": 134_217_728.0,
                "gibibits": 134_217_728.0,
                "TiB": 1_099_511_627_776.0,
                "tebibyte": 1_099_511_627_776.0,
                "tebibytes": 1_099_511_627_776.0,
                "Tib": 137_438_953_472.0,
                "tebibit": 137_438_953_472.0,
                "tebibits": 137_438_953_472.0,
            }
        },
        "speed": {
            "base": "meter_per_second",
            "units": {
                "meter_per_second": 1.0,
                "m_per_s": 1.0,
                "m/s": 1.0,
                "kilometer_per_hour": 1 / 3.6,
                "km_per_h": 1 / 3.6,
                "km/h": 1 / 3.6,
                "kph": 1 / 3.6,
                "mile_per_hour": 0.44704,
                "mi_per_h": 0.44704,
                "mph": 0.44704,
                "foot_per_second": 0.3048,
                "ft_per_s": 0.3048,
                "knot": 1852 / 3600,
                "knots": 1852 / 3600,
                "kt": 1852 / 3600,
            }
        },
        "energy": {
            "base": "joule",
            "units": {
                "joule": 1.0,
                "j": 1.0,
                "kilojoule": 1000.0,
                "kj": 1000.0,
                "megajoule": 1_000_000.0,
                "watt_hour": 3600.0,
                "wh": 3600.0,
                "Wh": 3600.0,
                "kilowatt_hour": 3_600_000.0,
                "kwh": 3_600_000.0,
                "kWh": 3_600_000.0,
                "megawatt_hour": 3_600_000_000.0,
                "mwh": 3_600_000_000.0,
                "MWh": 3_600_000_000.0,
                "mJ": 0.001,
                "MJ": 1_000_000.0,
                # Thermochemical calorie, exactly 4.184 joules.
                "calorie": 4.184,
                "cal": 4.184,
                "calorie_th": 4.184,
                "calorie_15c": 4.1855,
                "cal15": 4.1855,
                "calorie_it": 4.1868,
                "cal_it": 4.1868,
                "kilocalorie": 4184.0,
                "kcal": 4184.0,
                # International Table Btu.
                "btu_it": 1055.05585262,
                "btu": 1055.05585262,
                "btu_thermochemical": 1054.35026444,
                "btu_th": 1054.35026444,
                "electronvolt": 1.602176634e-19,
                "ev": 1.602176634e-19,
            }
        },
        "power": {
            "base": "watt",
            "units": {
                "watt": 1.0,
                "w": 1.0,
                "milliwatt": 0.001,
                "kilowatt": 1000.0,
                "kw": 1000.0,
                "kW": 1000.0,
                "megawatt": 1_000_000.0,
                "MW": 1_000_000.0,
                "mW": 0.001,
                "gigawatt": 1_000_000_000.0,
                "gw": 1_000_000_000.0,
                "GW": 1_000_000_000.0,
                "mechanical_horsepower": 745.6998715822702,
                "horsepower": 745.6998715822702,
                "hp": 745.6998715822702,
                "metric_horsepower": 735.49875,
                "ps": 735.49875,
                "btu_per_hour": 0.2930710701722222,
                "btu/h": 0.2930710701722222,
            }
        },
        "pressure": {
            "base": "pascal",
            "units": {
                "pascal": 1.0,
                "pa": 1.0,
                "Pa": 1.0,
                "kilopascal": 1000.0,
                "kpa": 1000.0,
                "kPa": 1000.0,
                "megapascal": 1_000_000.0,
                "MPa": 1_000_000.0,
                "mPa": 0.001,
                "bar": 100_000.0,
                "millibar": 100.0,
                "mbar": 100.0,
                "atmosphere": 101_325.0,
                "standard_atmosphere": 101_325.0,
                "atm": 101_325.0,
                "psi": 6894.757293168,
                "pound_per_square_inch": 6894.757293168,
                "torr": 101_325.0 / 760.0,
                "mmhg": 133.322387415,
                "inch_of_mercury": 3386.389,
                "inhg": 3386.389,
            }
        },
        "force": {
            "base": "newton",
            "units": {
                "newton": 1.0,
                "n": 1.0,
                "N": 1.0,
                "millinewton": 0.001,
                "mN": 0.001,
                "kilonewton": 1000.0,
                "kn": 1000.0,
                "kN": 1000.0,
                "MN": 1_000_000.0,
                "dyne": 0.00001,
                "dyn": 0.00001,
                "pound_force": 4.4482216152605,
                "lbf": 4.4482216152605,
                "kilogram_force": 9.80665,
                "kgf": 9.80665,
            }
        },
        "frequency": {
            "base": "hertz",
            "units": {
                "hertz": 1.0,
                "hz": 1.0,
                "Hz": 1.0,
                "millihertz": 0.001,
                "mHz": 0.001,
                "kilohertz": 1000.0,
                "khz": 1000.0,
                "kHz": 1000.0,
                "megahertz": 1_000_000.0,
                "MHz": 1_000_000.0,
                "gigahertz": 1_000_000_000.0,
                "ghz": 1_000_000_000.0,
                "GHz": 1_000_000_000.0,
                "terahertz": 1_000_000_000_000.0,
                "thz": 1_000_000_000_000.0,
                "revolutions_per_minute": 1.0 / 60.0,
                "rev_per_min": 1.0 / 60.0,
                "rpm": 1.0 / 60.0,
                "beats_per_minute": 1.0 / 60.0,
                "bpm": 1.0 / 60.0,
            }
        },
        "angle": {
            "base": "radian",
            "units": {
                "radian": 1.0,
                "radians": 1.0,
                "rad": 1.0,
                "degree": math.pi / 180.0,
                "degrees": math.pi / 180.0,
                "deg": math.pi / 180.0,
                "°": math.pi / 180.0,
                "arcminute": math.pi / 10_800.0,
                "arcmin": math.pi / 10_800.0,
                "arcsecond": math.pi / 648_000.0,
                "arcsec": math.pi / 648_000.0,
                "gradian": math.pi / 200.0,
                "gradians": math.pi / 200.0,
                "gon": math.pi / 200.0,
                "turn": 2.0 * math.pi,
                "revolution": 2.0 * math.pi,
                "rev": 2.0 * math.pi,
            }
        },
        "time": {
            "base": "second",
            "units": {
                "nanosecond": 1e-9,
                "ns": 1e-9,
                "microsecond": 1e-6,
                "us": 1e-6,
                "millisecond": 1e-3,
                "ms": 1e-3,
                "second": 1.0,
                "s": 1.0,
                "minute": 60.0,
                "min": 60.0,
                "hour": 3600.0,
                "h": 3600.0,
                "day": 86400.0,
                "d": 86400.0,
                "week": 604800.0,
                "wk": 604800.0,
                # Fixed 365-day duration; calendar months/years are not fixed units.
                "year_365d": 31536000.0,
                "yr365": 31536000.0,
            }
        },
        "typography": {
            "base": "pixel",
            "units": {
                "pixel": 1.0,
                "px": 1.0,
                "point": 1.3333333333333333,
                "pt": 1.3333333333333333,
                "rem": 16.0,
                "em": 16.0
            }
        }
    }

    @classmethod
    def convert(cls, value: float, category: str, from_unit: str, to_unit: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Value must be a finite number")
        try:
            finite_value = math.isfinite(value)
        except OverflowError:
            finite_value = False
        if not finite_value or abs(value) > cls.MAX_ABSOLUTE_VALUE:
            raise ValueError("Value must be finite and within the supported range")
        if not isinstance(category, str) or not category.strip():
            raise ValueError("Conversion category must be a non-empty string")
        if not isinstance(from_unit, str) or not from_unit.strip():
            raise ValueError("Source unit must be a non-empty string")
        if not isinstance(to_unit, str) or not to_unit.strip():
            raise ValueError("Destination unit must be a non-empty string")

        cat = category.strip().lower()
        from_text = from_unit.strip()
        to_text = to_unit.strip()
        if cat in cls.CASE_SENSITIVE_UNIT_CATEGORIES:
            category_units = cls.CONVERSION_TREES[cat]["units"]
            u_from = from_text if from_text in category_units else from_text.lower()
            u_to = to_text if to_text in category_units else to_text.lower()
        else:
            u_from = from_text.lower()
            u_to = to_text.lower()

        # Handle non-linear temperature offset formulas
        if cat == "temperature":
            result = cls._convert_temperature(value, u_from, u_to)
            if not math.isfinite(result) or abs(result) > cls.MAX_ABSOLUTE_VALUE:
                raise ValueError("Conversion result exceeds the supported range")
            return result

        if cat not in cls.CONVERSION_TREES:
            raise ValueError(f"Unknown conversion category: {category}")

        tree = cls.CONVERSION_TREES[cat]["units"]
        if u_from not in tree:
            raise ValueError(f"Unknown source unit '{from_unit}' in category '{category}'")
        if u_to not in tree:
            raise ValueError(f"Unknown destination unit '{to_unit}' in category '{category}'")

        if u_from == u_to:
            return float(value)

        # Convert source -> Canonical Base -> Destination
        base_val = value * tree[u_from]
        target_val = base_val / tree[u_to]
        if not math.isfinite(target_val) or abs(target_val) > cls.MAX_ABSOLUTE_VALUE:
            raise ValueError("Conversion result exceeds the supported range")
        return target_val

    @staticmethod
    def _convert_temperature(val: float, u_from: str, u_to: str) -> float:
        # Convert u_from to Celsius canonical base
        if u_from in ("celsius", "c"):
            c = val
        elif u_from in ("fahrenheit", "f"):
            c = (val - 32.0) * (5.0 / 9.0)
        elif u_from in ("kelvin", "k"):
            c = val - 273.15
        else:
            raise ValueError(f"Unsupported temperature unit: {u_from}")

        if c < UnitConverterEngine.ABSOLUTE_ZERO_CELSIUS:
            if (
                UnitConverterEngine.ABSOLUTE_ZERO_CELSIUS - c
                > UnitConverterEngine.TEMPERATURE_ROUNDING_TOLERANCE_CELSIUS
            ):
                raise ValueError("Temperature cannot be below absolute zero")
            c = UnitConverterEngine.ABSOLUTE_ZERO_CELSIUS

        # Convert Celsius canonical base to u_to
        if u_to in ("celsius", "c"):
            return c
        elif u_to in ("fahrenheit", "f"):
            return (c * 9.0 / 5.0) + 32.0
        elif u_to in ("kelvin", "k"):
            return c + 273.15
        raise ValueError(f"Unsupported temperature unit: {u_to}")
