# HLD: Archive Manager

Version: 1.0.5 · UI approved: user “looks good”, 2026-10-18.

## Goal

Extend OfficeKit’s current ZIP-only file action into a local archive manager for macOS and Windows. Users can browse archive entries and nested archives, extract selected entries or a full archive, and create archives in formats the installed bundled engines can write. The user-provided 42-format list is represented in an explicit capability registry. Read, extract and create support are reported separately; unsupported combinations are not offered.

## Decision and options

The user approved the proposed mock and cross-platform direction with “looks good” on 2026-10-18. The selected architecture is a packaged multi-engine adapter with conservative per-format capabilities. The initial implementation currently packages 7-Zip only; libarchive and Unarchiver remain future adapter work, and the registry marks operations unsupported until their code is present.

1. **Packaged multi-engine adapter (recommended and selected).** Bundle compatible 7-Zip, libarchive and Unarchiver command-line engines for both desktop platforms; choose a fixed engine from a checked-in capability registry. Pros: local operation, consistent UX, broad coverage, no user setup. Cons: larger installers, per-platform packaging and license notices, capability differences remain. Effort L; risks include malformed archives, hostile metadata, subprocess isolation and platform-specific packaging.
2. **User-installed engines.** Detect a compatible utility on PATH. Pros: small installer and straightforward packaging. Cons: missing tools, versions and behavior vary by machine, and poor first-run experience. Effort M; high support risk.
3. **Native OS APIs only.** Use Archive Utility/Compression on macOS and Windows Shell APIs. Pros: no extra engine payload. Cons: format support and browsing behavior diverge, with limited selective access. Effort M; insufficient for the requested format set.

MacPacker is a product-behavior reference only. Its GPL-3.0 application code is not incorporated into the commercial OfficeKit product. The engine adapter uses separately licensed, redistributable engines and ships their required notices/source offer or corresponding materials. The LGPL and BSD engines must be packaged in a way that satisfies their licenses; the 7-Zip unRAR restriction is reviewed before enabling affected RAR operations.

## Boundaries

- `officekit/engines/engine_archive_manager.py` owns the 42-format registry, pinned 7-Zip resolution, bounded entry manifests and archive listing. Nested archive browsing is not implemented yet.
- `officekit/engines/engine_file_jobs.py` continues to own the existing direct selection and output grant lifecycle; archive creation extends its existing `archive-create` job.
- `app.py` exposes the format registry and bounded entry listing through a live native selection. Archive sessions and nested browsing are not implemented yet; selected entry extraction uses the existing file-job route.
- `src-tauri/` retains native file and destination picker authority. Backend code receives selection IDs and output grants, never arbitrary UI paths.
- `assets/officekit-files.js` and the existing direct file panel in `index.html` present browse, extract and create actions. No separate duplicate file-picker workflow is added.
- Bundled archive engines are pinned and placed with the packaged sidecar at build time for the current target triple; commands use fixed executable paths and argument arrays with `shell=False`.
- No database or tenant data is involved. The current browser reuses native file selections, which expire through the existing selection store; archive-specific sessions and persisted metadata are not added.

## Contract outline

- `GET /api/archive-formats`: exact registry of requested formats with separate `read`, `extract`, and `create` capability states/reasons.
- `GET /api/file-selections/{id}/archive-entries`: bounded root listing through a live selection; the current endpoint returns one page and no nested navigation.
- Future archive session endpoints will add nested browsing after safe staging and cleanup for nested archive inputs are implemented.
- Existing `POST /api/file-jobs` archive creation remains the creation job contract; its strict options add a registered create format. Existing cancellation, status and result routes remain in use.

The exact DTO keys, status codes and byte/count bounds are finalized in `API-CONTRACT.md` with the implementation.

## Safety and failure behavior

- Detect the format from content where possible; extensions are hints only.
- Reject absolute paths, `..`, alternate separators, duplicate normalized entries, unsafe links and special device entries before an extraction can publish output.
- Bound archive bytes, expanded bytes, entry count, nested depth, subprocess wall time and captured diagnostic bytes. Never return raw engine diagnostics to the UI or log file contents.
- Extract into a private staging directory. Verify selected output identities and the destination grant, then publish without following links or overwriting existing files.
- Use platform-specific safe directory operations on macOS and Windows; unsupported safe publication fails closed.
- A password is not collected or stored by this initial scope. Encrypted entries report a clear unsupported/password-required result; no implicit retry or external network behavior.
- Cancellation terminates the active engine process and removes only staging files owned by the operation.
- Unsupported, corrupted, encrypted and partial formats return stable error codes and no partial destination.

## UI decision

The approved mock was `design/mocks/archive-manager.html` (temporary preview removed after approval). The current UI adds archive entry browsing and selection to the existing file panel. ZIP uses the built-in bounded extractor. Fully supported bundled 7-Zip formats use an isolated extraction process after validating every listed path, then verify the staged tree before no-replace publication. Partial format variants remain browse-only. ZIP creation remains available, and additional creation formats are future work. The existing native file picker and destination grant remain the authority. UI tokens continue to come from `DESIGN_SYSTEM.md`.

Approved words: “looks good” (2026-10-18).

## Validation plan

Cover every format adapter with synthetic archive fixtures where licensing permits; include malformed input, traversal, links, collisions, nested depth, encrypted inputs, huge expansion, cancellation, output-grant mismatch, overwrite races and unsupported capability cases. Verify packaged macOS and Windows builds plus desktop/compact UI flows. The current task did not request tests to be run; verification is reported separately from implementation evidence.
