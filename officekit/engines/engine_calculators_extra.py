"""Pending calculators (C06-C07, C15-C25): exact and validated calculation engine.

Every public method takes plain Python values, validates them before any
arithmetic, and raises ``ValueError`` with a fixed message from ``MESSAGES``
for invalid input. Routes map ``ValueError`` to HTTP 422. Money and
percentages quantize to 0.01, approximate unit-free results to 1e-10 and
geometry to 1e-6, always with ``ROUND_HALF_UP``.
"""

import calendar
import importlib.metadata
import math
import re
import statistics
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, DecimalException, InvalidOperation, localcontext
from fractions import Fraction
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo, available_timezones

MESSAGES = {
    "value_type": "Values must be finite JSON numbers",
    "value_range": "Values must be between -1,000,000,000,000 and 1,000,000,000,000",
    "value_count": "Provide between 1 and 10,000 values",
    "weight_type": "Weights must be finite JSON numbers",
    "weight_range": "Weights must be between 0 and 1,000,000,000,000",
    "length_mismatch": "Weights must have the same count as values",
    "negative_weight": "Weights must not be negative",
    "zero_weight_total": "At least one weight must be greater than zero",
    "missing_value": "Null values are not allowed under the reject policy",
    "no_values_after_skip": "No values remain after skipping missing values",
    "missing_policy": "Missing-value policy must be reject or skip",
    "fraction_type": "Fraction parts must be integers",
    "fraction_range": "Fraction parts must be between -1,000,000,000,000 and 1,000,000,000,000",
    "zero_denominator": "Denominator must not be zero",
    "divide_by_zero": "Cannot divide by a zero fraction",
    "right_required": "The selected operation needs a right-hand fraction",
    "right_forbidden": "Simplify takes only one fraction",
    "operation": "Operation must be simplify, add, subtract, multiply or divide",
    "result_range": "The result is outside the supported range",
    "invested_range": "Invested amount must be greater than 0 and no more than 1,000,000,000,000",
    "returned_range": "Returned amount must be between 0 and 1,000,000,000,000",
    "fees_range": "Fees must be between 0 and 1,000,000,000,000",
    "start_range": "Start value must be greater than 0 and no more than 1,000,000,000,000",
    "end_range": "End value must be between 0 and 1,000,000,000,000",
    "years_range": "Years must be greater than 0 and no more than 100",
    "date": "Dates must be valid YYYY-MM-DD values between 1600-01-01 and 2400-12-31",
    "inclusive_type": "Inclusive must be true or false",
    "birth_after_as_of": "Birth date must not be after the as-of date",
    "range_order": "End date must not be before start date",
    "weekend_invalid": "Weekend must list distinct weekdays from 0 (Monday) to 6 (Sunday), at most six",
    "range_length": "The date range must not exceed 36,600 days",
    "holiday_count": "Provide no more than 1,000 holiday dates",
    "work_rows": "Provide between 1 and 400 rows",
    "row_type": "Each row must be an object with start, end and break_minutes",
    "row_time_format": "row {row}: times must use HH:MM on a 24-hour clock",
    "time_format": "Times must use HH:MM on a 24-hour clock",
    "break_range": "row {row}: break minutes must be a whole number from 0 to 1440",
    "break_row": "row {row}: break must be shorter than the shift",
    "zone_requires_date": "A time zone needs a date on every row",
    "zone_unknown": "Time zone must be a known IANA name",
    "nonexistent_row": "row {row}: this local time does not exist in the time zone",
    "ambiguous_time": "AMBIGUOUS_TIME: choose the earlier or later occurrence",
    "nonexistent_time": "NONEXISTENT_TIME: this local time does not exist in the source zone",
    "fold_invalid": "Fold must be earlier or later",
    "target_count": "Provide between 1 and 10 target zones",
    "conversion_year": "Conversion dates must be between 1900-01-01 and 2100-12-31",
    "coefficient_range": "Coefficients must be between -1,000,000,000,000 and 1,000,000,000,000",
    "integer_count": "Provide between 2 and 100 integers",
    "integer_type": "Each item must be an integer",
    "integer_range": "Integers must be between -1,000,000,000,000 and 1,000,000,000,000",
    "sample_needs_two": "Sample variance needs at least two values",
    "statistics_kind": "Kind must be sample or population",
    "unit_invalid": "Unit must be one of mm, cm, m, km, in, ft, yd or mi",
    "shape_invalid": "Shape must be circle, rectangle, triangle, sphere, cylinder, cone or cuboid",
    "dimension_missing": "Every dimension for the selected shape is required",
    "dimension_range": "Dimensions must be greater than 0 and no more than 1,000,000",
    "triangle_inequality": "Each side must be shorter than the sum of the other two",
}

GEOMETRY_UNITS = ("mm", "cm", "m", "km", "in", "ft", "yd", "mi")
GEOMETRY_SHAPES = {
    "circle": ("radius",),
    "rectangle": ("width", "height"),
    "triangle": ("a", "b", "c"),
    "sphere": ("radius",),
    "cylinder": ("radius", "height"),
    "cone": ("radius", "height"),
    "cuboid": ("length", "width", "height"),
}
PI = Decimal("3.141592653589793238462643383279502884197169399375105820974944")
MAX_DIMENSION = Decimal("1000000")

DATE_MIN = date(1600, 1, 1)
DATE_MAX = date(2400, 12, 31)
MAX_RANGE_DAYS = 36600
MAX_HOLIDAYS = 1000
DEFAULT_WEEKEND = (5, 6)
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_CLOCK = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
MINUTES_PER_DAY = 1440
MAX_WORK_ROWS = 400
MAX_TARGET_ZONES = 10

LIMIT = Decimal("1000000000000")
APPROX_QUANTUM = "0.0000000001"
MONEY_QUANTUM = "0.01"
GEOMETRY_QUANTUM = "0.000001"
MAX_VALUES = 10000
MAX_MODES = 20


def _number(value: Any, message: str) -> Decimal:
    """Return a finite Decimal for a JSON number; reject bool, strings, NaN and infinity."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(message)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(message)
        return Decimal(str(value))
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(message)
        return value
    return Decimal(value)


def _in_limit(value: Decimal, low: Decimal, high: Decimal, message: str) -> Decimal:
    if not low <= value <= high:
        raise ValueError(message)
    return value


def _quantize(value: Decimal, quantum: str) -> Decimal:
    """Round half-up to ``quantum``; a result that cannot be represented is a 422, not a 500."""
    try:
        with localcontext() as context:
            context.prec = 40
            result = value.quantize(Decimal(quantum), rounding=ROUND_HALF_UP)
    except InvalidOperation as error:
        raise ValueError(MESSAGES["result_range"]) from error
    if not result.is_finite():
        raise ValueError(MESSAGES["result_range"])
    return result


def _float(value: Decimal, quantum: str) -> float:
    return float(_quantize(value, quantum))


def _fraction_part(part: Any) -> Fraction:
    if not isinstance(part, dict):
        raise ValueError(MESSAGES["fraction_type"])
    numerator = part.get("numerator")
    denominator = part.get("denominator")
    for component in (numerator, denominator):
        if isinstance(component, bool) or not isinstance(component, int):
            raise ValueError(MESSAGES["fraction_type"])
    if denominator == 0:
        raise ValueError(MESSAGES["zero_denominator"])
    if abs(numerator) > 10**12 or abs(denominator) > 10**12:
        raise ValueError(MESSAGES["fraction_range"])
    return Fraction(numerator, denominator)


def _decimal_text(value: Fraction) -> str:
    """Twenty significant digits, half-up, as plain decimal text."""
    with localcontext() as context:
        context.prec = 20
        context.rounding = ROUND_HALF_UP
        result = Decimal(value.numerator) / Decimal(value.denominator)
    return format(result, "f")


def _fraction_payload(value: Fraction) -> Dict[str, Any]:
    negative = value < 0
    whole_abs, remainder = divmod(abs(value.numerator), value.denominator)
    if whole_abs == 0:
        # A proper fraction carries its sign on the fraction: "0" and "-1/2", never "-0".
        whole = "0"
        remainder_text = f"-{remainder}" if negative else str(remainder)
    else:
        whole = f"-{whole_abs}" if negative else str(whole_abs)
        remainder_text = str(remainder)
    return {
        "numerator": str(value.numerator),
        "denominator": str(value.denominator),
        "mixed": {
            "whole": whole,
            "numerator": remainder_text,
            "denominator": str(value.denominator),
        },
        "decimal": _decimal_text(value),
        "is_integer": value.denominator == 1,
        "assumptions": {"exact": True},
    }


def _parse_iso_date(value: Any) -> date:
    """Strict YYYY-MM-DD within the supported calendar range; no timezone is involved."""
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise ValueError(MESSAGES["date"])
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(MESSAGES["date"]) from error
    if not DATE_MIN <= parsed <= DATE_MAX:
        raise ValueError(MESSAGES["date"])
    return parsed


def _add_months(start: date, months: int) -> date:
    """Add calendar months; the day is clamped to the last day of the target month."""
    year_offset, month_index = divmod(start.month - 1 + months, 12)
    year = start.year + year_offset
    month = month_index + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def _calendar_breakdown(start: date, end: date) -> Tuple[int, int, int]:
    """Years, months and remaining days from ``start`` to ``end`` (start <= end), month-end clamped."""
    total_months = (end.year - start.year) * 12 + (end.month - start.month)
    if _add_months(start, total_months) > end:
        total_months -= 1
    anchor = _add_months(start, total_months)
    return total_months // 12, total_months % 12, (end - anchor).days


def _anniversary(birth: date, year: int) -> date:
    """Birthday in ``year``; 29 February falls back to 28 February in common years."""
    try:
        return date(year, birth.month, birth.day)
    except ValueError:
        return date(year, 2, 28)


def _next_anniversary(birth: date, as_of: date) -> date:
    candidate = _anniversary(birth, as_of.year)
    if candidate < as_of:
        candidate = _anniversary(birth, as_of.year + 1)
    return candidate


@lru_cache(maxsize=1)
def _zone_names() -> Tuple[str, ...]:
    return tuple(sorted(available_timezones()))


@lru_cache(maxsize=1)
def _zone_name_set() -> frozenset:
    return frozenset(_zone_names())


@lru_cache(maxsize=1)
def _tzdata_version() -> str:
    try:
        return importlib.metadata.version("tzdata")
    except importlib.metadata.PackageNotFoundError:
        return "system"


def _zone(name: Any) -> ZoneInfo:
    if not isinstance(name, str) or name not in _zone_name_set():
        raise ValueError(MESSAGES["zone_unknown"])
    return ZoneInfo(name)


def _clock_minutes(text: Any, message: str) -> int:
    if not isinstance(text, str) or not _CLOCK.fullmatch(text):
        raise ValueError(message)
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def _local_instants(zone: ZoneInfo, naive: datetime) -> List[datetime]:
    """Real instants that show the wall time ``naive`` in ``zone``.

    Empty: the wall time does not exist (a gap). Two entries: it is ambiguous
    (fall-back overlap), ordered earlier (fold=0) then later (fold=1). A round
    trip through UTC keeps only the folds whose wall time survives.
    """
    instants: List[datetime] = []
    seen = set()
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold)
        instant = candidate.astimezone(timezone.utc)
        if instant.astimezone(zone).replace(tzinfo=None) != naive or instant in seen:
            continue
        seen.add(instant)
        instants.append(candidate)
    return instants


def _local_instant(zone: ZoneInfo, day: date, minutes: int, row: int) -> datetime:
    """Earliest UTC instant for a row's wall time. UTC keeps subtraction exact (same-tzinfo subtraction ignores DST)."""
    instants = _local_instants(zone, datetime(day.year, day.month, day.day, minutes // 60, minutes % 60))
    if not instants:
        raise ValueError(MESSAGES["nonexistent_row"].format(row=row))
    return instants[0].astimezone(timezone.utc)


def _offset_text(moment: datetime) -> str:
    total_minutes = int((moment.utcoffset() or timedelta(0)).total_seconds()) // 60
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    return f"{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _polynomial_residual(a: Decimal, b: Decimal, c: Decimal, real_part: Decimal, imaginary: Decimal) -> Decimal:
    """|a x^2 + b x + c| at x = real_part + i*imaginary, evaluated from the coefficients (independent of the root formula)."""
    real_value = a * (real_part * real_part - imaginary * imaginary) + b * real_part + c
    imaginary_value = 2 * a * real_part * imaginary + b * imaginary
    return (real_value * real_value + imaginary_value * imaginary_value).sqrt()


def _geometry_measures(shape: str, v: Dict[str, Decimal]) -> List[Tuple[str, Decimal, int, str]]:
    """(name, value, unit power, formula) for one shape; caller holds the Decimal context."""
    if shape == "circle":
        radius = v["radius"]
        return [
            ("area", PI * radius * radius, 2, "pi * r^2"),
            ("circumference", 2 * PI * radius, 1, "2 * pi * r"),
        ]
    if shape == "rectangle":
        width, height = v["width"], v["height"]
        return [
            ("area", width * height, 2, "width * height"),
            ("perimeter", 2 * (width + height), 1, "2 * (width + height)"),
        ]
    if shape == "triangle":
        a, b, c = v["a"], v["b"], v["c"]
        if not (a + b > c and b + c > a and a + c > b):
            raise ValueError(MESSAGES["triangle_inequality"])
        half = (a + b + c) / 2
        area = (half * (half - a) * (half - b) * (half - c)).sqrt()
        return [
            ("area", area, 2, "sqrt(s(s-a)(s-b)(s-c)), s = (a + b + c) / 2"),
            ("perimeter", a + b + c, 1, "a + b + c"),
        ]
    if shape == "sphere":
        radius = v["radius"]
        return [
            ("surface_area", 4 * PI * radius * radius, 2, "4 * pi * r^2"),
            ("volume", Decimal(4) / 3 * PI * radius * radius * radius, 3, "4/3 * pi * r^3"),
        ]
    if shape == "cylinder":
        radius, height = v["radius"], v["height"]
        return [
            ("volume", PI * radius * radius * height, 3, "pi * r^2 * height"),
            ("surface_area", 2 * PI * radius * (radius + height), 2, "2 * pi * r * (r + height)"),
        ]
    if shape == "cone":
        radius, height = v["radius"], v["height"]
        slant = (radius * radius + height * height).sqrt()
        return [
            ("slant_height", slant, 1, "sqrt(r^2 + height^2)"),
            ("volume", PI * radius * radius * height / 3, 3, "pi * r^2 * height / 3"),
            ("lateral_area", PI * radius * slant, 2, "pi * r * slant_height"),
            ("total_surface_area", PI * radius * (radius + slant), 2, "pi * r * (r + slant_height)"),
        ]
    length, width, height = v["length"], v["width"], v["height"]
    return [
        ("volume", length * width * height, 3, "length * width * height"),
        ("surface_area", 2 * (length * width + length * height + width * height), 2, "2 * (length*width + length*height + width*height)"),
    ]


class ExtendedCalculatorEngine:
    @staticmethod
    def calculate_weighted_average(
        values: Sequence[Any],
        weights: Optional[Sequence[Any]] = None,
        missing: str = "reject",
    ) -> Dict[str, Any]:
        if missing not in ("reject", "skip"):
            raise ValueError(MESSAGES["missing_policy"])
        if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= MAX_VALUES:
            raise ValueError(MESSAGES["value_count"])
        if weights is not None and (not isinstance(weights, (list, tuple)) or len(weights) != len(values)):
            raise ValueError(MESSAGES["length_mismatch"])

        pairs: List[Tuple[Decimal, Decimal]] = []
        skipped = 0
        for index, raw_value in enumerate(values):
            raw_weight = None if weights is None else weights[index]
            if raw_value is None or (weights is not None and raw_weight is None):
                if missing == "reject":
                    raise ValueError(MESSAGES["missing_value"])
                skipped += 1
                continue
            value = _in_limit(_number(raw_value, MESSAGES["value_type"]), -LIMIT, LIMIT, MESSAGES["value_range"])
            if weights is None:
                weight = Decimal(1)
            else:
                weight = _number(raw_weight, MESSAGES["weight_type"])
                if weight < 0:
                    raise ValueError(MESSAGES["negative_weight"])
                weight = _in_limit(weight, Decimal(0), LIMIT, MESSAGES["weight_range"])
            pairs.append((value, weight))

        if not pairs:
            raise ValueError(MESSAGES["no_values_after_skip"])
        total_weight = sum((weight for _, weight in pairs), Decimal(0))
        if total_weight == 0:
            raise ValueError(MESSAGES["zero_weight_total"])
        with localcontext() as context:
            context.prec = 40
            weighted_sum = sum((value * weight for value, weight in pairs), Decimal(0))
            mean = weighted_sum / total_weight

        return {
            "mean": _float(mean, APPROX_QUANTUM),
            "count_used": len(pairs),
            "count_skipped": skipped,
            "weight_total": _float(total_weight, APPROX_QUANTUM),
            "weighted": weights is not None,
            "assumptions": {"precision": "1e-10", "rounding": "half_up", "missing": missing},
        }

    @staticmethod
    def calculate_fraction(
        operation: str,
        left: Any,
        right: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if operation not in ("simplify", "add", "subtract", "multiply", "divide"):
            raise ValueError(MESSAGES["operation"])
        if operation == "simplify" and right is not None:
            raise ValueError(MESSAGES["right_forbidden"])
        if operation != "simplify" and right is None:
            raise ValueError(MESSAGES["right_required"])

        left_value = _fraction_part(left)
        if operation == "simplify":
            return _fraction_payload(left_value)
        right_value = _fraction_part(right)
        if operation == "add":
            result = left_value + right_value
        elif operation == "subtract":
            result = left_value - right_value
        elif operation == "multiply":
            result = left_value * right_value
        else:
            if right_value == 0:
                raise ValueError(MESSAGES["divide_by_zero"])
            result = left_value / right_value
        return _fraction_payload(result)

    @staticmethod
    def calculate_roi(invested: Any, returned: Any, fees: Any = 0) -> Dict[str, Any]:
        """Return on investment for one period; not annualised, fees added to cost."""
        invested_value = _number(invested, MESSAGES["value_type"])
        returned_value = _number(returned, MESSAGES["value_type"])
        fees_value = _number(fees, MESSAGES["value_type"])
        if not Decimal(0) < invested_value <= LIMIT:
            raise ValueError(MESSAGES["invested_range"])
        if not Decimal(0) <= returned_value <= LIMIT:
            raise ValueError(MESSAGES["returned_range"])
        if not Decimal(0) <= fees_value <= LIMIT:
            raise ValueError(MESSAGES["fees_range"])

        with localcontext() as context:
            context.prec = 40
            total_cost = invested_value + fees_value
            net_gain = returned_value - total_cost
            roi_percent = net_gain / total_cost * Decimal(100)
        return {
            "net_gain": _float(net_gain, MONEY_QUANTUM),
            "roi_percent": _float(roi_percent, MONEY_QUANTUM),
            "total_cost": _float(total_cost, MONEY_QUANTUM),
            "assumptions": {
                "annualised": False,
                "fees": "added_to_cost",
                "currency_precision": "0.01",
                "percent_precision": "0.01",
            },
        }

    @staticmethod
    def calculate_cagr(start_value: Any, end_value: Any, years: Any) -> Dict[str, Any]:
        """Compound annual growth rate solved from two endpoints over a fractional period."""
        start = _number(start_value, MESSAGES["value_type"])
        end = _number(end_value, MESSAGES["value_type"])
        period = _number(years, MESSAGES["value_type"])
        if not Decimal(0) < start <= LIMIT:
            raise ValueError(MESSAGES["start_range"])
        if not Decimal(0) <= end <= LIMIT:
            raise ValueError(MESSAGES["end_range"])
        if not Decimal(0) < period <= 100:
            raise ValueError(MESSAGES["years_range"])

        with localcontext() as context:
            context.prec = 40
            growth = end / start
            try:
                cagr = growth ** (Decimal(1) / period) - Decimal(1)
            except DecimalException as error:
                raise ValueError(MESSAGES["result_range"]) from error
            percent = cagr * Decimal(100)
        return {
            "cagr_percent": _float(percent, MONEY_QUANTUM),
            "growth_multiple": _float(growth, APPROX_QUANTUM),
            "assumptions": {"compounding": "annual", "percent_precision": "0.01"},
        }

    @staticmethod
    def calculate_date_difference(start_date: Any, end_date: Any, inclusive: Any = False) -> Dict[str, Any]:
        """Signed day count plus a calendar breakdown; ``inclusive`` changes only the reported day count."""
        start = _parse_iso_date(start_date)
        end = _parse_iso_date(end_date)
        if not isinstance(inclusive, bool):
            raise ValueError(MESSAGES["inclusive_type"])
        raw_days = (end - start).days
        if raw_days == 0:
            direction = "same"
        elif raw_days > 0:
            direction = "forward"
        else:
            direction = "backward"
        reported = raw_days
        if inclusive:
            reported = raw_days + (1 if raw_days >= 0 else -1)
        earlier, later = (start, end) if start <= end else (end, start)
        years, months, remaining = _calendar_breakdown(earlier, later)
        magnitude = abs(raw_days)
        return {
            "days": reported,
            "direction": direction,
            "years": years,
            "months": months,
            "rem_days": remaining,
            "weeks": magnitude // 7,
            "week_days": magnitude % 7,
            "assumptions": {"month_end": "clamp", "time_zone": "none"},
        }

    @staticmethod
    def calculate_age(birth_date: Any, as_of_date: Any) -> Dict[str, Any]:
        """Age on an explicit as-of date, with the next birthday on or after it."""
        birth = _parse_iso_date(birth_date)
        as_of = _parse_iso_date(as_of_date)
        if birth > as_of:
            raise ValueError(MESSAGES["birth_after_as_of"])
        years, months, remaining = _calendar_breakdown(birth, as_of)
        next_birthday = _next_anniversary(birth, as_of)
        return {
            "years": years,
            "months": months,
            "days": remaining,
            "total_days": (as_of - birth).days,
            "next_birthday": next_birthday.isoformat(),
            "days_to_next_birthday": (next_birthday - as_of).days,
            "assumptions": {"leap_birthday": "feb_28"},
        }

    @staticmethod
    def calculate_business_days(
        start_date: Any,
        end_date: Any,
        inclusive: Any = True,
        weekend: Any = DEFAULT_WEEKEND,
        holidays: Any = (),
    ) -> Dict[str, Any]:
        """Working days in a range. Exclusive is [start, end); inclusive is [start, end]."""
        start = _parse_iso_date(start_date)
        end = _parse_iso_date(end_date)
        if not isinstance(inclusive, bool):
            raise ValueError(MESSAGES["inclusive_type"])
        if end < start:
            raise ValueError(MESSAGES["range_order"])
        if not isinstance(weekend, (list, tuple)) or len(weekend) > 6:
            raise ValueError(MESSAGES["weekend_invalid"])
        for weekday in weekend:
            if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
                raise ValueError(MESSAGES["weekend_invalid"])
        if len(set(weekend)) != len(weekend):
            raise ValueError(MESSAGES["weekend_invalid"])
        if not isinstance(holidays, (list, tuple)) or len(holidays) > MAX_HOLIDAYS:
            raise ValueError(MESSAGES["holiday_count"])
        parsed_holidays = [_parse_iso_date(item) for item in holidays]

        span = (end - start).days + (1 if inclusive else 0)
        if span > MAX_RANGE_DAYS:
            raise ValueError(MESSAGES["range_length"])
        weekend_set = set(weekend)
        weekend_days = sum(1 for offset in range(span) if (start + timedelta(days=offset)).weekday() in weekend_set)

        unique_holidays = set(parsed_holidays)
        excluded = on_weekend = outside = 0
        for holiday in unique_holidays:
            offset = (holiday - start).days
            if not 0 <= offset < span:
                outside += 1
            elif holiday.weekday() in weekend_set:
                on_weekend += 1
            else:
                excluded += 1

        return {
            "business_days": span - weekend_days - excluded,
            "calendar_days": span,
            "weekend_days": weekend_days,
            "holidays_excluded": excluded,
            "holidays_on_weekend": on_weekend,
            "holidays_outside_range": outside,
            "duplicate_holidays": len(parsed_holidays) - len(unique_holidays),
            "assumptions": {"holiday_source": "user_list"},
        }

    @staticmethod
    def calculate_work_hours(rows: Any, time_zone: Optional[Any] = None) -> Dict[str, Any]:
        """Shift lengths minus breaks. With a zone, elapsed time is measured with zoneinfo (DST aware)."""
        if not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= MAX_WORK_ROWS:
            raise ValueError(MESSAGES["work_rows"])
        zone = None if time_zone is None else _zone(time_zone)

        records: List[Tuple[int, Optional[date], int, bool, int]] = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise ValueError(MESSAGES["row_type"])
            row_date = row.get("date")
            if zone is not None and row_date is None:
                raise ValueError(MESSAGES["zone_requires_date"])
            parsed_date = None if row_date is None else _parse_iso_date(row_date)
            start_minutes = _clock_minutes(row.get("start"), MESSAGES["row_time_format"].format(row=index))
            end_minutes = _clock_minutes(row.get("end"), MESSAGES["row_time_format"].format(row=index))
            break_minutes = row.get("break_minutes")
            if (
                isinstance(break_minutes, bool)
                or not isinstance(break_minutes, int)
                or not 0 <= break_minutes <= MINUTES_PER_DAY
            ):
                raise ValueError(MESSAGES["break_range"].format(row=index))

            overnight = end_minutes <= start_minutes
            shift = end_minutes - start_minutes + (MINUTES_PER_DAY if overnight else 0)
            if zone is None:
                elapsed = shift
                dst_adjusted = 0
            else:
                start_at = _local_instant(zone, parsed_date, start_minutes, index)
                end_day = parsed_date + timedelta(days=1) if overnight else parsed_date
                end_at = _local_instant(zone, end_day, end_minutes, index)
                elapsed = int((end_at - start_at).total_seconds()) // 60
                dst_adjusted = elapsed - shift
            if break_minutes >= elapsed:
                raise ValueError(MESSAGES["break_row"].format(row=index))
            records.append((index, parsed_date, elapsed - break_minutes, overnight, dst_adjusted))

        total_minutes = sum(worked for _, _, worked, _, _ in records)
        weeks: Dict[str, int] = {}
        for _, parsed_date, worked, _, _ in records:
            if parsed_date is None:
                continue
            iso = parsed_date.isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
            weeks[key] = weeks.get(key, 0) + worked
        return {
            "rows": [
                {"index": index, "worked_minutes": worked, "overnight": overnight, "dst_adjusted_minutes": adjusted}
                for index, _, worked, overnight, adjusted in records
            ],
            "total_minutes": total_minutes,
            "total_hours": _float(Decimal(total_minutes) / Decimal(60), MONEY_QUANTUM),
            "weeks": [{"iso_week": key, "total_minutes": weeks[key]} for key in sorted(weeks)],
            "assumptions": {
                "dst": "zoneinfo" if zone is not None else "not_applied",
                "overnight": "end_before_start",
            },
        }

    @staticmethod
    def list_time_zones() -> Dict[str, Any]:
        return {"zones": list(_zone_names()), "tzdata_version": _tzdata_version()}

    @staticmethod
    def convert_time_zone(
        date_text: Any,
        time_text: Any,
        from_zone: Any,
        to_zones: Any,
        fold: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Convert one local wall time between zones using the zone rules for that date."""
        day = _parse_iso_date(date_text)
        if not 1900 <= day.year <= 2100:
            raise ValueError(MESSAGES["conversion_year"])
        minutes = _clock_minutes(time_text, MESSAGES["time_format"])
        source_zone = _zone(from_zone)
        if not isinstance(to_zones, (list, tuple)) or not 1 <= len(to_zones) <= MAX_TARGET_ZONES:
            raise ValueError(MESSAGES["target_count"])
        target_names = list(to_zones)
        for name in target_names:
            _zone(name)
        if fold not in (None, "earlier", "later"):
            raise ValueError(MESSAGES["fold_invalid"])

        naive = datetime(day.year, day.month, day.day, minutes // 60, minutes % 60)
        instants = _local_instants(source_zone, naive)
        if not instants:
            raise ValueError(MESSAGES["nonexistent_time"])
        if len(instants) > 1:
            if fold is None:
                raise ValueError(MESSAGES["ambiguous_time"])
            chosen = instants[0] if fold == "earlier" else instants[1]
        else:
            chosen = instants[0]

        instant = chosen.astimezone(timezone.utc)
        targets = []
        for name in target_names:
            local = instant.astimezone(_zone(name))
            targets.append(
                {
                    "zone": name,
                    "local": local.strftime("%Y-%m-%dT%H:%M"),
                    "offset": _offset_text(local),
                    "abbreviation": local.tzname(),
                    "dst": bool(local.dst()),
                    "day_shift": (local.date() - day).days,
                }
            )
        return {
            "utc": instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": {
                "zone": from_zone,
                "local": naive.strftime("%Y-%m-%dT%H:%M"),
                "offset": _offset_text(chosen),
                "abbreviation": chosen.tzname(),
                "dst": bool(chosen.dst()),
            },
            "targets": targets,
            "assumptions": {"tz_database": _tzdata_version()},
        }

    @staticmethod
    def solve_quadratic(a: Any, b: Any, c: Any) -> Dict[str, Any]:
        """Real, repeated, complex or degenerate roots. Stable formula; residuals recomputed independently."""
        coefficients = [
            _in_limit(_number(value, MESSAGES["value_type"]), -LIMIT, LIMIT, MESSAGES["coefficient_range"])
            for value in (a, b, c)
        ]
        qa, qb, qc = coefficients
        with localcontext() as context:
            context.prec = 40
            if qa == 0:
                if qb != 0:
                    kind = "linear"
                    roots = [(-qc / qb, Decimal(0))]
                    discriminant = None
                elif qc == 0:
                    kind, roots, discriminant = "all_numbers", [], None
                else:
                    kind, roots, discriminant = "no_solution", [], None
            else:
                discriminant = qb * qb - 4 * qa * qc
                if discriminant > 0:
                    kind = "two_real"
                    sign = Decimal(1) if qb >= 0 else Decimal(-1)
                    stable = -(qb + sign * discriminant.sqrt()) / 2
                    roots = sorted([(stable / qa, Decimal(0)), (qc / stable, Decimal(0))])
                elif discriminant == 0:
                    kind = "repeated_real"
                    roots = [(-qb / (2 * qa), Decimal(0))]
                else:
                    kind = "complex_pair"
                    real_part = -qb / (2 * qa)
                    imaginary = (-discriminant).sqrt() / abs(2 * qa)
                    roots = [(real_part, -imaginary), (real_part, imaginary)]
            max_residual = Decimal(0)
            for real_part, imaginary in roots:
                # Residual of the roots as returned (rounded to the approximate quantum), so a reader can check it.
                shown_real = _quantize(real_part, APPROX_QUANTUM)
                shown_imaginary = _quantize(imaginary, APPROX_QUANTUM)
                residual = _polynomial_residual(qa, qb, qc, shown_real, shown_imaginary)
                max_residual = max(max_residual, residual)

        return {
            "kind": kind,
            # Only a quadratic has a discriminant; linear and degenerate kinds report null.
            "discriminant": None if discriminant is None else _float(discriminant, APPROX_QUANTUM),
            "roots": [
                {"real": _float(real_part, APPROX_QUANTUM), "imaginary": _float(imaginary, APPROX_QUANTUM)}
                for real_part, imaginary in roots
            ],
            "max_residual": _float(max_residual, APPROX_QUANTUM),
            "assumptions": {"precision": "1e-10", "method": "stable_quadratic"},
        }

    @staticmethod
    def calculate_gcd_lcm(integers: Any) -> Dict[str, Any]:
        if not isinstance(integers, (list, tuple)) or not 2 <= len(integers) <= 100:
            raise ValueError(MESSAGES["integer_count"])
        magnitudes = []
        for item in integers:
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValueError(MESSAGES["integer_type"])
            if abs(item) > 10**12:
                raise ValueError(MESSAGES["integer_range"])
            magnitudes.append(abs(item))
        return {
            "gcd": str(math.gcd(*magnitudes)),
            "lcm": str(math.lcm(*magnitudes)),
            "count": len(magnitudes),
            "assumptions": {"sign": "absolute", "zero_policy": "gcd(0,0)=0; lcm with 0 = 0"},
        }

    @staticmethod
    def calculate_statistics(values: Any, kind: Any) -> Dict[str, Any]:
        """Descriptive statistics on Decimal values with the stdlib statistics module (no float conversion)."""
        if kind not in ("sample", "population"):
            raise ValueError(MESSAGES["statistics_kind"])
        if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= MAX_VALUES:
            raise ValueError(MESSAGES["value_count"])
        numbers = [
            _in_limit(_number(item, MESSAGES["value_type"]), -LIMIT, LIMIT, MESSAGES["value_range"])
            for item in values
        ]
        count = len(numbers)
        with localcontext() as context:
            context.prec = 40
            total = sum(numbers, Decimal(0))
            mean = statistics.mean(numbers)
            median = statistics.median(numbers)
            frequencies = Counter(numbers)
            top = max(frequencies.values())
            if top == 1:
                modes: List[Decimal] = []
                no_mode = True
            else:
                modes = sorted(value for value, seen in frequencies.items() if seen == top)
                no_mode = False
            if kind == "population":
                variance: Optional[Decimal] = statistics.pvariance(numbers)
                std_dev: Optional[Decimal] = statistics.pstdev(numbers)
                reason = None
            elif count < 2:
                variance, std_dev, reason = None, None, MESSAGES["sample_needs_two"]
            else:
                variance = statistics.variance(numbers)
                std_dev = statistics.stdev(numbers)
                reason = None
            minimum, maximum = min(numbers), max(numbers)

        return {
            "count": count,
            "sum": _float(total, APPROX_QUANTUM),
            "mean": _float(mean, APPROX_QUANTUM),
            "median": _float(median, APPROX_QUANTUM),
            "modes": [_float(value, APPROX_QUANTUM) for value in modes[:MAX_MODES]],
            "modes_truncated": len(modes) > MAX_MODES,
            "no_mode": no_mode,
            "minimum": _float(minimum, APPROX_QUANTUM),
            "maximum": _float(maximum, APPROX_QUANTUM),
            "range": _float(maximum - minimum, APPROX_QUANTUM),
            "variance": None if variance is None else _float(variance, APPROX_QUANTUM),
            "std_dev": None if std_dev is None else _float(std_dev, APPROX_QUANTUM),
            "variance_unavailable_reason": reason,
            "assumptions": {"kind": kind, "precision": "1e-10"},
        }

    @staticmethod
    def calculate_geometry(shape: Any, unit: Any, dimensions: Any) -> Dict[str, Any]:
        """Areas, perimeters, volumes and surfaces. Unit powers are 1 (length), 2 (area) or 3 (volume)."""
        if not isinstance(shape, str) or shape not in GEOMETRY_SHAPES:
            raise ValueError(MESSAGES["shape_invalid"])
        if not isinstance(unit, str) or unit not in GEOMETRY_UNITS:
            raise ValueError(MESSAGES["unit_invalid"])
        if not isinstance(dimensions, dict):
            raise ValueError(MESSAGES["dimension_missing"])
        values: Dict[str, Decimal] = {}
        for name in GEOMETRY_SHAPES[shape]:
            if name not in dimensions:
                raise ValueError(MESSAGES["dimension_missing"])
            number = _number(dimensions[name], MESSAGES["value_type"])
            if not Decimal(0) < number <= MAX_DIMENSION:
                raise ValueError(MESSAGES["dimension_range"])
            values[name] = number
        with localcontext() as context:
            context.prec = 40
            measures = _geometry_measures(shape, values)
        return {
            "shape": shape,
            "unit": unit,
            "measures": [
                {"name": name, "value": _float(value, GEOMETRY_QUANTUM), "unit_power": power, "formula": formula}
                for name, value, power, formula in measures
            ],
            "assumptions": {"pi": "decimal_40", "precision": "1e-6"},
        }
