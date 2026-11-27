# LLD: Archive Manager

Version: 1.0.7 · HLD: `docs/hld/archive-manager.md` v1.0.5.

## File map

| Path | Change | Contract reference |
| --- | --- | --- |
| `officekit/engines/engine_archive_manager.py` | Add the requested-format capability registry, target-specific pinned 7-Zip resolution and bounded root listing with entry-path validation. | `ARCH-FORMATS`, `ARCH-ENTRIES` |
| `officekit/engines/engine_file_jobs.py` | Add strict archive create/extract options, selected entry extraction, bounded 7-Zip extraction for fully supported formats, and private staging with no-replace publication on both platforms. | `ARCH-CREATE`, `ARCH-EXTRACT`, existing file job and output grant contracts |
| `app.py` | Add capability and selected-file archive listing routes; preserve native grants and generic error responses. | `ARCH-FORMATS`, `ARCH-ENTRIES` |
| `scripts/build-backend-sidecar.mjs` | Add the pinned per-target 7-Zip executable and Windows DLL to the frozen sidecar resources. | HLD engine packaging and native-grant boundary |
| `assets/officekit-files.js` | Add root entry listing, entry selection, all/selected extraction control, ZIP creation format choice, and an explicit warning when a selected format is unsupported or browse-only. | Approved initial UI mock and approved unsupported-format notice; `ARCH-*` |
| `index.html` | Adjust the existing direct file panel structure for archive browsing and creation without introducing another file-selection owner. | Approved UI mock; `ARCH-*` |
| `officekit/engines/engine_comms.py` | Update the existing archive tool’s description/discovery aliases only if the current registry wording requires it. | No API change |
| `API-CONTRACT.md` | Document implemented route/DTO shapes, limits and error codes after backend endpoints exist. | `ARCH-*` |
| `docs/TESTING.md` | Add archive manager acceptance and package verification guidance. | `ARCH-*` |

## DTO and state outline

- Format descriptors use exact keys: `id`, `label`, `extensions`, `read`, `extract`, `create`, `limitations`. Capability values are `supported`, `partial`, or `unsupported`; each non-supported capability includes a concise reason.
- Entry DTOs contain exact keys: `id`, `name`, `kind`, `size_bytes`, `compressed_bytes`, `modified_at`, `extractable`, and `nested_archive`. `id` is opaque and server-validated; client-supplied paths are not accepted.
- Listing accepts `offset` 0–10,000 and `limit` 1–200; nested `directory_id` navigation is future work. No absolute paths or engine switches cross the API boundary.
- Extraction accepts 1–500 entry IDs or an explicit `all=true`, never both. It requires the native output grant header and a new destination directory grant.
- Creation accepts a source selection ID and a format ID from the registry; names are path-safe relative names. Writer options stay format-specific and bounded.
- The current listing is a bounded read over an existing native selection, with no additional session store. Nested navigation and session cleanup are future work. No database, user-controlled tenant or persisted archive metadata.
- When a selected format is marked unsupported, the archive panel names the format, says it cannot be opened or extracted, and suggests ZIP, 7z, or TAR. Browse-only formats state that extraction is unavailable; extraction stays disabled.

## Engine process rules

- Resolve engine executables only beneath the packaged resource root; verify they are regular executable files with the expected manifest hash at startup.
- Invoke with argument arrays and `shell=False`; pass member selections using engine-supported safe arguments or validated staging paths, never command-line interpolation.
- Set a minimal environment, fixed private working directory, process-group/session isolation, bounded stdout/stderr, and wall-time/CPU limits.
- Engine output is treated as untrusted. Parse a defined machine-readable listing when available; otherwise normalize line records through a strict parser and reject ambiguous names.
- All engine extraction targets a private staging directory. Revalidate resulting paths and file types before no-replace publication. Never allow a backend engine to mount images or execute embedded files.
- Keep the tested capability registry conservative: read/list support, extract support, and create support are separately recorded. A version change cannot silently expand capabilities.

## Failure model

Use stable internal codes: `unsupported_format`, `partial_format`, `encrypted_archive`, `invalid_archive`, `unsafe_entry`, `limit_exceeded`, `engine_unavailable`, `engine_timeout`, `destination_changed`, `cancelled`. UI messages do not include raw output or local source paths. Engine failures remove operation-owned staging content; they never modify the source archive.

## Implementation checkpoints

1. Initial delivery: package 7-Zip for macOS/Windows and expose supported root listing formats.
2. Initial delivery: preserve ZIP creation, add selected-entry extraction, and safely extract the fully supported bundled 7-Zip formats after staging and output verification; partial variants are browse-only.
3. Remaining: add libarchive/Unarchiver adapters, nested archive navigation, broader extraction/creation, packaged format fixtures and review.

## Verification coverage

- `tests/test_archive_manager_unittest.py` checks all 42 capability states, longest-extension detection, real bundled ZIP listing and extraction, source preservation, and rejection of traversal paths.
- `tests/test_direct_file_api.py::test_archive_capability_route_and_native_zip_listing` checks the capability DTO and a ZIP listing through a native-authorized file selection.
- Source tests do not establish Windows runtime extraction, installed native picker behavior, or real app-bundle launch; those require platform build and smoke evidence.
