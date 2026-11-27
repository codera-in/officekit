# Pending tools — PDF slice (slice 6) — back-end LLD

**Version:** 1.0.3 · 2026-10-22 · Round 3: the image batch budget is 150 M pixels, not 400 MP (code-reviewer). Earlier: 1.0.2 · Round 1: route names, Tamil decision (owner) and the `preview_page` 0 sentinel. The 1.0.1 watermark body cap (76 MiB) is unchanged.

Parent: `docs/hld/pending-tools-pdf.md` (the contract; every row cited below is an HLD §3/§4 row). Foundation: `docs/hld/pending-tools-foundation.md` (route slot contract, `BODY_LIMITS` / `EXPOSE_HEADERS`). Roadmap rows: `docs/RELEASE-123-TOOLS.md` :84-95 (P06, P08, P10, P12, P13, P15, P16, P17).

Phase 1 delivers the Python engines, the router and the tests. Phase 2 (catalogue `officekit/tool_catalog/pdf.py`, `assets/officekit-slice-pdf-tools.js`, UI tests) is not part of this document.

## 1. File map

| File | Status | Purpose | HLD ref |
| --- | --- | --- | --- |
| `officekit/engines/engine_pdf_tool_common.py` | new (helper, not in HLD §7) | Shared source open with the 1–2,000 page bound, bounded save, inherited `/Rotate` resolution, mm/in/pt conversion. Keeps the five engine modules from importing each other. | HLD §2 reuse |
| `officekit/engines/engine_pdf_page_tools.py` | new | `PageToolsEngine.rotate_pages`, `PageToolsEngine.resize_pages`. | HLD §4 row 1, §3 rows `page-rotations`, `page-sizes` |
| `officekit/engines/engine_pdf_stamp.py` | new | `PdfStampEngine`: watermark (text/image), page numbers, and the engine-rendered previews. | HLD §4 row 2, §3 rows `watermark*`, `page-numbers*` |
| `officekit/engines/engine_pdf_inspect.py` | new | `PdfInspectEngine.inspect`, returns a typed `PdfInspectionResponse`-shaped dict. | HLD §4 row 3, §3 `inspection` |
| `officekit/engines/engine_pdf_grayscale.py` | new | `PdfGrayscaleEngine`: vector conversion with refusal, raster mode. | HLD §4 row 4, §3 `grayscale` |
| `officekit/engines/engine_pdf_flatten.py` | new | `PdfFlattenEngine.flatten`: forms, annotations or both, with structural read-back. | HLD §4 row 5, §3 `flatten` |
| `officekit/engines/engine_images_to_pdf.py` | new | `ImagesToPdfEngine.build`: ordered image batch to PDF. | HLD §4 row 6, §3 `image-pdfs` |
| `officekit/routes/pdf_tools.py` | existing stub, replaced | `router`, `BODY_LIMITS`, `EXPOSE_HEADERS`, the ten routes and their DTOs. | HLD §3 |
| `tests/pdf_tool_fixtures.py` | new (test helper) | Builds PDFs, PNGs and JPEGs in code. Imported by the test files below. | HLD §7 "fixtures generated in tests" |
| `tests/test_pdf_tools_page_tools_unittest.py` | new | P06 and P15 engine cases. | HLD §1 |
| `tests/test_pdf_tools_stamp_unittest.py` | new | P12, P13 and preview engine cases. | HLD §1 |
| `tests/test_pdf_tools_inspect_unittest.py` | new | P10 engine cases. | HLD §1 |
| `tests/test_pdf_tools_grayscale_unittest.py` | new | P16 engine cases. | HLD §1 |
| `tests/test_pdf_tools_flatten_unittest.py` | new | P17 engine cases. | HLD §1 |
| `tests/test_pdf_tools_images_unittest.py` | new | P08 engine cases. | HLD §1 |
| `tests/test_pdf_tools_api_unittest.py` | new | Every route: DTO bounds, body cap, output cap, error codes, headers, no source mutation. | HLD §8 API |
| `docs/VERSION-HISTORY.md` | edited | One row for this LLD. | `.claude/se-rules/versioning.md` |

Not touched: `app.py`, `engine_comms.py`, the existing PDF engines, `officekit/tool_catalog/*`, `index.html`, `assets/*`, `dist-ui/*`, `requirements.txt`, `API-CONTRACT.md`, `docs/TOOL-GUIDE.md`, `docs/FIRST-MAC-RELEASE.md`.

## 2. Reuse and imports

| Need | Source | Note |
| --- | --- | --- |
| Output cap, 64 MiB | `AdvancedPdfEngine.MAX_OUTPUT_BYTES` (`engine_pdf_advanced.py:24`) | Each engine class sets `MAX_OUTPUT_BYTES = AdvancedPdfEngine.MAX_OUTPUT_BYTES` and reads it at call time, so tests can patch it. |
| Page limit 2,000 | `AdvancedPdfEngine.MAX_PAGE_MANAGEMENT_PAGES` | Over-limit input → `ValueError` → 422. |
| Bounded writer, cap error | `BoundedPdfBuffer`, `PdfOutputLimitError`, `PDF_OUTPUT_LIMIT_ERROR` (`engine_pdf_security.py`) | Route maps `PdfOutputLimitError` → 413. |
| Range grammar | `parse_page_ranges` (`engine_pdf_ranges.py`, via `AdvancedPdfEngine.parse_page_ranges`) | Strict: no sorting, no dedupe, no silent clamp (P-029). Empty string means all pages, which is the only exception. |
| Raster budgets | `PdfImageExportEngine.MAX_PAGES` (100), `MAX_TOTAL_PIXELS` (120 MP), `MAX_PAGE_PIXELS` (20 MP) (`engine_pdf_images.py`) | Used by grayscale raster mode. Checked before render. |
| JSON options parser | `DevToolsEngine._parse_json` (`engine_devtools.py:49`) | Rejects duplicate keys and non-finite numbers. The route also checks the 4,096-byte `Form` limit. |
| Attachment name | `content_disposition_attachment` (`engine_file_responses.py`) | P-015. |
| Upload read | `read_bounded_upload` (`engine_uploads.py`) | **`read_api_upload`, `MAX_API_UPLOAD_BYTES` and `PDF_INPUT_ERROR_MESSAGE` exist only in `app.py`.** The route cannot import them without importing `app`, so the router defines a local `read_pdf_upload` that calls `read_bounded_upload` with its own 64 MiB constant, and a local copy of the fixed 422 message text. The final reply flags this. |
| Body cap middleware | `RequestBodyLimitMiddleware` (`engine_uploads.py`) | `BODY_LIMITS` is merged by the integrator (already wired in `officekit/routes/__init__.py`). |

## 3. Interfaces

All engine methods are classmethods or staticmethods that take `bytes` and return `bytes` (or a small typed result). None write to disk. None log input content.

```text
PageToolsEngine.rotate_pages(content: bytes, angle: int, page_ranges: str) -> tuple[bytes, int]
    # angle in {90,180,270}; page_ranges "" = all pages. Returns (pdf, affected_count).
PageToolsEngine.resize_pages(content: bytes, *, target: PageSize | None, preset: str,
                             orientation: str, mode: str, anchor: str,
                             page_ranges: str) -> tuple[bytes, float]
    # Returns (pdf, min_applied_scale). PageSize = (width_pt, height_pt) displayed size.

PdfStampEngine.watermark(content: bytes, spec: WatermarkSpec) -> bytes
PdfStampEngine.watermark_preview(content: bytes, spec: WatermarkSpec, preview_page: int) -> bytes  # PNG
PdfStampEngine.page_numbers(content: bytes, spec: PageNumberSpec) -> tuple[bytes, list[int]]
    # Returns (pdf, overlap_pages_1_based).
PdfStampEngine.page_numbers_preview(content, spec, preview_page) -> tuple[bytes, list[int]]  # PNG

PdfInspectEngine.inspect(content: bytes) -> dict  # matches PdfInspectionResponse

PdfGrayscaleEngine.convert(content: bytes, method: str, dpi: int | None) -> tuple[bytes, str]
    # Returns (pdf, method_used). Raises GrayscaleRefusedError (code "grayscale_needs_raster").

PdfFlattenEngine.flatten(content: bytes, scope: str, acknowledge_signature_loss: bool)
    -> tuple[bytes, int, int]   # (pdf, flattened_fields, flattened_annotations)
    # Raises FlattenRefusedError: code "signature_ack_required" (409), "xfa_unsupported" (422),
    # "appearance_missing" (422).

ImagesToPdfEngine.build(images: list[bytes], page_size: str, orientation: str, fit: str,
                        margin_mm: int) -> bytes
    # Raises ImageInputError(index) with the fixed copy "Image {n} could not be read.".
```

Error types (all subclass `ValueError` except the bounded-writer error, which is `PdfOutputLimitError`): `GrayscaleRefusedError`, `FlattenRefusedError`, `ImageInputError`. A route maps `ValueError`, `pikepdf.PdfError`, `pikepdf.PasswordError` and `OSError` to 422, except where a typed refusal names its own status.

Source-open helper (`engine_pdf_tool_common.open_source_pdf(content)`): rejects non-bytes and empty input with `ValueError`; opens with pikepdf (`PasswordError` for user-password encryption propagates); rejects zero pages and pages above `MAX_PAGE_MANAGEMENT_PAGES` with `ValueError`. Source bytes are never written back.

## 4. Behaviour decisions (where the HLD leaves room)

**Rotate (P06, HLD §4).** For each selected page, resolve the inherited `/Rotate` from the page or its `/Parent` chain (default 0), write it onto the page dict, then call `Page.rotate(angle, relative=True)`, which normalises mod 360. Content streams are untouched; the test asserts their raw bytes are equal.

**Resize (P15, HLD §4).** Presets are displayed sizes in points: A4 595.2756×841.8898, A5 419.5276×595.2756, Letter 612×792, Legal 612×1008, Tabloid 792×1224. Custom values convert from mm/in/pt, then must be in 72–14,400 pt.
- `orientation`: `keep` gives each page the target orientation that matches its own displayed orientation. `portrait`/`landscape` force the target.
- Displayed size is unrotated and swapped for `/Rotate` 90/270 before scaling.
- Scale (`mode=scale`): `s = min(tw/cw, th/ch)`, content centred in the target. Canvas (`mode=canvas`): `s = 1`, translated by the anchor only (`0`, `0.5` or `1` of the free space per axis). The anchor is ignored in scale mode.
- Each selected page: the source MediaBox becomes a Form XObject (`as_form_xobject`, `BBox` = source MediaBox so content outside the crop is retained in the file). The page content becomes `q s 0 0 s tx ty cm /Fx Do Q` with `tx = ox − s·cx0`, `ty = oy − s·cy0`, where `(cx0, cy0)` is the source CropBox origin and `(ox, oy)` the offset of the scaled crop in the target. MediaBox and CropBox become the target rectangle. `TrimBox`, `BleedBox`, `ArtBox` are removed.
- Annotations: `/Rect` and `/QuadPoints` pass through the same `[s 0 0 s tx ty]` matrix.
- `X-OfficeKit-Scale` is the minimum `s` over the selected pages (4 dp), which is the honest factor when pages differ.

**Stamps (P12, P13, HLD §4).** One reportlab overlay document is built with one page per stamped source page, sized to that page's displayed CropBox. The overlay page is placed as a Form XObject with a counter-rotation matrix per `/Rotate`. For displayed coordinates `(u, v)` and unrotated crop size `(w, h)` with origin `(cx0, cy0)`:

| Rotate | Matrix `[a b c d e f]` |
| --- | --- |
| 0 | `[1 0 0 1 cx0 cy0]` |
| 90 | `[0 1 -1 0 w+cx0 cy0]` |
| 180 | `[-1 0 0 -1 w+cx0 h+cy0]` |
| 270 | `[0 -1 1 0 cx0 h+cy0]` |

Opacity is `setFillAlpha(opacity/100)`, so the ExtGState carries `/ca`. Text: the Helvetica built-in is used while `WATERMARK_FONT_PATH = "assets/fonts/NotoSans-Regular.ttf"` is absent. Only printable ASCII (0x20–0x7E) is accepted. Anything else is 422 before drawing, so there are no missing glyphs. When the Noto file exists, coverage is checked with `TTFont.face.charToGlyph`. Tamil, CJK and other complex scripts are out of scope (owner decision 2026-10-22) and return the fixed 422.

Image watermark: header size checked before decode (≤16 MP, Pillow lazy open); PNG alpha becomes an SMask through reportlab `mask="auto"`.

Page numbers: `start` is the value of the first numbered page. Default `count_skipped=false` numbers the selected pages consecutively from `start`. `count_skipped=true` numbers by document position, so skipped pages consume numbers. `total` is the selected-page count, or the document page count when `count_skipped=true`. Roman formats need values 1–3,999; out of range is 422. Template tokens are `{n}` and `{total}` only; any other brace text is 422.

Overlap (numbers): object bounds come from pypdfium2 `get_objects` (≤10,000 objects per page, otherwise the page is reported as overlapping rather than silently passed), transformed into unrotated space, and intersected with the stamp box. The header value is a compact range list (≤256 chars, `…` appended when cut).

Previews: the full stamp path runs (P-164: the preview is the output path), then pypdfium2 renders one page at a long edge ≤800 px. The PNG must be ≤4 MiB.

**Inspect (P10, HLD §4).** pikepdf read-only. Text strings: UTF-16BE with BOM, UTF-8 with BOM, otherwise the PDFDocEncoding table for 0x80–0x9F (with Latin-1 for the rest). Dates parse to ISO 8601 when they match `D:YYYYMMDDHHmmSSOHH'mm'`; otherwise the raw value is shown. XMP comes from `open_metadata(read_only_mode=True)` simple entries (≤128). Page sizes group by (MediaBox w, h, `/Rotate`) with `count`, ≤50 groups plus `other_count`. Forms: `fields` are the terminal field nodes, `signature_fields` are `/FT /Sig`, `signed` means a signature field with `/V`, and `xfa` means `/AcroForm/XFA` is present. Annotations are the non-widget count.

**Grayscale (P16, HLD §4).** Honest rule: the whole conversion is computed in memory first. If any construct cannot be converted exactly, the engine raises `GrayscaleRefusedError` and writes nothing. Vector mode:
- Operators: `rg`/`RG` and `k`/`K` become `g`/`G` with BT.601 luma (CMYK via the naive RGB conversion). `cs`/`CS` with DeviceRGB, DeviceCMYK, ICCBased N=3/4 or Indexed with an RGB/CMYK base become DeviceGray, and the following `sc`/`scn`/`SC`/`SCN` values are converted. Indexed palettes are converted per index.
- Refused: `sh`, Pattern, Separation, DeviceN, Lab, shading resources, inline images in colour spaces, JPX and JBIG2 images.
- Walked: page content, Form XObjects, Type3 CharProcs, and annotation normal appearance streams.
- Images: check `/Width × /Height ≤ 40 MP` before decode (P-165). DCT sources are re-encoded as JPEG q90. Others are re-encoded as Flate DeviceGray. SMask is kept.
- Raster mode: pypdfium2 `render(grayscale=True)` at 150 or 300 DPI, one image per page at original MediaBox size, `/Rotate` copied, image counter-rotated so the page displays as the source did. Limits are `PdfImageExportEngine.MAX_PAGES` and `MAX_TOTAL_PIXELS`. The response says text is no longer selectable.
- `dpi` given with `method=vector` is 422.

**Flatten (P17, HLD §4).** Order of checks: XFA present → 422 `xfa_unsupported`. Any signed field (`/FT /Sig` with `/V`) without `acknowledge_signature_loss` → 409 `signature_ack_required`. Missing appearance: call `generate_appearance_streams()` once if `NeedAppearances` or any widget lacks `/AP /N`; still missing → 422 `appearance_missing`. Widget appearance: state chosen by `/AS` when `/N` is a dictionary, and an absent state is an unchecked box with nothing to draw. Mapping: the spec 12.5.5 BBox × Matrix → Rect, drawn as `q sx 0 0 sy tx ty cm /Fx Do Q`. Hidden (flag bit 2) and NoView (bit 6) annotations are removed without drawing. Popups are removed with their parent. Link annotations (no visual) are removed. Scope `forms` removes widgets and `/AcroForm`; `annotations` removes non-widget annotations; `all` does both.

Structural verification, required by P-071 and P-070: after building the output, the engine reopens it and asserts that no `/AcroForm` exists in scope `forms`/`all`, no Widget annotation exists, and no non-widget annotation remains in scope `annotations`/`all`. A failed self-check raises an internal error (500), never a partial file.

**Images to PDF (P08, HLD §4).** Each image: header read (`Image.open`, format allowlist PNG/JPEG/WebP/TIFF/GIF/BMP), EXIF orientation read from the header, and a `w·h ≤ 40 MP` check before decode. The total over the batch is ≤150 M pixels, checked from the headers before any decode (`MAX_TOTAL_PIXELS`). EXIF rotation with `ImageOps.exif_transpose` after decode. Alpha composited on white. First frame only for GIF/TIFF. A JPEG with no alpha and no EXIF rotation is embedded undecoded through reportlab's `ImageReader` (DCT pass-through). Page sizes: `a4`, `letter`, `legal` (from the table above), or `image` (the image size at its DPI, default 96, clamp 1–2,400). `orientation=auto` picks the page orientation that matches the image; `portrait` and `landscape` force it. Fit: `contain` (centred inside the margin box), `cover` (fills the margin box, clipped), `actual` (image DPI, centred, clipped to the page). Margins are `margin_mm` → points. Output goes through `BoundedPdfBuffer`.

## 5. Route contract (summary of HLD §3, implemented in `routes/pdf_tools.py`)

| Route | Body cap (upload + 4 MiB overhead) | Success | Headers (all in `EXPOSE_HEADERS`) |
| --- | --- | --- | --- |
| `POST /api/pdf/page-rotations` | 68 MiB | `application/pdf`, `<stem>-rotated.pdf` | `X-OfficeKit-Affected-Pages`, `X-OfficeKit-Page-Count` |
| `POST /api/pdf/image-pdfs` | 68 MiB | `application/pdf`, `images.pdf` | `X-OfficeKit-Page-Count` |
| `POST /api/pdf/inspections` | 68 MiB | `application/json` | — |
| `POST /api/pdf/watermarks` | 76 MiB (64 PDF + 8 image + 4 overhead) | `application/pdf`, `<stem>-watermarked.pdf` | `X-OfficeKit-Page-Count` |
| `POST /api/pdf/watermarks/previews` | 76 MiB | `image/png` | — |
| `POST /api/pdf/page-numbers` | 68 MiB | `application/pdf`, `<stem>-numbered.pdf` | `X-OfficeKit-Overlap-Pages`, `X-OfficeKit-Page-Count` |
| `POST /api/pdf/page-numbers/previews` | 68 MiB | `image/png` | `X-OfficeKit-Overlap-Pages` |
| `POST /api/pdf/page-sizes` | 68 MiB | `application/pdf`, `<stem>-resized.pdf` | `X-OfficeKit-Scale`, `X-OfficeKit-Page-Count` |
| `POST /api/pdf/grayscale-conversions` | 68 MiB | `application/pdf`, `<stem>-grayscale.pdf` | `X-OfficeKit-Grayscale-Method`, `X-OfficeKit-Output-Input-Ratio`, `X-OfficeKit-Page-Count` |
| `POST /api/pdf/flattenings` | 68 MiB | `application/pdf`, `<stem>-flattened.pdf` | `X-OfficeKit-Flattened-Fields`, `X-OfficeKit-Flattened-Annotations`, `X-OfficeKit-Page-Count` |

The HLD §3 "body cap" column lists the upload part total. The body cap adds `MAX_MULTIPART_OVERHEAD_BYTES` (4 MiB), which is what `RequestBodyLimitMiddleware` enforces before parse. This is a clarification, not a change of the contract.

Errors, common to all routes: 413 for body cap or `PdfOutputLimitError` (`PDF_OUTPUT_LIMIT_ERROR`, no body); 422 for DTO failure (pydantic, through the 422 handler) or the fixed `PDF_INPUT_ERROR_MESSAGE` for corrupt, empty, encrypted, zero-page or over-limit input. Typed refusals: grayscale 422 `{"detail": {"code": "grayscale_needs_raster", "message": "..."}}`; flatten 409 and 422 with the same detail shape; from-images 422 `"Image {n} could not be read."`. Watermark 422 `"The watermark text uses characters the bundled font can't draw."`. Filenames: `content_disposition_attachment(f"{stem}{suffix}")`, where the stem is the upload's basename.

Options: a `Form` string `options`, ≤4,096 bytes, parsed by `DevToolsEngine._parse_json`, then `Model.model_validate(parsed, strict=True)` with `extra="forbid"`. Route-level DTO classes live in `pdf_tools.py`.

## 6. Test hooks

- Engine classes read `MAX_OUTPUT_BYTES` at call time. API and engine tests patch it to a small value (e.g. 2 KiB) to assert the cap stops serialisation and the route returns 413 with no body.
- `PdfImageExportEngine` budgets are patched down in the grayscale raster test to exercise the refusal.
- Fixtures (`tests/pdf_tool_fixtures.py`) build PDFs with pikepdf and reportlab, PNG/JPEG with Pillow, and an AcroForm fixture with a text field, a checkbox and a signed field. No committed sample PDFs.
- Render checks use pypdfium2; text checks use pdfplumber (already pinned in `requirements.txt`).
- Source bytes are compared before and after each call (`bytes` are immutable, so the check also asserts the route cannot change the caller's view: upload bytes and the re-read source must hash equal).

## 7. Known gaps (recorded, not hidden)

- Watermark Unicode: Latin beyond ASCII, Greek and Cyrillic use the bundled `assets/fonts/NotoSans-Regular.ttf` (foundation). Tamil and other complex scripts are refused with the fixed 422 (owner decision 2026-10-22). `reportlab[shaping]` is not used.
- Grayscale: Type3 CharProcs and annotation appearances are converted, but Pattern and shading constructs refuse. Full CMYK/ICC colour management is not claimed (naive RGB conversion, as stated in the HLD).
- Flatten: XFA, digital signatures and form JavaScript are not preserved or validated.
- Page-number overlap is a bounding-box check, not glyph-level.
- The Noto file path is a named constant. The app-only `read_api_upload` / `PDF_INPUT_ERROR_MESSAGE` duplication is recorded above and in the final reply.

## 8. Commit plan

Each step is a Conventional Commit, ends with the required trailers, and is backed by a failing test first.

| # | Commit | HLD contract rows |
| --- | --- | --- |
| 1 | `docs(pdf): pending tools PDF back-end LLD 1.0.0` (this file, VERSION-HISTORY row) | §1–§5 |
| 2 | `feat(pdf): rotate and resize PDF pages engine` (common helper, page tools, tests) | §4 rotate, resize; §1 P06, P15 |
| 3 | `feat(pdf): PDF metadata inspection engine` | §4 inspect; §3 `inspection`; §1 P10 |
| 4 | `feat(pdf): watermark and page-number engines with previews` | §4 stamps; §3 `watermark*`, `page-numbers*`; §1 P12, P13 |
| 5 | `feat(pdf): grayscale engine with honest rasterization` | §4 grayscale; §3 `grayscale`; §1 P16 |
| 6 | `feat(pdf): flatten forms and annotations engine` | §4 flatten; §3 `flatten`; §1 P17 |
| 7 | `feat(pdf): images to PDF engine` | §4 images; §3 `image-pdfs`; §1 P08 |
| 8 | `feat(pdf): PDF tool routes with bounds and headers` (routes, API tests, BODY_LIMITS, EXPOSE_HEADERS) | §3 all rows, §5 |
