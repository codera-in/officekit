# Pending tools — developer slice LLD (phase 1, back end)

Version: 1.1.0 · 2026-10-22 · Phase 2 status: grapheme route, catalogue, UI asset and UI tests shipped; section 8 items closed. Earlier: initial low-level design for the back end of the developer slice (1.0.0).

Parent: `docs/hld/pending-tools-developer.md` (version 1.0.0, the contract). Foundation: `docs/hld/pending-tools-foundation.md` (version 1.1.0). Requirements and roadmap rows: `docs/RELEASE-123-TOOLS.md` D04, D10, D11, D15, D16, D17 (:211-224).

Phase 1 covers engines, the slice router, DTOs, body caps and tests. Phase 2 covers the catalogue (`officekit/tool_catalog/developer.py`), the UI asset, the `regex` package and the grapheme route. The HLD contract rows are the source of truth for every path, bound and error message below.

## 1. Scope of phase 1

| Item | In phase 1 | Deferred to phase 2 and why |
| --- | --- | --- |
| D04 `json_compare` engine + `POST /api/developer/json-diffs` | Yes | — |
| D17 `text_diff` engine + `POST /api/developer/text-diffs` | Yes | — |
| D16 `text_metrics` (code points, UTF-8 bytes, UTF-16 units, words, lines, blank lines, whitespace) | Yes, engine only | The route `POST /api/developer/text-analyses` is excluded. Its response needs `graphemes` and `longest_line_graphemes`, which need the `regex` package (not installed; the foundation adds it). |
| D16 grapheme counting | Stub `count_graphemes()` raises `NotImplementedError` | Phase 2 replaces the stub when `regex` is pinned. |
| D16 `text_case` + `POST /api/developer/text-case-conversions` | Yes | — |
| D10 `timestamp_converter` + `POST /api/developer/timestamp-conversions` + `GET /api/developer/time-zones` | Yes | — |
| D11 `uuid_generator` + `POST /api/developer/uuids` | Yes | — |
| D15 `qr_generator` + `POST /api/developer/qr-codes` | Yes | — |
| Catalogue, UI asset, slice doc page, `ui-tests` | No | Phase 2 (after mock approval, AC6). |
| `app.py`, `requirements.txt`, `API-CONTRACT.md`, `docs/TOOL-GUIDE.md`, `docs/FIRST-MAC-RELEASE.md` | Not edited | Integrator or phase 2. |

## 2. File-by-file map

| Path | Status | Responsibility | HLD rows |
| --- | --- | --- | --- |
| `officekit/engines/_myers.py` | new | Bounded linear-space Myers O(ND) diff over any sequence of hashable tokens. Raises `EditDistanceExceeded` above `max_edits` (default `MAX_EDIT_DISTANCE = 10_000`). | Engine design: Myers; D04 array alignment; D17 |
| `officekit/engines/engine_developer.py` | new | Pure functions for all six tools, `DeveloperInputError`, `count_graphemes` stub. Imports `DevToolsEngine` for `_parse_json`, `_dump_json`, `_text_bytes`. | Engine design sections; Contract surface |
| `officekit/routes/developer.py` | existing stub, filled | `router` (prefix `/api/developer`), `BODY_LIMITS`, `EXPOSE_HEADERS = ()`, DTOs, the fixed-message route class. | Contract surface table |
| `tests/engine_developer_unittest.py` | new | Engine cases for every verification row in the HLD scope table, bounds, property tests, QR decode. | Test plan: Engine |
| `tests/developer_routes_unittest.py` | new | `TestClient` on a fresh `FastAPI()` that mounts `developer.router`. DTO 422s, fixed messages, 413, body-cap equality, response DTO shape. | Test plan: Routes |
| `docs/VERSION-HISTORY.md` | edited | One row at the top of the table for this LLD. | Conventions (versioning) |
| `docs/lld/pending-tools-developer.md` | new | This document. | — |

Not edited, by rule: `app.py`, `officekit/engines/engine_comms.py`, `officekit/engines/engine_devtools.py`, `officekit/tool_catalog/*`, `index.html`, `assets/*`, `dist-ui/*`, `requirements.txt`, `API-CONTRACT.md`, `docs/TOOL-GUIDE.md`, `docs/FIRST-MAC-RELEASE.md`.

`routes/__init__.py` already imports `developer` and mounts it through `SLICES`, so no edit is needed there. The stub's `BODY_LIMITS` and `EXPOSE_HEADERS` are filled in place.

## 3. Interfaces

### 3.1 `_myers.py`

```python
MAX_EDIT_DISTANCE = 10_000
EQUAL, DELETE, INSERT = "equal", "delete", "insert"

class EditDistanceExceeded(ValueError): ...

def diff_ops(a: Sequence[Hashable], b: Sequence[Hashable], max_edits: int = MAX_EDIT_DISTANCE) -> list[tuple[str, int | None, int | None]]:
    # EQUAL -> (EQUAL, i, j); DELETE -> (DELETE, i, None); INSERT -> (INSERT, None, j)
    # Raises EditDistanceExceeded if the minimal edit count is greater than max_edits.
```

Algorithm: the middle-snake split from Myers (1986) §4b. Each range is trimmed of its common prefix and suffix, then split at the middle snake. Recursion is driven by an explicit stack, so depth does not depend on input. Memory is linear in the input. The search loop over `d` is capped at `max_edits + 1`, and a pre-check on `|len(a) - len(b)|` rejects early, because it is a lower bound on the edit distance.

### 3.2 `engine_developer.py`

```python
class DeveloperInputError(ValueError)           # public_message is never echoed by routes

def compare_json(original: str, changed: str, *, array_order: str = "ordered", numeric: str = "value") -> dict
def compare_text(original: str, changed: str, *, whitespace: str = "exact", line_endings: str = "normalize",
                 unicode_nfc: bool = False, context: int = 3, max_edits: int = MAX_EDIT_DISTANCE) -> dict
def text_metrics(text: str) -> dict                  # phase 1 keys only (no graphemes)
def count_graphemes(text: str) -> int                # raises NotImplementedError (phase 2)
def convert_case(text: str, style: str, locale: str = "root") -> dict
def convert_timestamp(value: str, input_type: str, source_zone: str | None, fold: str,
                      target_zones: list[str]) -> dict
def list_time_zones() -> dict                        # {"zones": [...], "local_zone": str | None}
def generate_uuids(version: int, count: int, *, namespace: str | None, name: str | None,
                   case: str, style: str) -> dict
def generate_qr(payload: str, error_correction: str, size_px: int, fmt: str) -> dict
def qr_matrix(payload: str, error_correction: str) -> list[list[bool]]   # test hook
```

Constants (named in code): `MAX_TEXT_BYTES = 1_048_576`, `MAX_DIFF_LINES = 50_000`, `MAX_JSON_CHANGES = 10_000`, `MAX_PREVIEW_CHARS = 256`, `MAX_INLINE_SPAN_CODE_POINTS = 1_000`, `MAX_CASE_OUTPUT_BYTES = 1_048_576`, `MAX_UUID_BATCH = 1_000`, `MAX_UUID_NAME_BYTES = 1_024`, `QR_BYTE_CAPACITY = {"L": 2953, "M": 2331, "Q": 1663, "H": 1273}`, `MAX_TARGET_ZONES = 8`, `MAX_TIME_ZONE_LIST = 1_000`.

Output shapes match the HLD contract rows exactly. Integers that can exceed 2^53 (microseconds, milliseconds) are strings.

## 4. Error handling

- Engines raise only `DeveloperInputError` for user input. They wrap `ValueError` from `_parse_json` and `_text_bytes`, and `EditDistanceExceeded`, into it. The wrapped text is kept on `__cause__` and never shown to the user.
- Routes map `DeveloperInputError` (and `RequestValidationError`) to a 422 whose `detail` is a fixed per-route message from the HLD table. Input is never echoed (P-013). Any other exception goes to the app's generic 500 handler.
- A route class `_FixedMessageRoute(APIRoute)` wraps each handler, so the message is decided per route and the app-level handler stays untouched.
- Oversized bodies get 413 from `RequestBodyLimitMiddleware` before parsing, driven by `BODY_LIMITS` (P-036).
- No route logs payloads, text, names or secrets.

## 5. Test hooks

- `max_edits` on `compare_text` and `diff_ops`: the too-different bound can be tested at a small value without building 10,001 edits. The default stays at the HLD value, and a constant test pins it.
- `qr_matrix()` returns the module matrix, so the Unicode QR case can assert on modules when the scanner cannot decode.
- `_myers.diff_ops` is tested against a brute-force LCS (edit count = `len(a) + len(b) - 2*LCS`) on random small sequences.
- `uuid7` helpers take a `now_ms` argument for deterministic tests of monotonicity and the counter overflow path.
- Route tests use a fresh `FastAPI()` plus `TestClient`. The body-cap test adds `RequestBodyLimitMiddleware` with the router's `BODY_LIMITS`.

## 6. Commit plan

Each commit has Conventional Commit messages and carries its own tests. Each step references the HLD rows it satisfies.

1. `docs(lld): pending developer slice LLD 1.0.0` — this file and the `VERSION-HISTORY.md` row. (Scope, file map, interfaces, errors, hooks.)
2. `feat(developer): bounded Myers diff helper` — `_myers.py`, its brute-force LCS tests, the too-different bound. (Engine design: Myers.)
3. `feat(developer): JSON comparison engine` — D04 rows: key order, missing vs null, arrays under both policies, `1` vs `"1"`, `1` vs `1.0`, `true` vs `1`. (HLD JSON row.)
4. `feat(developer): text diff engine` — D17 rows: insert/delete/change, Unicode, 1 MiB and 50,000-line bounds, too-different, `<script>` as text, `patch -p0` round trip, fence length. (HLD text row.)
5. `feat(developer): text metrics and case engine` — D16 metrics without graphemes, the `count_graphemes` stub, 9 case styles, tr/az, `ß`, growth cap. (HLD text-case row.)
6. `feat(developer): timestamp converter engine and time-zone list` — D10 rows: epoch 0, negatives, DST gap, fold, magnitude warnings, range, malformed numbers, 8 zones. (HLD timestamp row.)
7. `feat(developer): UUID generator engine` — D11 rows: format and version/variant, 10 × 1,000 uniqueness, v7 monotonic, v5 RFC 9562 vectors, 0 and 1,001 rejected. (HLD uuid row.)
8. `feat(developer): QR generator engine` — D15 rows: PNG and SVG, capacity per ECC level, `cv2.QRCodeDetector` decode for ASCII and URL payloads, SVG allow-list. (HLD QR row.)
9. `feat(developer): developer slice routes` — DTOs, `BODY_LIMITS`, fixed messages, the `text-analyses` exclusion, route tests (422 for every DTO violation, 413, P-036 equality). (HLD contract surface.)

Final verification before handoff: `python3 -m pytest -q tests/engine_developer_unittest.py tests/developer_routes_unittest.py tests/test_api_contract_unittest.py tests/test_tool_slots_unittest.py tests/test_devtools_validation_unittest.py`.

## 7. Pitfalls check

- P-102 / P-076: JSON compare and timestamps use only `DevToolsEngine._parse_json` (strict: duplicate keys, non-finite numbers, depth 128, nodes 100k, 1 MiB).
- P-036: all six POSTs are in `BODY_LIMITS` and a test asserts the map equals the POST route inventory.
- P-013: fixed per-route 422 messages. Tests check that submitted values are not echoed.
- P-011: the server never emits HTML. The SVG is generated from numbers and fixed attributes and is consumed only as an `<img>` by the UI (phase 2).
- P-075: UUID and QR results make no strength claims. Copy describes v4/v7 as random, not secret.

## 8. Open items carried to phase 2

1. Done in phase 2 (`fdaf5446`): `regex` is pinned, `count_graphemes` uses `\X`, `text_metrics` returns `graphemes` and `longest_line_graphemes`, and `POST /api/developer/text-analyses` has an 8 MiB cap.
2. Done in phase 2: seven catalogue entries, the `assets/officekit-slice-developer.js` UI (approved mock), and the UI logic tests in `tests/developer-slice-ui.test.mjs`.
3. QR Unicode decoding (decided): the default `cv2.QRCodeDetector` misreads one ECC-L matrix (the "hello lowercase bytes" payload), so the test helper falls back to `QRCodeDetectorAruco` when the default detector returns nothing. Non-ASCII payloads (`test_unicode_payloads_decode_as_utf8`) go through that same helper.
