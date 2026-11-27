# Pending tools — developer slice (D04, D10–D11, D15–D17)

Version: 1.1.1 · 2026-10-22 · Round-2 ARCH-1: UUID body cap row states 8 KiB, as the contract and code do. Round-1 decisions recorded (per-level QR capacity, UTF-8 byte text limit, work budgets, UUID body cap, QR side range, one line model).

Parent: `docs/hld/pending-tools-and-ergonomics.md` slice 3; ADR 2026-10-22 in `docs/ARCHITECTURE.md`; requirements `review/pending-tools-slices/requirements.md`. Mock: `design/mocks/pending-developer.html` (not yet approved; no UI code before approval, AC6).

## Scope

Depth and cases come from `docs/RELEASE-123-TOOLS.md` :211-224. All six are development-only and are left out of the private-beta profile (requirement 6).

| ID | Tool (stable ID) | Depth delivered | Verification cases (each gets a test) |
| --- | --- | --- | --- |
| D04 | `json_compare` | Structural diff with RFC 6901 paths. Object key order is always ignored. Array policy is `ordered` (aligned, so one insert does not cascade) or `unordered` (multiset). | Reordered keys = equal; missing vs `null` reported differently; array insert/move under each policy; `1` vs `"1"` is `type_changed`; `1` vs `1.0` equal by value and different with `numeric: lexical`; `true` vs `1` never equal |
| D10 | `timestamp_converter` | The user picks the input type: Unix s / ms / µs, ISO 8601 with offset, or local date-time plus IANA zone. Output in up to 8 zones. | Epoch 0; negative epochs; DST gap rejected and DST fold resolved only by explicit `fold`; seconds value that looks like ms gives a warning and is never reinterpreted; out-of-range values and malformed numbers rejected |
| D11 | `uuid_generator` | v4, v7 (RFC 9562), v5 (namespace + name). 1–1,000 per batch. Copy all, export .txt/.csv. | Regex format plus version nibble and variant bits; 10 × 1,000 v4/v7 have no duplicates; v7 is monotonic in a batch; v5 matches RFC 9562 vectors; 0 and 1,001 rejected |
| D15 | `qr_generator` | Text/URL payload, ECC L/M/Q/H, size 128–2,048 px, quiet zone 4. Local PNG or SVG. | An independent decoder reads back ASCII, URL and Unicode payloads; capacity limit per ECC level; SVG passes the safe-element allow-list |
| D16 | `text_metrics`, `text_case` | Defined counts (below) plus 9 case styles, with an optional Turkish/Azeri locale | Emoji ZWJ/flags/skin tones and combining marks; CRLF/CR/LS line breaks; blank lines; empty input = all zeros; `ß`→`SS`; Turkish `i`→`İ`; output growth cap |
| D17 | `text_diff` | Line diff shown side by side or unified, with in-line changed spans. Policies for whitespace, line endings and Unicode normalization. Export `.patch` and `.md`. | Insert/delete/change; Unicode lines; 1 MiB and 50,000 lines per side; the too-different bound; `<script>` stays text (P-011); the patch applies with `patch -p0` in a test; Markdown fence is longer than any backtick run in the content |

## Reuse vs new

- **Reuse:** `DevToolsEngine._parse_json` (dup keys, non-finite numbers, depth 128, nodes 100k, 1 MiB), `_text_bytes`, `_dump_json` for value previews, `RequestBodyLimitMiddleware`, the developer workbench shell, the `ok-action-dock` and the result-capability copy/download helpers, the global toast (P-161), pinned `qrcode==8.2` (matrix only) and `tzlocal`.
- **New:** `officekit/engines/engine_developer.py` (pure functions, controlled `DeveloperInputError`) and the private helper `_myers.py`, a bounded O(ND) diff shared by D04 array alignment and D17.
- **Not reused:** the `/api/devtools/process` `Literal`. New routes go on the slice router so this branch does not conflict with others. `uuid.uuid7` is not used because the installer build pins Python 3.13 (`build-installers.yml:89`) and `uuid7` arrived in 3.14. v7 is implemented in the engine.

## Contract surface

Every route is on `officekit/routes/developer.py` (`APIRouter(prefix="/api/developer")`). Every DTO uses `extra="forbid"` and strict types. These are computations with nothing stored, so a successful POST returns `200` with no `Location` header, the same as `/api/colors/convert`. Validation errors return `422`. Engine input errors return `422` with one fixed message per route (P-013). Unexpected failures go to the generic `500`. Each POST path is added to the body-cap map before parsing, and a test checks that the map equals the route inventory (P-036). Anything over the cap returns `413`.

| Method · path | Request DTO (bounds) | Response DTO | Codes · fixed error · body cap |
| --- | --- | --- | --- |
| POST `/json-diffs` | `original`, `changed`: str ≤1 MiB UTF-8 each; `array_order`: `ordered`\|`unordered` = ordered; `numeric`: `value`\|`lexical` = value | `{equal, changes:[{path, kind: added\|removed\|changed\|type_changed, before?, after?}] ≤10,000, truncated, counts{added,removed,changed,type_changed}}`. Previews ≤256 chars. | 200/413/422 · "JSON comparison input is invalid or exceeds supported limits." (the message names the side) · 16 MiB |
| POST `/text-diffs` | `original`, `changed`: str ≤1 MiB, ≤50,000 lines each; `whitespace`: `exact`\|`ignore_trailing`\|`ignore_all` = exact; `line_endings`: `normalize`\|`exact` = normalize; `unicode_nfc`: bool = false; `context`: 0–20 = 3 | `{equal, rows:[{op: equal\|insert\|delete\|change, left_no?, right_no?, left?, right?, left_spans?, right_spans?}], hunks, stats{inserted,deleted,changed}, line_endings{original,changed: lf\|crlf\|cr\|mixed\|none}, patch, markdown}` | 200/413/422 · "Text comparison input is invalid, too different, or exceeds supported limits." · 16 MiB |
| POST `/text-analyses` | `text`: str ≤1 MiB (empty allowed) | `{graphemes, code_points, utf8_bytes, utf16_units, words, lines, blank_lines, whitespace, longest_line_graphemes}` | 200/413/422 · "Text input is invalid or exceeds supported limits." · 8 MiB |
| POST `/text-case-conversions` | `text`: str ≤1 MiB; `style`: `lower`\|`upper`\|`title`\|`sentence`\|`camel`\|`pascal`\|`snake`\|`kebab`\|`constant`; `locale`: `root`\|`tr`\|`az` = root | `{result, style, locale}`. Result ≤1 MiB. | 200/413/422 · same fixed text message · 8 MiB |
| POST `/timestamp-conversions` | `value`: str 1–64; `input_type`: `unix_seconds`\|`unix_milliseconds`\|`unix_microseconds`\|`iso_8601`\|`local_datetime`; `source_zone`: IANA key ≤64 (required only for `local_datetime`); `fold`: `reject`\|`earlier`\|`later` = reject; `target_zones`: 1–8 unique IANA keys | `{instant_utc, unix_seconds, unix_milliseconds, unix_microseconds (decimal strings), conversions:[{zone, local_iso, offset, abbreviation, is_dst, weekday}], warnings:[code]}` | 200/413/422 · "Timestamp input is invalid, ambiguous or out of range." · 4 KiB |
| GET `/time-zones` | none | `{zones: string[] (sorted, ≤1,000), local_zone: string\|null}` | 200 · no body |
| POST `/uuids` | `version`: 4\|5\|7; `count`: 1–1,000 (must be 1 for v5); `namespace`: `dns`\|`url`\|`oid`\|`x500` or a canonical UUID (v5 only); `name`: str 1–1,024 UTF-8 bytes (v5 only, otherwise forbidden); `case`: `lower`\|`upper`; `style`: `canonical`\|`braces`\|`urn`\|`compact` | `{uuids: string[], version, count}` | 200/413/422 · "UUID request is invalid or exceeds the batch limit." · 8 KiB (sized for 1,024 control characters, each a six-byte JSON escape) |
| POST `/qr-codes` | `payload`: 1 byte up to the per-level capacity in UTF-8 bytes (L 2,953, M 2,331, Q 1,663, H 1,273; 422 above it); `error_correction`: `L`\|`M`\|`Q`\|`H` = M; `size_px`: 128–2,048 = 512; `format`: `png`\|`svg` | `{format, data (base64 PNG or SVG text), qr_version, modules, payload_bytes, size_px}`. PNG ≤512 KiB, SVG ≤1 MiB. | 200/413/422 · "QR payload is empty, invalid or too long for this error-correction level." · 32 KiB |

Integers that can exceed 2^53 (µs, ms with fractions) are sent as decimal strings. No route logs payloads, text or names.

## Engine design

- **JSON diff:** both sides go through `_parse_json`. The recursive walk uses an explicit stack, because the parser already bounds depth at 128. Type tags are checked before values, so a `bool` is never treated as an `int`. With `numeric: value`, numbers are compared as `Decimal` values; with `lexical`, the source token is compared. Object key order is ignored and keys are compared as a sorted union. `ordered` arrays are aligned with Myers on canonical element hashes (sorted-key canonical dump), and unaligned pairs at the same position recurse as `changed`. `unordered` arrays use a multiset of canonical hashes, and paths report the original indices. Paths are RFC 6901 (`~0`/`~1` escaping). Output stops at 10,000 changes with `truncated: true`.
- **Myers (`_myers.py`):** a linear-space O(ND) diff with `MAX_EDIT_DISTANCE = 10,000`. Above that it raises the fixed "too different" error instead of running quadratically. D17 changed lines get character spans from a second Myers pass only when both lines are ≤1,000 code points.
- **Text diff policy:** line endings are normalized to LF before comparison and the original style is reported per side. `ignore_*` affects only the equality key; the rows show the original text. The patch uses fixed labels `--- original` / `+++ changed` (no paths) and `\ No newline at end of file`. Markdown wraps the patch in a `diff` fence one backtick longer than the longest run in the content. The server never produces HTML; the UI renders rows with `textContent` (P-011).
- **Graphemes:** Python 3.13/3.14 stdlib has no UAX #29 segmentation and nothing installed provides it (`regex`/`grapheme` are absent). Proposed: pin `regex` and count `\X` (extended grapheme clusters). See open question 1. Other definitions: code points = `len(str)`; words = whitespace-separated tokens containing at least one letter or number (stated limitation: unspaced CJK text counts as one word per run); lines = segments split on LF, CRLF, CR, U+2028 and U+2029, with empty text = 0 lines and a trailing break not adding a line; whitespace = `str.isspace`.
- **Casing:** uses Unicode full case mapping (`str.upper/lower`). `tr`/`az` override only `I→ı`, `İ→i`, `i→İ`. Title, sentence and identifier styles are built from the same word tokenizer, not `str.title()` (apostrophe bug). Output above 1 MiB is rejected.
- **Timestamps:** values are parsed as `Decimal` and never as float. Fraction digits are capped (s ≤6, ms ≤3, µs 0). The range is 0001-01-01 to 9999-12-31 UTC. ISO input must carry `Z` or an offset; naive ISO input is rejected and the user is pointed to Local date-time. `local_datetime` checks the DST gap (round-trip mismatch → reject) and the fold (two offsets → `reject` unless `fold` is set). Warning codes: `magnitude_suggests_milliseconds` (seconds input |v| ≥ 1e11), `magnitude_suggests_seconds` (ms input |v| < 1e11, except 0). Zone keys must be members of `zoneinfo.available_timezones()`.
- **UUIDs:** v4 uses `uuid.uuid4` (OS CSPRNG). v7 uses a 48-bit Unix ms timestamp, a 12-bit `rand_a` counter seeded randomly per ms and incremented within the same ms (it advances the ms on overflow, RFC 9562 §6.2 method 1), and 62 bits from `secrets`. v5 uses `uuid.uuid5`. v1/v6 are excluded because they expose host or clock identity; v3 is excluded as MD5; v8 is excluded as vendor-defined. Nothing is stored or remembered.
- **QR + SVG safety:** `qrcode.QRCode(error_correction=…, box_size=1, border=4)`, `make(fit=True)`. `DataOverflowError` maps to the fixed 422. Only `get_matrix()` is used. PNG is drawn with Pillow in 1-bit mode at the integer module size nearest to `size_px`. SVG is written by the engine and does not use the qrcode SVG factories: `<svg xmlns viewBox width height>`, then `<rect fill="#fff">`, then one `<path fill="#000" d="M…h1v1h-1z…">` made only of numbers and command letters. It has no text, title, payload, `href`, `style`, script or `foreignObject`. Colors are fixed black on white so scanners read it.

## UI component tree

```
Developer & Data category (shared registration hook, assets/officekit-developer.js)
├─ #developer-tools-panel (existing select; gains optgroups)
│  ├─ "Text": Text metrics → stat grid; Change case → style + locale selects, output textarea
│  └─ "Time": Convert timestamp → input-type select, value, source zone (local only),
│            target-zone chips (≤8), result table; "Use now" fills the value from the device clock
├─ #developer-compare-panel (new; D04 opens in JSON mode, D17 in Text mode)
│  ├─ mode segmented control, Original | Changed textareas, Options <details>
│  └─ results: JSON change list (path, kind badge, before → after) | text rows, Side by side / Unified toggle
├─ #uuid-generator-panel (new): version, count, case/style, v5 namespace + name; numbered list
└─ #qr-generator-panel (new): payload, ECC, size, format; preview <img> (PNG as data: URL, SVG as Blob URL) + capacity meter
Each panel: one ok-action-dock (primary Run/Compare/Generate; Copy, Download/Export, Clear), statuses via role=status + global toast.
```

## Files owned (foundation slots)

`officekit/tool_catalog/developer.py`, `officekit/routes/developer.py`, `officekit/engines/engine_developer.py`, `officekit/engines/_myers.py`, `assets/officekit-developer.js`, the slice doc page (foundation-named, e.g. `docs/tools/developer.md`), `tests/engine_developer_unittest.py`, `tests/developer_routes_unittest.py`, `tests/officekit-developer.test.mjs`, `ui-tests/developer-pending.spec.mjs`. Panel markup is injected by the slice JS (or added at a foundation-provided `index.html` anchor). The only shared files this slice touches are the foundation's registration points and `requirements.txt` (`regex`, and `tzdata` if approved).

## Test plan

- **Engine (pytest, 100% branch coverage of the new modules):** every verification case in the Scope table. Bounds at the limit and one past it (1 MiB, 50,000 lines, 10,000 edits/changes, 1,000 UUIDs, 2,953/2,331/1,663/1,273 bytes for L/M/Q/H, 8 zones). Property tests: diff(a, a) is equal; applying the patch to the original gives the changed text; the `unordered` result does not depend on order.
- **Routes:** a 422 for every DTO violation (extra field, wrong type, out-of-range enum); fixed messages with no reflected input (P-013); a 413 for an oversized declared body before reading; body-cap map = route inventory (P-036); response DTO validated.
- **D15 scanner:** decode each PNG with `cv2.QRCodeDetector` (`opencv-python==4.13.0.90` is already pinned in `requirements.txt`, independent of `qrcode`). Convert SVG to a bitmap for the decoder by rasterizing its `get_matrix()`-equivalent path with Pillow in the test. Parse SVG with `xml.etree` to check the allow-list, and check the payload is absent from the SVG text.
- **UI (node + WebKit):** search by every stable ID opens the exact panel/mode (AC2, P-108 cold-load); `<img onerror>` payloads render as text in both diff views; copy/export toasts (P-161); action dock geometry (P-172/P-167); counts derived from the registry (P-150); development-only exclusion from the beta profile.

## Pitfalls check

P-102/P-076: D04 uses the strict parser only. P-036: all six POSTs are in the cap map, with an equality test. P-013: fixed per-route messages. P-011: no `innerHTML` for user data; the SVG preview is an `<img>` and is never inlined. P-075: UUID/QR copy makes no strength claims; v4/v7 is described as "random", not "secret". P-150/P-108/P-167/P-172/P-161: covered in the UI tests above.

## Open questions

1. **Graphemes:** pin `regex` (new runtime dependency; licence and sidecar-size review), or count graphemes in the UI with `Intl.Segmenter` and keep the engine to code points and bytes? Recommended: `regex`, so the engine stays authoritative and testable.
2. **QR Unicode decode:** `qrcode` writes UTF-8 in byte mode with no ECI. If `cv2` decodes non-ASCII as Latin-1, either add a dev-only `zxing-cpp` test dependency or accept "scanner-dependent" copy for non-ASCII payloads.
3. **Windows time zones:** the frozen sidecar needs `tzdata` for `zoneinfo` on Windows. The calculators slice (C22) needs it too, so pin it once in the foundation?

## Decisions recorded in round 1 (version 1.1.0)

- **Text limit unit:** 1,048,576 UTF-8 bytes per text field. The DTO's code-point bound is a pre-filter only (ARCH-2).
- **Work budgets:** `MAX_SEARCH_WORK` and `MAX_INLINE_SPAN_WORK` are 4,000,000 units each; `MAX_JSON_OUTPUT_BYTES` is 1,048,576 bytes (CR-1 to CR-3). Budget overrun returns the route's fixed 422 or `spans_omitted`, never a partial diff.
- **UUID body cap:** 8 KiB, sized for 1,024 control characters, each a six-byte JSON escape (ARCH-1).
- **QR side:** the whole-module multiple nearest the request, clamped into 128–2,048 px (ARCH-4, CR-6).
- **Line model:** CRLF, CR and LF only, shared by text metrics and text diff (CR-7).
