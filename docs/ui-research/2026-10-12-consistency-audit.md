# OfficeKit consistency critique

2026-10-12 · Scoped design/source review, not production visual acceptance.

## Design brief

Everyday desktop users need to find a tool, complete one task and use its result immediately. Register: calm, capable desktop utility. Emotional job: clarity, control and confidence. Retain native/system typography, the approved monogram and existing semantic colors. User direction: "make ux consistent accrrosss the app// user shoudl feel simple. intutive , appelaling".

## Evidence and limits

Reviewed `index.html`, DESIGN_SYSTEM.md, design/COMPONENT_STRUCTURE.md and existing result/file/editor flows. Three focused read-only passes covered consistency, accessibility and shared interaction patterns; primary review synthesized the design. Inspected Home, editor, transcripts, results and files in the Superset Browser mock. No production-browser audit, automated contrast/a11y scan, complete style-token counter or registry-wide coverage claim. Those checks are implementation acceptance work, not invented measurements.

## Improve

| ID | Severity | Current evidence | Required change | Cost |
| --- | --- | --- | --- | --- |
| UI-1 | Major | `index.html` header sticky; notice/rail ordinary flow | One viewport shell with measured chrome, independently scrolling work area and rail | M |
| UI-2 | Major | Home recents/favorites precede full catalogue | Home limits recents to five and exposes favorites; move catalogue browsing to All tools | M |
| UI-3 | Major | Calculator Export/Save, system Copy-only, PDF format buttons | One capability-driven Copy/Download result row; retain full immutable result scope | L across registry |
| UI-4 | Major | File selection explicitly copies to workspace | Native scoped selection of originals, bounded streaming and explicit output destinations | L |
| UI-5 | Major | Screenshot settings/export share long inspector; single-color operation DTO | Contextual tools, visible completion actions, movable/removable dual-color annotations | L |
| UI-6 | Major | Transcript history Open/Remove and clipped preview | Direct full-text Copy and relevant Download using shared feedback | S/M |
| UI-7 | Major | Click-bound brand div, compact search without explicit name, small icon controls | Semantic navigation controls, accessible names and shared 40/44px targets | S |

Every change must preserve existing path/clipboard/output integrity and operation-error recovery pitfalls. Estimates cover relative implementation scope, not promised delivery dates.

## Add

- A per-tool adoption matrix: layout family, inputs/action labels, result source, clipboard representation, download formats, errors/empty/busy states and exceptions. This is the evidence for all-tool completion.
- One consistent Download dialog and native save adapter, with honest cancellation/initiation/write status.
- Explicit annotation selection, keyboard move/delete, dual-color styling and renderer parity.

## Remove

- Mandatory copy/import workspace stage and its implementation terminology.
- Duplicate calculator result action areas; one result row owns all actions.
- Universal unsupported export choices and separate buttons for every format.
- Irrelevant editor settings, buried export controls and repeated local-processing paragraphs on every screen. Keep meaningful privacy/network facts at the relevant boundary and the requested fixed notice.
- Hardcoded combined chrome heights and automatic unlabelled compact navigation. The revised mock uses grid auto rows and a labelled expandable drawer.

## Shared system decisions

Three layout families: compute/text (including split text input/output), files/batches, canvas/live work. One token vocabulary; 40px desktop and 44px compact controls, 6/10/14px radii, 24px section spacing, 3px visible focus outline. Existing contrast floors and reduced-motion requirements remain. No framework rewrite or new visual dependency is justified by this review.

The one craft investment is the working canvas: opening a tool frees space by collapsing navigation and presents only relevant controls. The rest of the app stays deliberately quiet. No animation budget is needed for this behavior.

## Adoption order and gates

Shared primitives/shell → representative scalar/text/table/file/canvas screens → all registry entries → whole-screen review. Preserve tests and semantic snapshot behavior; do not remove controls until their replacement is verified. Design changes remain proposed until exact combined mock review; shared result-action direction was accepted with the user's "ok". Detailed architecture agreement precedes implementation. No product code changed in this design pass.

Research provenance: user requirements and repository evidence drive this revision. Evernote/Preview annotation sources are linked in the requirements document and support familiar toolbar/text/shape conventions; no unsourced award/trend claim determines these rules.
