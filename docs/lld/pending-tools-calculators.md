# LLD: Pending calculators, back end (slice 2: C06–C07, C15–C25)

Version: 1.0.0 · 2026-10-22 · Initial low-level design for phase 1 (back end only).

Parent: `docs/hld/pending-tools-calculators.md` (contract rows cited below as "HLD §1" for the verification table and "HLD §3" for routes). Foundation: `docs/hld/pending-tools-foundation.md` (router slot, `BODY_LIMITS`, `EXPOSE_HEADERS`). Roadmap: `docs/RELEASE-123-TOOLS.md` :134-135 and :143-153.

Phase 1 delivers the engine, the routes and their tests. Catalogue entries, the UI, `dist-ui`, and the mock review are phase 2 and are not in this document's scope. No catalogue entry is added in phase 1, so the 13 tools are not searchable until phase 2 lands.

## 1. Decisions taken for phase 1

| # | Decision | Reason |
| --- | --- | --- |
| D1 | Route paths follow HLD §3 exactly, including the non-plural acronyms (`roi`, `cagr`, `fractions`, `geometry`, `statistics`, `gcd-lcm`). Plural nouns are used where HLD §3 gives them. | HLD §3 is the contract surface. Open question 3 in the HLD is still open, so the spec wins until the owner decides. |
| D2 | Errors use the existing calculator convention, `HTTPException(422, detail=str(error))`, not the `rest.md` error envelope. | Matches the 11 existing `POST /api/calculator/*` routes in `app.py:1251-1350`. |
| D3 | Pydantic validation failures are handled by the app-level `RequestValidationError` handler (`app.py:280-288`), which returns a fixed detail and does not echo input. Tests reproduce that handler on the fresh app. | Input is never echoed. The router cannot register app-level handlers. |
| D4 | Pasted-text list parsing (newline, comma, tab, semicolon, space separators; `.` decimal; `line N` in errors) is a Python helper in the engine, `parse_number_lines`. Routes take JSON arrays only. | HLD §3 specifies JSON arrays. The text helper satisfies the "malformed token reports its line" case at engine level. The JS parser for the paste box is phase 2. |
| D5 | C24 uses the stdlib `statistics` module on `Decimal` inputs (`mean`, `median`, `multimode`, `variance`, `pvariance`, `stdev`, `pstdev`). No value is converted to float. | The task asks for `statistics`. HLD §2 forbids the float path. Decimal inputs keep exact Decimal arithmetic, so the two agree. |
| D6 | C07 ratio view is a UI derivation from the simplify response (`numerator:denominator`). The route does not return a `ratio` field. | HLD §3 lists no ratio field. Adding one would change the contract. |
| D7 | Calendar breakdown (C17 and C18) uses one helper, `_calendar_breakdown(start, end)`. `days`, `weeks` and `y/m/d` describe the exclusive span between the dates. `inclusive` changes only the reported `days` (plus or minus one day in magnitude). | Keeps the breakdown reconciling with the calendar span. HLD §1 fixes the inclusive example: "inclusive adds 1". |
| D8 | Business-day ranges are half-open when exclusive, `[start, end)`, and closed when inclusive, `[start, end]`. | Consistent with D7. Makes "empty exclusive range = 0" hold for `start == end`. |
| D9 | Repeated real root returns one root (`roots` length 1). Complex pair returns two roots sorted by imaginary part. Two real roots are sorted ascending. | Keeps `roots` at 0–2 with a stable order. |
| D10 | Work-hours: an end time at or before the start time is an overnight shift into the next day. `end == start` is therefore a 24-hour shift. Ambiguous local times use the earlier offset (`fold=0`). Nonexistent local times are 422. | HLD §3 names `overnight: end_before_start`. The rule covers `end == start` explicitly. |
| D11 | Work-hours `dst_adjusted_minutes` is the zone correction, `elapsed - wall-clock` (0 without a zone). `worked_minutes = wall-clock worked + dst_adjusted_minutes`. ISO-week totals cover dated rows only; undated rows are excluded from `weeks`. | Makes totals reconcile with `total_minutes` and gives the CSV export a single source. |
| D12 | `time-zones` `tzdata_version` is the installed `tzdata` distribution version when present, else `"system"`. `zones` comes from `zoneinfo.available_timezones()`, sorted, and is cached in the engine. | No network and no new dependency in phase 1 (`tzdata` is added by the foundation). |
| D13 | Money outputs quantize to `0.01`, percentages to `0.01`, approximate unit-free results (average, statistics, quadratic roots and residuals, growth multiple) to `1e-10`, geometry to `1e-6`. All quantize with `ROUND_HALF_UP`. Inputs enter as `Decimal(str(value))`. | HLD §4 and P-115. |
| D14 | A quantize that cannot be represented (`InvalidOperation`) or a non-finite result raises `ValueError` with a fixed message (422). | P-115: non-finite results are a safe 422, not a 500. |

## 2. File-by-file map

| File | Status | Contents | HLD rows served |
| --- | --- | --- | --- |
| `officekit/engines/engine_calculators_extra.py` | new | Class `ExtendedCalculatorEngine`, message table `MESSAGES`, helpers `_finite`, `_quantize`, `_calendar_breakdown`, `_add_months`, `_anniversary`, `_parse_iso_date`, `parse_number_lines`. | HLD §1 C06–C25, §4 |
| `officekit/routes/calculators.py` | stub → implemented | `router`, DTOs (request, response, assumptions), `BODY_LIMITS` (every POST), `EXPOSE_HEADERS = ()`. | HLD §3 (14 paths) |
| `tests/test_calculators_extra_unittest.py` | new | Engine tests per C-ID, bounds, boundaries, type rejection, `parse_number_lines`, the message table. | HLD §7 engine |
| `tests/test_calculators_extra_api.py` | new | `TestClient` on a fresh `FastAPI()` with `officekit.routes.calculators.router` and the app-equivalent `RequestValidationError` handler. Route shape, 422, unknown keys, bool/string rejection, body caps (via `BODY_LIMITS`). | HLD §3, §7 routes |
| `docs/lld/pending-tools-calculators.md` | new | This document. | — |
| `docs/VERSION-HISTORY.md` | edited | One row at the top of the table. | versioning rule |

Not touched: `app.py`, `officekit/engines/engine_comms.py`, `officekit/tool_catalog/*`, `index.html`, `assets/*`, `dist-ui/*`, `requirements.txt`, `API-CONTRACT.md`, `docs/TOOL-GUIDE.md`, `docs/FIRST-MAC-RELEASE.md`, `officekit/mcp/registry.py`, `engine_dispatcher.py`.

`app.py` already includes `calculators.router` and merges `BODY_LIMITS` through `slice_body_limits()` (`app.py:73`, `:217`, `:2455`). The routes therefore go live in the app as soon as the router has routes. The `BODY_LIMITS` keys must not clash with the inline keys in `app.py`. None of the 14 paths appears there.

## 3. Interfaces

### 3.1 Engine (`ExtendedCalculatorEngine`, static methods, all raise `ValueError` on invalid input)

| Method | Input | Output keys |
| --- | --- | --- |
| `calculate_weighted_average(values, weights=None, missing="reject")` | `values: list[Decimal \| float \| int \| None]`; `weights` same length or None; `missing` in `reject`/`skip` | `mean, count_used, count_skipped, weight_total, weighted, assumptions` |
| `calculate_fraction(operation, left, right=None)` | `left/right: (numerator:int, denominator:int)` | `numerator, denominator, mixed{whole,numerator,denominator}, decimal, is_integer, assumptions` (all strings except `is_integer` and `assumptions`) |
| `calculate_roi(invested, returned, fees=0)` | numbers | `net_gain, roi_percent, total_cost, assumptions` |
| `calculate_cagr(start_value, end_value, years)` | numbers | `cagr_percent, growth_multiple, assumptions` |
| `calculate_date_difference(start_date, end_date, inclusive=False)` | ISO date strings | `days, direction, years, months, rem_days, weeks, week_days, assumptions` |
| `calculate_age(birth_date, as_of_date)` | ISO date strings | `years, months, days, total_days, next_birthday, days_to_next_birthday, assumptions` |
| `calculate_business_days(start_date, end_date, inclusive=True, weekend=(5,6), holidays=())` | strings, ints, ISO strings | `business_days, calendar_days, weekend_days, holidays_excluded, holidays_on_weekend, holidays_outside_range, duplicate_holidays, assumptions` |
| `calculate_work_hours(rows, time_zone=None)` | rows as dicts `{date?, start, end, break_minutes}` | `rows, total_minutes, total_hours, weeks, assumptions` |
| `list_time_zones()` | none | `zones, tzdata_version` |
| `convert_time_zone(date, time, from_zone, to_zones, fold=None)` | strings | `utc, source, targets, assumptions` |
| `solve_quadratic(a, b, c)` | numbers | `kind, discriminant, roots, max_residual, assumptions` |
| `calculate_gcd_lcm(integers)` | ints | `gcd, lcm, count, assumptions` (strings for gcd/lcm) |
| `calculate_statistics(values, kind)` | Decimal-convertible numbers, `"sample"`/`"population"` | `count, sum, mean, median, modes, modes_truncated, no_mode, minimum, maximum, range, variance, std_dev, variance_unavailable_reason, assumptions` |
| `calculate_geometry(shape, unit, **dimensions)` | shape name, unit, dimension numbers | `shape, unit, measures, assumptions` |

Module-level function `parse_number_lines(text) -> list[Decimal | None]`: returns values in order; raises `ValueError("line N: value must be a finite number")` on the first malformed token. Tokens separated by `\n`, `,`, `\t`, `;` or space. Blank lines are skipped.

### 3.2 Routes (`officekit/routes/calculators.py`)

Each POST handler: `def handler(req: RequestDTO) -> ResponseDTO`, calls the engine inside `try`, maps `ValueError` to `HTTPException(422, detail=str(error))`, returns `ResponseDTO.model_validate(result)`.

| Method | Path | Body cap (`BODY_LIMITS`) | Response model |
| --- | --- | --- | --- |
| POST | `/api/calculator/averages` | 512 KiB | `AveragesResponse` |
| POST | `/api/calculator/fractions` | 16 KiB | `FractionsResponse` |
| POST | `/api/calculator/roi` | 16 KiB | `RoiResponse` |
| POST | `/api/calculator/cagr` | 16 KiB | `CagrResponse` |
| POST | `/api/calculator/date-differences` | 16 KiB | `DateDifferenceResponse` |
| POST | `/api/calculator/ages` | 16 KiB | `AgeResponse` |
| POST | `/api/calculator/business-days` | 512 KiB | `BusinessDaysResponse` |
| POST | `/api/calculator/work-hours` | 512 KiB | `WorkHoursResponse` |
| GET | `/api/calculator/time-zones` | — | `TimeZonesResponse` |
| POST | `/api/calculator/time-zone-conversions` | 16 KiB | `TimeZoneConversionResponse` |
| POST | `/api/calculator/quadratics` | 16 KiB | `QuadraticResponse` |
| POST | `/api/calculator/gcd-lcm` | 16 KiB | `GcdLcmResponse` |
| POST | `/api/calculator/statistics` | 512 KiB | `StatisticsResponse` |
| POST | `/api/calculator/geometry` | 16 KiB | `GeometryResponse` |

Request DTO rules (all POST):

- `model_config = ConfigDict(extra="forbid")`; unknown keys are 422 through pydantic.
- Numbers: `Field(..., allow_inf_nan=False)` with bounds from HLD §3, plus a `field_validator(mode="before")` that rejects `bool` and non-`int`/`float` values (the `SimpleInterestRequest` pattern, `app.py:1058-1091`).
- Lists: a before-validator checks each item is `None` or a non-bool number. Bounds use `Field(min_length, max_length)`.
- Strict ints (`gcd-lcm`, fraction parts): `StrictInt`, and a before-validator for bool.
- Dates: `str` with a regex `^\d{4}-\d{2}-\d{2}$`; range checked by the engine (1600-01-01..2400-12-31).
- Booleans: `StrictBool`.
- The geometry request is a discriminated union on `shape`.

Responses: `extra="forbid"` models mirroring HLD §3. The `assumptions` objects are typed with `Literal` values.

## 4. Error handling

- Engine: fixed messages from `MESSAGES` where the text is constant. The only dynamic text is `row N:` (work hours) and `line N:` (list parsing). No input string is ever echoed.
- Route: `ValueError` → `422` with `detail=str(error)`.
- Pydantic: `RequestValidationError` → app-level handler, `422` with `"Request contains invalid or unsupported values."`.
- Body over the cap: the middleware returns `413` before parsing (`RequestBodyLimitMiddleware`). The router does not handle this.
- Non-finite or unrepresentable results: `ValueError`, `422` (P-115).
- No route returns `500` for client input.

## 5. Test hooks and cases

Engine (`tests/test_calculators_extra_unittest.py`), one test class per C-ID:

- C06: `[1,2,3]=2`; `[80,90]` weights `[1,3]` = 87.5; zero weight allowed; all-zero and negative weights 422; count mismatch 422; `reject` with null 422; `skip` drops nulls and counts them; skip leaves nothing 422; bool, string, NaN and inf 422; `parse_number_lines` malformed token reports `line N`, separators, blank lines, tabs and semicolons; ties at the 1e-10 boundary round half-up.
- C07: `2/4 = 1/2`; `1/3 + 1/6 = 1/2`; subtract, multiply, divide; zero denominator 422; divide by zero fraction 422; `1/-2` normalised to `-1/2`; `right` missing for add 422, `right` extra for simplify 422; ±1e12 inputs exact strings; 20-significant-digit decimal; mixed number sign convention.
- C15: `120/100 = 20%`; fees 5 → `14.29%`; invested 0 → 422; returned 50 → `-50%`; `annualised` is `false`; ROI tie at `.xx5` rounds half-up.
- C16: `100→121 over 2y = 10.00%`; 1.5 years; start ≤0, end <0, years ≤0 and years >100 → 422; end 0 → `-100%`; bounds at 1e12 and 100 years.
- C17: `2024-01-31→2025-03-01 = 395 days, 1y 1m 1d`; `2024-02-28→2024-03-01 = 2 days`; reversed → negative days and `backward`; inclusive adds 1; same date → `same`; invalid and out-of-range dates 422; dates at 1600-01-01 and 2400-12-31 accepted.
- C18: `29 Feb` birthday ages on 28 Feb in common years (`2000-02-29` vs `2001-02-28` = 1 year, `2001-02-27` = 0); birth after as-of 422; birth = as-of → 0; next birthday on 29 Feb in a common year is 28 Feb; next birthday when today is the birthday.
- C19: Sat/Sun and Fri/Sat weekends; inclusive vs exclusive; duplicate holidays counted once and reported; holiday on a weekend not subtracted twice; holiday outside range reported; empty exclusive range = 0; end < start 422; 7 weekend days 422; range over 36,600 days 422; more than 1,000 holidays 422 (route).
- C20: `22:00→06:00` minus 30 = 450 minutes; break ≥ shift 422 with row index; zone `America/New_York` on `2026-03-07→08` overnight = 420 minutes elapsed (`dst_adjusted_minutes = -60`); without zone `dst: not_applied`; nonexistent wall time 422; unknown zone 422; zone without date on a row 422; totals reconcile across rows and ISO weeks; `end == start` is a 24-hour shift.
- C21: `2026-11-01 01:30 New York` ambiguous 422 without `fold`; `fold=earlier` → `05:30Z`; `fold=later` → `06:30Z`; `2026-03-08 02:30 New York` nonexistent 422; historical `1990` date; UTC round trip returns the input; unknown zone 422; 1–10 targets; year outside 1900–2100 422; `day_shift` across midnight.
- C22: `x²−3x+2 → 1, 2`; `x²−2x+1 → 1` (repeated); `x²+1 → ±i`; `a=0,b=2,c=−4 → linear 2`; `a=b=0`: `c=0 → all_numbers`, else `no_solution`; residual ≤ `1e-9 × scale` for each kind; cancellation case `x² + 1e6 x + 1` stable root.
- C23: `gcd(12,18)=6`, `lcm=36`; `gcd(0,0)=0`; lcm with any zero = 0; negatives give non-negative results; 1 integer 422; 101 integers 422; non-integer and bool 422; 2^60-scale values exact string.
- C24: `[2,4,4,4,5,5,7,9]`: mean 5, median 4.5, mode 4, population variance 4, population sd 2, sample variance `4.5714285714`; empty 422; singleton population variance 0; singleton sample variance `null` with reason; multimode lists all modes; all unique → `no_mode`; more than 20 modes → `modes_truncated`.
- C25: circle `r=1` area π (to `1e-6`); `3-4-5` triangle area 6; cylinder `r=1,h=2` volume `2π`; `1-2-3` triangle 422 (inequality, degenerate included); missing dimension 422 (route); zero and above `1e6` 422; each shape's formulas and unit powers; `unit` restricted to the eight units.

Routes (`tests/test_calculators_extra_api.py`):

- Each of the 14 routes returns 200 and a body whose keys equal the response DTO fields exactly.
- Unknown key → 422 on each POST.
- Bool and string number → 422 on each scalar field.
- Engine `ValueError` → 422 with the fixed `detail`.
- Body caps: every POST path in `BODY_LIMITS`; each path's cap equals the HLD value (16 KiB or 512 KiB); a body larger than the cap is rejected 413 before parsing (uses the middleware via the test app with `RequestBodyLimitMiddleware` mounted with `BODY_LIMITS`).
- `GET /api/calculator/time-zones` returns sorted zones and a `tzdata_version` string.

## 6. Checkpoint commits

Each commit is test-first: the test file for the step is written and seen failing, then the engine or route code makes it pass. Every commit runs the focused tests.

| Step | Commit subject | Covers | HLD rows |
| --- | --- | --- | --- |
| 1 | `docs(calculators): add pending calculators LLD 1.0.0` | this document, version-history row | §1 scope, §3, §4 |
| 2 | `feat(calculators): add weighted average and exact fraction engine` | C06, C07 engine | §1 C06–C07, §4 precision |
| 3 | `feat(calculators): add ROI and CAGR engine` | C15, C16 | §1 C15–C16 |
| 4 | `feat(calculators): add date difference, age and business day engine` | C17, C18, C19 | §1, §4 calendar, holidays |
| 5 | `feat(calculators): add work hours and time zone engine` | C20, C21 | §1, §4 time zones |
| 6 | `feat(calculators): add quadratic, GCD/LCM, statistics and geometry engine` | C22–C25 | §1, §4 |
| 7 | `feat(calculators): expose calculator routes with body caps` | 14 routes, `BODY_LIMITS`, route tests | §3 |
| 8 | `docs(calculators): record phase 1 verification` | none, only if a test count changes the version history row | — |

Step 8 is optional and only happens if the verification record needs an update.

## 7. Verification gate for phase 1

- `python3 -m pytest -q tests/test_calculators_extra_unittest.py tests/test_calculators_extra_api.py` passes.
- `python3 -m pytest -q tests/test_api_contract_unittest.py tests/test_tool_slots_unittest.py` passes.
- No file outside the list in §2 changes.
- Every verification case in HLD §1 and every roadmap row C06–C07 and C15–C25 is covered by a named test.

## 8. Pitfalls applied

- P-115: half-up everywhere; non-finite and unrepresentable results are 422.
- P-012: domain checks run before arithmetic (zero denominators, invalid spans, degenerate triangles, break ≥ shift).
- P-036: every POST path has a `BODY_LIMITS` entry; the route-map test reads the router's own map.
- Deferred to phase 2 (UI): P-087 (restore), P-088 (units), P-139 (visible inputs), P-140 (dock order), P-111 (CSP hash), P-120/P-150 (no hard-coded counts). These pitfalls depend on the UI and are not exercised by the back end.

## 9. Open items

- HLD §9 open question 3 (route noun style): this LLD follows HLD §3 as drafted (D1).
- The C07 ratio display (D6) and the pasted-text parser (D4) need phase 2 decisions in the UI.
