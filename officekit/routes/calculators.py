"""Calculators slice routes (C06–C07, C15–C25).

Request DTOs are strict: unknown keys are rejected, numbers must be JSON numbers
(no bool or string coercion) and finite. Domain errors from the engine map to
422 with the engine's fixed message. Computations store nothing, so they return 200.
"""

from typing import Annotated, List, Literal, Optional, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator

from officekit.engines.engine_calculators_extra import MESSAGES
from officekit.engines.engine_calculators_extra import ExtendedCalculatorEngine as Engine

RESULT_RANGE_MESSAGE = MESSAGES["result_range"]

router = APIRouter()

SCALAR_BODY_LIMIT = 16 * 1024
LIST_BODY_LIMIT = 512 * 1024

BODY_LIMITS = {
    "/api/calculator/averages": LIST_BODY_LIMIT,
    "/api/calculator/fractions": SCALAR_BODY_LIMIT,
    "/api/calculator/roi": SCALAR_BODY_LIMIT,
    "/api/calculator/cagr": SCALAR_BODY_LIMIT,
    "/api/calculator/date-differences": SCALAR_BODY_LIMIT,
    "/api/calculator/ages": SCALAR_BODY_LIMIT,
    "/api/calculator/business-days": LIST_BODY_LIMIT,
    "/api/calculator/work-hours": LIST_BODY_LIMIT,
    "/api/calculator/time-zone-conversions": SCALAR_BODY_LIMIT,
    "/api/calculator/quadratics": SCALAR_BODY_LIMIT,
    "/api/calculator/gcd-lcm": SCALAR_BODY_LIMIT,
    "/api/calculator/statistics": LIST_BODY_LIMIT,
    "/api/calculator/geometry": SCALAR_BODY_LIMIT,
}

EXPOSE_HEADERS = ()

MAGNITUDE = 1e12
DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
CLOCK_PATTERN = r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"

WeightNumber = Annotated[float, Field(ge=-MAGNITUDE, le=MAGNITUDE, allow_inf_nan=False)]
Integer = Annotated[StrictInt, Field(ge=-int(MAGNITUDE), le=int(MAGNITUDE))]


def _json_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Value must be a JSON number")
    return value


def _json_number_list(value):
    if not isinstance(value, list):
        raise ValueError("Value must be a JSON array")
    for item in value:
        if item is not None:
            _json_number(item)
    return value


JsonNumber = BeforeValidator(_json_number)
ValueNumber = Annotated[float, JsonNumber, Field(ge=-MAGNITUDE, le=MAGNITUDE, allow_inf_nan=False)]
PositiveNumber = Annotated[float, JsonNumber, Field(gt=0, le=MAGNITUDE, allow_inf_nan=False)]
NonNegativeNumber = Annotated[float, JsonNumber, Field(ge=0, le=MAGNITUDE, allow_inf_nan=False)]


def _calculate(call):
    try:
        return call()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ArithmeticError as error:
        # Backstop: any decimal or integer overflow that escapes an engine guard is a client
        # range error with the fixed result message, never a 500.
        raise HTTPException(status_code=422, detail=RESULT_RANGE_MESSAGE) from error


# Averages (C06)

class AveragesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: List[Optional[ValueNumber]] = Field(min_length=1, max_length=10000)
    weights: Optional[List[Optional[WeightNumber]]] = Field(default=None, min_length=1, max_length=10000)
    missing: Literal["reject", "skip"] = "reject"

    @field_validator("values", "weights", mode="before")
    @classmethod
    def numbers_are_json_numbers_or_null(cls, value):
        return value if value is None else _json_number_list(value)


class AveragesAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    precision: Literal["1e-10"]
    rounding: Literal["half_up"]
    missing: Literal["reject", "skip"]


class AveragesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mean: float
    count_used: int
    count_skipped: int
    weight_total: float
    weighted: bool
    assumptions: AveragesAssumptions


@router.post("/api/calculator/averages", response_model=AveragesResponse)
def api_averages(req: AveragesRequest) -> AveragesResponse:
    return AveragesResponse.model_validate(_calculate(lambda: Engine.calculate_weighted_average(
        req.values, req.weights, req.missing
    )))


# Fractions (C07)

class FractionPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numerator: Integer
    denominator: Integer


class FractionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["simplify", "add", "subtract", "multiply", "divide"]
    left: FractionPart
    right: Optional[FractionPart] = None


class MixedNumber(BaseModel):
    model_config = ConfigDict(extra="forbid")
    whole: str
    numerator: str
    denominator: str


class FractionsAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exact: Literal[True]


class FractionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numerator: str
    denominator: str
    mixed: MixedNumber
    decimal: str
    is_integer: bool
    assumptions: FractionsAssumptions


@router.post("/api/calculator/fractions", response_model=FractionsResponse)
def api_fractions(req: FractionsRequest) -> FractionsResponse:
    left = req.left.model_dump()
    right = None if req.right is None else req.right.model_dump()
    return FractionsResponse.model_validate(_calculate(lambda: Engine.calculate_fraction(
        req.operation, left, right
    )))


# ROI (C15)

class RoiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invested: PositiveNumber
    returned: NonNegativeNumber
    fees: NonNegativeNumber = 0


class RoiAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    annualised: Literal[False]
    fees: Literal["added_to_cost"]
    currency_precision: Literal["0.01"]
    percent_precision: Literal["0.01"]


class RoiResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    net_gain: float
    roi_percent: float
    total_cost: float
    assumptions: RoiAssumptions


@router.post("/api/calculator/roi", response_model=RoiResponse)
def api_roi(req: RoiRequest) -> RoiResponse:
    return RoiResponse.model_validate(_calculate(lambda: Engine.calculate_roi(
        req.invested, req.returned, req.fees
    )))


# CAGR (C16)

class CagrRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_value: PositiveNumber
    end_value: NonNegativeNumber
    years: Annotated[float, JsonNumber, Field(gt=0, le=100, allow_inf_nan=False)]


class CagrAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compounding: Literal["annual"]
    percent_precision: Literal["0.01"]


class CagrResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cagr_percent: float
    growth_multiple: float
    assumptions: CagrAssumptions


@router.post("/api/calculator/cagr", response_model=CagrResponse)
def api_cagr(req: CagrRequest) -> CagrResponse:
    return CagrResponse.model_validate(_calculate(lambda: Engine.calculate_cagr(
        req.start_value, req.end_value, req.years
    )))


# Date differences (C17)

class DateDifferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: StrictStr = Field(pattern=DATE_PATTERN)
    end_date: StrictStr = Field(pattern=DATE_PATTERN)
    inclusive: StrictBool = False


class DateDifferenceAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month_end: Literal["clamp"]
    time_zone: Literal["none"]


class DateDifferenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int
    direction: Literal["forward", "backward", "same"]
    years: int
    months: int
    rem_days: int
    weeks: int
    week_days: int
    assumptions: DateDifferenceAssumptions


@router.post("/api/calculator/date-differences", response_model=DateDifferenceResponse)
def api_date_differences(req: DateDifferenceRequest) -> DateDifferenceResponse:
    return DateDifferenceResponse.model_validate(_calculate(lambda: Engine.calculate_date_difference(
        req.start_date, req.end_date, req.inclusive
    )))


# Ages (C18)

class AgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    birth_date: StrictStr = Field(pattern=DATE_PATTERN)
    as_of_date: StrictStr = Field(pattern=DATE_PATTERN)


class AgeAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    leap_birthday: Literal["feb_28"]


class AgeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    years: int
    months: int
    days: int
    total_days: int
    next_birthday: str
    days_to_next_birthday: int
    assumptions: AgeAssumptions


@router.post("/api/calculator/ages", response_model=AgeResponse)
def api_ages(req: AgeRequest) -> AgeResponse:
    return AgeResponse.model_validate(_calculate(lambda: Engine.calculate_age(req.birth_date, req.as_of_date)))


# Business days (C19)

class BusinessDaysRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: StrictStr = Field(pattern=DATE_PATTERN)
    end_date: StrictStr = Field(pattern=DATE_PATTERN)
    inclusive: StrictBool = True
    weekend: List[Annotated[StrictInt, Field(ge=0, le=6)]] = Field(default_factory=lambda: [5, 6], max_length=6)
    holidays: List[StrictStr] = Field(default_factory=list, max_length=1000)

    @field_validator("holidays", mode="before")
    @classmethod
    def holidays_are_a_list(cls, value):
        if not isinstance(value, list):
            raise ValueError("Value must be a JSON array")
        return value


class BusinessDaysAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    holiday_source: Literal["user_list"]


class BusinessDaysResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_days: int
    calendar_days: int
    weekend_days: int
    holidays_excluded: int
    holidays_on_weekend: int
    holidays_outside_range: int
    duplicate_holidays: int
    assumptions: BusinessDaysAssumptions


@router.post("/api/calculator/business-days", response_model=BusinessDaysResponse)
def api_business_days(req: BusinessDaysRequest) -> BusinessDaysResponse:
    return BusinessDaysResponse.model_validate(_calculate(lambda: Engine.calculate_business_days(
        req.start_date, req.end_date, req.inclusive, tuple(req.weekend), tuple(req.holidays)
    )))


# Work hours (C20)

class WorkRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: Optional[StrictStr] = Field(default=None, pattern=DATE_PATTERN)
    start: StrictStr = Field(pattern=CLOCK_PATTERN)
    end: StrictStr = Field(pattern=CLOCK_PATTERN)
    break_minutes: Annotated[StrictInt, Field(ge=0, le=1440)]


class WorkHoursRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: List[WorkRow] = Field(min_length=1, max_length=400)
    time_zone: Optional[StrictStr] = Field(default=None, max_length=64)


class WorkRowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    worked_minutes: int
    overnight: bool
    dst_adjusted_minutes: int


class WeekTotal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    iso_week: str
    total_minutes: int


class WorkHoursAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dst: Literal["zoneinfo", "not_applied"]
    overnight: Literal["end_before_start"]


class WorkHoursResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: List[WorkRowResult]
    total_minutes: int
    total_hours: float
    weeks: List[WeekTotal]
    assumptions: WorkHoursAssumptions


@router.post("/api/calculator/work-hours", response_model=WorkHoursResponse)
def api_work_hours(req: WorkHoursRequest) -> WorkHoursResponse:
    rows = [row.model_dump() for row in req.rows]
    return WorkHoursResponse.model_validate(_calculate(lambda: Engine.calculate_work_hours(rows, req.time_zone)))


# Time zones (C21)

class TimeZonesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zones: List[str]
    tzdata_version: str


@router.get("/api/calculator/time-zones", response_model=TimeZonesResponse)
def api_time_zones() -> TimeZonesResponse:
    return TimeZonesResponse.model_validate(Engine.list_time_zones())


class TimeZoneConversionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: StrictStr = Field(pattern=DATE_PATTERN)
    time: StrictStr = Field(pattern=CLOCK_PATTERN)
    from_zone: StrictStr = Field(max_length=64)
    to_zones: List[Annotated[StrictStr, Field(max_length=64)]] = Field(min_length=1, max_length=10)
    fold: Optional[Literal["earlier", "later"]] = None


class ZoneInstant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zone: str
    local: str
    offset: str
    abbreviation: str
    dst: bool


class ZoneTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zone: str
    local: str
    offset: str
    abbreviation: str
    dst: bool
    day_shift: int


class TimeZoneAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tz_database: str


class TimeZoneConversionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    utc: str
    source: ZoneInstant
    targets: List[ZoneTarget]
    assumptions: TimeZoneAssumptions


@router.post("/api/calculator/time-zone-conversions", response_model=TimeZoneConversionResponse)
def api_time_zone_conversions(req: TimeZoneConversionRequest) -> TimeZoneConversionResponse:
    return TimeZoneConversionResponse.model_validate(_calculate(lambda: Engine.convert_time_zone(
        req.date, req.time, req.from_zone, list(req.to_zones), req.fold
    )))


# Quadratics (C22)

class QuadraticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: ValueNumber
    b: ValueNumber
    c: ValueNumber


class QuadraticRoot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    real: float
    imaginary: float


class QuadraticAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    precision: Literal["1e-10"]
    method: Literal["stable_quadratic"]


class QuadraticResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["two_real", "repeated_real", "complex_pair", "linear", "all_numbers", "no_solution"]
    discriminant: Optional[float]
    roots: List[QuadraticRoot] = Field(max_length=2)
    max_residual: float
    assumptions: QuadraticAssumptions


@router.post("/api/calculator/quadratics", response_model=QuadraticResponse)
def api_quadratics(req: QuadraticRequest) -> QuadraticResponse:
    return QuadraticResponse.model_validate(_calculate(lambda: Engine.solve_quadratic(req.a, req.b, req.c)))


# GCD and LCM (C23)

class GcdLcmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    integers: List[Integer] = Field(min_length=2, max_length=100)


class GcdLcmAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sign: Literal["absolute"]
    zero_policy: Literal["gcd(0,0)=0; lcm with 0 = 0"]


class GcdLcmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gcd: str
    lcm: str
    count: int
    assumptions: GcdLcmAssumptions


@router.post("/api/calculator/gcd-lcm", response_model=GcdLcmResponse)
def api_gcd_lcm(req: GcdLcmRequest) -> GcdLcmResponse:
    return GcdLcmResponse.model_validate(_calculate(lambda: Engine.calculate_gcd_lcm(req.integers)))


# Statistics (C24)

class StatisticsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: List[ValueNumber] = Field(min_length=1, max_length=10000)
    kind: Literal["sample", "population"]

    @field_validator("values", mode="before")
    @classmethod
    def numbers_are_json_numbers(cls, value):
        return _json_number_list(value)


class StatisticsAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["sample", "population"]
    precision: Literal["1e-10"]


class StatisticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int
    sum: float
    mean: float
    median: float
    modes: List[float] = Field(max_length=20)
    modes_truncated: bool
    no_mode: bool
    minimum: float
    maximum: float
    range: float
    variance: Optional[float]
    std_dev: Optional[float]
    variance_unavailable_reason: Optional[str]
    assumptions: StatisticsAssumptions


@router.post("/api/calculator/statistics", response_model=StatisticsResponse)
def api_statistics(req: StatisticsRequest) -> StatisticsResponse:
    return StatisticsResponse.model_validate(_calculate(lambda: Engine.calculate_statistics(req.values, req.kind)))


# Geometry (C25)

Dimension = Annotated[float, BeforeValidator(_json_number), Field(gt=0, le=1e6, allow_inf_nan=False)]


class _GeometryBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit: Literal["mm", "cm", "m", "km", "in", "ft", "yd", "mi"]


class CircleGeometry(_GeometryBase):
    shape: Literal["circle"]
    radius: Dimension


class RectangleGeometry(_GeometryBase):
    shape: Literal["rectangle"]
    width: Dimension
    height: Dimension


class TriangleGeometry(_GeometryBase):
    shape: Literal["triangle"]
    a: Dimension
    b: Dimension
    c: Dimension


class SphereGeometry(_GeometryBase):
    shape: Literal["sphere"]
    radius: Dimension


class CylinderGeometry(_GeometryBase):
    shape: Literal["cylinder"]
    radius: Dimension
    height: Dimension


class ConeGeometry(_GeometryBase):
    shape: Literal["cone"]
    radius: Dimension
    height: Dimension


class CuboidGeometry(_GeometryBase):
    shape: Literal["cuboid"]
    length: Dimension
    width: Dimension
    height: Dimension


GeometryRequest = Annotated[
    Union[
        CircleGeometry,
        RectangleGeometry,
        TriangleGeometry,
        SphereGeometry,
        CylinderGeometry,
        ConeGeometry,
        CuboidGeometry,
    ],
    Field(discriminator="shape"),
]


class GeometryMeasure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    value: float
    unit_power: Literal[1, 2, 3]
    formula: str


class GeometryAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pi: Literal["decimal_40"]
    precision: Literal["1e-6"]


class GeometryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shape: Literal["circle", "rectangle", "triangle", "sphere", "cylinder", "cone", "cuboid"]
    unit: Literal["mm", "cm", "m", "km", "in", "ft", "yd", "mi"]
    measures: List[GeometryMeasure]
    assumptions: GeometryAssumptions


@router.post("/api/calculator/geometry", response_model=GeometryResponse)
def api_geometry(req: GeometryRequest) -> GeometryResponse:
    fields = req.model_dump()
    shape = fields.pop("shape")
    unit = fields.pop("unit")
    return GeometryResponse.model_validate(_calculate(lambda: Engine.calculate_geometry(shape, unit, fields)))
