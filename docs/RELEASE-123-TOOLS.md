# OfficeKit release: 123 deep capabilities and reusable workflows

Version: 1.89.44 · Release specification and implementation backlog, not a completion claim. Password generation now returns an exact theoretical search-space estimate in its typed API response, verified against independent inclusion-exclusion vectors; the passphrase mode now has a bundled-list typed API and packaging coverage; the searchable password and passphrase screen now uses the bundled local APIs with explicit copy and clear controls; UI tests reject malformed responses, verify bounds and ensure copy denial does not disclose the secret; installed visual behavior remains unverified. JWT inspection now rejects ambiguous/oversized JSON claims and noncanonical Base64URL while keeping the signature explicitly unverified. Meeting Notes preserves independent positive clauses beside negations and excludes pending, open and non-final decisions with engine, HTTP and packaged-smoke regressions; its semantic quality and release status remain open. Live Dictation now repairs the missing Parakeet vocabulary through a bridge-compatible FluidAudio 0.14.8 path before ASR initialization; 6 Swift cache-repair tests and 37 Rust tests pass; the repair helper has 100% line/function/region coverage. Fresh v3 installation and synthetic WAV/sample transcription passed, including a rebuilt network-denied cached run. Corrupt caches are repaired, wrong-type artifacts rejected and failed repair remains retryable. It also has a tested cleanup API, explicit Parakeet model preparation/cache validation, native microphone permission commands, and bounded manual AVAudioEngine capture/local transcription commands. The v3 and English-only v2 models were downloaded and actual CoreML inference transcribed generated speech fixtures; v2 also passed cached inference with network access denied. The UI allows local selection and persistence between these open-source variants. Whisper is not exposed until a runtime is integrated.  this does not verify microphone capture. The native Fn monitor/state machine and bounded paste-back IPC compile but have not been exercised with a real model, audio, focused app or clipboard restoration that must not overwrite concurrent copies; cleanup/dictionary-to-paste integration exists in native IPC, and the approved UI plus local dictionary persistence now have source-level tests; installed microphone/Fn/focused-app runtime remains open. No release-ready claim is made. On 2026-10-08, statement PDF pages with headers but structurally weak dated rows now enter bounded local OCR; a structurally stronger OCR candidate replaces the weak vector rows, while unavailable, empty or worse OCR preserves them. The API, parser and OCR integration tests pass; the supplied customer PDF now passes opt-in API acceptance: four expected transactions and balance movements are verified, CSV/XLSX exports match, and selectable-table preview keeps dates in separate rows; installed-app visual acceptance remains open. On 2026-10-07, margin/markup, break-even, simple-interest and depreciation gained searchable calculator forms with strict result validation, shared saving/export and authenticated Mac sidecar smoke coverage. URL encode/decode gained a searchable local screen with strict typed API handling; focused UI, edge-case, catalogue and packaged sidecar checks pass. Scientific math and unit conversion gained searchable calculator screens, strict clients and a typed unit catalogue; 19 focused Node checks and 2 catalogue API tests pass. Image resizing gained a searchable single/batch screen with bounded dimensions and typed output validation; 17 focused UI/search tests and 34 API/search backend tests pass. EXIF cleanup gained a searchable screen with bounded typed output validation; its 28 focused Node checks and 24 API/engine checks pass. The approved F08 split/join flow passed 32 focused backend/API tests, 31 workspace/search/mock tests and packaged sidecar health; PDF page-management tests passed 50 backend/API cases and 21 workbench/client tests. These checks establish source and API behavior, while installed visual interaction remains unverified. On 2026-10-07, DNS lookup, ping diagnostics and interface inventory gained searchable routes to a responsive network workbench. Requests remain user-triggered; the UI explains external DNS/ping activity and hides local addresses until explicit opt-in. Strict client validation covers all declared status and result variants, error handling, bounds and search routing; packaged DNS/ping/interface privacy-mode smoke is the next release verification.

## Calculator WebKit follow-up

Real browser interaction checks now cover the complete saved-result flow, all ten calculator input-restoration paths, nine real export downloads and persisted favorite/recent destinations at two supported desktop widths. The tests exposed and drove fixes for unassociated EMI labels, raw currency display, a dropdown accessible-name mismatch, Markdown's incorrect extension and six inert Reuse inputs actions. Unit restoration waits for the local catalogue and does not claim success if its choices cannot load. macOS CI now runs `npm run test:ui` and retains failure evidence. This improves existing capabilities; it does not add tools or grant native release sign-off.

## Iterative first release

The user now prefers releasing the verified subset first, then adding capabilities in updates. [FIRST-MAC-RELEASE.md](FIRST-MAC-RELEASE.md) audits all 49 catalogue entries: 16 priority candidates, 18 next candidates needing additional depth or native verification, and 7 held back. Bank-statement extraction remains held because broad bank-layout accuracy is unverified, although the supplied statement now passes direct extraction and CSV checks. No tool is promoted merely to meet a count of 50. The 123-capability roadmap remains intact; current builds still expose the development catalogue, and a restricted release must gate all discovery/navigation/API paths before distribution.

## Linear ticket draft

- Project: OfficeKit (resolve the actual project/team through Linear before creation).
- Title: Deliver 123 deeply verified OfficeKit capabilities with reusable workflows and share-ready exports
- Type: Parent release planning ticket; create engine/workflow-sized children during implementation planning.
- Suggested priority: High; no assignee or deadline invented.
- Description: This complete document, including every capability row, export requirement, milestone and release checklist.
- Submission status: Prepared locally; no Linear issue has been created. Linear integration must be connected before submission.

## Outcome

Deliver OfficeKit as a beautifully simple, local-first cross-platform toolbox with **123 distinct launch capabilities**, grouped under shared engines and a searchable Mac-style Gallery/List. Customers should be able to finish routine work, batch it, retain results, and share useful outputs without assembling several subscriptions. The number is a scope inventory, not evidence of value or an excuse to count format pairs/buttons as separate tools. Release only after all mandatory capabilities meet depth gates; incomplete tools are not advertised as available. Phase milestones below enable real releases without claiming the full target prematurely.

Current audit as of 2026-10-09: 53 tool families in code, 49 catalogue entries, 53 API-wired families and 53 UI-wired families; none is release-verified. Everyday Percentages is one catalogue tool with three operation families and remains outside the private-beta profile. Scientific math and unit conversion now have dedicated searchable calculator forms with strict API clients, a typed local unit catalogue and shared calculation save/history/export actions; focused UI, search and catalogue API tests pass, while installed GUI behavior remains unverified. P01 reconciliation now distinguishes verified, partial, discrepancy and unverified results; missing parsed amounts are not coerced to zero, and no-check results cannot claim a pass. The four-state statement mock is approved and the screen now renders verified, partial, discrepancy and unverified results with row statuses and arithmetic limitations. The newly built macOS arm64 sidecar passes an authenticated amount-only statement smoke that requires `valid: null` and `status: unverified`. PDF protect, unlock, merge, split, compression and metadata removal now encode into a bounded 64 MiB response buffer and return HTTP 413 on overflow; image conversions also cap output while encoding. Engine and API regressions confirm that partial output is never returned. Image resize now has bounded single-file and batch multipart APIs; batch resize accepts up to 50 files, caps aggregate input and ZIP output at 64 MiB, sanitizes member names and fails all-or-nothing. Its searchable image workbench exposes dimensions, aspect-ratio handling, batch selection and validated downloads; the packaged macOS arm64 sidecar smoke resizes generated PNGs singly and as a batch through authenticated routes. The metadata-removal tool has a searchable image screen backed by its typed API, with bounded responses and strict client validation. Both screens have source-level coverage; installed visual behavior remains unverified. PDF-to-PNG/JPEG now has a bounded API and an approved workbench UI with DPI, format and page-count reporting; the rebuilt OfficeKit.app bundled macOS sidecar now passes authenticated health, CSV-to-JSON, typed XLSX result export, PDF protect/unlock, PDF-to-PNG, selected-workspace similar-image scanning, duplicate/storage reports, rename artifact download, file split/join ZIP round-trip with byte-for-byte and checksum verification, and workspace cleanup on this host; the rebuilt app and DMG include the split/join screen, while mounted visual interaction remains unverified; the image finder groups generated JPEG burst frames with half-frame center zoom and four off-center corner crops and caps cumulative scan work at 3bn pixels while continuing with later smaller files; macOS additionally decodes bounded HEIC/HEIF copies with the built-in sips codec, and generated HEIC/HEIF burst frames pass unit and packaged authenticated-sidecar grouping checks; an expanded opt-in macOS benchmark grouped 95/95 JPEG-converted frames across 15 real HDR+ burst sequences with zero cross-scene merges; broader device/HEIC recall and personal-library precision remain unverified. Merge, split, compression, metadata, unlock and protect also route to the PDF workbench; PDF-to-CSV/XLS/XLSX searches use supported bank statement extraction; vector, scanned and mixed-page statement PDFs now have bounded page-level OCR fallback; tests exercise raster-only and rotated PDFs through multipart HTTP with macOS Vision, verify blank financial-column alignment, reversed-header orientation scoring and bounded 90/180/270-degree retries, and enforce page, rendered/retry-pixel, encoded-output, text and time limits; real-world OCR accuracy and Windows/Linux OCR providers remain unverified; the rebuilt macOS app backend smoke also parses a ruled statement PDF and verifies the reconciliation result; color conversion now has a searchable HEX/RGB/HSL/HSV screen connected to the existing typed local API; strict client validation and source tests cover response shape, bounds, alpha preview, copy denial and clear, while installed visual review remains open; loan EMI now has HTTP-level full-schedule reconciliation tests and packaged macOS checks for all 60 balances, cent totals and final payoff. N01 now has a typed redacted macOS support report with no device/account identifiers; the packaged macOS smoke validates its shape, but the report UI and other platform adapters are open. N02 now returns typed measured CPU and RAM metrics, bounds sensor outputs, caches refreshes for one second and passes a packaged macOS metric smoke; its screen and other-platform runtime behavior remain unverified. N03 now has a bounded local interface inventory API; IP addresses are hidden by default, MAC/link-layer identifiers are omitted, and the packaged macOS smoke verifies the hidden-address mode. Its private-address opt-in lacks the interface-selection UI, and Windows/Linux interface behavior remains unverified. N04 now has A/AAAA/MX/TXT DNS lookup through a bounded typed resolver API with deterministic mocked coverage; a packaged macOS system-resolver A query for example.com also passes; its user-facing screen and packaged custom-server/MX/TXT paths remain open. N05 now has a macOS-only native ICMP endpoint with 100% engine line/branch coverage and a packaged loopback smoke; other platforms remain explicitly unsupported and there is no UI route. Compound interest now has independent HTTP vectors for annual/quarterly/monthly/daily frequencies, fractional/zero-rate cases and a packaged macOS schedule smoke. Favorites and recent-tool screens are connected. File split/join (F08) now has a searchable, approved screen backed by strict split/join API client validation; packaged macOS API coverage passes, while installed visual interaction remains unverified. Batch rename, exact-duplicate scan and storage analysis now use the approved workspace flow: import local copies, preview or inspect, download outputs where applicable, then clear temporary storage. Folder comparison (F04) now has a searchable selected-copy workbench with non-overlapping folder selectors, hash/status summary, safe table rendering and bounded CSV export; URL encoding/decoding now have a searchable local screen; color conversion and screenshot editing now have searchable local screens with source-level tests, while installed-app visual interaction remains open. The bounded typed result-export endpoint emits Markdown, self-contained HTML, versioned JSON, formula-safe long-form CSV, typed XLSX, paginated PPTX and searchable PDF; the PDF font is bundled under its SIL Open Font License and the macOS app backend smoke now covers Tamil PDF output. XLSX, PPTX and PDF now connect to the common result-screen export dialog; PNG/JPEG result exports now return bounded, decoded 150 DPI one-page summary images with optional visible attribution and PNG/EXIF metadata; long summaries fail with guidance instead of truncating. All four financial calculator result screens now save immutable local snapshots and connect current/saved results to nine typed export formats; end-user installed visual review remains open. The user confirms a successful local installer build and install, which exposed PDF/tool-discovery, UI-layout and icon defects; this worktree build has not been reproduced on the user's machine. D1/D2 implementation does not mean a finished desktop capability. The current family-level evidence and known gaps are in `docs/TOOL-GUIDE.md`; route inventory is in `API-CONTRACT.md`. Hosted activation and challenge handlers now run through a composed Lambda entrypoint; the initial API Gateway/DynamoDB/KMS CDK stack synthesizes and FakeCloud covers the full route flow. The stack is not deployed; production licensing and the desktop activation path remain release blockers. Screenshot editing now has a searchable local workbench with explicit clipboard paste/copy, crop, blur, opaque masks, undo/redo, clear and PNG/JPEG export. The typed API emits metadata-free bounded PNG/JPEG; unit/API tests cover transformations, JPEG alpha flattening, format validation and output overflow; UI tests cover ordered multipart operations, signatures, MIME, limits and resource cleanup. Installed-app clipboard and visual smoke remain open. The macOS arm64 release now bundles local UI CSS, fonts and icons under a restrictive Tauri CSP; the authenticated sidecar smoke passes. Exact duplicate scanning now applies a same-size/4 KiB-prefix candidate filter before full SHA-256 and detects files changed between phases. The existing burst-aware similar-image API is now connected to the searchable selected-copy workbench with a sensitivity control, safe report rendering, partial/error states and no deletion; source tests cover API validation, search routing and hostile filenames, while installed visual review remains open. Production-readiness work is in progress.

P03 grouped splitting now has an approved named-output flow in the PDF workbench: users define 2–50 page groups, preview the ZIP members, and download named PDFs together. The UI posts a strict manifest to the bounded multipart endpoint, validates group names and shape locally, and accepts only a bounded ZIP response with a valid signature. Route tests parse each returned PDF and cover malformed/unsafe manifests, overlap, ordering and overflow; the authenticated macOS sidecar smoke renders each grouped PDF and verifies page order. UI client and add/remove group regressions pass on this worktree, but the fresh arm64 app/DMG build and mounted-DMG sidecar smoke pass, while native interactive UI rendering remains unverified in this environment; P03 remains D2 and is not release-verified.

The shared JSON↔YAML formatter API now includes bounded YAML-to-JSON conversion using SafeLoader with YAML 1.2 scalar resolution, alias/duplicate-key rejection and depth/node limits. JSON formatting and both conversion directions also reject duplicate object keys, non-finite numbers and unpaired surrogates while retaining exact decimal precision and exponent values. Engine and HTTP regressions cover type fidelity and hostile inputs; the rebuilt arm64 macOS sidecar smoke passes exact-decimal formatting and duplicate-key rejection. The formatter UI remains absent, so this is D2 API progress only.

The C01 scientific expression evaluator now has bounded constants, allowlisted functions, and explicit radians/degrees behavior behind `/api/math/eval`. Independent unit and HTTP tests cover precedence, right-associative `^`, numerical bounds, function domains and malformed calls; the evaluator module has 100% line and branch coverage. The fresh arm64 macOS app build and authenticated sidecar reference smoke pass. The scientific calculator now has a dedicated searchable form with real WebKit save/reuse interaction coverage; installed-app verification and final release depth remain open.

## Mandatory depth contract (applies to every row)

The macOS release now requires a Developer ID certificate and App Store Connect API credentials, verifies the signed/notarized app and DMG, and publishes only after all matrix builds pass; actual release signing remains unverified until repository secrets are provisioned. Latest macOS verification: the mounted-DMG smoke confirms the packaged app references `icon.icns` and renders the approved OfficeKit monogram identically at every decoded icon size; `/Applications/OfficeKit.app` has the same rendered artwork despite its different ICNS container hash, leaving Launch Services display caching as the likely explanation if the icon still appears stale. The full built app and DMG smoke passed on Apple silicon. Latest PDF evidence: P11 now has an authenticated mounted-DMG smoke that removes unique document-info and XMP markers, rejects retained marker strings, and confirms page geometry after rendering. This covers standard metadata only; arbitrary embedded identifiers remain outside the claim. P07 has an authenticated mounted-DMG smoke for fast, balanced and maximum lossless compression; each response ratio is checked against the returned bytes and rendered page count/geometry is preserved. This does not downsample images or make P07 release-ready. P02 now has a bounded ordered page-count preflight route; mounted-DMG smoke verifies [2,1] counts, total 3 and no filename leakage, while the page-total UI awaits mock approval. Engine and multipart HTTP tests verify source-name bookmarks, nested internal outlines with page destinations and viewport/style, internal page-link retargeting, AcroForm values/widgets, duplicate field-name renaming, and safe 422 rejection of malformed outlines without partial output. A newly rebuilt macOS DMG smoke reads the merged output back with pikepdf, verifies both source bookmarks and nested destinations, checks distinct field values and unique names, then renders the merged pages to verify source order. XFA, signature validity, tagged-PDF structure, external outline actions and broader fidelity remain open. P03 has an authenticated packaged-sidecar split smoke that selects pages `3,1` from a generated three-page source and verifies the rendered page dimensions stay in that order. Unit/HTTP tests independently verify requested page order and invalid range rejection. larger-document performance remains open; the approved named-output group UI awaits mounted-DMG verification; this does not make P03 release-ready. P01 amount parsing now handles unambiguous US/EU decimal punctuation and Western/Indian grouping, with engine and HTTP regressions for EU decimal-comma and Indian rupee CSV fixtures; the freshly built macOS DMG sidecar also reconciles both. The API now accepts explicit `en-US`, `en-IN`, `de-DE` and `fr-FR` number locales, but the screen has no selector and automatic mode now leaves bare comma groups with a three-digit tail unparsed and reports them as unverified; explicit locale checks pass, and the packaged macOS DMG keeps ambiguous auto amounts unverified; date-order selection is accepted by the API and normalizes only valid four-digit dates; the packaged macOS DMG smoke checks German decimal ambiguity, explicit DMY normalization and stable 422 errors for invalid selectors; the screen lacks locale/date-order controls; broader bank layouts and accounting-export validation remain open; P01 is not release-ready.

Every tool must reach **D3 product-complete and D4 release-verified** on supported platforms: stable manifest ID, exact searchable destination, schema-validated inputs, correct deterministic/engine behavior, useful preview/result, safe chosen output destination, actionable errors, relevant export formats, immutable history/saved snapshots where safe, keyboard/theme/accessibility, documented assumptions and meaningful independent tests. File/batch tools also need per-item outcomes, bounded concurrency/input size/memory/time, honest progress and cancellation where the underlying engine supports it, originals preserved, collision handling, safe temporary files and cleanup. Instant calculations need no fake jobs/spinners. Unsupported platforms/permissions are explicit.

Every capability has a fixture-backed “done” record: independent reference/vector, boundary/invalid case, real exported output validation if applicable, UI journey, and clean-machine evidence for each supported platform. Baseline tests in each table are mandatory minimums, not exhaustive. Never automatically persist passwords/JWTs/secret inputs. Destructive tools require dry-run/review/confirm/audit and recovery limits. No network processing for imported files unless explicitly chosen and disclosed.

### Search behavior requiring verification

File checksum and type detection now have searchable screens in the selected-copy workspace. The authenticated packaged-sidecar smoke now exercises `PDF to` search and requires the statement CSV/XLSX and page-image PNG/JPEG destinations, with copy that limits spreadsheet extraction to supported bank statements and does not imply legacy `.xls` support. Browser-render tests require all returned PDF results to remain selectable. The backend and renderer checks pass on this worktree; the proposed grouped search presentation is in `design/mocks/related-tool-search.html` and awaits user approval before any visible search changes.

### Tabular converter preservation evidence

CSV/TSV conversion now preserves leading-zero identifiers and date-like text, retains numeric typing only for finite values with at most 15 significant digits, and rejects malformed input or row/column/cell-limit overruns before DataFrame allocation. Engine and multipart API regressions cover JSON and XLSX outputs, blank cells and exact data preservation; the rebuilt authenticated macOS sidecar smoke verifies the same identifiers, precision limits and dates survive packaging. XLSX inputs now preflight duplicate/unsafe ZIP paths, total uncompressed bytes, sheet dimensions and shared row/column/cell limits before pandas import; XLSX-to-JSON preserves text identifiers, simple zero-padding number masks and typed dates as ISO strings. Broader Excel display-format fidelity, sheet selection and user-facing source/target coverage remain open.

### Strict JSON imports in the shared tabular converter

JSON-to-tabular conversion now rejects duplicate keys, non-standard constants and float overflow, and bounds nested JSON to depth 64 and 250,000 nodes before DataFrame construction. Engine and multipart HTTP regressions cover duplicates, non-finite numbers, numeric overflow and excessive nesting. Nested structure/type fidelity, explicit null mapping and independent spreadsheet-reader validation remain open.

### Strict YAML file imports

Generic YAML imports now reuse the strict YAML 1.2 parser: duplicates, aliases, merge/non-string keys, multiple documents and non-finite values are rejected; text is capped at 1 MiB, depth at 128 and nodes at 100,000. YAML-to-JSON preserves exact decimal representations, and YAML-to-CSV retains them as text. Engine, multipart API and packaged sidecar regressions cover invalid documents and fidelity. Spreadsheet precision/type mapping and larger YAML inputs remain explicit converter limitations.

## Category coverage

| Category | Capabilities | Engine/screen grouping |
| --- | ---: | --- |
| PDF & documents | 20 | Shared page editor, conversion, security and statement flows |
| Images | 20 | Shared conversion/effects pipeline and batch editor |
| Calculators | 25 | Shared numeric forms/results and formula library |
| Unit & data-value converters | 16 | Canonical unit engine, explicit dimension/context |
| File utilities | 12 | Safe filesystem/archive engine |
| Storage analysis & safe cleanup | 6 | Shared scanner, review and Trash adapters |
| Developer & security utilities | 17 | Shared text/data workspace and secure utilities |
| System & network | 5 | Platform adapters and explicit network status |
| Dictation & meeting notes | 2 | Verified local audio path and editable notes |
| **Total** | **123** | Capabilities, not 123 disconnected applications |

Count deduplication: image→PDF appears only under PDF; CSV↔JSON appears under Developer and must use the same tabular engine as broader data-import/export; hash families consolidate algorithm variants; encoding directions are one capability; batch options and export formats do not increase tool count. Expanded tabular XLSX/YAML/SQL import/export is a shared workbench capability outside the 123 count, not extra marketing tools. Full file comparison and text diff differ because they accept/inspect different sources; implementation should reuse their comparison logic.

## PDF & documents — 20

| ID | Capability | Expected depth beyond a demo | Verification cases |
| --- | --- | --- | --- |
| P01 | Bank statement extraction | Text PDF/images/CSV/TSV; OCR fallback; explicit mapping/correction; baseline-aware verified/partial/discrepancy/unverified reconciliation; tri-state validity; currency/date context; reviewed CSV/XLSX/OFX; QBO only after institution-specific Web Connect support is importer-tested | Multi-bank fixtures, scanned/text/rotated pages, ambiguous columns, decimal/date locales, opening/closing balance discrepancies, missing intermediate balances that must break the check chain, importer-compatible accounting exports; invalid input never says reconciled |
| P02 | Merge PDFs | Reorder source files, preview page totals, preserve nested internal outlines, internal links and supported AcroForms, add source-name bookmarks, preserve originals; batch safe outputs | Two documents with mixed sizes/fonts/forms/bookmarks; verify page order, nested titles, destinations, viewport/style, internal-link retargeting, field values/widgets and duplicate-name renaming; reject malformed outline without partial output; packaged pikepdf read-back and render smoke; explicitly characterize XFA/signature/tagged-PDF limits; corrupt/encrypted source; duplicate output name; cancellation |
| P03 | Split/extract pages | Ranges, every-page/selected-group outputs, naming and ZIP; preserve requested order; reject duplicate/overlapping page selections explicitly | `1-3,5`, reversed/overlapping/out-of-range/empty selections; exact output page sequence; malformed range errors |
| P04 | Delete pages | Visual selection and review before creating a new PDF | First/last/all-page selections, cancel, source hash unchanged, correct survivors |
| P05 | Reorder pages | Thumbnail and keyboard reorder; mixed page sizes | Drag/keyboard sequence; repeat/delete behavior if offered; page-count and rendered identity |
| P06 | Rotate pages | Selected/all pages; 90/180/270 degrees; preview | Existing rotations, mixed pages, apply twice, visible output orientation and preserved content |
| P07 | Compress PDF | Real documented presets, measured actual size/fidelity, expansion reported honestly | Distinct presets on image-rich/text PDFs; expanded output warning; text/image checks; no fake ratio cap |
| P08 | Images→PDF | Ordered batch, page size/orientation/margins, image fitting | Mixed orientation/transparency/EXIF, large batch, DPI/fit, page count and order |
| P09 | PDF→images | Selected pages, PNG/JPEG, DPI/resolution, batch/ZIP | Known page pixel dimensions at DPI, transparency/background, encrypted/corrupt file, exact selection |
| P10 | PDF metadata inspection | Readable standard fields and supported XMP, absent fields distinguished | Known docinfo/XMP fixture, Unicode metadata, absent values, no modification |
| P11 | PDF metadata removal | Before/after inspection, explicit removal limits | Docinfo/XMP/nested fixtures, write/read-back verification, source unchanged; no redaction claim |
| P12 | Watermark PDF | Text/image position/opacity, page ranges, preview | Font Unicode, portrait/landscape, image transparency, exact range and opacity, original unchanged |
| P13 | Page numbering | Format, start number, position, page range and margins | Roman/custom labels if supported, skipped pages/start offset, crop/rotation, no content overlap |
| P14 | Crop PDF | Visual crop per page/all; explain content is not securely removed | Mixed boxes/rotations, out-of-bounds prevention, rendered dimensions, underlying content warning |
| P15 | Resize PDF pages | Standard/custom dimensions and explicit scale-versus-canvas choice | A4/Letter/custom, mixed units, aspect rules, output boxes and rendering |
| P16 | Grayscale PDF | Actual images/graphics/text behavior, fidelity warning if rasterized | Color vector/image fixture, readable text, profile handling, documented rasterization/size |
| P17 | Flatten forms/annotations | Preview/reversibility warning; preserve visual appearance | AcroForm/annotation fixtures, values visible, fields no longer editable as promised, signatures warning |
| P18 | Protect PDF | Supported encryption, password confirmation, safe handling | Known-vector/round trip, incorrect password, empty/invalid policy, no secret storage/logs |
| P19 | Unlock PDF | Known-password authorization path, clear failure, batch | Valid/invalid password, owner restrictions, corrupt file, permissions/fidelity, source unchanged |
| P20 | PDF→text | Implemented as a bounded selectable-text extraction engine, API and workbench with page order, UTF-8 TXT/Markdown, mixed blank-page reporting and scanned-only guidance | Engine/API and client/search-routing edge cases pass; desktop/compact WebKit runner aborts before test execution, and packaged/installed Mac acceptance remains open; OCR and visual reading-order reconstruction are not claimed |

## Images — 20

| ID | Capability | Expected depth | Verification cases |
| --- | --- | --- | --- |
| I01 | Common image conversion | JPEG/PNG/WebP/BMP/TIFF/ICO as supported; direction/codec availability explicit; batch | Decode real outputs, alpha flattening/CMYK/palette/EXIF, animation/multipage policy, codec unavailable |
| I02 | Resize images | Dimensions/percentage, lock ratio, upscale policy, batch presets | 800×600→400×300, percentage, portrait/EXIF, invalid bounds, originals unchanged |
| I03 | Compress images | Quality presets, actual bytes and preview, batch | Comparable fixtures, min/max quality, expansion, output decode and visual quality |
| I04 | Target-size attempt | Bounded iterative sizing, quality/min-dimension limits, best-effort disclosure | Achievable/unachievable targets, exact versus approximate result, iteration/time limits |
| I05 | Crop images | Visual/keyboard crop, ratio presets, non-destructive preview | Edge pixels, out-of-bounds, rotated input, final dimensions and undo-before-export |
| I06 | Rotate/flip images | Direction/axis explicit; EXIF normalized | Pixel fixtures, four rotations, two flips, orientation tags removed/updated correctly |
| I07 | EXIF inspection | Date/camera/location fields with missing/unsupported states | Known GPS/date fixture, Unicode, malformed metadata, untouched original |
| I08 | Remove image metadata | Chosen metadata policy; output read-back verification | GPS/EXIF/ICC/XMP fixtures, retain intentional color profile if selected, no sensitive residue claim beyond verified fields |
| I09 | Image watermark | Text/logo, positions/opacity, batch | Unicode/font coverage, alpha/logo, tiny/large images, deterministic bounds |
| I10 | DPI/PPI metadata | Edit density without inventing pixels; units explained | Pixel dimensions identical, correct density tags and printer-oriented report |
| I11 | Grayscale images | Consistent preview and export, preserve alpha if supported | Color swatches, transparent pixels, output channels/fidelity |
| I12 | Color adjustments | Brightness/contrast/saturation with reset and preview | Identity settings, extrema clipping, alpha unaffected, preview/export agreement |
| I13 | Blur images | Radius/region controls where offered; no secure-redaction claim | Identity/known blur fixture, bounded radius, clipping/region, wording |
| I14 | Borders/rounded corners | Canvas/fill/alpha choices, dimension preview | Transparent/opaque export, width/radius limits, output size, batch |
| I15 | Dominant colors | Reproducible swatches/HEX/RGB, sample transparency policy | Solid/two-color known inputs, transparent background excluded, copy/export values |
| I16 | Image↔Base64/data URI | Binary-safe import/export, MIME and size bounds | Byte round trip, MIME mismatch, invalid/oversized URI, SVG handled safely |
| I17 | Favicon/app-icon pack | One tool generates reviewed size bundles, platform support explicit | ZIP contents/sizes/alpha, ICO multi-resolution, square/crop rules, names |
| I18 | Collage/merge images | Layout/gaps/background and ordered batch | Mixed image shapes, exact canvas, overflow/empty list, preview/export |
| I19 | Contact sheet | Thumbnails, filenames optionally, page/grid sizing | Long/Unicode labels, large folder, pagination, opt-out of names |
| I20 | Visual image comparison | Side-by-side/overlay/difference, scale alignment, honest thresholds | Identical/changed-pixel/size-mismatch fixtures; no automatic identity claim |

## Calculators — 25

| ID | Capability | Expected depth | Verification cases |
| --- | --- | --- | --- |
| C01 | Scientific expression calculator | Defined precedence, constants/functions, radians/degrees; bounded evaluation | Independent expression/trig vectors, power associativity, `^` policy, divide by zero, huge powers/nesting limits |
| C02 | Percentage | Part/whole/percent with explicit solved variable | 15% of 240=36, missing whole/zero denominator, decimals/negative policy |
| C03 | Percentage change | Signed increase/decrease, original/new labels | 80→100=25%, 100→80=-20%, zero original error |
| C04 | Discount | Multiple discounts/tax order only if explicitly supported, savings/net | 20% off 100=80, sequential versus additive discounts, currency/rounding |
| C05 | Margin/markup | Distinguish denominators; solve cost/revenue/target where offered | Cost80/revenue100: margin20%, markup25%; zero/negative domain errors |
| C06 | Average/weighted average | List/pasted table, weights, missing-value policy | [1,2,3]=2; known weighted result, zero/negative weights policy, malformed list |
| C07 | Fractions/ratios | Exact rational simplification and arithmetic | 2/4=1/2, rational operations, zero denominator, negative signs, large values bounds |
| C08 | Loan/EMI | Fixed-rate monthly payments, **complete** schedule, explicit currency/fees assumptions | Independent vectors, zero interest, monthly-term bounds, last balance zero, principal sum, export all rows |
| C09 | Compound growth | Correct compounding frequency, contribution timing, fractional durations | Independent monthly/annual/daily cases, fractional year, zero rate, all totals/schedule reconcile |
| C10 | Simple interest | Principal/rate/time units and exact assumptions | P1000/r10%/2y: interest200; months conversion, invalid time/rate |
| C11 | VAT/sales tax | Forward/reverse arithmetic with supplied rate, no jurisdiction claim | 100+20%=120; gross120 at20%=net100; invalid rates/denominator/rounding |
| C12 | Freelance rate | Take-home/expense/tax/work-time assumptions, scenarios | Known independent budget, tax100% rejection, vacation>=52, zero hours, day-length meaning |
| C13 | Break-even | Contribution margin, ceil for indivisible units, optional fractional-unit policy | Fixed1000/contribution30 requires34 units; no profitable solution, zero costs, export |
| C14 | Depreciation | Straight-line and explicitly supported methods; book-value schedule | Known salvage/life vector, salvage>cost rejection, zero/negative life, schedule sum and final book value |
| C15 | ROI | Gains/costs/time assumptions and nonannualized label | Gain20/cost100=20%, zero cost, negative returns, fee inclusion |
| C16 | CAGR | Start/end/period and domain assumptions | 100→121 over2y=10%, zero/negative bounds, fractional time |
| C17 | Date difference | Days/months/years semantics, inclusive option | Leap dates, ordering, month-end, inclusive/exclusive and timezone boundaries |
| C18 | Age | As-of date, years/months/days, date-only semantics | Leap birthdays, future date rejection, midnight/calendar boundaries |
| C19 | Business days | Workweek and explicit local holiday list/import, no claimed global holiday service | Weekend variants, inclusive mode, holiday duplication, empty range |
| C20 | Work hours/duration | Overnight shifts, breaks, weekly totals | 22:00→06:00 minus break, invalid break length, DST policy, CSV totals |
| C21 | Time-zone converter | Date-specific zone offsets and DST ambiguity | Named-zone transitions, nonexistent/ambiguous times, historical date, UTC round trip |
| C22 | Quadratic solver | Real/complex roots, degeneracy and precision | Two/repeated/complex roots, a=0 linear case, independent residual check |
| C23 | GCD/LCM | Integer lists, defined zero/negative behavior | gcd(12,18)=6, lcm=36, zero/sign/list bounds |
| C24 | Descriptive statistics | Mean/median/mode/range/variance/stddev; sample/population choice | Independent dataset, empty/singleton, multimode, sample n<2, precision |
| C25 | Geometry | Coherent 2D/3D shape workbench; labeled inputs/units/formulas | Known circle/triangle/cylinder volumes/areas, invalid triangles, unit dimensionality, diagrams if useful |

## Unit/value converters — 16

| ID | Capability | Expected depth | Verification cases |
| --- | --- | --- | --- |
| U01 | Length | Canonical SI/customary units, aliases and swap | 1in=25.4mm, feet/miles/nautical mile, round trip and unknown unit |
| U02 | Area | Squared units, hectares/acres | 1m²=10,000cm², acre reference, reject linear-unit mixing |
| U03 | Volume | Metric and named US/Imperial distinctions | Litres↔m³, differing gallons/cups, ambiguous “gallon” clarified |
| U04 | Mass | SI/customary, tonne/US/UK ton distinction | kg/lb vectors, micro/large scales, naming errors |
| U05 | Temperature | Offset formulas and absolute-zero policy | 0C=32F=273.15K, same-unit invalid input checked, below-zero-K error |
| U06 | Speed | Distance/time dimensions | 36km/h=10m/s, knots vector, swap/precision |
| U07 | Time duration | Fixed durations separate from calendar months/years | 90min=1.5h, calendar ambiguity explanation, negative policy |
| U08 | Digital storage | Bits/bytes, SI/IEC, case-sensitive ambiguities resolved | 1KiB=1024B, 1KB=1000B, 8bits=1B, ambiguous `b` rejected/clarified |
| U09 | Energy | J/cal/kWh/BTU and variant definitions | 1kWh=3.6MJ, calorie variants, unknown units |
| U10 | Power | W/kW/horsepower variants | 1kW=1000W, mechanical/metric hp distinction |
| U11 | Pressure | Pa/bar/PSI/atm | 1bar=100kPa, independent PSI vector, unknown units |
| U12 | Force | N/lbf/kgf with explicit gravity constant | Independent lbf↔N vector; not mass conversion |
| U13 | Frequency | Hz/kHz/MHz/GHz | 1MHz=1,000,000Hz, units/precision/round trip |
| U14 | Angles | Degrees/radians/gradians | 180°=πrad=200grad, wrap option separate from conversion |
| U15 | Colors | HEX/RGB/HSL/HSV; gamut/alpha rules, CMYK only with defined assumptions | Known primary colors, hue wrap, invalid channels, transparent alpha, round trip tolerance |
| U16 | Typography | px/pt/em/rem with explicit DPI/font/root context | pt↔px at96DPI, non16px contexts, no fixed-context surprise |

## File utilities — 12

| ID | Capability | Expected depth | Verification cases |
| --- | --- | --- | --- |
| F01 | Batch rename | Preview/apply/undo, numbering/case/literal/regex only if supported | Collisions, Unicode/reserved/long names, interrupted apply, no extension-as-conversion claim |
| F02 | File info | Size/timestamps/basic metadata, platform limits | Unicode/long paths, denied access, symlink display, no input mutation |
| F03 | File type detection | Signature/MIME plus extension mismatch | Renamed fake extension, known signatures, unknown/ambiguous binary |
| F04 | Folder comparison | Relative path/size/optional content hashes, no implicit sync | Missing/changed/same files, permissions, symlink escape policy, case collisions |
| F05 | File comparison | Binary/text distinctions, safe large-file view | Equal binaries, one-byte difference, encoding/line endings, bounded memory |
| F06 | Create ZIP | Selected inputs, relative paths, naming, safe output | Unicode, collisions, output in source scope, cancellation/source preserved |
| F07 | Extract ZIP | Preview destination, overwrite policy, bounded safe extraction | Path traversal, absolute paths/symlinks, decompression bombs, disk full |
| F08 | Split/join files | Binary-safe numbered parts, versioned manifest with per-part/whole SHA-256, bounded ordered recombination | Byte-identical binary join, empty/exact-boundary files, missing/extra/reordered/compressed/tampered parts, duplicate manifest fields, unsafe names, size/part limits, swapped symlinks, atomic artifact cleanup |
| F09 | File age finder | Selected scope, modified/created availability, inclusive thresholds | Timezone/date boundary, inaccessible records, recursive exclusions |
| F10 | Empty-file finder | Zero-byte review, no automatic removal | Empty versus whitespace/nonempty, symlinks, denied paths, source unchanged |
| F11 | Symlink inspector | Target/resolution/broken-link state and scope | Relative/broken/circular/out-of-scope links, no blind traversal |
| F12 | Archive inspector | Supported ZIP content tree/sizes, no extraction needed | Nested/duplicate paths, encrypted/unsupported archives, no fabricated uncompressed safety estimate |

## Storage & safe cleanup — 6

| ID | Capability | Expected depth | Verification cases |
| --- | --- | --- | --- |
| S01 | Volume/disk overview | Native volumes/free/used, permission/platform state | Multiple/removable volumes, unavailable stats, consistent units/refresh |
| S02 | Folder-size analyzer | Hierarchical totals, partial scan/error reporting, bounded cancellation | Known tree totals, permissions, symlinks/hardlinks policy, interrupted scan |
| S03 | Largest files | Filter/sort size/path/date over scoped scan | Known topN, zero/negative bounds, stable ties, no sensitive analytics paths |
| S04 | Exact duplicates | Size prefilter + content validation; explain hardlinks/empty files | Same-size different content, zero-byte duplicates, changed-during-scan file, errors/progress |
| S05 | Empty folders | Bottom-up inspection with clear exclusions | Nested empties, hidden files, symlinks/system boundaries, review only |
| S06 | Cleanup review/Trash | Selected findings, exact paths/actions, dry-run, confirm, native Trash and restore where supported | Nothing deletes preconfirm; partial errors/cancel; native restore; changed file/permission; freed space measured, not promised |

## Developer & security — 17

| ID | Capability | Expected depth | Verification cases |
| --- | --- | --- | --- |
| D01 | JSON formatter | Pretty-print options, preserve data semantics, large-input limits | Unicode/nesting/numeric fixtures; duplicate-key, non-finite and lone-surrogate rejection; exact decimal/exponent preservation; idempotence, parse equivalent |
| D02 | JSON validator | Location-specific syntax errors and strictness policy | Trailing comma, duplicate-key policy, control chars, valid scalars/large files |
| D03 | JSON minifier | Whitespace reduction without data loss | Spaces inside strings, Unicode escape policy, round-trip parse equality |
| D04 | JSON comparison | Structural/path diff, order policy | Reordered keys, missing/null, arrays, numeric/string distinctions |
| D05 | JSON↔YAML | Safe nonexecuting conversion with YAML 1.2 scalar resolution and explicit type/context policy | YAML aliases/tags/bombs, duplicate/non-string keys, booleans/dates/leading zeroes, reverse round trip and loss warnings |
| D06 | CSV↔JSON | Preview delimiter/header/type/null mapping | Quoted newline/comma, Unicode, empty cell/null, type preservation and formula-safe export |
| D07 | Base64 text codec | Encode/decode, standard/URL-safe, binary-versus-text error | Independent vectors, invalid padding/characters, nonUTF8, limits |
| D08 | URL codec/parser | Path/query/component semantics, repeated keys, parse results | Plus/space/slash distinction, percent errors, repeated keys/fragment, round trip |
| D09 | JWT inspector | Decode/claims/expiry display, explicit unverified state | Known token, wrong segments/JSON, never claim verified, no default secret/token retention |
| D10 | Timestamp converter | Seconds/milliseconds/ISO/time zones, explicit input type | Epoch0, negatives, DST, ms/seconds ambiguity, invalid range |
| D11 | UUID generator | Standard versions actually supported, bulk/copy/export | Validate format/version bits, duplicates in reasonable batch, batch limits |
| D12 | Hash/checksum workbench | Text and streaming files, selectable MD5/SHA/CRC, verify comparison | Independent standard vectors, zero/large files, binary correctness, weak-hash labels |
| D13 | HMAC workbench | Input/secret encoding and supported reviewed algorithm | Independent HMAC vectors, empty/nonASCII key, no secret logging/storage |
| D14 | Password/passphrase generator | Secure RNG, selectable constraints, bounds and strength assumptions | Length/classes/policy, rejection of insecure options, no automatic secret history |
| D15 | QR generator | Text/URL payload, size/error correction, local PNG/SVG output | Independent scanner decodes payload, Unicode, capacity limits, safe SVG |
| D16 | Text metrics/case | Defined word/character/line/grapheme counts and casing | Emoji/combining marks, whitespace/newlines, locale casing, empty input |
| D17 | Text diff | Readable side-by-side/unified view, whitespace/line-ending policy | Insert/delete/change, Unicode, large input, HTML escaping, export patch/MD |

## System/network — 5; audio — 2

| ID | Capability | Expected depth | Verification cases |
| --- | --- | --- | --- |
| N01 | System information | OS/CPU/memory/basic hardware support, redacted shareable report | Native adapter fixtures, unsupported fields, no serial/device IDs in generic report |
| N02 | Resource overview | Actual CPU/memory usage sampling, restrained refresh | Load/idle references, paused refresh, bounded CPU cost, denied/unsupported states |
| N03 | Network interface view | IPv4/IPv6/VPN/multiple interfaces, private-data warning | Multiple/disconnected adapters, IPv6, copy/export with explicit selected data |
| N04 | DNS lookup | Record type/resolver/timeouts, explicit network requirement | Controlled A/AAAA/MX/TXT, NXDOMAIN, timeout, no shell interpolation |
| N05 | Ping diagnostics | Safe target validation, latency/loss, supported adapter/permissions | Controlled success/loss/timeout, permission/unsupported OS, cancellable run |
| A01 | Local dictation | Verified on-device engine, mic permissions, languages and model download explicit; audio import only if supported | Offline network capture, native mic permission denial, noise/language fixtures, no Web Speech locality assumption |
| A02 | Meeting notes | Editable transcript and evidence-linked actions/decisions; regex mode labelled; semantic model only if reviewed/local | Negated/ambiguous tasks, mixed positive/negative contrastive clauses, pending decision language, no invented actions, timestamps/source links, MD/HTML/PDF exports, redaction/no default recording retention |

## Shared tabular workbench (not extra tool-count inflation)

Retain/complete existing CSV/TSV/XLSX/JSON/YAML/HTML/SQL conversion engine, including visible supported pairs, encoding/delimiter/sheet/type/null options, preview, SQL identifier/dialect handling, source fidelity and named batch exports. Tests: independent parser/importer, nested data-loss warnings, date/leading-zero preservation, Unicode/newline/quotes, invalid pair errors, formula-injection defenses, ZIP archive content and output collisions. Reuse D05/D06 rather than implementing duplicate converter code.

## Shared exports: useful for people, spreadsheets and AI chats

Export is a common local service driven by immutable typed results, not repeated per-tool code or DOM screenshots. Formats appear only when meaningful. An existing saved result must remain exportable without rerunning its engine. Preview is not completion: tests parse/render the real generated file.

| Format | Expected product depth | Acceptance tests |
| --- | --- | --- |
| Markdown `.md` | AI-chat-friendly context pack: title, inputs, units/assumptions, result, tables, original/export times, caveats; fenced code for code output; copy/download | Table/pipe/newline escaping, code fence/backtick handling, long tables, provenance preserved, no instruction injection added by renderer, no automatic chat upload |
| HTML `.html` | Self-contained readable report with bundled styles, semantic tables/headings; optional print view; no external tracking/resources | Open offline, keyboard/screen reader, escaped untrusted content, no scripts/remote requests, print layout, light report background |
| PowerPoint `.pptx` | Editable summary deck: context, principal result, table/chart, assumptions; split long content into sensible slides; no “screenshot on one slide” | Open in PowerPoint/LibreOffice, editable text/charts where supported, no clipping/overflow, fonts/fallbacks, unicode/numbers, provenance/notes, external relationships absent |
| PDF `.pdf` | Searchable printable report; repeated table headers, pagination, selected sections and assumptions | Render all pages, extract text, complete numeric rows, fonts, no footer overlap, long headings, signed input context |
| CSV/XLSX | Structured numeric data, currency/units/schema; CSV uses typed long-form rows and explicit row/column indices; optional OfficeKit attribution requires a separate opt-in metadata row; XLSX can use summary/detail sheets | Independent parse/import, exact totals/rows/types, formula safety, locale rules, Excel/LibreOffice, attribution omitted by default |
| PNG/JPEG | Shareable summary image, not app chrome; PNG preferred for text | Decode actual file, text readable at intended scale, white background, sizes, selected branding/metadata |
| JSON | Versioned machine-readable result bundle for automation/AI attachments | DTO/schema validation, round-trip, finite numbers/units, no secret/internal/device fields |
| ZIP bundle | User-selected report/data/artifacts with a manifest and checksums; complete offline handoff | Extract safely, named contents/hashes match, no unexpected inputs/secrets included |
| Copy | Single value or full context explicitly distinguished | Actual clipboard representation, unicode/tab/newline, permission failure surfaced |

Attribution: removable `Generated with OfficeKit · officekit.app`, no tracking parameters/pixels; timestamps include timezone; optional creator metadata off by default; CSV attribution, when explicitly enabled, is a metadata record rather than mixed into numeric data. Converted user PDFs/images remain unbranded unless explicitly requested. Provide a **Prepare for AI chat** preset that generates/copies Markdown or JSON with selected context and an explicit local preview. It does not require an AI subscription, send files to a provider, treat document text as instructions, or silently include names/paths/tokens. Redaction/omission and compact versus complete tables are explicit, with a truncation notice if selected. Chat/provider integrations are separate future opt-ins, not launch scope.

## Abundant value without bloating the UI

| Value feature | Why customers use it repeatedly | Depth/acceptance |
| --- | --- | --- |
| Batch everything appropriate | Saves repetitive work, rather than marketing another variant | Per-file outcome/retry, naming/collisions, folder/ZIP export, cancellation and bounded resources |
| Presets | One click restores frequently used options | Versioned options, name/edit/delete, restore across restart, engine-option upgrade/missing capability handling |
| Fixed typed recipes | Combines useful existing engines | Image resize→WebP→compress→strip metadata; PDF merge→compress→number; validate compatibility, preview, partial failures and safe intermediates; defer visual workflow editor |
| Favorites/recents/history/saved | Users don't reconstruct prior work | Restart persistence, immutable originals, reuse-input new run, missing-file recovery, retention and secret exceptions |
| Compare scenarios | A decision-ready result, not isolated calculator numbers | Loan/finance side-by-side from snapshots with shared assumptions and clear differences; export comparison report |
| Local-first processing | Useful without connection, privacy/provider costs | Network capture verifies no document uploads; online-tool labels; model downloads explicit |
| Fast discovery | A coherent toolbox instead of a giant grid | Category Gallery/List, aliases/exact routes, keyboard search, supported-tool visibility, no fake “123 tools” counter |
| Share-ready reports | Finish the work inside OfficeKit | All relevant local formats, editable PPT, clean CSV/JSON/MD, branding off, complete context |
| Reliable desktop delivery | Purchase works on a clean computer | Three-OS native packaging, scoped adapters, signed updates, good errors/docs and measured resource limits |
| Fair ownership | Low purchase/activation/support friction | Free/Paid build separation, per-key 1/N device allowances, clear offline/transfer tradeoffs; no telemetry coercion or secret issuer keys |

Success indicators: task completion/fidelity, user-reported time saved, repeat workflow use, fewer correction/retry steps, and support burden. Anonymous aggregate usage is optional and cannot alone prove willingness to pay. No guaranteed “everyone sees value” claim; validate with target users completing real document, image and finance workflows, and fix the top failure patterns before catalogue expansion.

## Architecture and delivery

Tauri shell already migrated; finish backend packaging/startup/shutdown and safe typed commands before claiming delivered-tool coverage. Shared PDF/image/calculation/conversion/filesystem engines, local SQLite records/artifacts, fixed typed recipes, report/export adapters and platform interfaces. One registry drives gallery, search, availability, favorites and tests. Keep React/TypeScript source/build single-source; native/engine boundaries own paths, permissions and paid-operation authorization. All licensing, updates/announcements and optional analytics network purposes remain separate.

| Milestone | Required deliverable | Release claim |
| --- | --- | --- |
| M0 | Exact inventory/manifest, library-license/native dependency review, packaged PDF/image/calculator spike | Technical baseline, no 123-tool claim |
| M1 | Approved light/dark UX + 20–30 complete tools, exports/history, critical existing formula fixes | Honest smaller paid preview/launch if desired |
| M2 | Batch/presets/recipes + 50–70 complete capabilities + Free/Paid activation | Publish only verified capabilities |
| M3 | Complete all mandatory matrix rows and safe platform adapters, reports, privacy/feedback/updates | 123-capability release only once all rows pass |
| M4 | User acceptance, clean installs/upgrades, signed delivery and support docs, regression/fidelity matrix | Public launch with transparent limitations |

If a capability cannot pass license/fidelity/safety/platform gates, mark it blocked with an explicit replacement/scope decision; do not substitute a shallow variant just to meet the count. Estimates follow M0; no invented deadline. Planning should be one parent release ticket, with implementation split into engine/workflow-sized children after approval, each referencing its matrix IDs and gates. This request creates one detailed planning ticket, not 123 individual issues or an immediate implementation instruction.

## Product-wide release checklist

- [ ] 123 manifest capabilities trace to matrix IDs; exports/batch/mode options not counted again.
- [ ] Every available capability has exact UI and native/API wiring, D3 contract and D4 evidence.
- [ ] Independent formula/codec/fixture results, not just nonempty bytes or broad value thresholds.
- [ ] Complete reports/exports open in independent readers; Markdown/HTML/PPT fixtures pass.
- [ ] Originals preserved, scoped file access, invalid/oversized/malicious input bounded; archives and cleanup safety tested.
- [ ] Favorites/recents/saved records and managed artifacts survive restart/upgrade; secret policies and missing artifacts work.
- [ ] Category Gallery/List/search/accessibility/theme/zoom/localization across complete screens.
- [ ] Free artifacts exclude paid implementations; signed per-device entitlements enforce server-owned 1/N allowances; recovery and offline limitations documented.
- [ ] What's new/version history, signed update alerts and one dismissible relevant communication banner.
- [ ] Bug/feature/testimonial submissions have honest remote acknowledgment and optional redacted diagnostics/publication consent.
- [ ] Usage/heartbeat off by default and independent; consent revocation purges queue; no sensitive payloads or undisclosed impression analytics.
- [ ] macOS/Windows/Linux supported targets install on clean machines without developer Python/codecs, start/stop engines, and update without losing records.
- [ ] Real user acceptance covers at least document workflow, batch-image workflow, finance/scenario workflow, AI-context handoff and file/storage inspection; record time-to-completion/errors and resolve top issues.

References: `docs/PRODUCT-PLAN.md`, `docs/TOOL-GUIDE.md`, `docs/TESTING.md`, `docs/COMMUNICATIONS-PLAN.md`, `DESIGN_SYSTEM.md`, `design/COMPONENT_STRUCTURE.md`. The inventory is a capability target with reusable engines; availability/licensing/performance/platform support must be demonstrated, not inferred from a candidate list.

## Meeting notes formatter update (2026-10-07)

The shared meeting-notes formatter now accepts only a strict transcript field, caps input at 262,144 characters, rejects extra/oversized/non-string API input, avoids inventing fallback actions, evaluates contrastive clauses independently so a negative statement does not mask a separate positive commitment, excludes explicit “no decision”, pending and non-final decision statements, escapes transcript-derived Markdown fields, and fences the original transcript safely. Engine and HTTP regressions cover mixed positive/negative clauses and pending decisions. This remains a heuristic text formatter; semantic summarization, diarization, speech capture, and curated classification accuracy are still open. It is not release-verified.


On 2026-10-08, Meeting Notes now keeps common tentative “will” phrases such as “will try,” “will probably,” and “will be trying” out of confirmed actions, retaining them as key points while direct commitments remain actions. Engine and HTTP edge cases plus the authenticated packaged-sidecar smoke cover the phrases and positive control. Classification remains heuristic, D1, and not release-verified.

## PDF page-management implementation and verification (2026-10-07)

P04 delete-pages and P05 reorder-pages now have the approved thumbnail workbench, exact gallery/search routes, bounded ordered previews (24 pages per request), separate output PDFs, and keyboard/button/drag interactions. Deletion cannot remove every page and is clearly distinguished from secure redaction. Engine and endpoint tests cover ordering, source preservation, invalid selections, internal references, page/output caps and malformed inputs. The rebuilt macOS arm64 sidecar smoke checks PNG signatures and order, then renders deletion/reorder outputs to verify page geometry and order; the rebuilt app and mounted DMG pass packaging smoke. Cross-platform support and broader PDF-reader fidelity are still release gates.
 On 2026-10-07, system information and CPU/RAM overview gained searchable manual-refresh screens. Strict client checks verify redacted report text, CPU/RAM arithmetic, bounds and unsupported-platform errors; the packaged sidecar already validates both local routes. Interactive desktop visual verification remains unavailable in this session.

## Developer utilities workbench (2026-10-07)

The searchable UI now connects the existing JSON formatter, JSON↔YAML operations, Base64, JWT decoder and hash/HMAC endpoints. Source tests validate search routing, strict response schemas, UTF-8 bounds, unverified-token disclosure, transient secrets, copy/download/clear controls and safe error text. These API-backed tools have not yet been individually release-verified; packaged input/response smoke and installed visual interaction remain required.


## Selected-copy file inspection (2026-10-07)

The workspace now exposes checksum generation (SHA-256/SHA-512) and content-based type detection. UI clients validate exact response schemas, record order, digest lengths, MIME/type bounds, byte totals and relative filenames before rendering. Search and malformed-response regressions pass. The application rebuild and authenticated package smoke remain the release evidence gate for these new routes; tool-level release verification remains 0/123.


## Statement locale controls (2026-10-07)

The bank statement upload now exposes the backend-supported number-locale and date-order options, with automatic interpretation as the default and explicit guidance to review ambiguous values and reconciliation. The form-data helper has unit coverage for every valid option and rejects unsupported values. Full multi-bank OCR/layout and accounting-importer checks remain open.


## Storage analysis folder totals (2026-10-07)

The selected-copy storage screen now displays recursive folder totals, explains overlap, and reports partial scan errors and skipped symbolic links. Its client validates exact DTO shape, relative names, byte/size arithmetic and scan-state consistency. Source tests pass; broader partial-scan and installed visual verification remain open. The tool is D2, not release-verified.
