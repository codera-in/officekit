# OfficeKit UI component structure

Version: 1.2.5 · Proposed long-term architecture; current reusable controls use daisyUI 5.7.50 with Tailwind CSS 4.3.3. App-wide consistency revision, 2026-10-12; component library adoption and upgrade, shared control dimensions and semantic action colors, 2026-10-15; shared title hierarchy and persistent tool actions, 2026-10-16; Apple Pro UI revamp (Liquid Glass AppBanner, ProgressBarSystem, SttFloatingHud), 2026-10-17.

All page titles inherit `--ok-title`. Result publishers retain their action controls and immutable snapshots; `assets/officekit-tool-actions.js` presents active task/result controls in a shared reserved area below `#app-main`. Existing controls retain DOM/form ownership. The workspace column reserves the measured action height; fixed controls never cover output. Browsing screens omit the bar. File reports use daisyUI tables, and duplicate rows use daisyUI checkboxes with a retained-file badge. Current approval: `docs/ui-research/2026-10-16-approved-persistent-tool-actions.md`.

## Current component implementation

Use daisyUI 5.7.50 classes for reusable buttons, fields, selects, toggles, checkboxes, ranges, tabs, dialogs and other library-provided UI in both static HTML and runtime-created tool screens. Do not add a custom implementation where daisyUI provides the component. App-specific canvas editing and file dropzone behavior can stay custom where the library has no equivalent; controls placed inside those surfaces still use daisyUI.

The shared control contract in `DESIGN_SYSTEM.md` is enforced at the app shell: 40px standard buttons and single-line fields on desktop; 44px minimum targets at 900px and below; 160px minimum textareas; Ice Blue primary actions in both themes. Use semantic success, warning and error variants only for their matching states. Tool-specific padding utilities may change horizontal spacing, but must not invent a different control height or primary-action color. Content that needs more than one line can grow naturally.

Apply this to the Tauri app incrementally. The current `dist-ui/index.html` is a built asset; establish a frontend source/build pipeline before adopting React/TypeScript structure. Do not maintain divergent editable copies in root and dist-ui. This plan introduces no runtime dependencies or endpoints.

```text
src/
  app/                 AppShell, router, ThemeProvider, AppBanner, ProgressBarSystem, SttFloatingHud, startup
  design-system/       tokens, BrandMark, Button, Field, Dialog, StatusMessage
  tools/               registry, ToolRoute, per-engine tool screens
  results/             ResultView, ResultActions, AssumptionDetails, ResultTable
  history/             HistoryPage, HistoryFilters, HistoryRow, SavedResultPage
  exports/             ExportDialog, ReportPreview, format capabilities
  settings/            AppearanceSettings, PrivacySettings, RetentionSettings
  feedback/            FeedbackForm, DiagnosticsPreview, SubmissionStatus
  application/         typed services and query adapters
  contracts/           generated/shared DTOs, registry and result schemas
```

Avoid a component for every minor layout div or one field. Extract a component when behavior, accessibility or repeated meaning warrants reuse. Engine-specific forms stay with their tool; shared result/history/export behavior does not.

| Component | Owns | Must not own |
| --- | --- | --- |
| AppShell | Viewport-bound title/notice/navigation, collapse/drawer state, compact layout, headings, active route | Tool execution, license/analytics side effects |
| AppBanner | Liquid Glass status announcement, release notes, tips, active background task percentage | Blocking content interactions or replacing modal alerts |
| ProgressBarSystem | Multistage pipeline states, animated progress bar, indeterminate shimmer | Mutating task jobs or fabricating artificial progress percentages |
| SttFloatingHud | Siri/Dynamic Island floating overlay, live audio equalizer soundbars, real-time transcription | Microphone hardware permissions administration |
| ThemeProvider | OS appearance and local preference | Branding changes per tool |
| BrandMark | One approved SVG and size/monochrome variants | External asset fetching |
| ToolSearch | Local query, matching, keyboard destination | Network requests, tracking search strings |
| ToolCatalogue | Registry-backed category grouping, counts, Gallery/List and filter/view preferences | Divergent gallery/list registries, promotional storefront UI |
| ToolRoute | Stable tool ID and capability availability | Listing unavailable tools as usable |
| ToolForm | Field validation, unit/currency labels, submission | Direct filesystem access or database writes |
| ToolRunner adapter | Execution service calls and typed status | Tool-specific presentation |
| ResultView | Immutable snapshot presentation and stale-input notice | Recalculating a reopened result |
| ResultActions | One ordered Copy/Download/optional Save row, immutable result scope, awaited feedback | A separate history implementation per tool, duplicate floating toolbars |
| ExportDialog | User-facing Download dialog, capability-filtered formats/content/attribution, filename and preview | DOM screenshots, unsanitized metadata, network exports, unsupported format choices |
| HistoryPage | Shared filters, pagination, empty states | Independent per-tool tables/databases |
| SavedResultPage | Original snapshot, label, reuse-input action | Mutating the underlying original result |
| PrivacySettings | Consent and payload explanation | Implicit consent from licensing or app use |
| FeedbackForm | Intent-specific fields, diagnostic preview | Fabricating delivery/triage |

## Proposed typed boundaries

ToolManifest: stable id, name, category, aliases, route, availability/platforms, permission requirements, input/output schemas, result/export capabilities, and retention policy. Metadata alone grants no access.

ResultSnapshot: operationId, toolId, schemaVersion, engineVersion, createdAt, permitted immutable input/assumption data, typed summary/table sections, units, and artifact references. History metadata and sensitive contents have distinct retention policies. Finite numeric values only. SavedResult: id, operationId, title, savedAt. Favorite: toolId and optional order. RecentTool: toolId and lastOpenedAt.

Define engine-specific result DTOs and a small common presentation model; avoid an untyped result blob masquerading as a universal schema. A single-value converter and file batch do not have to fabricate the same sections. Export capability registration filters formats by result type.

UI → application service → Tauri command adapter → Python/Rust engine and local repositories. Shared contracts validate each boundary. All filesystem operations, safe outputs and database migrations stay outside components. UI asks to export/save; it does not obtain broad shell permissions. A separately consent-aware collector receives sanitized allowlisted events; engines and UI components never post telemetry independently.

## State ownership

- Route/query and selected history filters: navigation state.
- Form draft and touched fields: tool-local state; reuse inputs seeds a draft.
- Original result: immutable application record keyed by operationId.
- Favorites, bookmarks, recents, theme/retention preferences: local persistence services.
- Dialog visibility, copy notification, current preview: ephemeral UI state.
- Running/cancelled jobs: execution service, not a component lifecycle.
- Consent and bounded queued telemetry: privacy service with send-time checks.

No global state library is selected yet. Begin with existing/native facilities; choose dependencies after source/build and actual contract needs are clear. No invented backend routes in frontend code.

## Consistent tool surfaces

Use three shared layout families from DESIGN_SYSTEM.md: compute/text, files/batches, and canvas/live work. Input/output split is a compute/text variant, not another design system. All families share Button, Field, StatusMessage, ResultActions and Download dialog behaviors. Home is a separate personal shortcut surface with five recents and visible favorites; All tools owns catalogue filtering.

Native filesystem selection creates scoped references to approved original paths, with lightweight session/job metadata in memory. Engines stream reads through application adapters. Components do not copy source trees or access arbitrary paths. Output publication and transactional in-place mutations remain engine responsibilities.

Canvas state separates the immutable source bitmap from editable annotation objects. Selection, dual-color styles, movement, delete and undo/redo feed the same renderer semantics used by preview, clipboard and export. Each result-producing tool declares its actual copy/download capabilities and full snapshot source in the registry-wide adoption matrix before migration.

## Implementation slices after approval

1. Tokens/brand/shell; searchable manifest with exact routes.
2. One calculator with validation, execution and immutable snapshot.
3. Shared exports and persistent saved-result round trip.
4. History/favorites/recents; missing artifact and retention semantics.
5. Adapt conversion and text tools; long-job lifecycle screens.
6. Settings, feedback, optional telemetry consent and ingest.

Each slice must prove behavior beyond its happy path. Review full screens, not isolated component diffs. The proposal prototype uses session-only fixture history and synchronous deterministic calculation; production storage, codecs, PDF rendering, OS permissions and asynchronous jobs are deliberately not implemented there.
