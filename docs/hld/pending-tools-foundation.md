# Pending tools foundation: per-slice slots for parallel delivery

Version: 1.2.0 · 2026-10-22 · Match the built foundation: slice asset names, `openView`/`sliceView` hook, slice-owned PDF/calculator chains.

## Problem and scope

Slices 2–6 (calculators, developer, files, image, PDF) will be built by five agents in parallel worktrees. Today every new tool edits the same lines in about 12 shared files, so parallel branches would conflict throughout. This foundation PR gives each slice its own files and replaces hardcoded counts with derived ones. It is a refactor with **no user-visible change**, so no mock is needed. It adds no tools, routes or stored data. See ADR 2026-10-22 in `docs/ARCHITECTURE.md`.

Slice keys: `calculators`, `developer`, `files`, `image`, `pdf_tools`.

## Slots

| Hot spot today | Slot after the foundation | Owned by |
| --- | --- | --- |
| `TOOL_REGISTRY` tail and `TOOL_SEARCH_KEYWORDS` in `engine_comms.py` | `officekit/tool_catalog/<slice>.py` exports `TOOLS: list[dict]` and `KEYWORDS: dict`. `engine_comms.py` builds `TOOL_REGISTRY = CORE_TOOLS + catalog.slice_tools()` in a fixed slice order, and the same for keywords. Existing entries stay where they are. | slice |
| Inline `@app.post` routes, the `path_limits` body-cap map and CORS `expose_headers` in `app.py` | `officekit/routes/<slice>.py` exports `router: APIRouter`, `BODY_LIMITS: dict[str, int]` and `EXPOSE_HEADERS: tuple[str, ...]`. `app.py` includes all five routers once and merges `BODY_LIMITS` into `path_limits` and `EXPOSE_HEADERS` into the CORS list. The route-map equality test reads the merged map. New paths use plural nouns (`.claude/se-rules/rest.md`); existing verb paths are not renamed. | slice |
| `requirements.txt` and bundled fonts | The foundation adds every new shared dependency once: `tzdata` (calculators, developer), `regex` (grapheme counts), and one bundled OFL Noto Sans for Latin text (PDF watermark, image contact-sheet labels) plus its licence note. Test-only: `zxing-cpp` if OpenCV can't decode Unicode QR payloads. Slices don't edit `requirements.txt`. | foundation |
| `OFFICEKIT_TOOL_DESTINATIONS` and `shellTabs` in `index.html` (edited by every slice) | `assets/officekit-slice-<key>.js` calls `window.OfficeKitExtensions.register({ slice, destinations, tabs, openView })` as its first statement. `selectSearchTool` looks up `officekitToolDestination(id)`, which checks the core map first and then the extensions. `switchTab` includes the registered tabs. A destination's `sliceView` is passed to that slice's `openView`. A slice's own screens are built by its JS inside a tab it registers, following the ergonomics pattern. | slice |
| `switchCalc` list, calculator pills/forms, the 8 PDF-op chains, the developer select and `officekit-files.js` | No hook is needed, because exactly one slice edits each of these (calculators, PDF, developer and files respectively). The PDF slice also groups the nav into the five approved sections. | that slice |
| `<script src>` / `<link>` tags in `index.html` and the copy list in `scripts/build-ui-assets.mjs` | The foundation pre-creates five stub `assets/officekit-slice-<key>.{js,css}` pairs, their tags and their copy entries. Slices edit only their own pair. | foundation |
| Inline-script CSP hash in `tauri.conf.json`, `dist-ui/**`, minified `officekit.css` | Any slice that edits the inline script changes the hash. These files are generated, and the integrator runs `npm run build:ui` after each rebase instead of hand-merging them. | integrator |
| Count literals: `ui-search-routing.test.mjs:173` (58), `first-release-scope.test.mjs:10` (58), `tool-guide-counts.test.mjs:35-39`, `TOOL-GUIDE.md` counts table | Tests read the live catalogue through `scripts/tool-catalog.mjs`, which runs `python3 -m officekit.tool_catalog --json`. They no longer parse `engine_comms.py` source text. `scripts/tool-counts.mjs` regenerates the TOOL-GUIDE rows *Search catalogue entries* and *Pending-tool slice entries*, and a test fails when they are stale. This fixes the existing 57-vs-58 drift. | foundation |
| `scripts/officekit-tool-audit.mjs` and the two tests that parse `TOOL_REGISTRY = [` source text | Same JSON dump. | foundation |
| `FIRST-MAC-RELEASE.md` and `TOOL-GUIDE.md` rows | Five pre-created headings, `## Development-only: <slice>`, with no counts in the headings. Each slice adds rows only under its own heading. Beta-section counts are untouched because the new tools are development-only. | slice |
| `API-CONTRACT.md` rows | Five pre-created sections, `### Pending tools — <slice>`. Each slice adds rows only in its own section. The line-3 version header is the one remaining shared line; the integrator resets it at rebase. | slice / integrator |
| `docs/VERSION-HISTORY.md` prepend | Conflicts here are trivial (keep both rows). The integrator resolves them at rebase. | integrator |
| `dist-ui/**`, minified `officekit.css` | Generated. They are never hand-merged; the integrator runs `npm run build:ui` after every rebase. | integrator |

Slice-local files (`engine_file_jobs.py` kinds for files, `officekit/mcp/registry.py` for calculators, `release-profile.json` route entries for F06/F07/F12) are edited only by their own slice and need no slot.

## Extension hook contract (`window.OfficeKitExtensions`)

```js
window.OfficeKitExtensions.register({
  slice: 'image',                          // one of the five keys; each registers once
  destinations: {
    image_rotate: { tab: 'image-tools', sliceView: 'rotate' },
    pdf_rotate: { tab: 'pdf', pdfTool: 'rotate' },          // existing options still work
  },
  tabs: ['image-tools'],                   // shell tabs this slice adds
  openView: view => { /* show the slice screen for this view */ },
});
```

Rules:
- An unknown slice, a second registration, a duplicate or core-overriding destination ID, a duplicate tab and a non-function `openView` all throw. Tests cover each case.
- Each destination is written as one `id: { tab: '…', … },` line inside the first `register()` call. `ui-search-routing.test.mjs` and `scripts/officekit-tool-audit.mjs` parse those lines alongside the inline map, and assert they match the live catalogue IDs.
- Keep DOM work lazy: inside `openView` or a tab handler, never at the top level of the file.

## Integration flow

1. Foundation PR, branch `feat/pending-tools-foundation` from main. CI green, then merge.
2. Five worktrees branch from the new main: `feat/pending-<slice>`. Each Haiku agent builds its engine, router and tests at once. It starts on the asset JS and docs rows only after the owner approves that slice's mock.
3. Merge order, lowest risk first: developer → calculators → PDF → image → files (track A). Before each merge the integrator does four things: rebase on main; resolve the `VERSION-HISTORY.md` and `API-CONTRACT.md` header conflicts; run `npm run build:ui` and `node scripts/tool-counts.mjs`; run `npm test` and `cargo test`. The PR merges only after CI is green.
4. Files track B (F11 symlinks, S06 restore) is a separate PR. It starts only after its native-authority design is approved.

## Pitfalls check

- P-150 / P-123: beta counts still come from `release-profile.json`; the new tools are not added there.
- P-111: the CSP hash changes only in the foundation PR. Slices change external assets only, and the integrator rebuilds after rebase.
- P-120: gallery size stays derived from search results; no hardcoded count is introduced.
- P-108 / P-124 / P-130: the extension lookup keeps current release-discovery loading and failure behaviour, because it only adds to the existing maps.
- P-036: router body caps are merged into the single pre-parse map, and the route-map equality test covers them.

## Verification

- Existing suites pass unchanged in behaviour (`npm test`, `cargo test`).
- New tests:
  - registry merge order and uniqueness;
  - `register()` duplicate rejection and the no-override rule for core entries;
  - destinations equal registry IDs across inline and extension sources;
  - stale `tool-counts` block detection;
  - router `BODY_LIMITS` included in the route map.
- `dist-ui` is rebuilt and the app is smoke-run once: search opens existing tools exactly as before.

## Open questions

None blocking. The integrator role (rebase, regenerate, merge) stays with the main session, not a subagent.
