# Pending file and storage tools: design

Version: 1.0.10 · 2026-10-23 · S06 restore built as option R1 (section 4), on the owner's approval “approved” (2026-10-23, the S06 mock and its disclosure). The disclosure placement is amended from “the confirm dialog” to “before each move, plus the Restore screen”, as the approved mock shows. Earlier: 1.0.9 · 2026-10-23 · F11 selection line: the folder name alone and “Choose a folder to begin.” when empty, as the approved mock shows (review round 2, UX-5). Earlier: 1.0.8 · 2026-10-23 · Amend the B1 design text in section 4 and the threat-model row to the built walk (owner answer “Amend the design text (Recommended)”, review round 1 ARCH-1 and PM-1): inside the selected roots, directories may be opened no-follow and lstat'd to resolve hops; nothing outside the roots is ever stat'd, opened or followed. Coordinator decision (ARCH-2, CR-4, PM-7): relative and absolute targets are resolved the same way, by walking real directories inside the roots, so an absolute target is mapped to a root-relative path and a `..` in it is walked physically. Earlier: 1.0.7 · 2026-10-23 · Record the owner answers for F11: “Keep it (Recommended)” for the `denied` state and “Folder name (Recommended)” for the selection line (section 4). Earlier: 1.0.6 · 2026-10-23 · F11 built as option B1 (section 4 status), on the approved mock of 2026-10-23. Earlier: 1.0.5 · 2026-10-22 · Round 4: owner answer “Refuse (Recommended)” recorded in section 9 for archive output inside the selected folder (PM-10). Earlier: 1.0.4 · Round 3: the empty-folders row records the Windows refusal (ARCH-6); the mock reference points to the approval record (ARCH-7, CR-11). Earlier: 1.0.3 · Round 2: deviations for the owner (compare headline, Windows walk refusal, duplicate member paths) recorded in section 9. Earlier: 1.0.2 · Owner decisions on section 9 (beta reveal route added to release profile; host paths shown; track B order; build choices accepted). Round 1 fixes: the release guard is the engine constant `DEVELOPMENT_ONLY_KINDS` rather than a catalogue flag (ARCH-4); owner answer to add `zip_extract` and `archive_inspector` (UX-4, QA-7); open build choices for the owner (PM-6). Initial draft was 1.0.0.

Slice 4 of `docs/hld/pending-tools-and-ergonomics.md`. Requirements: `review/pending-tools-slices/requirements.md`. The ADR is in `docs/ARCHITECTURE.md` (2026-10-22). Mock: approved 2026-10-22 as the v3 re-mock (UX-11). The HTML is removed from the worktree as `AGENTS.md` requires; the approved decisions are in `docs/ui-research/2026-10-22-approved-pending-tools.md`.

The work splits into two tracks:

- **Track A (safe now):** F06, F07 and F12 become discoverable, and five read-only kinds are added (F02, F05, F09, F10, S05). Track A adds no new routes, no Rust and no new authority.
- **Track B (needs new native authority):** F11 and S06 restore. **Track B needs separate owner approval before any code is written (AC7).** This document only sets out the options for it.

## 1. Scope

| ID | Track | Depth delivered | Verification cases (`RELEASE-123-TOOLS.md`) |
|---|---|---|---|
| F06 Create ZIP | A (discovery) | Catalogue entry `zip_create` → Archive tools `archive-create` | Unicode, collisions, output in source scope, cancellation/source preserved. Existing engine tests plus a new search→mode routing test |
| F07 Extract ZIP | A (discovery) | `zip_extract` → `archive-extract` | Traversal, absolute/symlink entries, bombs, disk full. Existing tests (P-020, P-027, P-157) plus routing |
| F12 Archive inspector | A (discovery) | `archive_inspector` → browse via `GET /api/file-selections/{id}/archive-entries` | Nested/duplicate paths, encrypted/unsupported formats, no fabricated uncompressed safety estimate |
| F02 File info | A | `file-info`: size, modified/created, permission bits, hidden flag, hard-link count, extension. Created date is null where the platform lacks it. Skipped links and denied folders appear as rows | Unicode/long paths, denied access, link shown but not followed, no input mutation |
| F05 File comparison | A | `compare-files` on two single-file selections: streamed byte equality, first differing offset, SHA-256 of each, plus a text view (encoding, line endings, bounded hunks) when both are UTF-8 and ≤ 2 MiB | Equal binaries, one-byte difference, encoding/line endings, bounded memory, same inode |
| F09 File age finder | A | `file-age`: modified or created date within inclusive UTC epoch bounds. The UI converts local dates (start of the first day to 23:59:59 of the last) | Timezone/date boundary, created date unavailable, inaccessible records, recursion off/on |
| F10 Empty-file finder | A | `empty-files`: zero-byte regular files only, review and reveal, no removal | Empty vs whitespace/non-empty, links, denied paths, source unchanged |
| S05 Empty folders | A | `empty-folders`: bottom-up. `empty` covers nested empties; `hidden-files-only` is reported separately. Does not cross mount points, enter protected paths or descend bundles | Nested empties, hidden files, links/system boundaries, review only |
| F11 Symlink inspector | **B** | Section 4 | Relative/broken/circular/out-of-scope links, no blind traversal |
| S06 restore | **B** | Section 4. Existing duplicate/storage Trash moves already cover dry-run, confirm and partial errors | Nothing deletes before confirmation, partial/cancel, native restore, changed file/permission, freed space measured |

Out of scope: F01, F03, F04, F08 and S01–S04 (already built), the converter's legacy "Extract ZIP" panel, and promotion to private beta.

## 2. Reuse versus new

- **Reuse:**
  - `FileSelectionStore` grants, `checked_path`/`open_parent`/`open_file` (no-follow, identity-checked).
  - The `FileJobStore` queue, cancellation, pinning, TTL, 32 MiB result retention and 200-row pagination.
  - `POST /api/file-jobs/{id}/reveals` for Show in Finder (populate `job.reveal_items`).
  - The `_file_dates` helper.
  - Protected-path checks from the storage engine (P-034).
  - The archive engine and routes, unchanged.
  - The existing fixed error mapping in `_run`.
- **New, in files this slice owns:**
  - `officekit/engines/engine_file_inspect.py`, holding five pure compute functions plus their option DTOs.
  - `officekit/tool_catalog/files.py`, holding eight entries and search synonyms.
  - Kind registrations in `assets/officekit-files.js` through the foundation hook.
  - A per-slice doc page.
- **Extended in shared code (minimal):**
  - `FileSelectionStore.iter_files(..., stats=None)` and `_walk` count skipped links, special entries, denied subfolders and other-device entries into an optional dict. The default behaviour stays byte-for-byte the same.
  - The `FileJobRequest.kind` Literal (:137) and `OPTION_MODELS` (:129) take registrations from the foundation's kind registry. Two-selection kinds come from a set, not `== 'compare-folders'` (:149).
- **Not done:**
  - No new Rust. `file_output_choose` (:1424) is untouched because every track A kind is read-only.
  - No new `APIRouter`, because every kind rides `/api/file-jobs`.

## 3. Contract surface (track A)

All kinds use the existing `POST /api/file-jobs` (1 MiB body cap, strict DTO, 202) and `GET /api/file-jobs/{id}/results` (paginated, 200 rows per page). Options are `StrictModel` (`extra='forbid'`, `strict=True`).

| Kind | Selections | Option DTO (bounds) | Result shape (top-level lists paginate) |
|---|---|---|---|
| `file-info` | 1 | `FileInfoOptions{includeSubfolders: bool=false}` | `files[{id,name,size_bytes,modified_at,created_at\|null,mode:"rw-r--r--",hidden,hard_links,extension}]`, `skipped[{name,reason:"link"\|"special"\|"denied"}]` (≤ 10,000; the rest are only counted), `total_files,total_bytes,skipped_links,denied_folders,platform_limits[str],complete` |
| `compare-files` | 2 (each exactly one regular file) | `EmptyOptions` | `equal,same_file,size_a,size_b,sha256_a,sha256_b,first_difference_offset\|null,bytes_a[≤16 hex],bytes_b,mode:"binary"\|"text"\|"text-too-large",encoding_a,encoding_b,line_endings_a\|b:"lf"\|"crlf"\|"cr"\|"mixed"\|"none",equal_ignoring_line_endings,hunks[{a_start,a_lines,b_start,b_lines,lines[{op:" "\|"-"\|"+",text≤500}]}],truncated,complete` |
| `file-age` | 1 | `FileAgeOptions{dateField:"modified"\|"created"="modified", notBefore:int\|null, notAfter:int\|null (0…253402300799), includeSubfolders:bool=false}`. At least one bound; `notBefore ≤ notAfter` | `files[{id,name,size_bytes,modified_at,created_at}]`, `scanned,matched,matched_bytes,unavailable_dates,date_field,not_before,not_after,complete` |
| `empty-files` | 1 | `EmptyFileOptions{includeSubfolders:bool=false}` | `files[{id,name,modified_at}]`, `scanned,skipped_links,denied_folders,complete` |
| `empty-folders` | 1 (folder roots only) | `EmptyOptions` | `folders[{id,name,state:"empty"\|"hidden-files-only",nested_empty_folders,depth}]`, `scanned_folders,skipped_links,skipped_other_volume,skipped_bundles,excluded_protected,denied_folders,complete` |

Named constants in the engine:

- `MAX_COMPARE_TEXT_BYTES = 2 MiB` per side
- `MAX_DIFF_LINES = 20_000`
- `MAX_HUNKS = 200`
- `MAX_HUNK_LINES = 40`
- `MAX_LINE_CHARS = 500`
- `MAX_SKIPPED_ROWS = 10_000`
- `BYTE_WINDOW = 16`
- `MAX_EPOCH = 253402300799`

The engine reuses `MAX_ENTRIES = 100_000`, `CHUNK_BYTES = 1 MiB` and `MAX_REPORT_BYTES`. Comparison streams both files in 1 MiB chunks and runs the text diff only after both pass the size and decode gates, so memory stays bounded.

**Errors.** Errors are the existing fixed strings: 422 for DTO violations; job `failed` for "Permission denied…", "Selection exceeds scan entry limit", "Selected file changed; select it again", "Choose two single files to compare" and "Choose a folder to check for empty folders". Host paths never appear in errors. Rows carry selection-relative `name`. Absolute paths reach the native side only through `reveals`.

**Catalogue, profile and copy.**

- Eight `TOOL_REGISTRY` entries go in `tool_catalog/files.py`, with the `File Utilities` category except `empty_folder_finder` (`Storage & Cleanup`):

  | Tool ID | Opens |
  |---|---|
  | `zip_create` | `{tab:'workspace', fileTool:'archive', archiveMode:'archive-create'}` |
  | `zip_extract` | `{tab:'workspace', fileTool:'archive', archiveMode:'archive-extract'}` |
  | `archive_inspector` | the same as `zip_extract`, with a browse focus |
  | `file_info` | `file-info` |
  | `file_compare` | `compare-files` |
  | `file_age_finder` | `file-age` |
  | `empty_file_finder` | `empty-files` |
  | `empty_folder_finder` | `empty-folders` |

- Destinations and `WORKSPACE_TOOL_COPY` entries are registered through the foundation hook. The `archive` copy entry replaces the hard-coded `'Archive tools'` at `officekit-files.js:58`.
- `release-profile.json` changes by one route only: `["POST", "/api/file-jobs/*/reveals"]` is added to the private-beta `routes` so the shipped `dup_finder` Show in Finder works (owner answer 2, section 9). New tools stay development-only, and the development profile already allows every route.
- **Gap found:** the private-beta profile gates by route, not by job kind. `POST /api/file-jobs` is allowed there, so the new kinds would run in beta. Add `DEVELOPMENT_ONLY_KINDS` (built as the engine constant `DEVELOPMENT_ONLY_KINDS = INSPECT_KINDS` in `engine_file_inspect.py`; the catalogue has no release flag, see LLD 1.0.2; ARCH-4), rejected under `private-beta` with 403 "This operation is not available in the OfficeKit private beta." Add a test for it.
- **Existing defect (fixed):** `POST /api/file-jobs/*/reveals` was absent from `release-profile.json`, so the beta `dup_finder` Show in Finder was blocked. Fixed per owner answer 2 (section 9); regression test `test_beta_profile_covers_every_route_the_shipped_duplicate_finder_calls`.

## 4. Track B: new native authority (separate owner approval required)

### F11 symlink inspector

Conflict: `checked_path` (:74) rejects any link on the path, and `_walk` (:257) silently skips links.

| Option | Authority change | Risk |
|---|---|---|
| B1 Inspect links found **inside** a selected folder | Engine only: a link-reporting walk that calls `os.readlink(name, dir_fd=parent)` and never `stat`s or opens the target. It resolves hops by walking real directories inside the granted roots: each component gets a no-follow `stat`, and a directory is descended into only by a no-follow open under a held descriptor. Inside the roots, directories may be opened no-follow and lstat'd to resolve hops; nothing outside the roots is ever stat'd, opened or followed | Low. Root selection rules are unchanged |
| B2 Also allow **choosing a link itself** | Rust `file_selection_open` gains `links:"inspect"` (picker with `resolvesAliases=false`). Backend `register_native(link_policy='inspect')` allows a link only as the final component; ancestors stay link-free | Medium. This relaxes the central path primitive |

Rules:

- Hops are capped at `MAX_LINK_HOPS = 40`, and a hop counts as circular if its `(dev, ino)` was already visited.
- Any hop leaving the selected roots gets the state `out-of-scope`, and resolution stops there.
- The link text is shown as written and is never logged.
- Windows reparse points report `unsupported`.

**Recommendation:** B1 now, and B2 only on demand.

**Built as B1 (2026-10-23, `symlinks` kind, tool `symlink_inspector`).** The engine is `symlink_links` in `engine_file_inspect.py`; root selection and `checked_path` are unchanged.

- Each link is followed one component at a time, with a no-follow stat or open under a held descriptor for the selected root. `readlink` is the only call on a link. Relative and absolute targets take the same walk: an absolute target inside the root maps to a root-relative path without normalising it, so a `..` in it is walked physically through real directories. Leaving the root is `out-of-scope`, and nothing outside the root is stat'd or opened (tested with a spy that also records keyword and parent-relative calls).
- Owner answer 2026-10-23, quoted as given: “Amend the design text (Recommended)”. A child that becomes a link during a hop (ELOOP on the no-follow open) fails the scan with `Folder changed during scan`; only ENOENT and ENOTDIR mark the hop `broken`.
- `MAX_LINK_HOPS = 40` counts distinct links. A link seen again in the same chain is `circular`, and `hops` is the number of distinct links followed. This matches the approved mock's `Circular (2 hops)` for a two-link loop.
- The entry cap and cancellation are checked at every entry and every hop. At the cap the scan stops with `entry_limit_reached`, and the links already resolved stay in the partial result.
- `denied` (“Not checked · permission denied”) marks a target inside the folder that cannot be read, and it is counted in the partial banner. Owner answer 2026-10-23, quoted as given: “Keep it (Recommended)”. `unsupported` ("Not supported on this system") marks every link on a platform without descriptor walks (Windows), and no target is read.
- Host paths: rows show the link name, its folder-relative path and its target as written. Owner answer 2026-10-23, quoted as given: “Folder name (Recommended)”. The selection line shows the folder name only, as other Files tools do, not the full path shown in the mock header. Showing the full host path would need native metadata, which B1 does not change.
- No reveal action is offered for links, because `checked_path` rejects links and reveal is not needed for the mock.
- Copy, owner answer 2026-10-23, quoted as given: “Keep shared, trim F11-only (Recommended)”. The shared result lines stay (“Preview shows 200 rows…” and “Options changed. Run again to update the result.”). The F11-only extras are trimmed: the safety note appears only on a complete result with links, and the summary has no “· N not supported” suffix. The selection line shows the folder name alone, without the shared “Selected: ” prefix, and an empty selection reads “Choose a folder to begin.”, as the approved mock shows (review round 2, UX-5); other Files tools keep the shared line.

### S06 restore

Cleanup moves to `~/.Trash/<uuid>-<name>` (`engine_storage_cleaner.py:787`) and records nothing, and Finder Put Back is unavailable.

| Option | Authority | Trade-off |
|---|---|---|
| R1 OfficeKit Trash ledger plus native restore grant | (1) An app-data ledger (0600, ≤ 10,000 records, 30-day TTL) written in the same critical section as the move: `{record_id, trash_name, trash_identity, original_parent_path, original_parent_identity, original_name, moved_at, size}`. (2) A Rust `trash_restore_confirm` native dialog that mints a single-use, 10-minute restore grant bound to record IDs. (3) Restore is a descriptor-relative no-replace rename from the Trash fd into a freshly opened `open_parent(original)`, guarded by an identity check | Works for every OfficeKit move. Stores deleted names and paths locally |
| R2 Finder AppleEvent `delete` (native Put Back) | New Automation (Finder) TCC permission | Finder resolves paths itself, which loses the no-follow/identity guarantees. It adds a permission prompt and is macOS only |
| R3 `NSFileManager trashItemAtURL:resultingItemURL:` via Swift | New Swift bridge | Handles per-volume `.Trashes` and returns the exact Trash URL. Put Back is not guaranteed, so R1 is still needed for restore |

R1 contract (approved by the owner 2026-10-23, answer “approved”, S06 mock and disclosure). The built routes are in API-CONTRACT.md. `TrashRecordPage` also carries `total`, which the Restore screen uses for its summary count, and the grant mint is the native-only `POST /api/trash-restore-grants` that the native confirm command calls:

| Method | Route | Request | Response |
|---|---|---|---|
| `GET` | `/api/trash-records?offset&limit≤200` | — | `TrashRecordPage{records[{id,name,original_folder_display,moved_at,size_bytes,state:"restorable"\|"name-taken"\|"changed"\|"missing"}],hasMore}` |
| `POST` | `/api/trash-restorations` | `{recordIds[1..100], restoreGrantId}` (native header) | 201 `{items[{id,state:"restored"\|"skipped",reason}],restored_bytes}` |
| `DELETE` | `/api/trash-records/{id}` | — | 204 (forget the record; the file stays in Trash) |

- "Restore to…" for `name-taken` reuses `file_output_choose` with a new `jobKind:"trash-restore"` directory grant.
- Freed space is measured with `statvfs` before and after, never promised.

**Built as R1 (2026-10-23, `trash_restore`, Storage & Cleanup).**

- The ledger is written inside `StorageCleaner._trash`, the one move both storage cleanup and the duplicate finder use. The move and its record share a critical section. If the record fails, the file stays in Trash and the result reads “not restorable”; nothing is rolled back after the move. Engine: `engine_trash_ledger.py` and `engine_trash_restore.py`.
- A grant is single use, bound to its exact ids, expires after 600 seconds, and is minted only by the native confirm command. A forged, reused, expired or mismatched grant answers 403, and a mismatch does not spend the grant.
- Restore holds the Trash folder and the target folder as descriptors, checks their identities, and renames with no-replace. A moved item that no longer has its identity is reported as `changed` and OfficeKit does not touch the new item at that name.
- Trash identity mismatch or an emptied Trash is `missing`. A changed or unreachable folder, or a folder owned by another user, on another volume, or inside a protected name (P-034), is `changed` (`protected` on restore).
- Freed space: R1 reports `restored_bytes` only and makes no space claim. The `statvfs` measurement is not built. Owner to confirm (see the LLD, section 11.7).
- Show in Finder for a restored item uses the new `trash_restore_reveal` command, which takes a path and checks that it is absolute and not a link. The existing `file_job_reveal` needs a job, and a restore has none.
- Development-only: every route answers 403 under private-beta, through an explicit guard, and the four routes are listed in the profile so the guard can answer.

### Threat model (track B)

| Threat | Mitigation |
|---|---|
| Script in the webview forges a restore or inspect request | Restore needs a native-minted single-use grant and a native token header, the same as `storage-cleanup-plans/*/execution` |
| Trash item swapped or replaced before restore | Hold the Trash fd, `lstat` the name, compare `trash_identity`, rename with `RENAME_EXCL`, re-check the moved inode (P-157) |
| Original parent replaced by a link or moved | `open_parent` no-follow, parent identity compared to the ledger. A mismatch means `changed`, with "Restore to…" offered |
| Destination name now exists | No-replace rename only. Report `name-taken`; never overwrite |
| Ledger tampered to restore into protected or system paths | Ledger is advisory. Re-run protected-path checks (P-034), require the same volume and a current-user owner, restore only records whose Trash identity still matches |
| Ledger as a privacy record | Local only, 0600, bounded, TTL, a "Forget" action, never logged or exported. Disclosed before each move and on the Restore screen (approved mock, 2026-10-23) |
| Link inspector discloses or traverses outside scope | Nothing outside the selected roots is ever stat'd, opened or followed. Inside the roots, directories may be opened no-follow and lstat'd to resolve hops. An absolute target is mapped to a root-relative path and walked the same way; a hop that leaves the roots stops as out-of-scope. Hop cap and cycle set |
| Link loops or huge trees exhaust resources | `MAX_ENTRIES`, `MAX_LINK_HOPS`, cancellation at each hop |

**Recommendation:** approve F11 B1 together with track A's walker stats work, and S06 R1 as its own PR after an owner review of the ledger's privacy disclosure. Defer R2 and R3.

## 5. UI component tree (track A)

```
#tab-workspace  (officekitBindDirectFiles, unchanged frame)
├─ h1#direct-file-title, p#direct-file-description   ← kind registration supplies copy
├─ section#direct-selections.ok-file-panel
│  ├─ Choose files… | Choose folder… | Choose folder B… (F05 relabels A/B, compare-files uses slot 1)
│  ├─ p#direct-selection-summary
│  ├─ #direct-file-options  ← registration.options(): includeSubfolders checkbox; F09 date field + From/To + tz note
│  └─ #direct-file-actions: Reset selection · Run (registration.runLabel) · Cancel
├─ p#direct-file-status (fixed errors + "Open System Settings →")
└─ section#direct-file-results.ok-file-panel
   ├─ h2 Result · p.ok-file-summary · .banner.warn (partial counts)
   ├─ .ok-file-report-scroll > table.ok-file-report-table  ← registration.columns (labelled, formatted)
   ├─ F05: A/B facts table + .diff hunks | byte window
   └─ result actions (Copy report · Download) appended after content; row "Show in Finder" uses reveals
```

The hook's shape is `officekitRegisterDirectFileKind({action, kind, title, description, runLabel, icon, selections: 'one'|'two-files', options(container), collect(), columns, summary(report)})`. The existing kinds stay on their current code paths.

## 6. Files owned

**Track A:**

- `officekit/engines/engine_file_inspect.py`
- `officekit/tool_catalog/files.py`
- `assets/officekit-files.js` (registrations, column renderer)
- `docs/tools/files.md` (the per-slice page)
- Tests:
  - `tests/test_file_inspect_unittest.py`
  - `tests/test_file_inspect_api.py`
  - `tests/files-tools-ui.test.mjs`
  - `ui-tests/workspace-files-pending.spec.mjs`

Shared edits, each kept to its foundation slot:

- `engine_file_selections.py` (`stats` parameter)
- `engine_file_jobs.py` (registry and two-selection set)

**Track B (after approval):**

- `engine_trash_ledger.py`
- A trash router module
- `src-tauri/src/workspace_native.rs` (confirm dialog command, `trash-restore` job kind)

## 7. Test plan per ID

| ID | Engine (pytest) | Route | UI |
|---|---|---|---|
| F06/F07/F12 | Existing archive suites stay green | `archive-formats`, `archive-entries` and `reveals` reachable in development | Search "zip"/"extract archive"/"archive contents" → exact ID → correct `direct-archive-mode`. Count tests derive from the registry (P-150) |
| F02 | NFC/NFD and 255-byte names, a 1,000-character nested path, a `chmod 000` subfolder → `denied_folders=1`, a link row with no target stat, `created_at` None when `st_birthtime` is absent (monkeypatched), source `identity()` unchanged | 422 on unknown or non-bool options; pagination | Labelled columns, partial banner, desktop/compact |
| F05 | Equal 3 MiB binaries; a one-byte difference at 0, the middle and the last byte; length-only difference; UTF-8 BOM vs none; LF vs CRLF → `equal_ignoring_line_endings`; Latin-1 → binary; > 2 MiB → `text-too-large`; same inode → `same_file`; peak memory under bound (tracemalloc); hunk/line truncation | 2 selections required; a folder selection is rejected | A/B relabel, diff render, binary byte window |
| F09 | Inclusive at exactly `notBefore`/`notAfter` (ns precision); one-sided ranges; reversed bounds → 422; created unavailable → `unavailable_dates`; recursion off vs on; denied subfolder | Bound range 0…MAX_EPOCH, strict ints | Local-to-UTC conversion across a DST change and at UTC+05:30/−10:00 (fixed `Intl` zone in test) |
| F10 | 0-byte vs `" "`/`"\n"` (not listed); link to an empty file skipped and counted; denied folder; sources unchanged | strict DTO | Show in Finder calls reveals |
| S05 | Nested empties counted bottom-up (P-170 ordering); `.DS_Store`-only → `hidden-files-only`; a link inside → not empty; other `st_dev` skipped; `.app` bundle not descended; protected subtree excluded (P-034); denied child → ancestor not empty, `complete=false` | Folder-only selection | Compact table scroll |
| All new kinds | Cancellation mid-scan, the 100k entry limit, a changed root, result over 32 MiB rejected | **403 under the private-beta profile** for development-only kinds | Fixed error text, no host paths in DOM except via reveal |
| F11/S06 (B) | Per the section 4 threats: race swaps, no-replace, ledger tamper, hop cap, cycles, out-of-scope never stat'd | Native-grant required, single-use, expiry | Mock section 7 after approval |

Use only synthetic temporary trees. Never touch the developer's Downloads or Trash (TESTING.md :139).

## 8. Pitfalls check

- **P-001, P-042:** every catalogue entry maps to a reachable kind or route with a transport test.
- **P-150:** counts are derived from the registry.
- **P-167:** actions come after content; each workflow is completed, not just its geometry checked.
- **P-170:** bottom-up depth ordering with deduplicated roots in S05.
- **P-034:** protected subtrees are excluded in S05 and in restore.
- **P-157, P-027, P-026:** reads go through `open_file` (no-follow, identity); restore uses held descriptors and no-replace.
- **P-020:** archive code is unchanged.
- **P-163:** no external tools are invoked.
- **P-155:** no new native HTTP client.

## 9. Open questions

1. Should the converter's legacy "Extract ZIP" panel (`index.html:2041`) stay as a redirect into Archive tools, or be removed now that search opens it directly? It is a duplicate entry point.
2. The private-beta profile lacks `POST /api/file-jobs/*/reveals` while `dup_finder` ships in beta. Is this a live beta defect that should be fixed in this slice?
3. F11 and the restore ledger show link text and original folder paths. Is it acceptable to show host paths in these local-only views (they are never logged)?
4. Track B: approve F11 B1 now, and S06 R1 as a separate PR?
5. Owner to confirm the build choices that were not in the approved design (PM-6): (a) the 403 for kind-level refusal under private beta, where the route-level beta gate answers 404 (ARCH-5); (b) the limits `MAX_SKIPPED_ROWS` 10,000, `MAX_DIFF_LINES` 20,000 and the 2 MiB text view, set by the builder; (c) "Show" as the row action that reveals a scanned item, per the approved v2 mock.

Owner answer 2026-10-22 (UX-4): add the two search IDs `zip_extract` and `archive_inspector` (section 3), which open Archive tools in extract or inspect mode. The dropped-ID wording of round 1 (QA-7) no longer applies.

Owner decisions 2026-10-22 (version 1.0.2):

1. **Converter's Extract ZIP panel:** keep it (approval record). It stays as the converter's entry point alongside the search IDs.
2. **Private-beta reveal route:** fix in the files slice. `POST /api/file-jobs/*/reveals` is added to the private-beta `release-profile.json` `routes`, so the beta `dup_finder` Show in Finder works. This is a release-profile change. The existing sensitive-route checks are unchanged. The regression test `test_beta_profile_covers_every_route_the_shipped_duplicate_finder_calls` fails without the route.
3. **Host paths:** show full paths in the local-only F11 and restore views. Paths are never logged.
4. **Track B:** ship F11 first, then the S06 restore in a separate PR.
5. **Build choices (PM-6):** accepted as built: the 403 for kind-level refusal under private beta, the limits `MAX_SKIPPED_ROWS` 10,000, `MAX_DIFF_LINES` 20,000 and the 2 MiB text view, and "Show" as the row action.

Round 2 deviations for the owner to confirm (version 1.0.3):

- **Compare headline (UX-7).** The build keeps the byte wording, "Files differ · first difference at byte N". The approved v2 frame reads "3 lines changed", and the build cannot count lines without a second pass over the files. Owner to accept the byte wording or to ask for a line count.
- **Windows folder walk (CR-9).** The empty-folder finder refuses on Windows with "Folder checks need macOS or Linux." because junctions cannot be detected there. The macOS product is unaffected. Owner to confirm the refusal over a Windows walk.
- **Duplicate member paths (PM-3).** An archive with a repeated member path fails the listing with "The archive contains an unsafe entry path." rather than listing both copies. Owner to confirm.

Owner answer 2026-10-22 (PM-10, version 1.0.5): “Refuse (Recommended)”. Archive create refuses an output file inside a selected folder before any byte is read. The job fails with "The output file is inside the selected folder. Choose another place to save it.", no ZIP is written and the sources are unchanged. Before this answer the build zipped the folder and left its own ZIP out of the archive; that behaviour is no longer offered.
