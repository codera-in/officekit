import json
import unittest

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from officekit.engines.engine_calculators_extra import MESSAGES
from officekit.engines.engine_uploads import RequestBodyLimitMiddleware
from officekit.routes.calculators import BODY_LIMITS, EXPOSE_HEADERS, router

GENERIC_422 = "Request contains invalid or unsupported values."
SCALAR_CAP = 16 * 1024
LIST_CAP = 512 * 1024

POST_PAYLOADS = {
    "/api/calculator/averages": {"values": [80, 90], "weights": [1, 3]},
    "/api/calculator/fractions": {
        "operation": "add",
        "left": {"numerator": 1, "denominator": 3},
        "right": {"numerator": 1, "denominator": 6},
    },
    "/api/calculator/roi": {"invested": 100, "returned": 120, "fees": 5},
    "/api/calculator/cagr": {"start_value": 100, "end_value": 121, "years": 2},
    "/api/calculator/date-differences": {"start_date": "2024-01-31", "end_date": "2025-03-01"},
    "/api/calculator/ages": {"birth_date": "2000-02-29", "as_of_date": "2001-02-27"},
    "/api/calculator/business-days": {"start_date": "2024-01-01", "end_date": "2024-01-07"},
    "/api/calculator/work-hours": {
        "rows": [{"date": "2026-03-07", "start": "22:00", "end": "06:00", "break_minutes": 30}],
        "time_zone": "America/New_York",
    },
    "/api/calculator/time-zone-conversions": {
        "date": "2026-11-01",
        "time": "01:30",
        "from_zone": "America/New_York",
        "to_zones": ["UTC"],
        "fold": "earlier",
    },
    "/api/calculator/quadratics": {"a": 1, "b": -3, "c": 2},
    "/api/calculator/gcd-lcm": {"integers": [12, 18]},
    "/api/calculator/statistics": {"values": [2, 4, 4, 4, 5, 5, 7, 9], "kind": "population"},
    "/api/calculator/geometry": {"shape": "triangle", "unit": "m", "a": 3, "b": 4, "c": 5},
}

RESPONSE_KEYS = {
    "/api/calculator/averages": {"mean", "count_used", "count_skipped", "weight_total", "weighted", "assumptions"},
    "/api/calculator/fractions": {"numerator", "denominator", "mixed", "decimal", "is_integer", "assumptions"},
    "/api/calculator/roi": {"net_gain", "roi_percent", "total_cost", "assumptions"},
    "/api/calculator/cagr": {"cagr_percent", "growth_multiple", "assumptions"},
    "/api/calculator/date-differences": {
        "days", "direction", "years", "months", "rem_days", "weeks", "week_days", "assumptions",
    },
    "/api/calculator/ages": {
        "years", "months", "days", "total_days", "next_birthday", "days_to_next_birthday", "assumptions",
    },
    "/api/calculator/business-days": {
        "business_days", "calendar_days", "weekend_days", "holidays_excluded", "holidays_on_weekend",
        "holidays_outside_range", "duplicate_holidays", "assumptions",
    },
    "/api/calculator/work-hours": {"rows", "total_minutes", "total_hours", "weeks", "assumptions"},
    "/api/calculator/time-zone-conversions": {"utc", "source", "targets", "assumptions"},
    "/api/calculator/quadratics": {"kind", "discriminant", "roots", "max_residual", "assumptions"},
    "/api/calculator/gcd-lcm": {"gcd", "lcm", "count", "assumptions"},
    "/api/calculator/statistics": {
        "count", "sum", "mean", "median", "modes", "modes_truncated", "no_mode", "minimum", "maximum",
        "range", "variance", "std_dev", "variance_unavailable_reason", "assumptions",
    },
    "/api/calculator/geometry": {"shape", "unit", "measures", "assumptions"},
}

LIST_PATHS = {
    "/api/calculator/averages",
    "/api/calculator/business-days",
    "/api/calculator/work-hours",
    "/api/calculator/statistics",
}


def build_client():
    """Fresh app with only the calculators router, the body-cap middleware and the app's 422 handler."""
    app = FastAPI()
    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error_handler(request, exc):
        # Mirrors app.py: pydantic errors never echo the rejected input.
        return JSONResponse(status_code=422, content={"detail": GENERIC_422})

    app.add_middleware(RequestBodyLimitMiddleware, path_limits=BODY_LIMITS)
    return TestClient(app)


class RouteInventoryTests(unittest.TestCase):
    def test_router_exposes_exactly_the_hld_routes(self):
        routes = {(method, route.path) for route in router.routes for method in route.methods}
        expected = {("POST", path) for path in POST_PAYLOADS} | {("GET", "/api/calculator/time-zones")}
        self.assertEqual(routes, expected)

    def test_every_post_path_has_a_body_limit_and_no_other_path_does(self):
        self.assertEqual(set(BODY_LIMITS), set(POST_PAYLOADS))

    def test_body_caps_are_sixteen_kib_for_scalars_and_512_kib_for_lists(self):
        for path, cap in BODY_LIMITS.items():
            with self.subTest(path=path):
                self.assertEqual(cap, LIST_CAP if path in LIST_PATHS else SCALAR_CAP)

    def test_no_expose_headers_are_needed(self):
        self.assertEqual(EXPOSE_HEADERS, ())


class SuccessfulResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = build_client()

    def test_each_post_returns_200_with_exactly_the_response_fields(self):
        for path, body in POST_PAYLOADS.items():
            with self.subTest(path=path):
                response = self.client.post(path, json=body)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(set(response.json()), RESPONSE_KEYS[path])

    def test_time_zones_get_returns_sorted_zones_and_version(self):
        response = self.client.get("/api/calculator/time-zones")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"zones", "tzdata_version"})
        self.assertEqual(body["zones"], sorted(body["zones"]))
        self.assertIn("America/New_York", body["zones"])
        self.assertIsInstance(body["tzdata_version"], str)

    def test_fraction_and_ratio_values_reach_the_wire_as_exact_strings(self):
        body = self.client.post("/api/calculator/fractions", json=POST_PAYLOADS["/api/calculator/fractions"]).json()
        self.assertEqual((body["numerator"], body["denominator"]), ("1", "2"))
        self.assertEqual(set(body["mixed"]), {"whole", "numerator", "denominator"})

    def test_weighted_average_matches_reference_vector(self):
        body = self.client.post("/api/calculator/averages", json=POST_PAYLOADS["/api/calculator/averages"]).json()
        self.assertEqual(body["mean"], 87.5)
        self.assertTrue(body["weighted"])
        self.assertEqual(body["assumptions"]["missing"], "reject")

    def test_business_days_and_roi_and_cagr_reference_values(self):
        roi = self.client.post("/api/calculator/roi", json={"invested": 100, "returned": 120, "fees": 5}).json()
        self.assertEqual(roi["roi_percent"], 14.29)
        cagr = self.client.post("/api/calculator/cagr", json={"start_value": 100, "end_value": 121, "years": 2}).json()
        self.assertEqual(cagr["cagr_percent"], 10.0)
        days = self.client.post("/api/calculator/business-days", json={"start_date": "2024-01-01", "end_date": "2024-01-07"}).json()
        self.assertEqual(days["business_days"], 5)

    def test_work_hours_tz_targets_and_timezone_conversion_shapes(self):
        body = self.client.post(
            "/api/calculator/work-hours", json=POST_PAYLOADS["/api/calculator/work-hours"]
        ).json()
        self.assertEqual(body["rows"][0]["worked_minutes"], 390)
        self.assertEqual(body["rows"][0]["dst_adjusted_minutes"], -60)
        self.assertEqual(body["assumptions"]["dst"], "zoneinfo")
        conversion = self.client.post(
            "/api/calculator/time-zone-conversions", json=POST_PAYLOADS["/api/calculator/time-zone-conversions"]
        ).json()
        self.assertEqual(conversion["utc"], "2026-11-01T05:30:00Z")
        self.assertEqual(
            set(conversion["targets"][0]),
            {"zone", "local", "offset", "abbreviation", "dst", "day_shift"},
        )
        self.assertEqual(set(conversion["source"]), {"zone", "local", "offset", "abbreviation", "dst"})

    def test_geometry_measures_carry_unit_power_and_formula(self):
        body = self.client.post("/api/calculator/geometry", json=POST_PAYLOADS["/api/calculator/geometry"]).json()
        self.assertEqual(body["unit"], "m")
        self.assertEqual({"name", "value", "unit_power", "formula"}, set(body["measures"][0]))
        areas = [measure for measure in body["measures"] if measure["name"] == "area"]
        self.assertEqual(areas[0]["value"], 6.0)
        self.assertEqual(areas[0]["unit_power"], 2)

    def test_statistics_null_variance_for_sample_singleton(self):
        body = self.client.post(
            "/api/calculator/statistics", json={"values": [3], "kind": "sample"}
        ).json()
        self.assertIsNone(body["variance"])
        self.assertIsNone(body["std_dev"])
        self.assertEqual(body["variance_unavailable_reason"], MESSAGES["sample_needs_two"])

    def test_quadratic_degenerate_all_numbers(self):
        body = self.client.post("/api/calculator/quadratics", json={"a": 0, "b": 0, "c": 0}).json()
        self.assertEqual((body["kind"], body["roots"]), ("all_numbers", []))

    def test_averages_accepts_ten_thousand_values_within_list_cap(self):
        body = self.client.post("/api/calculator/averages", json={"values": [1.0] * 10000})
        self.assertEqual(body.status_code, 200)
        self.assertEqual(body.json()["count_used"], 10000)


class EngineErrorTests(unittest.TestCase):
    """Domain errors come from the engine as ValueError and map to 422 with the fixed message."""

    @classmethod
    def setUpClass(cls):
        cls.client = build_client()

    def assert_domain_422(self, path, body, message):
        response = self.client.post(path, json=body)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json(), {"detail": message})

    def test_fraction_divide_by_zero_fraction(self):
        self.assert_domain_422(
            "/api/calculator/fractions",
            {"operation": "divide", "left": {"numerator": 1, "denominator": 2}, "right": {"numerator": 0, "denominator": 5}},
            MESSAGES["divide_by_zero"],
        )

    def test_fraction_zero_denominator(self):
        self.assert_domain_422(
            "/api/calculator/fractions",
            {"operation": "simplify", "left": {"numerator": 1, "denominator": 0}},
            MESSAGES["zero_denominator"],
        )

    def test_fraction_right_operand_missing_for_add(self):
        self.assert_domain_422(
            "/api/calculator/fractions",
            {"operation": "add", "left": {"numerator": 1, "denominator": 2}},
            MESSAGES["right_required"],
        )

    def test_averages_null_value_under_reject_policy(self):
        self.assert_domain_422("/api/calculator/averages", {"values": [1, None]}, MESSAGES["missing_value"])

    def test_averages_negative_weight_and_zero_total(self):
        # DTO bounds for weights are -1e12..1e12 so the engine can name the negative-weight rule.
        self.assert_domain_422("/api/calculator/averages", {"values": [1, 2], "weights": [1, -1]}, MESSAGES["negative_weight"])
        self.assert_domain_422("/api/calculator/averages", {"values": [1, 2], "weights": [0, 0]}, MESSAGES["zero_weight_total"])

    def test_averages_weight_count_mismatch(self):
        self.assert_domain_422("/api/calculator/averages", {"values": [1, 2], "weights": [1]}, MESSAGES["length_mismatch"])

    def test_date_difference_invalid_calendar_date(self):
        self.assert_domain_422(
            "/api/calculator/date-differences",
            {"start_date": "2024-02-30", "end_date": "2024-03-01"},
            MESSAGES["date"],
        )

    def test_age_birth_after_as_of(self):
        self.assert_domain_422(
            "/api/calculator/ages",
            {"birth_date": "2026-10-23", "as_of_date": "2026-10-22"},
            MESSAGES["birth_after_as_of"],
        )

    def test_business_days_end_before_start(self):
        self.assert_domain_422(
            "/api/calculator/business-days",
            {"start_date": "2024-01-07", "end_date": "2024-01-01"},
            MESSAGES["range_order"],
        )

    def test_work_hours_break_names_the_row(self):
        self.assert_domain_422(
            "/api/calculator/work-hours",
            {"rows": [{"start": "09:00", "end": "10:00", "break_minutes": 0}, {"start": "09:00", "end": "10:00", "break_minutes": 60}]},
            MESSAGES["break_row"].format(row=2),
        )

    def test_work_hours_nonexistent_local_time(self):
        self.assert_domain_422(
            "/api/calculator/work-hours",
            {"rows": [{"date": "2026-03-08", "start": "02:30", "end": "05:00", "break_minutes": 0}], "time_zone": "America/New_York"},
            MESSAGES["nonexistent_row"].format(row=1),
        )

    def test_time_zone_ambiguous_without_fold(self):
        self.assert_domain_422(
            "/api/calculator/time-zone-conversions",
            {"date": "2026-11-01", "time": "01:30", "from_zone": "America/New_York", "to_zones": ["UTC"]},
            MESSAGES["ambiguous_time"],
        )

    def test_time_zone_nonexistent_and_unknown(self):
        self.assert_domain_422(
            "/api/calculator/time-zone-conversions",
            {"date": "2026-03-08", "time": "02:30", "from_zone": "America/New_York", "to_zones": ["UTC"]},
            MESSAGES["nonexistent_time"],
        )
        self.assert_domain_422(
            "/api/calculator/time-zone-conversions",
            {"date": "2026-03-08", "time": "12:00", "from_zone": "Mars/Olympus", "to_zones": ["UTC"]},
            MESSAGES["zone_unknown"],
        )

    def test_geometry_triangle_inequality(self):
        self.assert_domain_422(
            "/api/calculator/geometry",
            {"shape": "triangle", "unit": "cm", "a": 1, "b": 2, "c": 3},
            MESSAGES["triangle_inequality"],
        )

    def test_cagr_power_past_decimal_range_is_a_fixed_422_not_a_500(self):
        self.assert_domain_422(
            "/api/calculator/cagr",
            {"start_value": 1, "end_value": 1000000000000, "years": 0.000001},
            MESSAGES["result_range"],
        )

    def test_arithmetic_overflow_that_escapes_an_engine_guard_maps_to_fixed_422(self):
        from decimal import Overflow

        from fastapi import HTTPException

        from officekit.routes.calculators import _calculate

        def overflowing():
            raise Overflow()

        with self.assertRaises(HTTPException) as caught:
            _calculate(overflowing)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.detail, MESSAGES["result_range"])

    def test_statistics_empty_list_is_a_request_bound_error_with_fixed_text(self):
        response = self.client.post("/api/calculator/statistics", json={"values": [], "kind": "sample"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": GENERIC_422})

    def test_gcd_single_integer_is_rejected_with_fixed_text(self):
        response = self.client.post("/api/calculator/gcd-lcm", json={"integers": [12]})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": GENERIC_422})

    def test_roi_returned_above_bound_is_rejected_with_fixed_text(self):
        response = self.client.post("/api/calculator/roi", json={"invested": 1e12, "returned": 1e12 + 1})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": GENERIC_422})


class RequestDtoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = build_client()

    def test_unknown_key_is_rejected_on_every_post(self):
        for path, body in POST_PAYLOADS.items():
            with self.subTest(path=path):
                response = self.client.post(path, json={**body, "unexpected": 1})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json(), {"detail": GENERIC_422})

    def test_bool_and_string_numbers_are_rejected(self):
        cases = [
            ("/api/calculator/roi", "invested", True),
            ("/api/calculator/roi", "invested", "100"),
            ("/api/calculator/cagr", "years", False),
            ("/api/calculator/cagr", "start_value", "10"),
            ("/api/calculator/quadratics", "a", True),
            ("/api/calculator/quadratics", "c", "1"),
            ("/api/calculator/statistics", "values", ["1", 2]),
            ("/api/calculator/averages", "values", [True, 2]),
            ("/api/calculator/averages", "weights", [1, "2"]),
            ("/api/calculator/gcd-lcm", "integers", [12, 18.0]),
            ("/api/calculator/gcd-lcm", "integers", [True, 3]),
        ]
        for path, field, bad in cases:
            with self.subTest(path=path, field=field, bad=bad):
                body = {**POST_PAYLOADS[path], field: bad}
                response = self.client.post(path, json=body)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json(), {"detail": GENERIC_422})

    def test_bool_and_string_numbers_in_scalar_fields_of_each_route(self):
        bad_fields = {
            "/api/calculator/roi": ("invested", "returned", "fees"),
            "/api/calculator/cagr": ("start_value", "end_value", "years"),
            "/api/calculator/quadratics": ("a", "b", "c"),
        }
        for path, fields in bad_fields.items():
            for field in fields:
                for bad in (True, "1"):
                    with self.subTest(path=path, field=field, bad=bad):
                        body = {**POST_PAYLOADS[path], field: bad}
                        self.assertEqual(self.client.post(path, json=body).status_code, 422)

    def test_non_finite_json_numbers_are_rejected(self):
        raw = '{"invested": NaN, "returned": 10}'
        response = self.client.post("/api/calculator/roi", content=raw, headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 422)
        raw_inf = '{"invested": 10, "returned": Infinity}'
        response = self.client.post("/api/calculator/roi", content=raw_inf, headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 422)

    def test_numeric_bounds_are_enforced_at_the_boundary(self):
        self.assertEqual(self.client.post("/api/calculator/roi", json={"invested": 1e12, "returned": 0}).status_code, 200)
        self.assertEqual(self.client.post("/api/calculator/roi", json={"invested": 1e12 + 1, "returned": 0}).status_code, 422)
        self.assertEqual(self.client.post("/api/calculator/roi", json={"invested": 1, "returned": -1}).status_code, 422)
        self.assertEqual(self.client.post("/api/calculator/cagr", json={"start_value": 1, "end_value": 1, "years": 100}).status_code, 200)
        self.assertEqual(self.client.post("/api/calculator/cagr", json={"start_value": 1, "end_value": 1, "years": 100.01}).status_code, 422)
        self.assertEqual(self.client.post("/api/calculator/quadratics", json={"a": 1e12, "b": 0, "c": -1e12}).status_code, 200)
        self.assertEqual(self.client.post("/api/calculator/quadratics", json={"a": 1, "b": -1e12 - 1, "c": 0}).status_code, 422)

    def test_list_bounds_are_enforced_at_the_boundary(self):
        empty = self.client.post("/api/calculator/averages", json={"values": []})
        self.assertEqual(empty.status_code, 422)
        too_many = self.client.post("/api/calculator/averages", json={"values": [1] * 10001})
        self.assertEqual(too_many.status_code, 422)
        self.assertEqual(
            self.client.post("/api/calculator/gcd-lcm", json={"integers": [6] * 101}).status_code, 422
        )
        self.assertEqual(self.client.post("/api/calculator/gcd-lcm", json={"integers": [6]}).status_code, 422)
        self.assertEqual(self.client.post("/api/calculator/gcd-lcm", json={"integers": [6] * 100}).status_code, 200)
        self.assertEqual(
            self.client.post("/api/calculator/gcd-lcm", json={"integers": [10**12 + 1, 1]}).status_code, 422
        )

    def test_dates_must_match_iso_shape(self):
        for bad in ("2024-1-5", "20240105", "2024-01-05T00:00", "", 20240105):
            with self.subTest(bad=bad):
                response = self.client.post(
                    "/api/calculator/ages", json={"birth_date": bad, "as_of_date": "2024-01-05"}
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json(), {"detail": GENERIC_422})

    def test_inclusive_flags_must_be_booleans(self):
        response = self.client.post(
            "/api/calculator/date-differences", json={"start_date": "2024-01-01", "end_date": "2024-01-02", "inclusive": "yes"}
        )
        self.assertEqual(response.status_code, 422)
        response = self.client.post(
            "/api/calculator/business-days", json={"start_date": "2024-01-01", "end_date": "2024-01-02", "inclusive": 1}
        )
        self.assertEqual(response.status_code, 422)

    def test_weekend_must_be_zero_to_six_and_at_most_six_items(self):
        base = {"start_date": "2024-01-01", "end_date": "2024-01-07"}
        for weekend in ([0, 1, 2, 3, 4, 5, 6], [7], [-1], [True], ["5"]):
            with self.subTest(weekend=weekend):
                self.assertEqual(
                    self.client.post("/api/calculator/business-days", json={**base, "weekend": weekend}).status_code, 422
                )
        self.assertEqual(
            self.client.post("/api/calculator/business-days", json={**base, "weekend": []}).status_code, 200
        )

    def test_holiday_list_is_capped_at_one_thousand(self):
        holidays = ["2024-01-02"] * 1001
        response = self.client.post(
            "/api/calculator/business-days",
            json={"start_date": "2024-01-01", "end_date": "2024-01-07", "holidays": holidays},
        )
        self.assertEqual(response.status_code, 422)

    def test_work_rows_are_limited_to_one_to_four_hundred(self):
        row = {"start": "09:00", "end": "10:00", "break_minutes": 0}
        self.assertEqual(self.client.post("/api/calculator/work-hours", json={"rows": []}).status_code, 422)
        self.assertEqual(self.client.post("/api/calculator/work-hours", json={"rows": [row] * 401}).status_code, 422)
        self.assertEqual(self.client.post("/api/calculator/work-hours", json={"rows": [row] * 400}).status_code, 200)

    def test_work_hour_time_and_break_shape(self):
        for bad_time in ("24:00", "9:00", "09:60", 900):
            with self.subTest(time=bad_time):
                body = {"rows": [{"start": bad_time, "end": "10:00", "break_minutes": 0}]}
                self.assertEqual(self.client.post("/api/calculator/work-hours", json=body).status_code, 422)
        body = {"rows": [{"start": "09:00", "end": "10:00", "break_minutes": 1441}]}
        self.assertEqual(self.client.post("/api/calculator/work-hours", json=body).status_code, 422)

    def test_time_zone_conversion_targets_and_fold_are_shaped(self):
        base = {"date": "2026-01-01", "time": "00:00", "from_zone": "UTC"}
        self.assertEqual(self.client.post("/api/calculator/time-zone-conversions", json={**base, "to_zones": []}).status_code, 422)
        self.assertEqual(
            self.client.post("/api/calculator/time-zone-conversions", json={**base, "to_zones": ["UTC"] * 11}).status_code, 422
        )
        self.assertEqual(
            self.client.post("/api/calculator/time-zone-conversions", json={**base, "to_zones": ["UTC"], "fold": "middle"}).status_code,
            422,
        )
        # Each target name is capped at 64 characters, as from_zone is: 64 passes the DTO (the engine then
        # rejects the unknown name with its fixed message), 65 fails the DTO with the generic message.
        at_cap = self.client.post("/api/calculator/time-zone-conversions", json={**base, "to_zones": ["A" * 64]})
        self.assertEqual(at_cap.json(), {"detail": MESSAGES["zone_unknown"]})
        over_cap = self.client.post("/api/calculator/time-zone-conversions", json={**base, "to_zones": ["UTC", "A" * 65]})
        self.assertEqual(over_cap.status_code, 422)
        self.assertEqual(over_cap.json(), {"detail": GENERIC_422})

    def test_geometry_discriminated_union_requires_known_shape_fields_only(self):
        path = "/api/calculator/geometry"
        cases = [
            {"unit": "m", "radius": 1},
            {"shape": "pyramid", "unit": "m"},
            {"shape": "circle", "unit": "parsec", "radius": 1},
            {"shape": "circle", "unit": "m", "radius": 1, "width": 2},
            {"shape": "circle", "unit": "m"},
            {"shape": "circle", "unit": "m", "radius": True},
            {"shape": "circle", "unit": "m", "radius": 0},
            {"shape": "circle", "unit": "m", "radius": 1e6 + 1},
            {"shape": "cylinder", "unit": "m", "radius": 1},
        ]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(self.client.post(path, json=body).status_code, 422)
        self.assertEqual(self.client.post(path, json={"shape": "circle", "unit": "m", "radius": 1e6}).status_code, 200)
        for unit in ("mm", "cm", "m", "km", "in", "ft", "yd", "mi"):
            with self.subTest(unit=unit):
                self.assertEqual(
                    self.client.post(path, json={"shape": "circle", "unit": unit, "radius": 1}).status_code, 200
                )

    def test_geometry_triangle_side_bounds(self):
        path = "/api/calculator/geometry"
        self.assertEqual(
            self.client.post(path, json={"shape": "triangle", "unit": "m", "a": 3, "b": 4, "c": 5}).status_code, 200
        )
        self.assertEqual(
            self.client.post(path, json={"shape": "triangle", "unit": "m", "a": 3, "b": 4}).status_code, 422
        )


class BodyCapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = build_client()

    def test_scalar_route_rejects_body_over_sixteen_kib_before_parsing(self):
        padded = {"invested": 100, "returned": 120, "note": "x" * (SCALAR_CAP + 1)}
        response = self.client.post("/api/calculator/roi", json=padded)
        self.assertEqual(response.status_code, 413)

    def test_every_post_rejects_its_cap_plus_one_byte(self):
        for path, cap in BODY_LIMITS.items():
            with self.subTest(path=path):
                # "{" + spaces + "}" is valid JSON whitespace; the total is exactly cap + 1 bytes.
                self.assertIn(cap, (SCALAR_CAP, LIST_CAP))
                body = "{" + " " * (cap - 1) + "}"
                self.assertEqual(len(body.encode("utf-8")), cap + 1)
                response = self.client.post(path, content=body, headers={"content-type": "application/json"})
                self.assertEqual(response.status_code, 413)

    def test_every_post_accepts_a_body_of_exactly_its_cap(self):
        for path, cap in BODY_LIMITS.items():
            with self.subTest(path=path):
                self.assertIn(cap, (SCALAR_CAP, LIST_CAP))
                body = "{" + " " * (cap - 2) + "}"
                self.assertEqual(len(body.encode("utf-8")), cap)
                response = self.client.post(path, content=body, headers={"content-type": "application/json"})
                self.assertNotEqual(response.status_code, 413)

    def test_scalar_body_at_exactly_the_cap_is_parsed(self):
        padded = json.dumps({"invested": 100, "returned": 120, "note": "x"}).ljust(SCALAR_CAP, " ")
        response = self.client.post(
            "/api/calculator/roi", content=padded, headers={"content-type": "application/json"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": GENERIC_422})


if __name__ == "__main__":
    unittest.main()
