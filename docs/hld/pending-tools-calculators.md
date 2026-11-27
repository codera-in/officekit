# HLD: Pending calculators (slice 2: C06–C07, C15–C25)

Version: 1.0.2 · 2026-10-22 · Round-2 review: quadratic `discriminant` is null for the linear, all-numbers and no-solution kinds (ARCH-6). Round-1 review: weight sign enforced by the engine (ARCH-4), zone names capped at 64 characters (ARCH-5). Earlier: initial draft.

Status: draft for owner review. Mock: `design/mocks/pending-calculators.html` (not yet approved). Requirements: `review/pending-tools-slices/requirements.md`. ADR: `docs/ARCHITECTURE.md` 2026-10-22 (foundation first).

## 1. Scope

Thirteen new searchable calculators, each a separate catalogue entry (stable ID) on the existing Calculators tab, local and synchronous. Depth and cases come from `docs/RELEASE-123-TOOLS.md` :134-135 and :143-153.

| ID | Tool ID | Depth delivered | Verification cases the tests must satisfy |
| --- | --- | --- | --- |
| C06 | `weighted_average` | Pasted list (newline/comma/tab/semicolon/space; `.` decimal), optional same-length weights, missing-value policy `reject` (default) or `skip` | [1,2,3]=2; values [80,90] weights [1,3]=87.5; zero weight allowed, all-zero or negative weight → 422; malformed token reports its line; count mismatch → 422 |
| C07 | `fractions_ratios` | Exact `Fraction` simplify/add/subtract/multiply/divide; ratio a:b shown as simplified ratio; mixed number and 20-digit decimal | 2/4=1/2; 1/3+1/6=1/2; zero denominator and ÷0 → 422; sign normalised to numerator (−1/2 for 1/−2); bounds ±1e12 inputs, exact string outputs |
| C15 | `roi` | Invested, returned, fees (visible, default 0); ROI % signed; labelled not annualised | Returned 120 / invested 100 = 20%; fees 5 → 14.29%; invested 0 → 422; returned 50 → −50% |
| C16 | `cagr` | Start, end, years (fractional); growth multiple | 100→121 over 2y = 10.00%; 1.5 years supported; start ≤0, end <0, years ≤0 → 422; end 0 → −100% |
| C17 | `date_difference` | Signed days, weeks+days, y/m/d breakdown with month-end clamp rule, inclusive option | 2024-01-31→2025-03-01 = 395 days, 1y 1m 1d; 2024-02-28→2024-03-01 = 2 days (leap); reversed order → negative days, direction `backward`; inclusive adds 1; date-only, no timezone shift |
| C18 | `age_calculator` | Birth date, as-of date (UI sends local today); y/m/d, total days, next birthday | 29 Feb birthday ages on 28 Feb in common years; birth after as-of → 422; birth = as-of → 0; as-of explicit so saved results reproduce |
| C19 | `business_days` | Range, inclusive flag, weekend weekday set, user holiday list (paste or local .txt/.csv import parsed in the UI); no holiday service | Sat/Sun and Fri/Sat weekends; inclusive vs exclusive; duplicate holidays counted once and reported; holiday on a weekend not double-subtracted; empty exclusive range = 0; end < start → 422 |
| C20 | `work_hours` | Rows of start/end HH:MM, break minutes, optional date + IANA zone; overnight; per-row and ISO-week totals | 22:00→06:00 minus 30 = 7h30; break ≥ shift → 422 naming the row; with zone America/New_York on 2026-03-07→08 overnight = 7h elapsed (DST); without zone, wall-clock with `dst: not_applied` assumption; totals reconcile in CSV export |
| C21 | `time_zone_converter` | Date-specific offsets via `zoneinfo`; ambiguity `earlier`/`later`, nonexistent rejected; 1–10 targets | 2026-11-01 01:30 New York ambiguous → 422 without choice, 05:30Z earlier / 06:30Z later; 2026-03-08 02:30 New York → 422 nonexistent; historical 1990 date; UTC round trip returns the input |
| C22 | `quadratic_solver` | Real/repeated/complex roots; a=0 linear and degenerate cases; numerically stable formula; residuals | x²−3x+2 → 1,2; x²−2x+1 → 1 repeated; x²+1 → ±i; a=0,b=2,c=−4 → linear 2; a=b=0: c=0 → `all_numbers`, else `no_solution`; independent residual |f(x)| ≤ 1e-9·scale |
| C23 | `gcd_lcm` | 2–100 integers; gcd/lcm of absolute values; exact strings | gcd(12,18)=6, lcm=36; gcd(0,0)=0; lcm with any 0 = 0; negatives → non-negative results; 101 items or non-integer → 422 |
| C24 | `descriptive_statistics` | Count, sum, mean, median, all modes, min, max, range, variance and stddev for `sample` or `population` | [2,4,4,4,5,5,7,9]: mean 5, median 4.5, mode 4, pop var 4, pop sd 2, sample var 4.5714285714; empty → 422; singleton population ok, sample → variance `null` with reason; multimode lists all; all unique → no mode |
| C25 | `geometry` | Circle, rectangle, triangle (3 sides), sphere, cylinder, cone, cuboid; one length unit; formula string per result; diagrams not included | r=1 circle area π; 3-4-5 triangle area 6; cylinder r=1 h=2 volume 2π; 1-2-3 triangle → 422 (inequality); outputs carry unit, unit² and unit³ |

Out of scope: C01–C05, C08–C14 changes beyond the shared shell; the scientific calculator; any network lookup (rates, holidays, zones).

## 2. Reuse vs new

- **Reuse:** `CalculatorEngine` patterns (`_percentage_number`-style finite checks, `Decimal` + `localcontext(prec=40)`, `ROUND_HALF_UP`); DTO style of `SimpleInterestRequest/Response` (`extra="forbid"`, `allow_inf_nan=False`, before-validator rejecting bool/string numbers, `Literal` assumptions); the shared result snapshot (Copy, Download via `/api/export/result`, Save, History, Reuse inputs); `officekitReadCalculatorResponse`; `RequestBodyLimitMiddleware`; release-profile gating.
- **No duplicates:** ROI is not `percentage_change` (fees, invested/returned labels, not-annualised note); CAGR solves the rate from endpoints, unlike `compound_interest` (projection). Average and Statistics share one list parser and engine helper; Date difference and Age share one calendar-delta helper.
- **Not reused:** `engine_dispatcher.py` `_handle_c15…c25` — unreferenced float stubs with wrong semantics (two-integer GCD only, offset-hours time zones, no DST). Left untouched; deletion is an owner question.
- **New:** standard-library `zoneinfo` and `fractions`, Decimal statistics (the float `statistics` module is not used), and the `tzdata` data package for platforms without a system zone database.

## 3. Contract surface

All routes are local, in the development profile only (blocked in private beta by the existing release-scope middleware). They follow the existing `/api/calculator/<calculator>` convention: a computation that stores nothing returns `200`, not `201`; this deviation from `rest.md` matches the 11 existing `POST /api/calculator/*` routes. Common to every POST: JSON object body, unknown fields rejected, numbers must be finite JSON numbers (no bool/string coercion), dates `YYYY-MM-DD` within 1600-01-01..2400-12-31, `200` typed response with a `Literal` assumptions object, `413` before parsing when the body exceeds the cap, `422` with a fixed public message for validation or domain errors (no echo of input text beyond a line number), never `500` for client input. Caps: 16 KiB for scalar routes, 512 KiB for list routes (marked †).

| Route | Request DTO (bounds) | Response DTO | Status / errors |
| --- | --- | --- | --- |
| `POST /api/calculator/averages` † | `{values: (number\|null)[] 1–10,000, \|v\|≤1e12; weights?: (number\|null)[] same length, \|w\|≤1e12 at the DTO; the engine enforces the sign (negative → fixed `negative_weight` 422); missing: "reject"\|"skip"="reject"}` | `{mean, count_used, count_skipped, weight_total, weighted: bool, assumptions{precision:"1e-10", rounding:"half_up", missing}}` | 422: length mismatch, negative/all-zero weights, null under `reject`, no values after skip |
| `POST /api/calculator/fractions` | `{operation: "simplify"\|"add"\|"subtract"\|"multiply"\|"divide", left{numerator, denominator}, right?{…}}` strict ints \|n\|≤1e12, denominator ≠0; `right` required unless simplify | `{numerator: str, denominator: str (>0), mixed{whole, numerator, denominator}: str, decimal: str (20 sig.), is_integer, assumptions{exact:true}}` | 422: zero denominator, divide by zero fraction, missing/extra `right` |
| `POST /api/calculator/roi` | `{invested (0,1e12], returned [0,1e12], fees [0,1e12]=0}` | `{net_gain, roi_percent, total_cost, assumptions{annualised:false, fees:"added_to_cost", currency_precision:"0.01", percent_precision:"0.01"}}` | 422: invested ≤0 |
| `POST /api/calculator/cagr` | `{start_value (0,1e12], end_value [0,1e12], years (0,100]}` | `{cagr_percent, growth_multiple, assumptions{compounding:"annual", percent_precision:"0.01"}}` | 422: domain bounds |
| `POST /api/calculator/date-differences` | `{start_date, end_date, inclusive: bool=false}` | `{days (signed), direction: "forward"\|"backward"\|"same", years, months, rem_days, weeks, week_days, assumptions{month_end:"clamp", time_zone:"none"}}` | 422: invalid/out-of-range date |
| `POST /api/calculator/ages` | `{birth_date, as_of_date}` | `{years, months, days, total_days, next_birthday, days_to_next_birthday, assumptions{leap_birthday:"feb_28"}}` | 422: birth after as-of |
| `POST /api/calculator/business-days` † | `{start_date, end_date, inclusive: bool=true, weekend: int[] 0–6 (Mon=0) unique, 0–6 items =[5,6], holidays: date[] ≤1,000}`; range ≤36,600 days | `{business_days, calendar_days, weekend_days, holidays_excluded, holidays_on_weekend, holidays_outside_range, duplicate_holidays, assumptions{holiday_source:"user_list"}}` | 422: end<start, 7 weekend days, range too long |
| `POST /api/calculator/work-hours` † | `{rows: [{date?: date, start: "HH:MM", end: "HH:MM", break_minutes 0–1440}] 1–400, time_zone?: IANA name}`; `time_zone` requires every row to carry `date` | `{rows: [{index, worked_minutes, overnight, dst_adjusted_minutes}], total_minutes, total_hours (0.01), weeks: [{iso_week, total_minutes}], assumptions{dst:"zoneinfo"\|"not_applied", overnight:"end_before_start"}}` | 422: break ≥ shift (row index), unknown zone, nonexistent wall time |
| `GET /api/calculator/time-zones` | none | `{zones: str[] (sorted IANA names), tzdata_version: str}` | 200 only; safe, cacheable in memory |
| `POST /api/calculator/time-zone-conversions` | `{date, time: "HH:MM", from_zone, to_zones: str[] 1–10, each ≤64 characters, fold?: "earlier"\|"later"}`; zones must be in `available_timezones()`; years 1900–2100 | `{utc: ISO8601Z, source{zone, local, offset, abbreviation, dst}, targets: [{zone, local, offset, abbreviation, dst, day_shift}], assumptions{tz_database}}` | 422 `AMBIGUOUS_TIME` (no `fold`), `NONEXISTENT_TIME`, unknown zone |
| `POST /api/calculator/quadratics` | `{a, b, c}` each \|x\|≤1e12 | `{kind: "two_real"\|"repeated_real"\|"complex_pair"\|"linear"\|"all_numbers"\|"no_solution", discriminant (null for linear, all_numbers and no_solution), roots: [{real, imaginary}] 0–2, max_residual, assumptions{precision:"1e-10", method:"stable_quadratic"}}` | 422: bounds only (degenerate cases are 200 kinds) |
| `POST /api/calculator/gcd-lcm` | `{integers: int[] 2–100, \|n\|≤1e12}` strict ints | `{gcd: str, lcm: str, count, assumptions{sign:"absolute", zero_policy:"gcd(0,0)=0; lcm with 0 = 0"}}` | 422: count, non-integer |
| `POST /api/calculator/statistics` † | `{values: number[] 1–10,000, \|v\|≤1e12; kind: "sample"\|"population"}` | `{count, sum, mean, median, modes: number[] ≤20, modes_truncated, no_mode, minimum, maximum, range, variance\|null, std_dev\|null, variance_unavailable_reason\|null, assumptions{kind, precision:"1e-10"}}` | 422: empty list |
| `POST /api/calculator/geometry` | Discriminated union on `shape`: circle{radius}, rectangle{width,height}, triangle{a,b,c}, sphere{radius}, cylinder{radius,height}, cone{radius,height}, cuboid{length,width,height}; each (0,1e6]; `unit: "mm"\|"cm"\|"m"\|"km"\|"in"\|"ft"\|"yd"\|"mi"` | `{shape, unit, measures: [{name, value, unit_power 1\|2\|3, formula}], assumptions{pi:"decimal_40", precision:"1e-6"}}` | 422: triangle inequality, missing dimension |

Path nouns are plural where the existing routes allow (`averages`, `date-differences`); the HLD reviewer may align them to the existing singular style instead (open question 3).

## 4. Engine design (`officekit/engines/engine_calculators_extra.py`, class `ExtendedCalculatorEngine`)

- **Precision.** Money-like outputs (ROI amounts) quantize to `0.01`, percentages to `0.01` (ROI, CAGR), `ROUND_HALF_UP` (P-115). Unit-free approximate results (average, statistics, quadratic) use `Decimal` with `localcontext(prec=40)` and quantize to `1e-10` half-up before conversion to JSON numbers; geometry to `1e-6`. Inputs enter as `Decimal(str(value))`. Exact results (fractions, GCD/LCM) use `fractions.Fraction` / `math.gcd` on ints and return decimal-digit strings so values beyond 2^53 survive. Median/variance are computed in Decimal (two-pass), never via float `statistics`.
- **Quadratic.** D = b²−4ac in Decimal; q = −(b + sign(b)·√|D|)/2; roots q/a and c/q (avoids cancellation); complex pair from −b/2a ± i√(−D)/2a. Residuals recomputed independently and returned.
- **Calendar.** Pure `datetime.date`. y/m/d: largest m with `add_months(start, m)` (day clamped to month end) ≤ end, then days. Age reuses it; 29 Feb in a common year → 28 Feb. No server clock: the UI sends local today as `as_of_date` built from `getFullYear/getMonth/getDate`, never `toISOString()` (UTC shift).
- **Time zones / DST.** `zoneinfo.ZoneInfo` only; validate names against `available_timezones()`. Detect ambiguity by comparing `fold=0` and `fold=1` offsets; detect nonexistent times by round-tripping through UTC and checking the wall time changes. `tzdata` pinned in `requirements.txt` and collected by the sidecar build so Windows and the PyInstaller bundle carry the same database; the version is reported in assumptions.
- **Holidays.** Only the user's list; deduplicated via a set; counts reported separately. Iteration is O(days) bounded at 36,600 days.
- **Errors.** Engine raises `ValueError` with fixed messages (from a module-level message table); routes map to 422.

## 5. UI component tree

```
#tab-calculators
├─ h1 "Calculators" (28px, left)        MOVES from the centred hero; subtitle rewritten
├─ Calculator menu (themed select, 4 optgroups, 24 options)   NEW, replaces 11 #calc-pill-*
├─ calculator card
│  ├─ existing #calc-form-* (11)       STAY unchanged; heading = selected calculator
│  └─ new #calc-form-* (13)            NEW, injected by assets/officekit-calculators.js
│     ├─ fields (labels above, hints below; lists use 160px textarea)
│     ├─ Details (weights / weekend+holidays / zone / unit options)
│     └─ result frame (empty → result → "Inputs changed" stale) with inline Copy result link
└─ bottom dock (officekit-tool-actions): Calculate │ Download… · Save result · Calculate again
```

Goes: the 11 pills and their `switchCalc` className swapping (menu sets the value and calls `switchCalc(key)`); Copy result as a dock button (becomes an inline link). The 13 new tools register through the foundation hook (`registerCalculator({toolId, key, group, label, formHtml|build, endpoint, inputIds↔keys, resultId, title, validate, units, restore})`), which feeds the destination map, `switchCalc`, the request config (~:11223), units (`officekitResultFieldUnit`, P-088) and the restore map (~:11907, P-087).

## 6. Files this slice owns (new files only, in foundation slots)

- `officekit/tool_catalog/calculators.py` — 13 entries + aliases, merged into `TOOL_REGISTRY`.
- `officekit/routes/calculators.py` — `APIRouter`, request/response DTOs, body caps exported for the middleware.
- `officekit/engines/engine_calculators_extra.py` — engine.
- `assets/officekit-calculators.js` — forms, menu entries, response validators, units, restore.
- `docs/tools/calculators.md` — slice doc page (foundation slot).
- Tests: `tests/test_calculators_extra_unittest.py`, `tests/test_calculators_extra_routes_unittest.py`, `tests/calculators-extra-ui.test.mjs`, `ui-tests/calculators-extra.spec.mjs`.
- Shared edits outside the slot (need foundation or owner sign-off): `requirements.txt` (`tzdata`), the sidecar build data collection, and the menu/dock change in the shared calculator shell.

## 7. Test plan

- **Engine (pytest, per ID):** every case in §1 plus bool/string/NaN/∞/out-of-range rejection; independent reference vectors (hand-computed or `fractions`/`datetime` oracles, never the code under test); half-up ties (x.xx5).
- **Routes:** each route 200 shape matches the response DTO exactly; unknown field → 422; fixed message (no input echo); body over cap → 413 before parsing; release profile: reachable in development, blocked in private beta.
- **UI (node):** registration produces the destination, menu option, restore mapping and units for all 13; strict response validators reject drifted keys; snapshot inputs equal the visible form (P-139); local-date helper never uses UTC.
- **WebKit (desktop/compact/phone):** search by tool ID opens the exact form and sets the menu (AC2); calculate → result → Download primary, Save secondary, ≤3 dock buttons asserted (P-140, conventions); stale notice; save → History → Reuse inputs restores without recalculating (P-087); field errors focus the first invalid field; gallery counts via `expectGalleryMatchesCatalog` (P-120, P-150); CSP navigation passes after the build hash sync (P-111).

## 8. Pitfalls check

P-115 half-up everywhere, non-finite → 422 · P-140 dock order/emphasis · P-139 every request field visible and in the snapshot (ROI fees, weekend set, holidays, zone) · P-087 restore mapping per tool via the hook · P-088 per-field units (unit-free except geometry and money fields; no `$` inference) · P-012 domain checks before arithmetic, schedules/totals reconcile · P-172 actions in the reserved dock · P-111 CSP hash regenerated by `build:ui` · P-120/P-150 no hardcoded counts.

## 9. Open questions for the owner

1. Apply the 3-button dock (Copy result as an inline link, Calculate again quiet) to all 24 calculators? It changes the shared renderer used by the 11 existing ones.
2. Add the pinned `tzdata` dependency (small, Apache-2.0 package of public-domain IANA data) so time zones work identically in the packaged sidecar on macOS and Windows?
3. Route nouns: keep the existing singular style (`/api/calculator/date-difference`) for consistency, or plural as drafted?
