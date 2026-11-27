"""
TDD Tests for Canonical Unit Converter & Expression Evaluator (officekit/engines/engine_units.py)
Covers:
- Safe math expression evaluator without unsafe eval()
- Length, Area, Mass, Speed, Time canonical conversions
- Binary IEC (KiB, MiB, GiB) vs Decimal SI (KB, MB, GB) digital storage
- Temperature conversions with non-zero offsets (Celsius, Fahrenheit, Kelvin)
- Typography (px to pt, rem)
"""

import pytest
from officekit.engines.engine_units import UnitConverterEngine, MathEvaluator

def test_safe_math_expression_evaluator():
    assert MathEvaluator.evaluate("2 + 3 * 4") == 14
    assert MathEvaluator.evaluate("(10 - 2) / 4") == 2.0
    assert MathEvaluator.evaluate("2 ^ 3") == 8
    assert MathEvaluator.evaluate("15 % 4") == 3
    # Unsafe code injection rejection
    with pytest.raises(ValueError):
        MathEvaluator.evaluate("__import__('os').system('ls')")

def test_temperature_offset_conversions():
    # 0 Celsius = 32 Fahrenheit = 273.15 Kelvin
    f_res = UnitConverterEngine.convert(0, "temperature", "celsius", "fahrenheit")
    assert round(f_res, 2) == 32.0

    k_res = UnitConverterEngine.convert(0, "temperature", "celsius", "kelvin")
    assert round(k_res, 2) == 273.15

    c_back = UnitConverterEngine.convert(212, "temperature", "fahrenheit", "celsius")
    assert round(c_back, 1) == 100.0

def test_digital_storage_iec_vs_si():
    # Decimal SI: 1 MB = 1000 KB = 1,000,000 bytes
    bytes_si = UnitConverterEngine.convert(1, "digital_storage", "MB", "bytes")
    assert bytes_si == 1000000.0

    # Binary IEC: 1 MiB = 1024 KiB = 1,048,576 bytes
    bytes_iec = UnitConverterEngine.convert(1, "digital_storage", "MiB", "bytes")
    assert bytes_iec == 1048576.0

def test_length_and_mass_conversions():
    # 1 mile in meters (~1609.344)
    meters = UnitConverterEngine.convert(1, "length", "mile", "meter")
    assert round(meters, 3) == 1609.344

    # 1 kg in pounds (~2.20462)
    lbs = UnitConverterEngine.convert(1, "mass", "kg", "pound")
    assert round(lbs, 4) == 2.2046
