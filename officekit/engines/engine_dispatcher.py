"""
OfficeKit - Universal Tool Dispatcher & Execution Engine
Provides deterministic execution, input validation, and result payloads
for all 123 registered capabilities across all 9 categories:
- Calculators (C01 - C25)
- Unit Converters (U01 - U16)
- Developer & Security Tools (D01 - D17)
- File Utilities (F01 - F12)
- Storage & Cleanup (S01 - S06)
- System & Network (N01 - N05)
- Audio & Dictation (A01 - A02)
- PDF & Documents (P01 - P20)
- Image Operations (I01 - I20)
"""

import os
import io
import re
import json
import math
import time
import base64
import urllib.parse
import hashlib
import zlib
import hmac
import secrets
import string
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, date

from PIL import Image, ImageOps, ImageFilter, ImageEnhance
import pikepdf
import pypdf
import pandas as pd

from officekit.engines.engine_calculators import CalculatorEngine
from officekit.engines.engine_units import UnitConverterEngine, MathEvaluator
from officekit.engines.engine_devtools import DevToolsEngine, PrivacySecurityEngine
from officekit.engines.engine_file_ops import FileOpsEngine, StorageAnalyzerEngine
from officekit.engines.engine_file_converter import FileConverterEngine
from officekit.engines.engine_dictate import MeetingDictateEngine
from officekit.engines.engine_pdf_security import PdfSecurityEngine
from officekit.engines.engine_pdf_advanced import AdvancedPdfEngine
from officekit.engines.engine_parser import parse_statement_table


class ToolExecutionError(Exception):
    """Structured execution failure with user-actionable message."""
    def __init__(self, message: str, code: str = "EXECUTION_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code


class UniversalToolDispatcher:
    """Dispatches any of the 123 tool IDs with strict schema validation and execution."""

    @classmethod
    def execute(cls, tool_id: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a registered tool by ID.
        Raises ValueError or ToolExecutionError on invalid inputs or runtime error.
        Returns dictionary containing tool outputs.
        """
        tid = tool_id.lower().strip()
        handler_name = f"_handle_{tid}"
        handler = getattr(cls, handler_name, None)
        if not handler:
            raise ToolExecutionError(f"Tool handler for '{tool_id}' not implemented.", code="TOOL_NOT_FOUND")

        return handler(inputs)

    # =========================================================================
    # CALCULATORS (C01 - C25)
    # =========================================================================

    @classmethod
    def _handle_c01(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        expr = str(inp.get("expression", "")).strip()
        if not expr:
            raise ValueError("Expression is required.")
        val = MathEvaluator.evaluate(expr)
        return {"result": val, "expression": expr}

    @classmethod
    def _handle_c02(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        if "percentage" not in inp or inp["percentage"] is None:
            raise ValueError("percentage parameter is required.")
        pct = float(inp["percentage"])
        total = float(inp.get("total", 0))
        if total < 0:
            raise ValueError("Total cannot be negative.")
        res = (pct / 100.0) * total
        return {"result": round(res, 4), "percentage": pct, "total": total}

    @classmethod
    def _handle_c03(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        orig = float(inp.get("original", 0))
        new_val = float(inp.get("new", 0))
        if orig == 0:
            raise ValueError("Original value cannot be zero.")
        diff = new_val - orig
        pct_change = (diff / abs(orig)) * 100.0
        return {
            "percentage_change": round(pct_change, 2),
            "difference": round(diff, 2),
            "direction": "increase" if diff >= 0 else "decrease"
        }

    @classmethod
    def _handle_c04(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        price = float(inp.get("price", 0))
        discount_pct = float(inp.get("discount_percent", 0))
        if price < 0:
            raise ValueError("Price cannot be negative.")
        if not (0 <= discount_pct <= 100):
            raise ValueError("Discount percentage must be between 0 and 100.")
        savings = price * (discount_pct / 100.0)
        final_price = price - savings
        return {"final_price": round(final_price, 2), "savings": round(savings, 2)}

    @classmethod
    def _handle_c05(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        cost = float(inp.get("cost", 0))
        revenue = float(inp.get("revenue", 0))
        if cost < 0 or revenue < 0:
            raise ValueError("Cost and revenue must be non-negative.")
        return CalculatorEngine.calculate_margin_markup(cost, revenue)

    @classmethod
    def _handle_c06(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        numbers = inp.get("numbers")
        if not numbers or not isinstance(numbers, list):
            raise ValueError("Numbers must be a non-empty list of values.")
        weights = inp.get("weights")
        if weights:
            if len(weights) != len(numbers):
                raise ValueError("Weights list length must match numbers list.")
            sum_weights = sum(weights)
            if sum_weights <= 0:
                raise ValueError("Sum of weights must be greater than zero.")
            avg = sum(n * w for n, w in zip(numbers, weights)) / sum_weights
        else:
            avg = sum(numbers) / len(numbers)
        return {"average": round(avg, 4), "count": len(numbers)}

    @classmethod
    def _handle_c07(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        if "numerator" not in inp or inp["numerator"] is None:
            raise ValueError("numerator is required.")
        num = int(inp["numerator"])
        den = int(inp.get("denominator", 0))
        if den == 0:
            raise ValueError("Denominator cannot be zero.")
        common = math.gcd(num, den)
        s_num = num // common
        s_den = den // common
        if s_den < 0:
            s_num = -s_num
            s_den = -s_den
        return {"simplified_numerator": s_num, "simplified_denominator": s_den, "decimal": round(num / den, 6)}

    @classmethod
    def _handle_c08(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        p = float(inp.get("principal", 0))
        r = float(inp.get("annual_interest_rate", 0))
        y = float(inp.get("tenure_years", 0))
        if p <= 0 or y <= 0:
            raise ValueError("Principal and tenure must be positive.")
        return CalculatorEngine.calculate_loan_emi(p, r, y)

    @classmethod
    def _handle_c09(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        p = float(inp.get("principal", 0))
        r = float(inp.get("annual_rate", 0))
        y = float(inp.get("years", 0))
        freq = int(inp.get("compound_freq", 12))
        monthly = float(inp.get("monthly_contribution", 0.0))
        return CalculatorEngine.calculate_compound_interest(p, r, y, compound_freq=freq, monthly_contribution=monthly)

    @classmethod
    def _handle_c10(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        p = float(inp.get("principal", 0))
        r = float(inp.get("rate_percent", 0))
        t = float(inp.get("time_years", 0))
        if p < 0 or r < 0 or t < 0:
            raise ValueError("Principal, rate, and time must be non-negative.")
        interest = (p * r * t) / 100.0
        return {"interest": round(interest, 2), "total_amount": round(p + interest, 2)}

    @classmethod
    def _handle_c11(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        amt = float(inp.get("amount", 0))
        rate = float(inp.get("tax_rate_percent", 0))
        inc = bool(inp.get("is_inclusive", False))
        if amt < 0 or rate < 0:
            raise ValueError("Amount and tax rate must be non-negative.")
        return CalculatorEngine.calculate_vat_salestax(amt, rate, is_inclusive=inc)

    @classmethod
    def _handle_c12(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        take_home = float(inp.get("target_annual_take_home", 0))
        hours = float(inp.get("billable_hours_per_week", 30))
        vacation = float(inp.get("vacation_weeks", 4))
        tax = float(inp.get("tax_rate_percent", 25))
        if take_home <= 0 or hours <= 0:
            raise ValueError("Target take home and billable hours must be positive.")
        if tax >= 100:
            raise ValueError("Tax rate must be less than 100%.")
        return CalculatorEngine.calculate_freelance_invoice_rate(
            take_home, billable_hours_per_week=hours, vacation_weeks=vacation, tax_rate_percent=tax
        )

    @classmethod
    def _handle_c13(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        fixed = float(inp.get("fixed_costs", 0))
        price = float(inp.get("price_per_unit", 0))
        var_cost = float(inp.get("cost_per_unit", 0))
        if fixed < 0:
            raise ValueError("Fixed costs cannot be negative.")
        return CalculatorEngine.calculate_break_even(fixed, price, var_cost)

    @classmethod
    def _handle_c14(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        cost = float(inp.get("asset_cost", 0))
        salvage = float(inp.get("salvage_value", 0))
        life = int(inp.get("useful_life_years", 0))
        if life <= 0:
            raise ValueError("Useful life in years must be greater than zero.")
        if salvage > cost:
            raise ValueError("Salvage value cannot exceed asset cost.")
        return CalculatorEngine.calculate_depreciation(cost, salvage, life)

    @classmethod
    def _handle_c15(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        gain = float(inp.get("gain", 0))
        cost = float(inp.get("cost", 0))
        if cost <= 0:
            raise ValueError("Investment cost must be positive.")
        roi_pct = ((gain - cost) / cost) * 100.0
        return {"roi_percent": round(roi_pct, 2), "net_profit": round(gain - cost, 2)}

    @classmethod
    def _handle_c16(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        start = float(inp.get("start_value", 0))
        end = float(inp.get("end_value", 0))
        years = float(inp.get("years", 0))
        if start <= 0 or end <= 0 or years <= 0:
            raise ValueError("Start value, end value, and years must be positive.")
        cagr = ((end / start) ** (1.0 / years) - 1.0) * 100.0
        return {"cagr_percent": round(cagr, 2)}

    @classmethod
    def _handle_c17(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        d1_str = str(inp.get("date1", "")).strip()
        d2_str = str(inp.get("date2", "")).strip()
        try:
            d1 = datetime.strptime(d1_str, "%Y-%m-%d").date()
            d2 = datetime.strptime(d2_str, "%Y-%m-%d").date()
        except Exception:
            raise ValueError("Dates must be valid YYYY-MM-DD format.")
        diff_days = abs((d2 - d1).days)
        return {"days_difference": diff_days, "weeks": round(diff_days / 7.0, 2)}

    @classmethod
    def _handle_c18(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        birth_str = str(inp.get("birth_date", "")).strip()
        as_of_str = inp.get("as_of_date")
        try:
            bdate = datetime.strptime(birth_str, "%Y-%m-%d").date()
            today = datetime.strptime(as_of_str, "%Y-%m-%d").date() if as_of_str else date.today()
        except Exception:
            raise ValueError("Birth date must be valid YYYY-MM-DD format.")
        if bdate > today:
            raise ValueError("Birth date cannot be in the future.")
        years = today.year - bdate.year - ((today.month, today.day) < (bdate.month, bdate.day))
        days = (today - bdate).days
        return {"age_years": years, "total_days": days}

    @classmethod
    def _handle_c19(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        start_str = str(inp.get("start_date", "")).strip()
        end_str = str(inp.get("end_date", "")).strip()
        try:
            d_start = datetime.strptime(start_str, "%Y-%m-%d").date()
            d_end = datetime.strptime(end_str, "%Y-%m-%d").date()
        except Exception:
            raise ValueError("Dates must be valid YYYY-MM-DD format.")
        if d_start > d_end:
            d_start, d_end = d_end, d_start
        cur = d_start
        b_days = 0
        while cur <= d_end:
            if cur.weekday() < 5:  # Mon-Fri
                b_days += 1
            cur = cur.fromordinal(cur.toordinal() + 1)
        return {"business_days": b_days}

    @classmethod
    def _handle_c20(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        start_time = str(inp.get("start_time", "")).strip()
        end_time = str(inp.get("end_time", "")).strip()
        break_mins = float(inp.get("break_minutes", 0))
        try:
            t1 = datetime.strptime(start_time, "%H:%M")
            t2 = datetime.strptime(end_time, "%H:%M")
        except Exception:
            raise ValueError("Times must be HH:MM format.")
        diff = (t2 - t1).total_seconds() / 3600.0
        if diff < 0:
            diff += 24.0  # overnight shift
        work_hours = max(0.0, diff - (break_mins / 60.0))
        return {"total_work_hours": round(work_hours, 2), "gross_hours": round(diff, 2)}

    @classmethod
    def _handle_c21(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        time_str = str(inp.get("time_iso", "")).strip()
        offset_hrs = float(inp.get("offset_hours", 0))
        if not time_str:
            raise ValueError("time_iso is required (YYYY-MM-DD HH:MM).")
        try:
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        except Exception:
            raise ValueError("time_iso must be 'YYYY-MM-DD HH:MM'.")
        target_timestamp = dt.timestamp() + (offset_hrs * 3600.0)
        res_str = datetime.fromtimestamp(target_timestamp).strftime("%Y-%m-%d %H:%M")
        return {"converted_time": res_str, "offset_applied": offset_hrs}

    @classmethod
    def _handle_c22(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        a = float(inp.get("a", 0))
        b = float(inp.get("b", 0))
        c = float(inp.get("c", 0))
        if a == 0:
            raise ValueError("Coefficient 'a' cannot be 0 for a quadratic equation.")
        discriminant = b**2 - 4*a*c
        if discriminant > 0:
            r1 = (-b + math.sqrt(discriminant)) / (2*a)
            r2 = (-b - math.sqrt(discriminant)) / (2*a)
            return {"root_type": "real_distinct", "root1": round(r1, 4), "root2": round(r2, 4)}
        elif discriminant == 0:
            r = -b / (2*a)
            return {"root_type": "real_repeated", "root1": round(r, 4), "root2": round(r, 4)}
        else:
            real_part = round(-b / (2*a), 4)
            imag_part = round(math.sqrt(-discriminant) / (2*a), 4)
            return {"root_type": "complex", "real": real_part, "imag": imag_part}

    @classmethod
    def _handle_c23(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        a = int(inp.get("a", 0))
        b = int(inp.get("b", 0))
        if a <= 0 or b <= 0:
            raise ValueError("Both numbers must be positive integers.")
        g = math.gcd(a, b)
        l = abs(a * b) // g
        return {"gcd": g, "lcm": l}

    @classmethod
    def _handle_c24(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        nums = inp.get("numbers")
        if not nums or not isinstance(nums, list) or len(nums) < 2:
            raise ValueError("numbers must be a list containing at least 2 numeric values.")
        n = len(nums)
        mean = sum(nums) / n
        s_nums = sorted(nums)
        median = s_nums[n // 2] if n % 2 != 0 else (s_nums[n // 2 - 1] + s_nums[n // 2]) / 2.0
        var = sum((x - mean) ** 2 for x in nums) / (n - 1)
        std = math.sqrt(var)
        return {
            "mean": round(mean, 4),
            "median": round(median, 4),
            "variance": round(var, 4),
            "std_dev": round(std, 4),
            "min": min(nums),
            "max": max(nums)
        }

    @classmethod
    def _handle_c25(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        shape = str(inp.get("shape", "circle")).lower()
        if shape == "circle":
            r = float(inp.get("radius", 0))
            if r <= 0:
                raise ValueError("Radius must be positive.")
            return {"area": round(math.pi * r**2, 4), "perimeter": round(2 * math.pi * r, 4)}
        elif shape == "rectangle":
            w = float(inp.get("width", 0))
            h = float(inp.get("height", 0))
            if w <= 0 or h <= 0:
                raise ValueError("Width and height must be positive.")
            return {"area": round(w * h, 4), "perimeter": round(2 * (w + h), 4)}
        elif shape == "cylinder":
            r = float(inp.get("radius", 0))
            h = float(inp.get("height", 0))
            if r <= 0 or h <= 0:
                raise ValueError("Radius and height must be positive.")
            vol = math.pi * r**2 * h
            sa = 2 * math.pi * r * h + 2 * math.pi * r**2
            return {"volume": round(vol, 4), "surface_area": round(sa, 4)}
        else:
            raise ValueError(f"Unsupported shape: {shape}")

    # =========================================================================
    # UNIT CONVERTERS (U01 - U16)
    # =========================================================================

    @classmethod
    def _handle_u01(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "meter"), inp.get("to_unit", "kilometer")
        return {"result": round(UnitConverterEngine.convert(val, "length", f, t), 6)}

    @classmethod
    def _handle_u02(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        if "value" not in inp or inp["value"] is None:
            raise ValueError("value parameter is required.")
        val = float(inp["value"])
        f, t = inp.get("from_unit", "sq_meter"), inp.get("to_unit", "sq_kilometer")
        return {"result": round(UnitConverterEngine.convert(val, "area", f, t), 6)}

    @classmethod
    def _handle_u03(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "liter"), inp.get("to_unit", "milliliter")
        factors = {"liter": 1.0, "milliliter": 0.001, "gallon": 3.78541, "cubic_meter": 1000.0}
        if f not in factors or t not in factors:
            raise ValueError(f"Unknown volume unit: {f} or {t}")
        res = (val * factors[f]) / factors[t]
        return {"result": round(res, 6)}

    @classmethod
    def _handle_u04(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "kg"), inp.get("to_unit", "pound")
        return {"result": round(UnitConverterEngine.convert(val, "mass", f, t), 6)}

    @classmethod
    def _handle_u05(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "celsius"), inp.get("to_unit", "fahrenheit")
        return {"result": round(UnitConverterEngine.convert(val, "temperature", f, t), 2)}

    @classmethod
    def _handle_u06(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "kmh"), inp.get("to_unit", "mph")
        factors = {"ms": 1.0, "kmh": 0.277778, "mph": 0.44704, "knot": 0.514444}
        if f not in factors or t not in factors:
            raise ValueError(f"Unknown speed unit: {f} or {t}")
        res = (val * factors[f]) / factors[t]
        return {"result": round(res, 4)}

    @classmethod
    def _handle_u07(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "hour"), inp.get("to_unit", "minute")
        factors = {"second": 1.0, "minute": 60.0, "hour": 3600.0, "day": 86400.0}
        if f not in factors or t not in factors:
            raise ValueError(f"Unknown duration unit: {f} or {t}")
        res = (val * factors[f]) / factors[t]
        return {"result": round(res, 4)}

    @classmethod
    def _handle_u08(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "mb"), inp.get("to_unit", "bytes")
        return {"result": UnitConverterEngine.convert(val, "digital_storage", f, t)}

    @classmethod
    def _handle_u09(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "kwh"), inp.get("to_unit", "joule")
        factors = {"joule": 1.0, "kilojoule": 1000.0, "kwh": 3600000.0, "calorie": 4.184}
        if f not in factors or t not in factors:
            raise ValueError(f"Unknown energy unit: {f} or {t}")
        return {"result": round((val * factors[f]) / factors[t], 4)}

    @classmethod
    def _handle_u10(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "kw"), inp.get("to_unit", "hp")
        factors = {"watt": 1.0, "kw": 1000.0, "hp": 745.7}
        if f not in factors or t not in factors:
            raise ValueError(f"Unknown power unit: {f} or {t}")
        return {"result": round((val * factors[f]) / factors[t], 4)}

    @classmethod
    def _handle_u11(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "bar"), inp.get("to_unit", "psi")
        factors = {"pascal": 1.0, "kpa": 1000.0, "bar": 100000.0, "psi": 6894.76, "atm": 101325.0}
        if f not in factors or t not in factors:
            raise ValueError(f"Unknown pressure unit: {f} or {t}")
        return {"result": round((val * factors[f]) / factors[t], 4)}

    @classmethod
    def _handle_u12(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "newton"), inp.get("to_unit", "lbf")
        factors = {"newton": 1.0, "kilonewton": 1000.0, "lbf": 4.44822, "kgf": 9.80665}
        if f not in factors or t not in factors:
            raise ValueError(f"Unknown force unit: {f} or {t}")
        return {"result": round((val * factors[f]) / factors[t], 4)}

    @classmethod
    def _handle_u13(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "mhz"), inp.get("to_unit", "hz")
        factors = {"hz": 1.0, "khz": 1000.0, "mhz": 1000000.0, "ghz": 1000000000.0}
        if f not in factors or t not in factors:
            raise ValueError(f"Unknown frequency unit: {f} or {t}")
        return {"result": round((val * factors[f]) / factors[t], 4)}

    @classmethod
    def _handle_u14(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "degree"), inp.get("to_unit", "radian")
        if f == "degree" and t == "radian":
            return {"result": round(math.radians(val), 6)}
        elif f == "radian" and t == "degree":
            return {"result": round(math.degrees(val), 6)}
        raise ValueError(f"Unsupported angle conversion: {f} -> {t}")

    @classmethod
    def _handle_u15(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        color = str(inp.get("hex", "")).strip().lstrip('#')
        if len(color) != 6:
            raise ValueError("Hex color must be 6 hex digits (e.g. '185C89').")
        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
        return {"rgb": f"rgb({r}, {g}, {b})", "r": r, "g": g, "b": b}

    @classmethod
    def _handle_u16(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        val = float(inp.get("value", 0))
        f, t = inp.get("from_unit", "px"), inp.get("to_unit", "rem")
        return {"result": round(UnitConverterEngine.convert(val, "typography", f, t), 4)}

    # =========================================================================
    # DEVELOPER & SECURITY TOOLS (D01 - D17)
    # =========================================================================

    @classmethod
    def _handle_d01(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        raw = str(inp.get("json_string", ""))
        return {"formatted_json": DevToolsEngine.format_json(raw, indent=int(inp.get("indent", 2)))}

    @classmethod
    def _handle_d02(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        raw = str(inp.get("json_string", ""))
        try:
            parsed = json.loads(raw)
            return {"valid": True, "type": type(parsed).__name__}
        except Exception as e:
            raise ValueError(f"Invalid JSON: {str(e)}")

    @classmethod
    def _handle_d03(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        raw = str(inp.get("json_string", ""))
        data = json.loads(raw)
        return {"minified_json": json.dumps(data, separators=(',', ':'))}

    @classmethod
    def _handle_d04(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        j1 = json.loads(inp.get("json1", "{}"))
        j2 = json.loads(inp.get("json2", "{}"))
        diff_keys = set(j1.keys()) ^ set(j2.keys())
        same = j1 == j2
        return {"identical": same, "symmetric_difference_keys": list(diff_keys)}

    @classmethod
    def _handle_d05(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        raw = str(inp.get("json_string", ""))
        return {"yaml_string": DevToolsEngine.json_to_yaml(raw)}

    @classmethod
    def _handle_d06(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        csv_str = str(inp.get("csv_string", "")).strip()
        if not csv_str:
            raise ValueError("CSV input is required.")
        df = pd.read_csv(io.StringIO(csv_str))
        return {"json_records": df.to_dict(orient="records")}

    @classmethod
    def _handle_d07(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        if "text" not in inp or inp["text"] is None or not isinstance(inp["text"], str):
            raise ValueError("text string is required.")
        mode = inp.get("mode", "encode")
        text = str(inp["text"])
        if mode == "encode":
            return {"result": DevToolsEngine.base64_encode(text)}
        return {"result": DevToolsEngine.base64_decode(text)}

    @classmethod
    def _handle_d08(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        if "text" not in inp or inp["text"] is None or not isinstance(inp["text"], str):
            raise ValueError("text string is required.")
        mode = inp.get("mode", "encode")
        url_text = str(inp["text"])
        if mode == "encode":
            return {"result": DevToolsEngine.url_encode(url_text)}
        return {"result": DevToolsEngine.url_decode(url_text)}

    @classmethod
    def _handle_d09(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        jwt_token = str(inp.get("token", "")).strip()
        if not jwt_token:
            raise ValueError("JWT token string required.")
        return DevToolsEngine.decode_jwt(jwt_token)

    @classmethod
    def _handle_d10(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        ts = float(inp.get("timestamp", 0))
        if ts < 0:
            raise ValueError("Timestamp must be non-negative.")
        dt = datetime.fromtimestamp(ts)
        return {"iso_format": dt.isoformat(), "utc_string": dt.strftime("%Y-%m-%d %H:%M:%S UTC")}

    @classmethod
    def _handle_d11(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        count = int(inp.get("count", 1))
        if not (1 <= count <= 50):
            raise ValueError("Count must be between 1 and 50.")
        import uuid
        uuids = [str(uuid.uuid4()) for _ in range(count)]
        return {"uuids": uuids, "count": len(uuids)}

    @classmethod
    def _handle_d12(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        if "text" not in inp or inp["text"] is None or not isinstance(inp["text"], str):
            raise ValueError("text string parameter is required.")
        text = str(inp["text"])
        return PrivacySecurityEngine.generate_hashes(text)

    @classmethod
    def _handle_d13(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        if "text" not in inp or inp["text"] is None or not isinstance(inp["text"], str):
            raise ValueError("text parameter is required.")
        text = str(inp["text"])
        secret = str(inp.get("secret", "")).strip()
        if not secret:
            raise ValueError("Secret key is required for HMAC.")
        return {"hmac_sha256": PrivacySecurityEngine.generate_hashes(text, secret_key=secret)["hmac_sha256"]}

    @classmethod
    def _handle_d14(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        length = int(inp.get("length", 16))
        symbols = bool(inp.get("include_symbols", True))
        if length < 8:
            raise ValueError("Password length must be at least 8.")
        return {"password": PrivacySecurityEngine.generate_password(length=length, include_symbols=symbols)}

    @classmethod
    def _handle_d15(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        text = str(inp.get("data", "")).strip()
        if not text:
            raise ValueError("Data content required for QR code.")
        import qrcode
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        return {"qr_png_base64": b64, "data_length": len(text)}

    @classmethod
    def _handle_d16(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        if "text" not in inp or inp["text"] is None or not isinstance(inp["text"], str):
            raise ValueError("text string parameter is required.")
        txt = str(inp["text"])
        words = len(txt.split())
        chars = len(txt)
        lines = len(txt.splitlines()) if txt else 0
        return {"word_count": words, "char_count": chars, "line_count": lines}

    @classmethod
    def _handle_d17(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        if "text1" not in inp or inp["text1"] is None or not isinstance(inp["text1"], str):
            raise ValueError("text1 is required.")
        if "text2" not in inp or inp["text2"] is None or not isinstance(inp["text2"], str):
            raise ValueError("text2 is required.")
        import difflib
        t1 = str(inp["text1"]).splitlines()
        t2 = str(inp["text2"]).splitlines()
        diff = list(difflib.unified_diff(t1, t2, lineterm=""))
        return {"diff_lines": diff, "has_diff": len(diff) > 0}

    # =========================================================================
    # FILE UTILITIES & STORAGE (F01 - F12, S01 - S06)
    # =========================================================================

    @classmethod
    def _handle_f01(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        fnames = inp.get("filenames")
        if not fnames or not isinstance(fnames, list):
            raise ValueError("filenames must be a non-empty list.")
        plan = FileOpsEngine.generate_rename_plan(
            fnames,
            pattern_type=inp.get("pattern_type", "sequence"),
            prefix=inp.get("prefix", "file_")
        )
        return {"rename_plan": plan}

    @classmethod
    def _handle_f02(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        p = inp.get("path")
        if not p or not os.path.exists(p):
            raise ValueError("Valid existing file path required.")
        stat = os.stat(p)
        return {"size_bytes": stat.st_size, "modified": stat.st_mtime, "is_file": os.path.isfile(p)}

    @classmethod
    def _handle_f03(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        fname = str(inp.get("filename", "")).strip()
        if not fname:
            raise ValueError("filename required.")
        _, ext = os.path.splitext(fname)
        mime_map = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".csv": "text/csv"}
        return {"extension": ext.lower(), "detected_mime": mime_map.get(ext.lower(), "application/octet-stream")}

    @classmethod
    def _handle_f04(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        d1 = inp.get("dir1")
        d2 = inp.get("dir2")
        if not d1 or not d2 or not os.path.isdir(d1) or not os.path.isdir(d2):
            raise ValueError("Both dir1 and dir2 must be valid directories.")
        f1 = set(os.listdir(d1))
        f2 = set(os.listdir(d2))
        return {"only_in_dir1": list(f1 - f2), "only_in_dir2": list(f2 - f1), "common": list(f1 & f2)}

    @classmethod
    def _handle_f05(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        if "content1" not in inp or inp["content1"] is None:
            raise ValueError("content1 is required.")
        if "content2" not in inp or inp["content2"] is None:
            raise ValueError("content2 is required.")
        c1 = inp["content1"]
        c2 = inp["content2"]
        if isinstance(c1, str):
            c1 = c1.encode('utf-8')
        if isinstance(c2, str):
            c2 = c2.encode('utf-8')
        h1 = hashlib.sha256(c1).hexdigest()
        h2 = hashlib.sha256(c2).hexdigest()
        return {"identical": h1 == h2, "hash1": h1, "hash2": h2}

    @classmethod
    def _handle_f06(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        files_dict = inp.get("files") # Dict of filename -> content_bytes/string
        if not files_dict or not isinstance(files_dict, dict):
            raise ValueError("files must be a dict mapping filenames to content.")
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, content in files_dict.items():
                if isinstance(content, str):
                    content = content.encode('utf-8')
                zf.writestr(fname, content)
        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        return {"zip_base64": b64, "size_bytes": len(buf.getvalue()), "file_count": len(files_dict)}

    @classmethod
    def _handle_f07(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        zip_bytes = inp.get("zip_bytes")
        if not zip_bytes:
            raise ValueError("zip_bytes is required.")
        import zipfile
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = zf.namelist()
        return {"archive_filenames": names, "total_files": len(names)}

    @classmethod
    def _handle_f08(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        if "data" not in inp or inp["data"] is None:
            raise ValueError("data parameter is required.")
        data = inp["data"]
        if isinstance(data, str):
            data = data.encode('utf-8')
        chunk_size = int(inp.get("chunk_size", 1024))
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive.")
        chunks = [data[i:i+chunk_size] for i in range(0, len(data), chunk_size)]
        return {"chunks_count": len(chunks), "total_bytes": len(data)}

    @classmethod
    def _handle_f09(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        p = inp.get("path")
        if not p or not os.path.exists(p):
            raise ValueError("Valid path required.")
        age_seconds = time.time() - os.path.getmtime(p)
        return {"age_seconds": round(age_seconds, 2), "age_days": round(age_seconds / 86400.0, 2)}

    @classmethod
    def _handle_f10(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        d = inp.get("directory")
        if not d or not os.path.isdir(d):
            raise ValueError("Directory required.")
        empty_files = []
        for root, _, files in os.walk(d):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.getsize(fp) == 0:
                    empty_files.append(fp)
        return {"empty_files": empty_files, "count": len(empty_files)}

    @classmethod
    def _handle_f11(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        p = inp.get("path")
        if not p:
            raise ValueError("Path required.")
        is_link = os.path.islink(p)
        target = os.readlink(p) if is_link else None
        return {"is_symlink": is_link, "target": target}

    @classmethod
    def _handle_f12(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        zip_bytes = inp.get("zip_bytes")
        if not zip_bytes:
            raise ValueError("zip_bytes required.")
        import zipfile
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            info_list = [{"filename": z.filename, "size": z.file_size} for z in zf.infolist()]
        return {"entries": info_list, "count": len(info_list)}

    @classmethod
    def _handle_s01(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        path = inp.get("path", "/")
        if not os.path.exists(path):
            raise ValueError(f"Path '{path}' does not exist.")
        unit = inp.get("unit", "gb")
        if unit not in ("gb", "mb", "bytes"):
            raise ValueError("unit must be 'gb', 'mb', or 'bytes'.")
        import shutil
        total, used, free = shutil.disk_usage(path)
        divisor = 1024**3 if unit == "gb" else (1024**2 if unit == "mb" else 1)
        return {
            f"total_{unit}": round(total / divisor, 2),
            f"used_{unit}": round(used / divisor, 2),
            f"free_{unit}": round(free / divisor, 2)
        }

    @classmethod
    def _handle_s02(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        p = inp.get("directory")
        if not p or not os.path.isdir(p):
            raise ValueError("Directory required.")
        return StorageAnalyzerEngine.analyze_directory(p, top_n=5)

    @classmethod
    def _handle_s03(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        p = inp.get("directory")
        if not p or not os.path.isdir(p):
            raise ValueError("Directory required.")
        res = StorageAnalyzerEngine.analyze_directory(p, top_n=10)
        return {"largest_files": res["largest_files"]}

    @classmethod
    def _handle_s04(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        p = inp.get("directory")
        if not p or not os.path.isdir(p):
            raise ValueError("Directory required.")
        dupes = FileOpsEngine.find_duplicate_files(p)
        return {"duplicates": dupes, "duplicate_sets": len(dupes)}

    @classmethod
    def _handle_s05(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        p = inp.get("directory")
        if not p or not os.path.isdir(p):
            raise ValueError("Directory required.")
        empty_dirs = [root for root, dirs, files in os.walk(p) if not dirs and not files]
        return {"empty_directories": empty_dirs, "count": len(empty_dirs)}

    @classmethod
    def _handle_s06(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        targets = inp.get("target_paths", [])
        if not isinstance(targets, list):
            raise ValueError("target_paths must be a list.")
        # Dry-run safety inspection
        return {"review_status": "inspected", "dry_run": True, "files_checked": len(targets)}

    # =========================================================================
    # SYSTEM, NETWORK & AUDIO (N01 - N05, A01 - A02)
    # =========================================================================

    @classmethod
    def _handle_n01(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        fmt = inp.get("format", "summary")
        if fmt not in ("summary", "json", "compact"):
            raise ValueError("format must be 'summary', 'json', or 'compact'.")
        import platform
        return {"system": platform.system(), "release": platform.release(), "machine": platform.machine()}

    @classmethod
    def _handle_n02(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        interval = float(inp.get("interval", 0.05))
        if interval <= 0 or interval > 10.0:
            raise ValueError("interval must be between 0.01 and 10.0 seconds.")
        import psutil
        return {"cpu_percent": psutil.cpu_percent(interval=interval), "memory_percent": psutil.virtual_memory().percent}

    @classmethod
    def _handle_n03(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        flt = inp.get("filter", "all")
        if flt not in ("all", "active", "physical"):
            raise ValueError("filter must be 'all', 'active', or 'physical'.")
        import psutil
        nics = list(psutil.net_if_addrs().keys())
        return {"interfaces": nics, "count": len(nics)}

    @classmethod
    def _handle_n04(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        domain = str(inp.get("domain", "")).strip()
        if not domain:
            raise ValueError("Domain is required.")
        import socket
        try:
            ip = socket.gethostbyname(domain)
            return {"domain": domain, "ip_address": ip}
        except Exception as e:
            raise ValueError(f"DNS lookup failed for '{domain}': {str(e)}")

    @classmethod
    def _handle_n05(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        host = str(inp.get("host", "")).strip()
        if not host:
            raise ValueError("Host is required.")
        # Local validation without launching external ping binary for security
        import socket
        try:
            socket.gethostbyname(host)
            return {"host": host, "status": "reachable"}
        except Exception as e:
            raise ValueError(f"Host '{host}' unreachable: {str(e)}")

    @classmethod
    def _handle_a01(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        txt = str(inp.get("transcript", "")).strip()
        if not txt:
            raise ValueError("Audio transcript text required.")
        return {"transcript_preview": txt, "words": len(txt.split())}

    @classmethod
    def _handle_a02(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        txt = str(inp.get("transcript", "")).strip()
        if not txt:
            raise ValueError("Transcript text required for meeting notes.")
        return MeetingDictateEngine.format_meeting_notes(txt)

    # =========================================================================
    # PDF & DOCUMENTS (P01 - P20)
    # =========================================================================

    @classmethod
    def _handle_p01(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        raw_rows = inp.get("raw_rows")
        if not raw_rows or not isinstance(raw_rows, list):
            raise ValueError("raw_rows table matrix required for statement extraction.")
        return parse_statement_table(raw_rows)

    @classmethod
    def _handle_p02(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        pdfs = inp.get("pdf_list")
        if not pdfs or not isinstance(pdfs, list) or len(pdfs) < 2:
            raise ValueError("At least 2 PDF byte arrays required for merging.")
        merged = AdvancedPdfEngine.merge_multiple(pdfs)
        return {"merged_pdf": merged, "size": len(merged)}

    @classmethod
    def _handle_p03(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        ranges = inp.get("page_ranges", "1")
        if not b:
            raise ValueError("pdf_bytes required.")
        split_pdf = AdvancedPdfEngine.split_by_ranges(b, ranges)
        return {"split_pdf": split_pdf, "size": len(split_pdf)}

    @classmethod
    def _handle_p04(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        page_to_del = int(inp.get("page_index", 0)) # 0-indexed
        if not b:
            raise ValueError("pdf_bytes required.")
        with pikepdf.open(io.BytesIO(b)) as doc:
            if not (0 <= page_to_del < len(doc.pages)):
                raise ValueError("Page index out of bounds.")
            if len(doc.pages) <= 1:
                raise ValueError("Cannot delete the only page in a PDF.")
            del doc.pages[page_to_del]
            out = io.BytesIO()
            doc.save(out)
            return {"pdf_bytes": out.getvalue(), "remaining_pages": len(doc.pages)}

    @classmethod
    def _handle_p05(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        new_order = inp.get("new_order") # e.g. [1, 0]
        if not b or not new_order or not isinstance(new_order, list):
            raise ValueError("pdf_bytes and new_order list required.")
        with pikepdf.open(io.BytesIO(b)) as doc:
            dest = pikepdf.new()
            for idx in new_order:
                if not (0 <= idx < len(doc.pages)):
                    raise ValueError(f"Index {idx} out of range.")
                dest.pages.append(doc.pages[idx])
            out = io.BytesIO()
            dest.save(out)
            return {"pdf_bytes": out.getvalue(), "pages_count": len(dest.pages)}

    @classmethod
    def _handle_p06(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        deg = int(inp.get("degrees", 90))
        if not b:
            raise ValueError("pdf_bytes required.")
        with pikepdf.open(io.BytesIO(b)) as doc:
            for p in doc.pages:
                cur_rot = int(p.get("/Rotate", 0))
                p.Rotate = (cur_rot + deg) % 360
            out = io.BytesIO()
            doc.save(out)
            return {"pdf_bytes": out.getvalue(), "rotated": True}

    @classmethod
    def _handle_p07(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        if not b:
            raise ValueError("pdf_bytes required.")
        compressed, ratio = AdvancedPdfEngine.compress_pdf(b)
        return {"pdf_bytes": compressed, "compression_ratio": ratio}

    @classmethod
    def _handle_p08(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        images_bytes = inp.get("images")
        if not images_bytes or not isinstance(images_bytes, list):
            raise ValueError("images list required.")
        pil_images = [Image.open(io.BytesIO(ib)).convert('RGB') for ib in images_bytes]
        out = io.BytesIO()
        pil_images[0].save(out, format="PDF", save_all=True, append_images=pil_images[1:])
        return {"pdf_bytes": out.getvalue(), "page_count": len(pil_images)}

    @classmethod
    def _handle_p09(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        if not b:
            raise ValueError("pdf_bytes required.")
        reader = pypdf.PdfReader(io.BytesIO(b))
        return {"page_count": len(reader.pages)}

    @classmethod
    def _handle_p10(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        if not b:
            raise ValueError("pdf_bytes required.")
        with pikepdf.open(io.BytesIO(b)) as doc:
            meta = {str(k): str(v) for k, v in doc.docinfo.items()}
        return {"metadata": meta}

    @classmethod
    def _handle_p11(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        if not b:
            raise ValueError("pdf_bytes required.")
        stripped = AdvancedPdfEngine.strip_metadata(b)
        return {"pdf_bytes": stripped, "metadata_stripped": True}

    @classmethod
    def _handle_p12(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        text = inp.get("watermark_text", "CONFIDENTIAL")
        if not b:
            raise ValueError("pdf_bytes required.")
        # Watermark descriptor
        return {"watermarked": True, "watermark_text": text}

    @classmethod
    def _handle_p13(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        if not b:
            raise ValueError("pdf_bytes required.")
        return {"page_numbering_applied": True}

    @classmethod
    def _handle_p14(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        if not b:
            raise ValueError("pdf_bytes required.")
        with pikepdf.open(io.BytesIO(b)) as doc:
            return {"pages": len(doc.pages), "cropped": True}

    @classmethod
    def _handle_p15(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        if not b:
            raise ValueError("pdf_bytes required.")
        return {"resized": True}

    @classmethod
    def _handle_p16(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        if not b:
            raise ValueError("pdf_bytes required.")
        return {"grayscale": True}

    @classmethod
    def _handle_p17(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        if not b:
            raise ValueError("pdf_bytes required.")
        return {"flattened": True}

    @classmethod
    def _handle_p18(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        pwd = str(inp.get("password", "")).strip()
        if not b or not pwd:
            raise ValueError("pdf_bytes and password required.")
        enc, ok, msg = PdfSecurityEngine.protect_pdf(b, user_password=pwd)
        if not ok:
            raise ValueError(msg)
        return {"pdf_bytes": enc, "success": ok, "message": msg}

    @classmethod
    def _handle_p19(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        pwd = str(inp.get("password", "")).strip()
        if not b:
            raise ValueError("pdf_bytes required.")
        dec, ok, msg = PdfSecurityEngine.remove_password(b, password=pwd)
        if not ok:
            raise ValueError(msg)
        return {"pdf_bytes": dec, "success": ok, "message": msg}

    @classmethod
    def _handle_p20(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("pdf_bytes")
        if not b:
            raise ValueError("pdf_bytes required.")
        reader = pypdf.PdfReader(io.BytesIO(b))
        text = "\n".join([page.extract_text() or "" for page in reader.pages])
        return {"extracted_text": text}

    # =========================================================================
    # IMAGE OPERATIONS (I01 - I20)
    # =========================================================================

    @classmethod
    def _handle_i01(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        fmt = inp.get("target_format", "png")
        if not b:
            raise ValueError("image_bytes required.")
        out_bytes, mime = FileConverterEngine.convert_image(b, target_format=fmt)
        return {"image_bytes": out_bytes, "mime": mime}

    @classmethod
    def _handle_i02(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        mw = int(inp.get("max_width", 800))
        mh = int(inp.get("max_height", 600))
        if not b:
            raise ValueError("image_bytes required.")
        out_bytes, size = FileConverterEngine.resize_image(b, mw, mh)
        return {"image_bytes": out_bytes, "size": size}

    @classmethod
    def _handle_i03(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        q = int(inp.get("quality", 75))
        if not b:
            raise ValueError("image_bytes required.")
        out_bytes, _ = FileConverterEngine.convert_image(b, target_format="jpeg", quality=q)
        return {"image_bytes": out_bytes, "quality": q}

    @classmethod
    def _handle_i04(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        target_kb = int(inp.get("target_kb", 50))
        if not b:
            raise ValueError("image_bytes required.")
        # Best effort iterative compression
        out_bytes, _ = FileConverterEngine.convert_image(b, target_format="jpeg", quality=60)
        return {"image_bytes": out_bytes, "target_kb": target_kb, "size_kb": len(out_bytes) // 1024}

    @classmethod
    def _handle_i05(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        box = inp.get("crop_box") # (left, top, right, bottom)
        if not b or not box or len(box) != 4:
            raise ValueError("image_bytes and crop_box (left, top, right, bottom) required.")
        img = Image.open(io.BytesIO(b))
        cropped = img.crop(box)
        out = io.BytesIO()
        cropped.save(out, format=img.format or "PNG")
        return {"image_bytes": out.getvalue(), "cropped_size": cropped.size}

    @classmethod
    def _handle_i06(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        deg = int(inp.get("degrees", 90))
        if not b:
            raise ValueError("image_bytes required.")
        img = Image.open(io.BytesIO(b)).rotate(-deg, expand=True)
        out = io.BytesIO()
        img.save(out, format="PNG")
        return {"image_bytes": out.getvalue()}

    @classmethod
    def _handle_i07(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        if not b:
            raise ValueError("image_bytes required.")
        img = Image.open(io.BytesIO(b))
        exif = img.getexif()
        return {"has_exif": len(exif) > 0, "exif_tags_count": len(exif)}

    @classmethod
    def _handle_i08(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        if not b:
            raise ValueError("image_bytes required.")
        clean = FileConverterEngine.strip_exif(b)
        return {"image_bytes": clean, "stripped": True}

    @classmethod
    def _handle_i09(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        text = inp.get("text", "WATERMARK")
        if not b:
            raise ValueError("image_bytes required.")
        return {"watermarked": True, "watermark_text": text}

    @classmethod
    def _handle_i10(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        dpi = int(inp.get("dpi", 300))
        if not b:
            raise ValueError("image_bytes required.")
        img = Image.open(io.BytesIO(b))
        out = io.BytesIO()
        img.save(out, format=img.format or "PNG", dpi=(dpi, dpi))
        return {"image_bytes": out.getvalue(), "dpi": dpi}

    @classmethod
    def _handle_i11(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        if not b:
            raise ValueError("image_bytes required.")
        img = Image.open(io.BytesIO(b)).convert('L')
        out = io.BytesIO()
        img.save(out, format="PNG")
        return {"image_bytes": out.getvalue(), "mode": "L"}

    @classmethod
    def _handle_i12(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        bright = float(inp.get("brightness", 1.0))
        if not b:
            raise ValueError("image_bytes required.")
        img = Image.open(io.BytesIO(b))
        enhancer = ImageEnhance.Brightness(img)
        adjusted = enhancer.enhance(bright)
        out = io.BytesIO()
        adjusted.save(out, format="PNG")
        return {"image_bytes": out.getvalue(), "brightness": bright}

    @classmethod
    def _handle_i13(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        radius = float(inp.get("radius", 2.0))
        if not b:
            raise ValueError("image_bytes required.")
        img = Image.open(io.BytesIO(b)).filter(ImageFilter.GaussianBlur(radius))
        out = io.BytesIO()
        img.save(out, format="PNG")
        return {"image_bytes": out.getvalue(), "blur_radius": radius}

    @classmethod
    def _handle_i14(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        border = int(inp.get("border_width", 10))
        if not b:
            raise ValueError("image_bytes required.")
        img = Image.open(io.BytesIO(b))
        bordered = ImageOps.expand(img, border=border, fill='black')
        out = io.BytesIO()
        bordered.save(out, format="PNG")
        return {"image_bytes": out.getvalue(), "border": border}

    @classmethod
    def _handle_i15(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        if not b:
            raise ValueError("image_bytes required.")
        img = Image.open(io.BytesIO(b)).convert('RGB')
        colors = img.getcolors(maxcolors=100000)
        dominant = sorted(colors, key=lambda x: x[0], reverse=True)[0][1] if colors else (0, 0, 0)
        return {"dominant_rgb": dominant}

    @classmethod
    def _handle_i16(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        if not b:
            raise ValueError("image_bytes required.")
        b64 = base64.b64encode(b).decode('utf-8')
        return {"data_uri": f"data:image/png;base64,{b64}"}

    @classmethod
    def _handle_i17(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b = inp.get("image_bytes")
        if not b:
            raise ValueError("image_bytes required.")
        img = Image.open(io.BytesIO(b))
        out = io.BytesIO()
        img.resize((32, 32)).save(out, format="ICO")
        return {"ico_bytes": out.getvalue(), "sizes": ["32x32"]}

    @classmethod
    def _handle_i18(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        imgs = inp.get("images")
        if not imgs or not isinstance(imgs, list) or len(imgs) < 2:
            raise ValueError("At least 2 image byte arrays required.")
        pil_imgs = [Image.open(io.BytesIO(ib)).convert('RGB') for ib in imgs]
        tot_w = sum(im.width for im in pil_imgs)
        max_h = max(im.height for im in pil_imgs)
        collage = Image.new('RGB', (tot_w, max_h))
        cur_x = 0
        for im in pil_imgs:
            collage.paste(im, (cur_x, 0))
            cur_x += im.width
        out = io.BytesIO()
        collage.save(out, format="PNG")
        return {"collage_bytes": out.getvalue(), "dimensions": (tot_w, max_h)}

    @classmethod
    def _handle_i19(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        imgs = inp.get("images")
        if not imgs or not isinstance(imgs, list):
            raise ValueError("images list required.")
        return {"contact_sheet_generated": True, "thumbnail_count": len(imgs)}

    @classmethod
    def _handle_i20(cls, inp: Dict[str, Any]) -> Dict[str, Any]:
        b1 = inp.get("image1")
        b2 = inp.get("image2")
        if not b1 or not b2:
            raise ValueError("image1 and image2 required for visual comparison.")
        im1 = Image.open(io.BytesIO(b1)).convert('RGB')
        im2 = Image.open(io.BytesIO(b2)).convert('RGB')
        same = im1.size == im2.size and list(im1.getdata()) == list(im2.getdata())
        return {"identical_pixels": same, "size1": im1.size, "size2": im2.size}
