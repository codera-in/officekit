# HLD: Pending image tools (slice 5)

Version: 1.0.3 · 2026-10-28 · Open question 1 answered: 12 ordinary gallery cards, no family card. Earlier: 1.0.2 · 2026-10-22 · I14 border batch recorded as API-only for now (PM-6, owner answer). Earlier: 1.0.1 · 2026-10-22 · Round 1 review: built-file name corrected (ARCH-6); Rotate & flip scope recorded (PM-1).

Status: draft for owner review. Mock: `design/mocks/pending-image.html` (not yet approved). Parent: `docs/hld/pending-tools-and-ergonomics.md` slice 5; ADR 2026-10-22 in `docs/ARCHITECTURE.md`; requirements `review/pending-tools-slices/requirements.md`.

## Decision: dedicated Image tools workbench, not Media Toolkit operations

All 12 tools live in one **Image tools** workbench (`converterMode: 'image_tools'`, `imageTool: '<slug>'`). It calls bounded multipart/JSON routes in `officekit/routes/image.py`. Media Toolkit gets no new operations.

- **Routing.** Media Toolkit needs native media authority, so private beta and the browser are sent to separate workbenches (`selectSearchTool` `betaDestinations`, index.html:12593). An HTTP workbench has one destination everywhere. That removes a second routing fork for 12 IDs, and slice 7 can promote a tool by editing `release-profile.json` alone.
- **Fit.** Media Toolkit jobs map one file to one file with a generic settings form and no live preview. Seven of the 12 tools have a different shape: inspect (I07, I15), two images to a report (I20), many to one (I18, I19), text out (I16), one to a bundle (I17). I12 needs a preview that matches the export.
- **No duplicates.** Convert, resize, compress, crop, watermark and strip stay in Media Toolkit and the existing workbenches, reached from an in-text rail link. Screenshot Editor keeps its quick 90° rotate. Exposing I06/I11/I12/I14 as Media Toolkit pipeline steps later is open question 4. It would reuse this engine, not add a second tool.

## Scope (depth and verification from `docs/RELEASE-123-TOOLS.md` :109-123)

| ID | Tool ID / slug | Depth delivered | Verification cases (automated) |
| --- | --- | --- | --- |
| I06 | `image_rotate_flip` / rotate-flip | 90/180/270° clockwise and horizontal/vertical flip, with direction labelled in the UI. EXIF orientation is applied first and the tag reset to 1. | 2×2 pixel fixture: all four turns and both flips give exact pixels; an Orientation=6 source produces upright output with tag 1 (or absent) |
| I07 | `image_exif_view` / exif | Date, camera, exposure, image and location groups. Each field is present, missing, unsupported or malformed. GPS is withheld unless requested. | Known GPS+date fixture; Unicode Artist/UserComment; truncated or malformed GPS IFD; original bytes unchanged (hash); default response has no coordinates |
| I10 | `image_dpi` / dpi | Sets density (1–2400, inch or cm) without resampling. The UI shows print size. | Pixel dimensions and decoded pixels identical (PNG/TIFF/BMP); JPEG JFIF/EXIF density tags read back; WebP/GIF rejected |
| I11 | `image_grayscale` / grayscale | ITU-R 601 luma (`L`), with alpha kept as `LA`. Preview and export match. | RGB primaries give known luma; transparent pixels keep alpha; output mode L/LA; RGB ICC dropped |
| I12 | `image_adjust` / adjust | Brightness, contrast and saturation from −100 to 100 (factor 1+v/100). Reset; live server preview. | All zero gives byte-identical pixels; ±100 extremes clip to 0/255; alpha plane unchanged; preview vs downscaled export within tolerance |
| I14 | `image_border` / border | Border width, fill colour and opacity, rounded corners, transparent or opaque canvas, single image in the UI; batch is API-only for now (owner, 2026-10-22: "API-only for now (Recommended)"), and the batch UI or MCP agent is slice 7 work. | Output size = w+2b × h+2b; transparent corners in PNG, fill-flattened in JPEG; width/radius bounds; 3-file batch ZIP |
| I15 | `image_palette` / palette | 1–12 deterministic swatches (HEX, RGB, share). Transparent pixels excluded. Copy/CSV. | Solid colour gives 1 swatch at 100%; known two-colour 70/30 split; transparent background excluded; repeat runs byte-identical |
| I16 | `image_data_uri` / data-uri | Image → data URI and back, binary-safe. MIME sniffed; 8 MiB binary cap; SVG never previewed. | Byte round trip (SHA-256); declared/sniffed MIME mismatch; bad base64 and oversized URI; SVG returned as attachment with nosniff |
| I17 | `image_icon_pack` / icon-pack | Web, Windows and macOS `.iconset` bundles in one ZIP. Pad or centre-crop for non-square sources; upscaled sizes disclosed. | ZIP names and sizes exact; ICO holds every resolution; alpha kept (except apple-touch); non-square pad/crop; small-source header |
| I18 | `image_collage` / collage | Ordered 2–50 images in a grid with columns, cell size, contain/cover, gap, padding and background. Preview and export. | Mixed portrait/landscape/alpha inputs; exact canvas formula; canvas overflow and too few images rejected; upload order kept |
| I19 | `image_contact_sheet` / contact-sheet | Paged A4/Letter grid with optional filenames, as PDF pages or a PNG ZIP. | Long and Unicode names truncated in the middle; 180 images at 4×6 give 8 pages; names off draws no text; page count header |
| I20 | `image_compare` / compare | Side by side and overlay drawn locally; difference heatmap and counts at a stated threshold; explicit scale-to-match. | Identical files give changed_pixels=0 and the wording has no "identical"; one changed pixel found with its bbox; size mismatch gives comparable=false until scaling is chosen |

## Reuse vs new

- **Reused:** `FileConverterEngine` limits (engine_file_converter.py:95-105: 40 MP/frame, 200 MP total, 500 frames, 10,000 px side, 64 MiB output, 50 files, 400 MP batch work); EXIF-transpose and ICC/DPI save-kwargs preservation (:722-765, P-049); JPEG quantization-table reuse (`strip_exif`, P-046); per-frame loop of `resize_image` (:841); `read_api_upload`/`read_bounded_upload`, `content_disposition_attachment` (P-015), `ConversionInputError.public_message`; strict-DTO-in-multipart pattern of `/api/screenshot/edit` (app.py:697-790); `ColorConverterEngine` HEX/RGB formatting (I15); the `SimilarImagePixelBudget` reservation pattern (I20 loading only, no perceptual hash).
- **New:** `ImageToolsEngine` (renditions, metadata report, palette, data URI, comparison) and `ImageComposeEngine` (collage, contact sheet, icon pack). A small refactor pulls `resize_image`'s frame loop into a shared `_map_frames(content, fn, limits)` helper with no behaviour change, pinned by the existing resize tests.

## Contract surface (`officekit/routes/image.py`, prefix `/api`)

All are `POST` (each derives a new, unstored rendition or report, so the answer is `200`, never `201`/`Location`, matching the existing attachment routes). Image parts accept `.jpg .jpeg .png .webp .bmp .tif .tiff .gif` only; any other gives `415`. JSON-in-form fields are parsed with `json.loads` and then a pydantic model with `extra="forbid"` and strict types. Errors use the existing fixed `detail` strings plus a stable `code`. The router exports `PATH_LIMITS` for the body-cap middleware (P-036). Caps are checked before parsing.

| Route | Request (multipart unless noted) | Response | Status | Body cap |
| --- | --- | --- | --- | --- |
| `/image-renditions` (I06, I10–I12, I14) | `file`; `operations` str ≤16 KiB → `RenditionRequest{operations: 1–8 of Rotate{degrees_cw∈90/180/270} \| Flip{axis∈horizontal/vertical} \| Grayscale{} \| Adjust{brightness,contrast,saturation: StrictInt −100..100} \| Border{width 0–2000, corner_radius 0–5000, fill `^#[0-9A-F]{6}$`, fill_opacity 0–100} \| Density{x,y 1–2400, unit∈inch/cm}}` (Density at most once and alone or last); `format∈same/png/jpeg/webp`; `quality` 1–100 (P-014); `preview_max_edge` 64–2048 optional | image bytes; `Content-Disposition`; `X-OfficeKit-Image-Width/Height`; `X-OfficeKit-Image-Density` (new) | 200, 413, 415, 422 | 64 MiB + 4 MiB |
| `/image-rendition-batches` (I14 batch; any rendition) | `files` 1–50; same `operations`/`format`/`quality`; no preview | `application/zip` | 200, 413, 415, 422 | 64 MiB + 4 MiB |
| `/image-metadata-reports` (I07) | `file`; `include_location` bool = false | `MetadataReport{format, width, height, frames, groups[{group∈date/camera/exposure/image/location, tag, label, value ≤512 chars, status∈present/missing/unsupported/malformed}] ≤256, location{present, withheld, latitude?, longitude?, altitude_m?}, has_icc, has_xmp, has_iptc}` | 200, 413, 415, 422 | 64 MiB + 4 MiB |
| `/image-palettes` (I15) | `file`; `count` 1–12 = 6; `alpha_threshold` 1–255 = 128 | `Palette{colors[{hex, rgb[3], share (4 dp), pixels}], sampled_pixels, excluded_transparent_pixels}` | 200, 413, 415, 422 (`NO_OPAQUE_PIXELS`) | 64 MiB + 4 MiB |
| `/data-uris` (I16 encode) | `file` ≤8 MiB (also `.svg`) | `DataUri{mime, byte_length, data_uri_length, data_uri}` | 200, 413, 415, 422 (`MIME_MISMATCH`) | 8 MiB + 4 MiB |
| `/data-uri-images` (I16 decode) | JSON `{data_uri: str ≤11,184,900}`; grammar `^data:image/(png\|jpeg\|webp\|gif\|bmp\|svg\+xml);base64,`; strict `b64decode(validate=True)` | bytes as an attachment; `X-Content-Type-Options: nosniff` | 200, 413, 422 | 12 MiB |
| `/icon-packs` (I17) | `file`; `platforms` str → list ⊆ {web, windows, macos}, 1–3 entries, unique; `fit∈pad/crop` = pad | `application/zip`; `X-OfficeKit-Upscaled-Sizes` (new, comma list or empty) | 200, 413, 415, 422 | 64 MiB + 4 MiB |
| `/image-collages` (I18) | `files` 2–50 (part order = layout order); `layout` str ≤4 KiB → `Collage{columns 1–10, cell_width/height 16–4000, fit∈contain/cover, gap 0–200, padding 0–400, background `#RRGGBB`\|transparent, format∈png/jpeg/webp}`; `preview_max_edge` optional | image; width/height headers | 200, 413, 415, 422 (`CANVAS_TOO_LARGE`: >10,000 px side or >40 MP, checked from the DTO before decode) | 64 MiB + 4 MiB |
| `/contact-sheets` (I19) | `files` 1–200 (≤128 MiB total, open q. 2); `sheet` str → `{page∈a4/letter, orientation, columns 1–10, rows 1–20, show_names bool = true, format∈pdf/png-zip}` | PDF or ZIP; `X-OfficeKit-Page-Count` | 200, 413, 415, 422 | 128 MiB + 4 MiB |
| `/image-comparisons` (I20) | `image_a`, `image_b` (≤64 MiB combined); `alignment∈none/scale-b-to-a` = none; `threshold` 0–255 = 0 | `Comparison{a{w,h}, b{w,h}, comparable, reason?∈size_mismatch, scaled_b, threshold, compared_pixels, changed_pixels, changed_ratio (6 dp), max_channel_delta, mean_abs_delta (3 dp), changed_bbox?, profiles_differ, difference_png ≤2048 px edge data URI}` | 200, 413, 415, 422 | 64 MiB + 4 MiB |

The new response headers `X-OfficeKit-Image-Density` and `X-OfficeKit-Upscaled-Sizes` must be added to CORS `expose_headers` (app.py:236). Open question 5 covers who owns that line. Every response DTO is declared as `response_model`. Image bytes never enter logs, History or the result store.

## Engine design

- **Limits.** Header dimensions are read with `Image.open` before `load()`, and excess is rejected (P-165, P-047). Per-frame, total, frame-count and output limits are the shared constants. Renditions add `MAX_RENDITION_WORK_PIXELS = 400_000_000`, the sum of output pixels over every op and frame (P-040). Compose routes reuse `MAX_RESIZE_BATCH_TOTAL_PIXELS`, counted after JPEG `draft()` reduction for contact-sheet thumbnails.
- **EXIF, ICC and DPI.** `exif_transpose` runs on every load. Rendition output keeps EXIF without Orientation (as conversion does), ICC where the format supports it, and DPI unless Density changes it. Grayscale drops an RGB ICC profile, because it is invalid for `L`. Collage, contact-sheet, icon and diff outputs carry no EXIF.
- **Alpha.** Adjust works on RGB and re-attaches alpha untouched. Grayscale produces `LA`. Border and rounded corners need an alpha-capable target. A JPEG target flattens onto the fill colour, with a status warning. `corner_radius` above half the shorter side of the bordered canvas is a `422`; the UI caps its slider so this is not reached. CMYK, P and 16-bit inputs convert to RGB(A) before pixel ops, and this is disclosed.
- **Animation.** Renditions apply per frame and keep duration, loop and disposal (P-046/P-048). Palette, compare, collage, contact sheet and icon pack use the first frame and say so.
- **Rotate scope (PM-1).** Rotate & flip (I06) is the batch and arbitrary-turn tool and keeps its own rendition operation. The Screenshot Editor's Rotate 90° stays the in-editor action and is not shared, per the owner's stage-4 decision "Accept all defaults", which names twelve separately searchable image IDs.
- **Rotate.** Clockwise maps to Pillow `ROTATE_270` (90° CW), `ROTATE_180` and `ROTATE_90` (270° CW). Pillow's names are counter-clockwise, and a test pins the mapping. A JPEG re-encode reuses the source quantization tables and subsampling. Lossless jpegtran rotation is not claimed.
- **Density.** Without pixel ops, density is lossless. JPEG: rewrite the JFIF APP0 density bytes (or insert APP0) and swap the APP1 EXIF segment (X/YResolution, ResolutionUnit) via `Exif.tobytes()`; scan data is not re-encoded. PNG pHYs, TIFF and BMP are lossless re-saves. WebP and GIF give `422 DENSITY_UNSUPPORTED`.
- **Preview.** The engine downsizes first (JPEG `draft`, then LANCZOS to `preview_max_edge`). Pixel-unit parameters (border, radius) scale by the same factor, and the output is PNG. The agreement test downsizes the full export to the same size and allows mean absolute difference ≤1.5 levels (order of resampling differs; the doc and test state this).
- **Palette (deterministic).** Downsample with BOX to fit 256×256. Drop pixels with alpha below the threshold. Pack the kept RGB pixels in raster order into one row, then `quantize(colors=count, method=MEDIANCUT, kmeans=0, dither=NONE)`. Count via `getcolors()` and sort by (−pixels, hex). The result is deterministic for the pinned Pillow version, and the fixtures assert exact values.
- **Icon pack.** Web: `favicon.ico` (16/32/48), `favicon-16x16.png`, `favicon-32x32.png`, `apple-touch-icon.png` (180, opaque on white), `android-chrome-192x192.png`, `android-chrome-512x512.png`. Windows: `app.ico` (16/24/32/48/64/128/256, PNG entries). macOS: `icon.iconset/icon_{16,32,128,256,512}x{…}[@2x].png` (16–1024). No `.icns` and no manifest is generated, and the UI says so. LANCZOS on RGBA; sizes above the source edge are listed in `X-OfficeKit-Upscaled-Sizes`.
- **Compare (honest thresholds).** Both images are transposed and converted to RGBA with no colour management. A pixel counts as changed when any channel's |Δ| exceeds `threshold`. Size mismatch with `alignment=none` gives `comparable:false` and no numbers. Scaling B is LANCZOS, reported as `scaled_b` and labelled as introducing resampling differences. Differing ICC profiles set `profiles_differ`. The API and UI never state "identical" or "same image", only counts at the stated threshold and resolution.
- **Data URI.** MIME comes from magic bytes; SVG is detected as text with an `<svg` root after an optional XML prolog. An extension or declared-type mismatch gives `422`. Base64 is standard alphabet with padding; whitespace and URL-safe variants are rejected. SVG is never rasterised, previewed or inlined.
- **Labels (I19).** `ImageFont.load_default(size)` (existing practice). The name is NFC-normalised, control characters are removed, and it is truncated in the middle to the cell width. Glyph coverage is open question 3.

## UI component tree (`assets/officekit-slice-image.js`, registered through the foundation hook)

```
#image-tools-panel (converterMode image_tools; heading h1, eyebrow, lead)
├─ ImageToolNav: grouped rail ≥761 px (Adjust 5 · Inspect 3 · Combine 2 · Export 2, footer link → Media Toolkit); themed "Tool" menu ≤760 px; slug in URL hash
├─ SingleImageView (rotate-flip, grayscale, adjust, border, dpi): FileRow · PreviewPair (original object URL | server preview, AbortController + 250 ms debounce) · tool form · "Reset to original" link
├─ ExifView: FileRow · LocationRow (withheld → "Show location" re-request) · grouped table · "Remove metadata" link → image_exif_strip
├─ PaletteView: swatch grid (Copy / CSV; "Convert" link → color converter)
├─ CompareView: two FileRows · ok-segmented Side|Overlay|Difference · stats row · mismatch alert with "Scale B to A"
├─ CollageView / ContactSheetView: OrderedFileList (drag, Alt+↑/↓, ↑ ↓ × row actions) · layout form · live canvas size / page count
├─ DataUriView: ok-segmented direction · textarea or FileRow · size readout
├─ IconPackView: platform checkboxes · fit choice · upscale warning
└─ ok-action-dock: status + at most 3 buttons (per-view counts in the mock)
```

State is in memory per view. Object URLs are revoked on change or leave. Image contents are not added to History. The 12 destinations, gallery family and search keywords come from `officekit/tool_catalog/image.py`. Every tool is development-only (absent from the private-beta profile).

## Files owned by this slice

`officekit/tool_catalog/image.py`, `officekit/routes/image.py`, `officekit/engines/engine_image_tools.py`, `officekit/engines/engine_image_compose.py`, `assets/officekit-slice-image.js`, the per-slice doc page (foundation path), `tests/engine_image_tools_unittest.py`, `tests/engine_image_compose_unittest.py`, `tests/image_routes_unittest.py`, `tests/officekit-image.test.mjs`, `ui-tests/image-tools.spec.mjs`, and this HLD and mock. Shared touch, kept minimal: the `_map_frames` extraction in `engine_file_converter.py` and the two CORS header names.

## Test plan

- **Engine (pytest, generated fixtures):** each row of the scope table. Plus patched-limit boundaries for frame pixels, total pixels, frames, work budget and output bytes. Preview/export agreement (I11, I12, I14, I18). Deterministic palette across two runs. ICO read-back of `info['sizes']`. Clockwise mapping pin.
- **Route (TestClient):** every route has 422 for unknown fields, wrong types and bounds edges (min−1, min, max, max+1); 415 for extension; 413 from the body cap before parsing (declared Content-Length); fixed `detail` strings; a Unicode/path filename becomes a safe `Content-Disposition` (P-015); response headers present and exposed via CORS; `include_location=false` output contains no coordinate digits; originals unchanged.
- **Catalogue/routing (node):** each of the 12 IDs is searchable and resolves to `{tab:'converter', converterMode:'image_tools', imageTool}`; all are absent from the private-beta profile; counts are derived (AC4).
- **UI (Playwright WebKit, desktop 1240 px and compact 390 px):** for each view, open by search, run with fixtures staged on disk with byte lengths asserted (P-116), and check a result is produced. The button count is ≤3 and asserted per view. No `hidden` element shows. Reset restores identity. GPS is hidden until clicked. Collage reorder changes the output order. Compare wording has no "identical". Heading hierarchy and action order are asserted, not just presence (P-167). Rebuild the CSP hash and `dist-ui/` (P-111).

## Pitfalls check

P-165/P-047: dimensions checked before decode. P-040: cumulative work budget. P-036: `PATH_LIMITS` for every route with a route-map equality test. P-015: shared filename helper. P-014: quality 1–100 at form and engine. P-046/P-048: frames, palettes and timing kept. P-049: transpose, then ICC/DPI per format. P-116: on-disk fixtures. P-167: whole-workflow UI tests. P-111: CSP hash rebuilt at merge. P-107: compare and icon-upscale copy is hedged and states measured facts only, never a confirmed identity. New risk with no existing pitfall: GPS display. Coordinates are withheld server-side by default, never logged, never put in History, and excluded from Copy while hidden. Record a P-entry if review finds a leak path.

## Open questions

1. ~~Can the foundation gallery render a `family` (one "Image tools" card with 12 links)?~~ Answered 2026-10-28 (owner: component driven, all tools reuse the same component): the gallery renders 12 ordinary cards in Images from the shared tool-card component; the family card is removed.
2. Contact sheet for large folders: keep the 200-file / 128 MiB upload cap, or read paths through the desktop file-selection grant (desktop only)?
3. Unicode labels: bundle a Noto Sans subset (licence and size review), or keep `load_default` and disclose that missing glyphs render as boxes?
4. Later, expose rotate/flip, grayscale, adjust and border as Media Toolkit pipeline steps (same engine) for automations?
5. Should routers declare their own CORS `expose_headers` through the foundation, so `app.py` is not hand-merged?
