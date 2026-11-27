# Pending image tools: back-end implementation (slice 5, phase 1)

Version: 1.1.2 · 2026-10-22 · Round 2 review: the stale font sentence is removed from the contact-sheet paragraph (DEVOPS-2). Earlier: 1.1.1 · Round 1 review: font note corrected (DEVOPS-2); contact-sheet PDF ceiling recorded (CR-6).

## Delivered deviations (1.1.0)

The back end was built to this LLD. These points were settled during the build and supersede the text below where they differ:

- `platforms` on `/api/icon-packs` is a comma-separated string (for example `web,windows`), not a JSON list. Values outside `web`, `windows`, `macos`, duplicates and more than three entries are 422 `INVALID_OPTIONS`.
- `/api/data-uri-images` checks the decoded bytes against the declared MIME as well as the encoder does (`MIME_MISMATCH`, 422).
- `X-OfficeKit-Image-Density` is `<x>,<y>,inch` in dots per inch, with `cm` input converted (for example `299.72,299.72,inch`).
- `/api/image-rendition-batches` with more than 50 files is 413 `TOO_LARGE_INPUT`, as the existing resize batch does. Zero files is 422. The collage (2–50) and contact-sheet (1–200) file-count bounds are 422 `INVALID_OPTIONS`.
- The ZIP for icon packs places members under `web/`, `windows/` and `macos/icon.iconset/`.
- `/api/image-comparisons` reports the dimensions as `a.w`, `a.h`, `b.w` and `b.h`.
- `palette.sampled_pixels` counts pixels kept after the alpha threshold. `excluded_transparent_pixels` counts the rest.
- Rendition output keeps the source EXIF without Orientation, as the HLD states, and so it can keep GPS coordinates that the source file already has. This is an open owner decision (see the HLD open questions), not a change from this LLD.
- The `_map_frames` extraction is deferred (see Decisions).

The 1.0.0 design text follows.

Version 1.0.0 · 2026-10-22.

Parent: `docs/hld/pending-tools-image.md` (1.0.0, draft for owner review). Every contract row below cites the HLD route row (R-n = the row order in the HLD "Contract surface" table, starting at 1) or the HLD scope row (I-nn). This LLD covers the back end only. The UI (`assets/officekit-image.js`), the tool catalogue (`officekit/tool_catalog/image.py`) and the mock are phase 2 and are not touched here.

## Decisions carried into the build

- Routes live only in `officekit/routes/image.py` (exports `router`, `BODY_LIMITS`, `EXPOSE_HEADERS`). `app.py` is not edited; the foundation mounts the router and merges the limits.
- The shared upload helper `read_api_upload` is defined inside `app.py`, so it is not imported. The slice calls `read_bounded_upload` from `officekit/engines/engine_uploads.py` directly and maps `UploadTooLargeError` to 413 itself. This keeps `app` out of the import graph.
- `ImageOutputLimitError`, `ImageWorkLimitError`, `ConversionInputError`, `_BoundedImageBuffer` and the `FileConverterEngine.MAX_*` constants are imported from `engine_file_converter.py`, which is not edited.
- The HLD's `_map_frames` extraction is **not** done: it would edit `engine_file_converter.py`, which this phase may not touch. The HLD says it is pinned by existing resize tests and has no behaviour change, so it is deferred to the integrator as a follow-up. This slice's frame loops live in `engine_image_tools.py`.
- The HLD names the body-cap map `PATH_LIMITS`. The foundation (`officekit/routes/__init__.py`) names it `BODY_LIMITS`. This LLD follows the foundation.
- The `X-OfficeKit-Image-Width`, `X-OfficeKit-Image-Height` and `X-OfficeKit-Page-Count` headers are already in the `app.py` CORS list. `EXPOSE_HEADERS` lists only the two new ones (`X-OfficeKit-Image-Density`, `X-OfficeKit-Upscaled-Sizes`) to avoid duplicates. The HLD open question 5 (who owns that line) is answered for this slice by the foundation's `slice_expose_headers()`.
- Error bodies: `HTTPException` in this app renders `{"detail": "<string>"}`. A stable `code` is added in the body as `{"detail": "<fixed message>", "code": "<CODE>"}`, produced by a route-level decorator (see Error handling). No app-level exception handler is added, because the router must work when mounted on a bare `FastAPI()`.

## File-by-file map

| File | Change | Contract rows |
| --- | --- | --- |
| `docs/lld/pending-tools-image.md` | New (this file) | — |
| `docs/VERSION-HISTORY.md` | One row prepended | — |
| `officekit/engines/engine_image_tools.py` | New. `ImageToolsEngine` (load guard, renditions, metadata report, palette, data URI, comparison), `ImageToolInputError`, shared limits | R-1 I06, I07, I10, I11, I12, I14, I15, I16, I20; R-2; R-3; R-4; R-5; R-6; R-7; R-8 |
| `officekit/engines/engine_image_compose.py` | New. `ImageComposeEngine` (collage, contact sheet, icon pack). Imports the loader from `engine_image_tools` | R-9 I17, I18; R-10 I19 |
| `officekit/routes/image.py` | Replace stub: 10 `POST` routes, DTOs, decorator, `BODY_LIMITS`, `EXPOSE_HEADERS` | all R-rows |
| `tests/engine_image_tools_unittest.py` | New. Engine tests with generated pixel fixtures | I06, I07, I10, I11, I12, I14, I15, I16, I20 |
| `tests/engine_image_compose_unittest.py` | New. Engine tests for I17–I19 | I17, I18, I19 |
| `tests/image_routes_unittest.py` | New. `TestClient` on `FastAPI()` mounting `officekit.routes.image.router` | all R-rows |

Not edited: `app.py`, `officekit/engines/engine_comms.py`, `officekit/engines/engine_file_converter.py`, `officekit/tool_catalog/*`, `index.html`, `assets/*`, `dist-ui/*`, `requirements.txt`, `API-CONTRACT.md`, `docs/TOOL-GUIDE.md`, `docs/FIRST-MAC-RELEASE.md`.

## Interfaces

### Shared load guard (`engine_image_tools.py`)

```python
class ImageToolInputError(ConversionInputError):
    code: str            # stable machine code, e.g. "INVALID_IMAGE"
    public_message: str  # fixed per code; str(error) returns it
    def __init__(self, code: str = "INVALID_IMAGE"): ...

def open_first_frame(content: bytes) -> Image.Image        # header-only checks, then load frame 0
def open_checked(content: bytes) -> ImageFrames            # all frames, per-frame checks before load
```

Limits (module constants, all read from `FileConverterEngine` so one number changes everywhere):
`FRAME_PIXELS` 40 000 000, `TOTAL_PIXELS` 200 000 000, `MAX_FRAMES` 500, `MAX_SIDE` 10 000, `MAX_OUTPUT_BYTES` 64 MiB, `MAX_BATCH_FILES` 50, `MAX_RENDITION_WORK_PIXELS = 400_000_000` (new, P-040), `MAX_DATA_URI_BINARY_BYTES = 8 MiB`, `MAX_DATA_URI_CHARS = 11_184_900`, `MAX_OPERATION_JSON_BYTES = 16 * 1024`.

Accepted decoder formats: `JPEG, PNG, WEBP, BMP, TIFF, GIF` (the HLD extension list, which is also the `Image.open` format set after sniffing).

Order of checks inside `open_checked` (P-165, P-047): `Image.open` (header only) → format allowlist → `n_frames` ≤ `MAX_FRAMES` → for each frame, `size` read **before** `load()`: width and height > 0, side ≤ `MAX_SIDE`, pixels ≤ `FRAME_PIXELS`, running total ≤ `TOTAL_PIXELS` → `load()`. `DecompressionBombError` and `OSError`, `SyntaxError`, `ValueError`, `EOFError`, `UnidentifiedImageError` map to `ImageToolInputError("INVALID_IMAGE")`. Dimension overflow maps to `ImageWorkLimitError` (413).

Work budget: `SimilarImagePixelBudget(limit)` from `engine_similar_images.py` is reused. Its `SimilarImagePixelBudgetError` is translated to `ImageWorkLimitError`.

### Renditions (R-1, R-2)

```python
@dataclass(frozen=True)
class RenditionOp:  # built from the route DTO
    kind: Literal["rotate", "flip", "grayscale", "adjust", "border", "density"]
    # per-kind fields: degrees_cw | axis | brightness/contrast/saturation | width/corner_radius/fill/fill_opacity | x/y/unit

@dataclass(frozen=True)
class Rendition:
    content: bytes
    extension: str        # png, jpg, webp, bmp, tiff, gif
    media_type: str
    width: int
    height: int
    density: tuple[float, float, str] | None   # (x, y, "inch") after conversion; None if not set
    warnings: tuple[str, ...]                  # "color_mode_converted", "alpha_flattened"

class ImageToolsEngine:
    @staticmethod
    def render_rendition(content: bytes, operations: Sequence[RenditionOp], output_format: str,
                         quality: int | None = None, preview_max_edge: int | None = None,
                         work_budget: SimilarImagePixelBudget | None = None) -> Rendition
```

`output_format` is `"same"`, `"png"`, `"jpeg"` or `"webp"`. `"same"` resolves to the source's Pillow format (JPEG, PNG, WEBP, BMP, TIFF, GIF).

Behaviour (HLD "Engine design" rules):
- Load: `ImageOps.exif_transpose` per frame (P-049), then CMYK, P, 16-bit and other modes convert to RGB(A) (disclosed in `warnings`).
- Rotate: clockwise maps to Pillow `ROTATE_270` (90° CW), `ROTATE_180` (180°), and `ROTATE_90` (270° CW). A unit test pins the mapping with a 2×2 fixture.
- Flip: horizontal → `FLIP_LEFT_RIGHT`; vertical → `FLIP_TOP_BOTTOM`.
- Grayscale: RGB → `L`, RGBA/LA → `LA`, using Pillow's ITU-R 601 luma. The RGB ICC profile is dropped.
- Adjust: factor = 1 + v/100 per channel. A channel at 0 is skipped (byte identity). RGB only (L/LA are converted to RGB(A) first); alpha re-attached untouched.
- Border: outer canvas (w+2b, h+2b) filled with `fill` at `fill_opacity` (0–100 → alpha round(v·255/100)); image pasted at (b, b) with its own alpha; corners outside a rounded rectangle of `corner_radius` set to alpha 0. `corner_radius` > half the shorter side of the bordered canvas → `ImageToolInputError("CORNER_RADIUS_TOO_LARGE")` (422). A JPEG target flattens onto `fill` (or white when there is no border) and appends `"alpha_flattened"`.
- Density (no pixel op): JPEG → byte surgery: parse marker segments, rewrite the JFIF APP0 density bytes (or insert APP0 after SOI), and replace the APP1 Exif segment with `Exif.tobytes()` that sets XResolution/YResolution/ResolutionUnit; scan data is copied byte-for-byte. PNG, TIFF and BMP → lossless re-save with `dpi`. WebP and GIF output → `ImageToolInputError("DENSITY_UNSUPPORTED")` (422).
- Density units: `inch` stores x, y as given; `cm` stores x·2.54 as dpi (JFIF unit 2 / EXIF unit 3 on JPEG).
- Density with pixel ops is applied on save (last op only).
- Preview (`preview_max_edge`): downsize first (JPEG `draft`, then LANCZOS to the edge). Pixel-unit parameters (border width, radius) scale by the same factor. Output is PNG. Density is not applied to previews.
- Quality: `quality` is `None` (keep: for a JPEG source reuse its quantization tables and subsampling; otherwise 90) or 1–100 (validated again in the engine, P-014).
- Work: every op adds its output pixels per frame to `work_budget` (P-040). Exhaustion → `ImageWorkLimitError`.
- Output: encoded into `_BoundedImageBuffer(MAX_OUTPUT_BYTES)`; overflow → `ImageOutputLimitError` (413).
- Animation: each frame gets the same op; duration, loop and disposal are kept (P-046/P-048).
- Metadata: EXIF is kept without Orientation when pixel ops ran; a density-only JPEG keeps the source EXIF (orientation untouched, because pixels are not rotated). ICC is kept where the format supports it, and is dropped for `L`/`LA`.

`render_rendition_batch(files: Sequence[tuple[str, bytes]], ...) -> bytes` builds the ZIP, sharing one `work_budget`. Names use the `resize_images_to_zip` rule (basename, stem sanitised to 100 characters, `_edited` suffix, dedupe with ` (n)`). Output uses `_BoundedImageBuffer`.

### Metadata report (R-3, I07)

```python
def metadata_report(content: bytes, include_location: bool = False) -> dict   # MetadataReport-shaped
```

Field table (fixed order, one entry per row, so the entry count is ≤ 256 by construction):

| group | tag | label |
| --- | --- | --- |
| date | DateTimeOriginal (0x9003), DateTime (0x0132), DateTimeDigitized (0x9004) | Taken, Modified, Digitized |
| camera | Make, Model, LensModel | Make, Model, Lens |
| exposure | ExposureTime, FNumber, ISOSpeedRatings, FocalLength | Exposure, Aperture, ISO, Focal length |
| image | Orientation, ColorSpace, Artist, ImageDescription, UserComment, Software | Orientation, Colour space, Artist, Description, Comment, Software |
| location (only when `include_location=True`) | GPSLatitude+Ref, GPSLongitude+Ref, GPSAltitude+Ref | Latitude, Longitude, Altitude |

Status per entry: `present` (decoded), `missing` (absent), `unsupported` (UserComment with an unknown charset prefix, or a tag type with no decoder), `malformed` (decode raised, a rational has denominator 0, a coordinate is out of range, or a GPS pointer resolves to no readable IFD). Values are NFC-normalised, control characters removed, and cut to 512 characters.

`location` object: `{present, withheld, latitude?, longitude?, altitude_m?}`. Default (`include_location=False`): `present` says whether a GPS IFD with a parseable coordinate pair exists, `withheld=True`, and no coordinate field is emitted. Location group entries are emitted only when `include_location=True`. This keeps the value out of `groups` too.

Always present: `format, width, height, frames, has_icc, has_xmp, has_iptc`. Metadata is read from the first frame's EXIF (`Image.getexif`). The source bytes are never written (hash test).

### Palette (R-4, I15)

```python
def palette(content: bytes, count: int = 6, alpha_threshold: int = 128) -> dict
```

Steps (HLD "Palette (deterministic)"): first frame → `exif_transpose` → RGBA → `thumbnail((256, 256), BOX)` → drop pixels with alpha < threshold, counting them as `excluded_transparent_pixels` → pack kept RGB in raster order into a `(kept, 1)` RGB image → `quantize(colors=count, method=MEDIANCUT, kmeans=0, dither=NONE)` → `getcolors(65536)` → sort by `(-pixels, hex)`. HEX is produced via `ColorConverterEngine.convert("rgb(r, g, b)", "rgb", "hex").upper()`. `share` is pixels/kept to 4 dp. No kept pixels → `ImageToolInputError("NO_OPAQUE_PIXELS")` (422).

### Data URI (R-5, R-6, I16)

```python
def encode_data_uri(content: bytes, declared_mime: str) -> dict   # DataUri
def decode_data_uri(data_uri: str) -> tuple[bytes, str]           # (bytes, mime)
def sniff_mime(content: bytes) -> str | None                      # png, jpeg, webp, gif, bmp, tiff, svg+xml
```

- Encode: `content` ≤ 8 MiB (else 413 `TOO_LARGE_BINARY`). `sniff_mime` must equal `declared_mime` (derived by the route from the extension). Mismatch or unknown signature → `ImageToolInputError("MIME_MISMATCH")`.
- SVG detection: strict UTF-8 (BOM stripped), an optional XML prolog, comments and DOCTYPE, then a `<svg` root. Never rasterised.
- Decode: grammar `^data:image/(png|jpeg|webp|gif|bmp|svg\+xml);base64,` then `base64.b64decode(payload, validate=True)`; invalid → `ImageToolInputError("INVALID_DATA_URI")`. Decoded > 8 MiB → 413 `TOO_LARGE_BINARY`. Sniffed MIME must equal the declared one → `MIME_MISMATCH`.

### Comparison (R-8, I20)

```python
def compare(a: bytes, b: bytes, alignment: Literal["none", "scale-b-to-a"] = "none",
            threshold: int = 0) -> dict   # Comparison-shaped
```

Both images: `exif_transpose`, first frame, RGBA, no colour management. Header dimensions are checked before load and reserved from one `SimilarImagePixelBudget(MAX_RENDITION_WORK_PIXELS)`. Size mismatch with `alignment="none"` → `comparable=false`, `reason="size_mismatch"`, numeric fields `null`, `difference_png` `null`. `scale-b-to-a` → LANCZOS, `scaled_b=true`. Changed = any channel |Δ| > threshold (per-band `ImageChops.difference`, then a max across bands). Counts come from histograms. `mean_abs_delta` is over all four channels, 3 dp. `changed_bbox` is `[left, top, right, bottom]` (exclusive) from `getbbox()` of the changed mask. `profiles_differ` compares the ICC bytes (one present and one absent counts as different). `difference_png` is a heatmap (changed pixels red, unchanged pixels a faded grey of A), downscaled to ≤ 2048 px edge, falling back to 512 px if the data URI exceeds 16 M characters. Wording in code and responses is measured counts only, never "identical" (P-107).

### Compose (`engine_image_compose.py`)

```python
@dataclass(frozen=True)
class CollageLayout: columns: int; cell_width: int; cell_height: int; fit: str; gap: int; padding: int; background: str; format: str

class ImageComposeEngine:
    @staticmethod
    def collage_canvas(count: int, layout: CollageLayout) -> tuple[int, int]     # the exact formula, from DTO
    @staticmethod
    def build_collage(images: Sequence[bytes], layout: CollageLayout, preview_max_edge: int | None = None) -> tuple[bytes, str, tuple[int, int]]
    @staticmethod
    def build_contact_sheets(files: Sequence[tuple[str, bytes]], sheet: ContactSheetLayout) -> tuple[bytes, str, int]   # bytes, media_type, pages
    @staticmethod
    def build_icon_pack(content: bytes, platforms: Sequence[str], fit: str) -> tuple[bytes, list[int]]     # zip, upscaled sizes
```

Collage canvas: `rows = ceil(n / columns)`; `W = 2·padding + columns·cell_width + (columns−1)·gap`; `H = 2·padding + rows·cell_height + (rows−1)·gap`. Over `MAX_SIDE` (10,000) or over 40 MP → `CANVAS_TOO_LARGE` (422), checked from the DTO before any decode. `contain` centres the image inside the cell; `cover` scales to fill and centre-crops. Output has no EXIF. JPEG output over a transparent background flattens onto white and warns. Order of the uploaded parts is the layout order. Preview scales cell, gap and padding by `preview_max_edge / max(W, H)`, output PNG.

Contact sheet: pages A4 (210×297 mm) or Letter (8.5×11 in), rendered at 150 dpi. `capacity = columns·rows`; `pages = ceil(n / capacity)`. Each thumbnail is decoded for its page and fitted to its cell box, so none is retained. PDF output holds every page bitmap at once and is refused (`TOO_LARGE_WORK`) above `CONTACT_SHEET_RETAINED_PAGE_BYTES` (256 MiB); ZIP output encodes each page as it is drawn. Thumbnails use `draft()` for JPEG and count their decoded pixels after reduction against `MAX_RESIZE_BATCH_TOTAL_PIXELS` (400 M). Names: NFC, control characters removed, middle truncation to cell width with `…` (measured with `font.getlength`). Font: `CONTACT_SHEET_FONT_PATH = "assets/fonts/NotoSans-Regular.ttf"`; the sidecar bundles this font under `fonts/`, and `ImageFont.load_default(size)` is a dev-only fallback. `format="pdf"` → Pillow multi-page PDF; `format="png-zip"` → ZIP of `contact-sheet-001.png` …. `show_names=False` draws no text (test: `ImageDraw.text` is never called).

Icon pack: first frame → `exif_transpose` → RGBA. Non-square: `pad` centres on a transparent square of the longer side; `crop` centre-crops to the shorter side. Layout inside the ZIP:
- `web/favicon.ico` (16, 32, 48), `web/favicon-16x16.png`, `web/favicon-32x32.png`, `web/apple-touch-icon.png` (180, flattened on white), `web/android-chrome-192x192.png`, `web/android-chrome-512x512.png`
- `windows/app.ico` (16, 24, 32, 48, 64, 128, 256)
- `macos/icon.iconset/icon_{16,32,128,256,512}x{…}.png` plus `@2x` (sizes 16–1024)

No `.icns`, no manifest (the UI says so). Sizes above the base square edge are upscaled and returned as `upscaled_sizes` (sorted, unique). Platforms selection: the set of folders included.

### Routes (`officekit/routes/image.py`)

Prefix `/api`. All `POST`. Responses 200 (derived, not stored: no `201`/`Location`).

| # | Path | Scope rows | Body cap (bytes) | Accepted parts | Response | Statuses |
| --- | --- | --- | --- | --- | --- | --- |
| R-1 | `/api/image-renditions` | I06, I10, I11, I12, I14 | 64 MiB + 4 MiB | `file`; `operations` (Form, ≤16 KiB, `RenditionRequest`); `format`; `quality`; `preview_max_edge` | image bytes, `Content-Disposition`, `X-OfficeKit-Image-Width/Height`, `X-OfficeKit-Image-Density` | 200, 413, 415, 422 |
| R-2 | `/api/image-rendition-batches` | I14 batch | 64 MiB + 4 MiB | `files` 1–50; same `operations`, `format`, `quality` | ZIP | 200, 413, 415, 422 |
| R-3 | `/api/image-metadata-reports` | I07 | 64 MiB + 4 MiB | `file`; `include_location` bool = false | `MetadataReport` JSON (`response_model`) | 200, 413, 415, 422 |
| R-4 | `/api/image-palettes` | I15 | 64 MiB + 4 MiB | `file`; `count` 1–12 = 6; `alpha_threshold` 1–255 = 128 | `Palette` JSON | 200, 413, 415, 422 |
| R-5 | `/api/data-uris` | I16 encode | 8 MiB + 4 MiB | `file` ≤ 8 MiB (includes `.svg`) | `DataUri` JSON | 200, 413, 415, 422 |
| R-6 | `/api/data-uri-images` | I16 decode | 12 MiB | JSON `DataUriDecodeRequest{data_uri: str max 11,184,900, extra forbid}` | bytes, attachment, `X-Content-Type-Options: nosniff` | 200, 413, 422 |
| R-7 | `/api/icon-packs` | I17 | 64 MiB + 4 MiB | `file`; `platforms` str → list, 1–3 unique from {web, windows, macos}; `fit` pad/crop = pad | ZIP; `X-OfficeKit-Upscaled-Sizes` | 200, 413, 415, 422 |
| R-9 | `/api/image-collages` | I18 | 64 MiB + 4 MiB | `files` 2–50 (order = layout); `layout` (Form ≤4 KiB → `CollageRequest`); `preview_max_edge` | image bytes; `X-OfficeKit-Image-Width/Height` | 200, 413, 415, 422 |
| R-10 | `/api/contact-sheets` | I19 | 128 MiB + 4 MiB | `files` 1–200; `sheet` (Form ≤4 KiB → `ContactSheetRequest`) | PDF or ZIP; `X-OfficeKit-Page-Count` | 200, 413, 415, 422 |
| R-8 | `/api/image-comparisons` | I20 | 64 MiB + 4 MiB | `image_a`, `image_b`; `alignment` none/scale-b-to-a = none; `threshold` 0–255 = 0 | `Comparison` JSON | 200, 413, 415, 422 |

Row numbers R-1…R-10 follow the HLD table row order (routes 1–8 are the HLD rows; R-9 and R-10 are the compose routes, which the HLD lists as rows 7 and 8 under I18/I19. This LLD keeps the HLD path order in the table but numbers the compose rows here.)

`BODY_LIMITS` keys: the exact path strings above. The 64 MiB + 4 MiB caps follow `app.py:MAX_API_UPLOAD_BYTES` and `MAX_MULTIPART_OVERHEAD_BYTES`, which are re-declared as module constants in `routes/image.py` (not imported from `app`).

`EXPOSE_HEADERS = ("X-OfficeKit-Image-Density", "X-OfficeKit-Upscaled-Sizes")`.

Extension allowlist (415 `"Choose a supported image file."`): `.jpg .jpeg .png .webp .bmp .tif .tiff .gif`. `/api/data-uris` also accepts `.svg`. Filename handling: basename of `file.filename` after replacing backslashes; download names go through `content_disposition_attachment` (P-015).

Strict DTOs (pydantic, `extra="forbid"`, `StrictInt`, `StrictStr`, `Literal`):
- `RenditionOperation` discriminated on `type`: `rotate{degrees_cw: 90|180|270}`, `flip{axis: horizontal|vertical}`, `grayscale{}`, `adjust{brightness, contrast, saturation: −100..100}`, `border{width 0–2000, corner_radius 0–5000 = 0, fill ^#[0-9A-F]{6}$ = #FFFFFF, fill_opacity 0–100 = 100}`, `density{x, y: 1–2400, unit: inch|cm}`. A model validator rejects more than one `density`, and a `density` that is neither last nor alone (the HLD rule), and any list outside 1–8 entries.
- `CollageRequest{columns 1–10, cell_width/cell_height 16–4000, fit contain|cover, gap 0–200, padding 0–400, background ^#[0-9A-F]{6}$|transparent, format png|jpeg|webp}`.
- `ContactSheetRequest{page a4|letter, orientation portrait|landscape, columns 1–10, rows 1–20, show_names bool = true, format pdf|png-zip}`.
- `DataUriDecodeRequest{data_uri}`.
- Response models: `MetadataReport`, `Palette`, `DataUri`, `Comparison`.

Form field validation uses `Form(..., ge=, le=, max_length=)`. `quality` uses `Form(None, ge=1, le=100)` (P-014). Every JSON-in-form field is parsed with `json.loads` (`object_pairs_hook` rejects duplicate keys) and then `model_validate`. Caps are checked before parsing.

### Error handling

Route decorator `_guarded` (applied to every handler, `functools.wraps` so FastAPI reads the original signature) converts:

| Source | HTTP | `detail` | `code` |
| --- | --- | --- | --- |
| extension not allowed | 415 | "Choose a supported image file." | `UNSUPPORTED_MEDIA` |
| `UploadTooLargeError` (from `read_bounded_upload`) | 413 | "The image exceeds the supported 64 MiB input limit." (route-specific text) | `TOO_LARGE_INPUT` |
| `ImageOutputLimitError` | 413 | "The output exceeds the supported 64 MiB limit." | `TOO_LARGE_OUTPUT` |
| `ImageWorkLimitError` | 413 | "The image requires too much processing; select fewer or smaller images." | `TOO_LARGE_WORK` |
| `ImageToolInputError` (any code) | 422 | its `public_message` | its `code` |
| `ConversionInputError` (other) | 422 | `ConversionInputError.public_message` | `INVALID_IMAGE` |
| DTO/Form validation | 422 | FastAPI default (unchanged) | — |

Body shape for the decorator-produced errors: `{"detail": "<message>", "code": "<CODE>"}` through `JSONResponse`. The decorator must never echo parser text, paths or stack traces (P-013). Unexpected exceptions propagate to the app's generic 500 handler.

Image bytes, EXIF values and coordinates are never logged, stored in History or placed in the result store.

### Test hooks

- Engine fixtures are generated in memory with Pillow (`Image.new`, `putpixel`, `save(exif=...)`), with no network and no on-disk fixtures except as noted in P-116 (in-memory bytes are fine for `TestClient`, which takes bytes directly).
- Limit boundaries: each limit is a class attribute on `FileConverterEngine` or a module constant in `engine_image_tools`; tests patch them with `unittest.mock.patch.object` to exercise the boundary cheaply (P-047 style).
- The route tests mount `officekit.routes.image.router` on `FastAPI()`. A test asserts that `BODY_LIMITS` covers every `POST` path in `router.routes`, and that `EXPOSE_HEADERS` includes the two new headers.
- `ImageDraw.text` is patched to count calls in the names-off contact-sheet test.

## Commit plan

Each commit is a red→green TDD step (test first, then code) and ends with the focused tests passing.

1. `docs(lld): pending image tools back-end LLD 1.0.0` — this file plus the `VERSION-HISTORY.md` row. Refs: all HLD rows.
2. `feat(image): load guard and rotate/flip, density, grayscale, adjust, border renditions` — `engine_image_tools.py` part 1 plus its tests. Refs: R-1 I06, I10, I11, I12, I14 (engine), R-2 engine helper; P-040, P-047, P-049, P-046/P-048.
3. `feat(image): EXIF metadata report with location withheld by default` — `metadata_report`, tests for GPS known fixture, Unicode, malformed GPS IFD, unchanged source hash, default no coordinates. Refs: I07, R-3; P-015 not applicable (engine only).
4. `feat(image): deterministic dominant palette` — `palette`, tests for solid, 70/30, transparent exclusion, repeat run. Refs: I15, R-4.
5. `feat(image): binary-safe data URI encode and decode` — `encode_data_uri`, `decode_data_uri`, `sniff_mime`, tests for round trip (SHA-256), MIME mismatch, bad base64, oversized, SVG. Refs: I16, R-5, R-6.
6. `feat(image): collage, contact sheet and icon pack engines` — `engine_image_compose.py`, tests for canvas formula, overflow, order, names truncation, 180-image pagination, icon ZIP names and sizes, ICO sizes, alpha. Refs: I17, I18, I19, R-7, R-9, R-10.
7. `feat(image): side-by-side comparison with honest thresholds` — `compare`, tests for identical (`changed_pixels=0`, no "identical" wording), one changed pixel with bbox, size mismatch `comparable=false`, scale-to-match. Refs: I20, R-8.
8. `feat(image): image tool routes with strict DTOs and body caps` — `officekit/routes/image.py` plus `tests/image_routes_unittest.py` (bounds edges min−1/min/max/max+1 for each numeric field, 415, 413 before parse, `detail`+`code`, `Content-Disposition` for Unicode and path names, headers exposed, `include_location=false` has no coordinates, original bytes unchanged). Refs: all R-rows.
9. `docs(versions): bump image LLD to match delivered back end` — only if the implementation changes the LLD (version bump plus history row). Otherwise omitted.

## Verification

- Focused: `python3 -m pytest -q tests/engine_image_tools_unittest.py tests/engine_image_compose_unittest.py tests/image_routes_unittest.py tests/test_api_contract_unittest.py tests/test_tool_slots_unittest.py tests/test_image_resize_api.py`.
- Full `npm test` and the UI gate belong to the integrator at merge; phase 1 does not change `index.html` or `assets/*`.

## Open items (carried from the HLD)

- Open question 2 (contact-sheet upload cap) is implemented as the HLD's 200 files / 128 MiB.
- Open question 3 (Noto Sans) is resolved: the sidecar bundles `NotoSans-Regular.ttf` under `fonts/` (`scripts/build-backend-sidecar.mjs`), and the engine reads that copy first. `load_default` is a dev-only fallback.
- Open question 5 is answered by the foundation's `slice_expose_headers()`.
- The `_map_frames` extraction described in the HLD is deferred (see Decisions).
