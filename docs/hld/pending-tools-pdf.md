# Pending tools — PDF slice (slice 6) — HLD

**Version:** 1.0.4 · 2026-10-22 · Round 4: `doneLine` statuses follow the owner's answer of 2026-10-22 (PM-9, UX-21); the image-pdfs budget wording is fixed (CR-10). Earlier: 1.0.3 · Round 3: §5 names `limitFor` and `doneLine`; the images limit line comes from the slice (ARCH-5); the batch budget is 150 M pixels, not 400 MP (code-reviewer). Earlier: 1.0.2 · Round 2: §5 rewritten as the implemented shell and slice contract (ARCH-9). Earlier: 1.0.1 · Round 1: plural-noun route names, Tamil removed (owner decision), nav and glue contract recorded (ARCH-4), `preview_page` 0 sentinel.

Status: draft for review. Mock: `design/mocks/pending-pdf.html` (not yet approved). Parent: `docs/hld/pending-tools-and-ergonomics.md`, ADR 2026-10-22 in `docs/ARCHITECTURE.md`, requirements `review/pending-tools-slices/requirements.md`.

## 1. Scope

Eight new PDF workbench operations, development-only until slice 7 installed acceptance. Depth and verification cases come from `docs/RELEASE-123-TOOLS.md` :84-95.

| ID | Op key / tool ID | Depth delivered | Verification cases (automated) |
| --- | --- | --- | --- |
| P06 | `rotate` / `pdf_rotate_pages` | Real page `/Rotate` (90/180/270, relative), selected or all pages; thumbnail preview | Inherited and existing `/Rotate`, mixed sizes, apply twice (90+90=180, 4×90=0), rendered orientation, content stream bytes unchanged |
| P08 | `images-to-pdf` / `pdf_from_images` | Ordered batch 1–200 images; page size, orientation, margin, fit | Mixed orientation, EXIF orientation 6/8, alpha → white, 200-image batch, DPI for actual size, page count and order by pixel signature |
| P10 | `metadata-view` / `pdf_metadata_view` | Read-only docinfo (standard + custom), XMP, page sizes, form/annotation summary; absent fields listed | Known docinfo/XMP fixture, Unicode (UTF-16BE and PDFDocEncoding), absent vs empty, malformed date shown raw, source unchanged |
| P12 | `watermark` / `pdf_watermark` | Text or image; position/tile, opacity, angle, size, color, page ranges; engine-rendered preview | Latin, Greek and Cyrillic text drawn; Tamil, CJK and emoji refused with the fixed 422; portrait/landscape/rotated pages, PNG alpha kept, exact range, ExtGState `ca` equals opacity, source unchanged |
| P13 | `page-numbers` / `pdf_page_numbers` | Formats `1`, `Page 1`, `Page 1 of N`, roman lower/upper, custom template; start, position, margin, range, count-skipped | Roman, template tokens, skipped pages + start offset, CropBox offset and `/Rotate` upright placement, overlap detection reports pages |
| P15 | `resize-pages` / `pdf_resize_pages` | A4/A5/Letter/Legal/Tabloid/custom (mm/in/pt); explicit Scale-to-fit vs Change-canvas; anchor | A4/Letter/custom, unit conversion, aspect-preserving scale, output Media/CropBox, annotation `/Rect` moved with content, render dimensions |
| P16 | `grayscale` / `pdf_grayscale` | Vector-preserving conversion with honest refusal; explicit Rasterize alternative | Color vector + image fixture → every rendered pixel R=G=B; text still extractable (vector); ICC/Indexed handled; shading → 422 code; raster mode text gone + size reported |
| P17 | `flatten` / `pdf_flatten` | Forms, annotations or both; signature and XFA guards; irreversible warning | AcroForm text/checkbox/choice values visible in rendered pixels and page text; no `/AcroForm`, no Widget annots (P-071: structure, not render only); signed field → 409 without ack; XFA → 422 |

Out of scope: page labels (`/PageLabels`) writing, CJK/Arabic watermark fonts, PDF/A, OCR, secure removal of content outside a resized canvas.

## 2. Reuse vs new

- **Reuse:** `read_api_upload` + `RequestBodyLimitMiddleware`, `BoundedPdfBuffer`/`PdfOutputLimitError` (64 MiB), `PDF_INPUT_ERROR_MESSAGE`/`PDF_OUTPUT_LIMIT_ERROR`, `content_disposition_attachment` (P-015), strict `engine_pdf_ranges.parse_page_ranges` (P-029), `DevToolsEngine._parse_json` duplicate-key-rejecting JSON, `/api/pdf/page-thumbnails` for Rotate/Resize previews, `engine_pdf_images` pixel budgets and pdfium handle hygiene, workbench drop zone/options/preview/dock, Reorder-pages keyboard pattern for image order, no Tamil font is bundled (Tamil is out of scope, owner decision 2026-10-22).
- **Not duplicated:** editor object rotate (`engine_pdf_editor.py:380-391`) stays an editor feature; `/api/convert/image` single image → PDF stays; `/api/pdf/metadata` removal stays (View metadata links to it).
- **New:** five engine modules, one router, one JS registration module, one bundled Latin/Greek/Cyrillic font (open question 2).
- **Nav and glue (ARCH-4, option b):** the PDF navigation stays hand-written in `index.html`. The contract between the shell and the slice is `window.OfficeKitPdfSlice`: `renderWorkbench`, `syncSelection`, `runWorkbench`, `dockFor`, `factsLine`, `copyReport`, `renderJsonReport`, `schedulePreview` and `loadFlattenFacts`. The shell passes the current tool, files and callbacks; the module owns requests, validation and option rendering.

## 3. Contract surface

All routes `POST`, multipart, in `officekit/routes/pdf_tools.py`. Every route takes `file` (one PDF, ≤ 64 MiB) except P08, plus `options`: a JSON string Form field ≤ 4,096 bytes parsed with duplicate-key rejection, then `Model.model_validate(..., strict=True)` with `extra="forbid"`. Body cap = upload cap + `MAX_MULTIPART_OVERHEAD_BYTES`, enforced before parse. Common statuses: **200**; **413** body cap or output > 64 MiB (`PDF_OUTPUT_LIMIT_ERROR`, no partial body); **422** DTO failure or `PDF_INPUT_ERROR_MESSAGE` for corrupt/empty/encrypted/>2,000-page input (no parser text, P-016/P-013); **500** generic safe handler. Common headers: `Content-Disposition` from the sanitized source stem + suffix, `X-OfficeKit-Page-Count`.

| Route | `options` fields (bounds) | Response | Extra statuses / headers | Body cap |
| --- | --- | --- | --- | --- |
| `/api/pdf/page-rotations` | `angle` ∈ {90,180,270}; `page_ranges` str ≤ 4,096 ("" = all) | `application/pdf` `<stem>-rotated.pdf` | `X-OfficeKit-Affected-Pages` | 64 MiB |
| `/api/pdf/image-pdfs` | parts `files[]` 1–200, each ≤ 40 MP, allowlist PNG/JPEG/WebP/TIFF/GIF/BMP; `page_size` ∈ {a4,letter,legal,image}; `orientation` ∈ {auto,portrait,landscape}; `fit` ∈ {contain,cover,actual}; `margin_mm` int 0–50 | `application/pdf` `images.pdf` | 422 `"Image {n} could not be read."` (index only); total decoded ≤ 150 M pixels | 64 MiB total |
| `/api/pdf/inspections` | none | `application/json` `PdfInspectionResponse` | — | 64 MiB |
| `/api/pdf/watermarks` | `kind` ∈ {text,image}; `text` NFC 1–200 chars, no C0/C1 controls; `font_size` 8–144; `color` `#RRGGBB`; `opacity` int 5–100; `angle` int −90..90; `position` ∈ {center,tile,top-left,top-center,top-right,bottom-left,bottom-center,bottom-right}; `page_ranges` ≤ 4,096; optional part `image` PNG/JPEG ≤ 8 MiB, ≤ 16 MP, required iff `kind=image` | `application/pdf` `<stem>-watermarked.pdf` | 422 `"The watermark text uses characters the bundled font can't draw."` | 72 MiB |
| `/api/pdf/watermarks/previews` | same + `preview_page` int 0–2,000 (0 = first landscape page) | `image/png` ≤ 4 MiB, long edge ≤ 800 px | — | 72 MiB |
| `/api/pdf/page-numbers` | `format` ∈ {number,page,page-of-total,roman-lower,roman-upper,custom}; `template` ≤ 64 chars, tokens `{n}` `{total}` only, required iff custom; `start` 0–9,999 (roman 1–3,999); `position` six edge positions; `margin_mm` 0–50; `font_size` 6–36; `page_ranges` ≤ 4,096; `count_skipped` bool | `application/pdf` `<stem>-numbered.pdf` | `X-OfficeKit-Overlap-Pages` (compact ranges ≤ 256 chars) | 64 MiB |
| `/api/pdf/page-numbers/previews` | same + `preview_page` | `image/png` as above | `X-OfficeKit-Overlap-Pages` | 64 MiB |
| `/api/pdf/page-sizes` | `preset` ∈ {a4,a5,letter,legal,tabloid,custom}; `width`,`height` decimal ≤ 2 dp + `unit` ∈ {mm,in,pt}, 72–14,400 pt after conversion, required iff custom; `orientation` ∈ {keep,portrait,landscape}; `mode` ∈ {scale,canvas}; `anchor` ∈ nine positions (canvas only); `page_ranges` | `application/pdf` `<stem>-resized.pdf` | `X-OfficeKit-Scale` (min applied factor, 4 dp) | 64 MiB |
| `/api/pdf/grayscale-conversions` | `method` ∈ {vector,raster}; `dpi` ∈ {150,300} (raster only, else 422) | `application/pdf` `<stem>-grayscale.pdf` | 422 `{code:"grayscale_needs_raster"}` fixed message; raster ≤ 100 pages / 120 MP; `X-OfficeKit-Grayscale-Method`, `X-OfficeKit-Output-Input-Ratio` | 64 MiB |
| `/api/pdf/flattenings` | `scope` ∈ {all,forms,annotations}; `acknowledge_signature_loss` bool | `application/pdf` `<stem>-flattened.pdf` | **409** signed field without ack; 422 XFA or field without appearance; `X-OfficeKit-Flattened-Fields`, `X-OfficeKit-Flattened-Annotations` | 64 MiB |

`PdfInspectionResponse` (all strings ≤ 2,000 chars, `truncated` flag): `pdf_version`, `page_count`, `docinfo: [{key, label, standard: bool, present: bool, value: str|null, truncated}]` (9 standard keys always listed + ≤ 64 custom), `dates` as ISO 8601 or raw when malformed, `xmp: {present, entries: [{name, value, truncated}] ≤ 128}`, `page_sizes: [{width_pt, height_pt, rotate, count}] ≤ 50 + other_count`, `forms: {fields, signature_fields, signed, xfa}`, `annotations` (non-widget count). Values are never logged.

## 4. Engine design

| Module | Ops | Libraries |
| --- | --- | --- |
| `engine_pdf_page_tools.py` | rotate, resize | pikepdf |
| `engine_pdf_stamp.py` | watermark, page numbers, previews | reportlab[shaping], pikepdf, pypdfium2 |
| `engine_pdf_inspect.py` | inspection | pikepdf (docinfo, `open_metadata()` read-only) |
| `engine_pdf_grayscale.py` | grayscale | pikepdf, Pillow, pypdfium2 (raster) |
| `engine_pdf_flatten.py` | flatten | pikepdf |
| `engine_images_to_pdf.py` | images → PDF | Pillow, reportlab |

- **Rotate:** `Page.rotate(angle, relative=True)` after resolving inherited `/Rotate`; result normalized mod 360. Content streams untouched (asserted byte-equal).
- **Resize:** target size is the *displayed* size (swap for `/Rotate` 90/270). Scale: wrap content as Form XObject (`as_form_xobject`), draw with `s 0 0 s tx ty cm`, new MediaBox = CropBox, drop Trim/Bleed/Art; transform annotation `/Rect`/`/QuadPoints` with the same matrix. Canvas: new MediaBox, translate by anchor only; content outside is kept in the file (UI says so).
- **Stamps (watermark, numbers):** reportlab draws one overlay per distinct (CropBox size, `/Rotate`) into a bounded buffer; pikepdf places it in the CropBox with a counter-rotation matrix so the stamp is upright as viewed. Opacity via ExtGState (`setFillAlpha`). Text: bundled Noto Sans (Latin/Greek/Cyrillic) only, checked against cmap coverage; any uncovered code point, including Tamil and other complex scripts (not shaped), → fixed 422 before drawing (no tofu). Fonts subset-embedded. Image watermark keeps alpha as SMask. Overlap check (numbers): pypdfium2 text/image object bounds (≤ 10,000 objects/page, as `MediaPdfEngine`) intersected with the stamp box. Preview renders one stamped page with pypdfium2 at ≤ 800 px.
- **Grayscale (honesty):** vector mode rewrites content streams (`parse_content_stream`) in pages, Form XObjects, tiling patterns, Type3 procs and annotation appearances: `rg/RG/k/K` → `g/G` (BT.601 luma; CMYK via naive RGB), `cs/CS` DeviceRGB/CMYK/ICCBased(N=3/4)/Indexed → DeviceGray (Indexed palettes converted); images: check `/Width`×`/Height` against the pixel budget **before** decode (P-165), convert to L, re-encode Flate (DCT sources re-encode JPEG q90), keep SMask. Shadings, Separation/DeviceN, Lab, JPX/JBIG2 images, transparency-group color spaces → refuse with `grayscale_needs_raster`; never emit a partly colored file. Raster mode: pypdfium2 `grayscale=True` at 150/300 DPI with `engine_pdf_images` budgets, one image per page at original page size; text is no longer selectable and the UI says so before running.
- **Flatten:** refuse XFA (`/AcroForm/XFA`) with 422. Signed `/FT /Sig` with `/V` → 409 unless acknowledged. If `NeedAppearances` or a field lacks `/AP /N`, call `generate_appearance_streams()`; still missing → 422 (never a blank field). Flatten per selected subtype using the spec 12.5.5 mapping (BBox × Matrix → Rect) appended as `q … cm /Fx Do Q`; hidden/NoView annotations removed without drawing, Popups removed with parents. Forms scope removes `/AcroForm` and widget kids; annotations scope removes non-widget annotations.
- **Images → PDF:** read size from header before decode (40 MP each / 150 M pixels total, checked from headers), `ImageOps.exif_transpose`, alpha composited on white, first frame only for GIF/TIFF; JPEG without EXIF rotation passes through undecoded. `actual` fit uses image DPI (default 96, clamp 1–2,400).

## 5. Shell and slice contract (implemented)

The PDF workbench shell is hand-written in `index.html`, as option (b) of round 1 (ARCH-9). There is no `registerOperation` hook. The shell holds the grouped PDF navigation, the drop zone, the file list, `#pdf-workbench-options`, the dock and the message host `#pdf-slice-message`. Each slice registers through `window.OfficeKitExtensions.register(...)` in `assets/officekit-slice-pdf-tools.js`, which declares one destination per new catalogue ID (`tab: 'pdf'`, with a `pdfTool` key). The slice exposes `window.OfficeKitPdfSlice`, which carries the operation contract:

- `isOperation(key)`, `toolId(key)`, `operations()`, `state(key)`, `renderOptions(key, container, ctx)`.
- `dockFor(key, phase)`: the dock actions for a phase, one primary (Run before a result; Download or Copy report after).
- `acceptFiles(key, current, incoming)`: selection rules, the image cap (200) and the 64 MiB total. Returns `{ files }` or `{ error }` with the user copy.
- `reordersRows(key)` and `keyboardMove(event, files, index)`: Alt+↑/↓ row reordering, images to PDF only.
- `workbenchPreviewVisible(key)`: the generic output preview is hidden for every slice task (UX-8).
- `limitFor(key)`: the file-limit line for a slice task. Only images has one, built from the slice's own cap (`MAX_IMAGE_FILES`).
- `doneLine(key, result, options)`: the dock status after a result. Images to PDF, grayscale and flatten show a bare "Done". Page numbers shows "Done · N of M pages numbered", with N from the selection and M from the page count (PM-9, owner answer 2026-10-22). Rotate, watermark and resize keep their approved forms.
- `buildRequest`, `validate`, `run`, `showError`, `runWorkbench(shell)`, `reportStatus`, `reportText`, `copyReport`: request building, validation, typed refusals and status copy.

The shell calls the slice. The slice writes only to the options container it is given and to its own nodes (`#pdf-slice-message`, `#pdf-slice-report`, `#pdf-slice-validation`). The slice supplies each slice task's file-limit line (`limitFor`), its selection rules and cap (`acceptFiles`), its dock status (`doneLine`), and its option and refusal copy (ARCH-5, ARCH-11, CR-4). `index.html` reads the limit line from the slice and keeps no copy of the image cap. The other `PDF_TOOL_COPY` titles and descriptions stay in `index.html`.

The PDF navigation is hand-written and not generated from the catalogue (PM-4, accepted as built). `test_every_pdf_slice_tool_is_found_by_its_stable_id_on_the_pdf_tab` checks that search reaches each stable ID.

## 6. UI component tree

`#tab-pdf` → `nav.pdf-nav` (5 `details.grp` → `button.pdf-tool-option[data-pdf-tool]`) | compact `PDF tool` menu → task `section`: title/description/Offline → drop zone (`accept` per op) → file list (P08: ordered rows with ↑/↓/✕, Alt+↑/↓, drag) → `#pdf-workbench-options` (op renderer, essential fields + one Details) → `#pdf-workbench-preview` (P06/P15 thumbnails, P12/P13 engine PNG, P10 report tables) → scope note → warnings (P13 overlap, P16 raster, P17 irreversible + signature checkbox) → `ok-action-dock` (status, one Run, Download; P10: Copy report + Remove metadata… link).

## 7. Files owned

`officekit/engines/engine_pdf_page_tools.py`, `engine_pdf_stamp.py`, `engine_pdf_inspect.py`, `engine_pdf_grayscale.py`, `engine_pdf_flatten.py`, `engine_images_to_pdf.py`; `officekit/routes/pdf_tools.py`; `officekit/tool_catalog/pdf.py`; `assets/officekit-pdf-tools.js`; `assets/fonts/NotoSans-Regular.ttf` + OFL notice; tests `tests/test_pdf_tools_<op>_unittest.py`, `tests/test_pdf_tools_api_unittest.py`, `tests/pdf-tools-ui.test.mjs`, `ui-tests/pdf-tools.spec.mjs`; fixtures generated in tests (no committed customer PDFs); slice doc page; this HLD; the mock until approval.

## 8. Test plan

- **Engine, per ID:** the verification cases in §1, each with a failure case (corrupt, encrypted, 2,001 pages, output cap forced small → `PdfOutputLimitError` before the cap) and source-bytes-unchanged assertion. Independent read-back with pikepdf + pdfplumber + pypdfium2 render; P17 asserts structure (no `/AcroForm`, no widgets) and visible values; P16 asserts R=G=B pixels and text survival; P12/P13 assert stamp text via pdfplumber chars and position within CropBox on rotated pages.
- **API (FastAPI multipart):** every route — DTO bounds (one under/at/over each limit), unknown and duplicate `options` keys, body cap 413 before parse, 413 output, fixed 422 copy with no filename or QPDF text (P-016/P-013), RFC 6266 Unicode filename (P-015), media type, exposed headers listed (TESTING :187), 409 flatten ack.
- **UI/client (`node --test`):** each tool ID opens its exact op and declared endpoint (AC2, P-042), group placement, image order serialization, client range validation, json result renders absent fields, signature checkbox gates Run, counts derived from the registry (P-150).
- **WebKit desktop + compact:** one real-API flow per op with real file bytes written to disk, not in-memory buffers (P-116); heading/action order and full task completion (P-167). If WebKit still aborts (P-144), record it as an open gate rather than passing.

## 9. Pitfalls check

P-016/P-013 fixed public errors · P-029 strict ranges, no silent fixes · P-042 every catalogue entry has a route and UI test · P-041 reported ratios/scale are measured · P-071/P-070 structural read-back, not render-only · P-164 previews come from the same engine path as output · P-165 budget before decode · P-167 complete-flow UI tests · P-150 derived counts · P-116 disk-backed fixtures · P-144 WebKit gate recorded honestly · P-015 safe filenames.

## 10. Open questions

1. Approve the nav grouping (5 groups; desktop disclosure with the active group open; compact grouped menu)? It changes the existing 12-op layout.
2. Bundle Noto Sans Regular (OFL, ~0.5 MB) for Latin/Greek/Cyrillic watermark and page-number text? CJK/Arabic stay unsupported (422).
3. Resolved (round 1, ARCH-1): the new routes use plural nouns (`page-rotations`, `image-pdfs`, `inspections`, `watermarks` with `previews`, `page-numbers` with `previews`, `page-sizes`, `grayscale-conversions`, `flattenings`). The existing verb routes (`pages/delete`, `pages/reorder`) are unchanged.
4. Resolved (owner, 2026-10-22, PM-6 and ARCH-6): Tamil is out of scope. Watermark text is Latin, Greek and Cyrillic only; the default text is CONFIDENTIAL; complex scripts get the fixed 422. The UI copy and this document say the same.
