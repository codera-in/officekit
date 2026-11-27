# Pending file tools: low-level design (phase 1, track A back end)

Version: 1.0.5 · 2026-10-23 · Round 1 review of the S06 build: the listing is a read and never rewrites the ledger (ARCH-2); the 10,000 cap holds in the stored file after every write, pruned after the append (QA-2, CR-1); the ledger folder is set to 0700 on every write, including a folder another store created (DEVOPS-1, CR-2); the three success bodies are named response DTOs (ARCH-1); the mint capacity check runs before the destination grant is spent (CR-5). Earlier: 1.0.4 · 2026-10-23 · Add section 11, the S06 restore low-level design (option R1, built on the owner's approval “approved”, 2026-10-23): file map, interfaces, errors and test hooks. Earlier: 1.0.3 · 2026-10-22 · Round 2: the walker's open-time check compares device, inode and directory type only (CR-8); Windows refuses the folder walk, a limit documented in section 7 (CR-9); the `_open_listed_folder` docstring matches the code (CR-10). Earlier: 1.0.2 corrects three passages to match the built engine: the `file_info` signature, the descriptor and walker wording (CR-2), and the "not touched" list (CR-5); the F02 nested-path row now matches the test (QA-6); file info reports `skipped_truncated`. Earlier: 1.0.1 aligned the `empty_folders` signature, reveal items, protected-root refusal and root-denied behaviour. Initial LLD for the back end of track A from `docs/hld/pending-tools-files.md` 1.0.0.

Scope of this document: the five read-only file-job kinds (F02 file info, F05 compare files, F09 file age, F10 empty files, S05 empty folders), their guard under the private-beta profile, the shared-engine hooks they need, and their tests. Out of scope here: catalogue entries and `release-profile.json` route entries (phase 2, with the UI and discovery for F06/F07/F12), all UI and assets, and track B (section 9).

## 1. Summary of decisions

1. The five kinds ride the existing `POST /api/file-jobs` pipeline. No new route, no new router, no Rust.
2. Substantive logic lives in a new module, `officekit/engines/engine_file_inspect.py`. The shared `engine_file_jobs.py` only gets registrations, one dispatch branch and the release check.
3. `FileSelectionStore.iter_files` and `_walk` gain an optional `stats` collector. With `stats=None` the behaviour is byte-for-byte unchanged.
4. `FileJobStore` receives the release profile name at construction. A development-only kind submitted under `private-beta` raises `ReleaseScopeError`, which the route maps to 403 with the beta message.
5. Empty-folder detection (S05) uses its own bounded walker in the new module. The selection store only yields files, and S05 needs directories, device identity and protected-name exclusions.
6. Stat-level metadata (mode, link count, hidden flag) is read through the parent opened per call by `open_parent`, with `stat(follow_symlinks=False)` and an identity check. Opening the file is not needed, so unreadable files still report metadata.

## 2. File-by-file map

| File | Change | Owner |
|---|---|---|
| `docs/lld/pending-tools-files.md` | new (this file) | slice |
| `docs/VERSION-HISTORY.md` | one row at the top | slice |
| `officekit/engines/engine_file_inspect.py` | **new**. Option DTOs, five pure compute functions, the S05 walker, constants | slice |
| `officekit/engines/engine_file_selections.py` | `MAX_SKIPPED_ROWS`; `iter_files(..., stats=None)`; `_walk(..., stats=None, label=None)` | slice (shared, minimal) |
| `officekit/engines/engine_file_jobs.py` | import option models and kind sets; `FileJobRequest.kind` Literal; `OPTION_MODELS`; two-selection set; `release_profile` in `FileJobStore`; `ReleaseScopeError`; `_inspect_files` helper; `_inspect` dispatch; `_compute` branch | slice (shared, minimal) |
| `app.py` | three lines: import `ReleaseScopeError`; `FileJobStore(..., release_profile=RELEASE_PROFILE.name)`; `except ReleaseScopeError` → 403 in `create_file_job` | slice (see section 4.3) |
| `tests/test_file_inspect_unittest.py` | **new** engine tests | slice |
| `tests/test_file_inspect_api.py` | **new** route tests through `/api/file-jobs` | slice |

Not touched by the phase 1 engine change: `officekit/engines/engine_comms.py`, `index.html`, `dist-ui/*`, `requirements.txt`, `src-tauri/*`, `release-profile.json`. Phase 2 files changed later on this branch, outside this LLD's engine scope: `officekit/tool_catalog/*`, `assets/*` (the Files screens and slice styles), `API-CONTRACT.md`, `docs/TOOL-GUIDE.md` and `docs/FIRST-MAC-RELEASE.md`.

## 3. Interfaces

### 3.1 `engine_file_selections.py` (shared, minimal)

```python
MAX_SKIPPED_ROWS = 10_000

# stats: None, or a dict the caller owns. Walks update it in place:
#   stats['skipped_links']   int   symlinks and Windows reparse points
#   stats['special']         int   FIFOs, sockets, devices and other non-regular entries
#   stats['denied_folders']  int   subfolders whose listing raised PermissionError
#   stats['rows']            list[(label, reason)]  capped at MAX_SKIPPED_ROWS
#   stats['rows_dropped']    int   rows beyond the cap (counted, not stored)
def iter_files(self, key, include_subfolders=True, stats=None) -> Iterator[SelectedFile]
```

- `_walk(root, include_subfolders=True, stats=None, label=None)`: with `stats`, a link or special entry is recorded and a denied subfolder is recorded. A denied root still raises, as before. `label(path)` is supplied by `iter_files` and produces the selection-relative name (with the `index+1/` prefix when there are several roots). Without `stats`, the existing code path runs unchanged.
- Subfolders not descended (`include_subfolders=False`) are not recorded as skips.

### 3.2 `engine_file_inspect.py` (new)

Constants:

```python
MAX_COMPARE_TEXT_BYTES = 2 * 1024 * 1024   # per side, text view gate
MAX_DIFF_LINES = 20_000                     # per side, before diffing
MAX_HUNKS = 200
MAX_HUNK_LINES = 40
MAX_LINE_CHARS = 500
BYTE_WINDOW = 16
MAX_EPOCH = 253_402_300_799                 # 9999-12-31T23:59:59Z
BUNDLE_SUFFIXES = ('.app', '.bundle', '.framework')
PROTECTED_NAMES = PROTECTED                 # imported from engine_storage_cleaner (P-034)
INSPECT_KINDS = frozenset({'file-info', 'compare-files', 'file-age', 'empty-files', 'empty-folders'})
DEVELOPMENT_ONLY_KINDS = INSPECT_KINDS
TWO_SELECTION_KINDS = frozenset({'compare-folders', 'compare-files'})  # defined in engine_file_jobs
```

Option DTOs (all `StrictModel`, `extra='forbid'`, `strict=True`):

```python
class FileInfoOptions(StrictModel):
    include_subfolders: bool = Field(default=False, alias='includeSubfolders')

class FileAgeOptions(StrictModel):
    date_field: Literal['modified', 'created'] = Field(default='modified', alias='dateField')
    not_before: int | None = Field(default=None, ge=0, le=MAX_EPOCH, alias='notBefore')
    not_after: int | None = Field(default=None, ge=0, le=MAX_EPOCH, alias='notAfter')
    include_subfolders: bool = Field(default=False, alias='includeSubfolders')
    # validator: at least one bound; not_before <= not_after when both are set

class EmptyFileOptions(StrictModel):
    include_subfolders: bool = Field(default=False, alias='includeSubfolders')
```

`compare-files` and `empty-folders` use the existing `EmptyOptions`, so no new option model is needed for them.

Compute functions (pure apart from reads through the injected callables):

```python
def file_info(items, stats, *, check, dates) -> dict
def compare_files(first, second, *, check, open_file) -> dict
def file_age(items, stats, *, options, check, dates) -> dict
def empty_files(items, stats, *, check, dates) -> dict
def empty_folders(roots, *, selection_id, check) -> tuple[dict, list[SelectedFile]]
```

- `file_info` calls the module-private `_stat_selected(item)` directly: `open_parent` plus `os.stat(name, dir_fd=parent, follow_symlinks=False)`, or `checked_path` plus `os.lstat` on Windows. It raises `ValueError('Selected file changed; select it again')` when the file is not regular or its identity differs from `item.signature`.
- `dates` is `FileJobStore._file_dates` (the existing helper, reused).
- `open_file` is `FileSelectionStore.open_file` (the existing no-follow, identity-checked reader).
- `empty_folders` returns the result and the list of reveal items (`SelectedFile` for each reported folder). The store registers them in `job.reveal_items`, the same way duplicate folders do. The file kinds (`file-info`, `file-age`, `empty-files`) also register each scanned file as a reveal item, so Show in Finder works on their rows.

### 3.3 `engine_file_jobs.py` (shared, minimal)

```python
class ReleaseScopeError(PermissionError):
    """Development-only operation requested under the private-beta profile."""

class FileJobStore:
    def __init__(self, selections, clock=time.monotonic, trash=None, release_profile='development'): ...

# FileJobRequest.kind Literal gains:
#   'file-info', 'compare-files', 'file-age', 'empty-files', 'empty-folders'
# OPTION_MODELS gains:
#   'file-info': FileInfoOptions, 'compare-files': EmptyOptions, 'file-age': FileAgeOptions,
#   'empty-files': EmptyFileOptions, 'empty-folders': EmptyOptions
# validate_options: selection count is 2 for kind in TWO_SELECTION_KINDS, else 1
```

`FileJobStore._inspect(job)` dispatches the five kinds. Its helper `_inspect_files(job, key, stats, include_subfolders)` wraps `iter_files` with the cancel check and progress, as `_files` does.

## 4. Behaviour

### 4.1 Kind results

| Kind | Selection rule | Result (top-level lists paginate) |
|---|---|---|
| `file-info` | 1 file or folder | `files[{id,name,size_bytes,modified_at,created_at\|null,mode,hidden,hard_links,extension}]`, `skipped[{name,reason:"link"\|"special"\|"denied"}]` (rows capped at 10,000), `skipped_truncated` (rows beyond the cap, counted), `total_files,total_bytes,skipped_links,denied_folders,platform_limits[str],complete` |
| `compare-files` | 2 selections, each exactly one regular file (`register_native` root, `directory=False`), else `ValueError('Choose two single files to compare')` | `equal,same_file,size_a,size_b,sha256_a,sha256_b,first_difference_offset\|null,bytes_a,bytes_b` (hex, ≤16 bytes from the first difference), `mode:"binary"\|"text"\|"text-too-large",encoding_a,encoding_b,line_endings_a,line_endings_b,equal_ignoring_line_endings,hunks[...],truncated,complete` |
| `file-age` | 1 | `files[{id,name,size_bytes,modified_at,created_at}]`, `scanned,matched,matched_bytes,unavailable_dates,date_field,not_before,not_after,complete` |
| `empty-files` | 1 | `files[{id,name,modified_at}]`, `scanned,skipped_links,denied_folders,complete` |
| `empty-folders` | 1 folder root, else `ValueError('Choose a folder to check for empty folders')` | `folders[{id,name,state:"empty"\|"hidden-files-only",nested_empty_folders,depth}]`, `scanned_folders,skipped_links,skipped_other_volume,skipped_bundles,excluded_protected,denied_folders,complete` |

`complete` means: no denied folder was encountered (for `file-info`, `file-age`, `empty-files`, `empty-folders`). For `empty-folders`, a denied child also makes its ancestors non-empty. Skipped links are reported, not treated as incomplete. For `compare-files`, `complete` is true when the byte comparison ran to the end; `truncated` is the separate flag for the text view.

### 4.2 Rules

- **file-info.** `mode` is `stat.filemode(st_mode)[1:]`, giving the nine permission characters. `hidden` is a leading dot or `st_flags & UF_HIDDEN`. `hard_links` is `st_nlink`. `extension` is the lowercased `splitext` suffix (empty for `.bashrc`). `created_at` is null when `signature[5]` is absent. `platform_limits` includes a line about birth time when any created date is null.
- **file-age.** Bounds are whole epoch seconds, and each bound includes its whole second. A timestamp `t` (ns) matches when `not_before * 1e9 <= t < (not_after + 1) * 1e9`. One-sided ranges are allowed. Reversed bounds, or neither bound, fail validation with 422. When the chosen date is unavailable, the file is counted in `unavailable_dates` and is not matched.
- **empty-files.** Only zero-byte regular files (`signature[2] == 0`). Whitespace-only and one-byte files are not empty. Links are skipped and counted.
- **compare-files.**
  - Pass 1 streams both files in lockstep, 1 MiB at a time, through `open_file`. Regular-file reads return full chunks except at end of file, so the offsets stay aligned. It computes SHA-256 of each side, the first differing byte offset (a shorter file differs at its length), and an incremental UTF-8 decoder per side, plus a NUL-byte check. It also retains each side's bytes up to `MAX_COMPARE_TEXT_BYTES`, dropping the retention when exceeded.
  - The byte window (`bytes_a`, `bytes_b`) is read with `seek(first_difference_offset)` inside the same `open_file` contexts.
  - Mode: `text` when both sides are valid UTF-8 with no NUL bytes and both are ≤ 2 MiB. `text-too-large` when both are valid UTF-8 with no NUL bytes but one is larger than 2 MiB. Otherwise `binary`. Latin-1 is therefore binary.
  - Encoding is `utf-8-bom` when the first three bytes are EF BB BF, `utf-8` for other text, and `binary` otherwise. The BOM is kept as a character, so BOM-vs-none text shows as a difference.
  - Line endings (text only): normalise to a set of `crlf`, `lf` and `cr` present; one kind gives that name, several give `mixed`, none gives `none`. Binary gives null.
  - `equal_ignoring_line_endings` (text only): the bodies with `\r\n` and `\r` mapped to `\n` compare equal.
  - Hunks (text only): lines are split on `\r\n|\r|\n`, with each line truncated to 500 characters. `difflib.SequenceMatcher(autojunk=default)` opcodes are grouped with 3 context lines. A side above `MAX_DIFF_LINES` lines gets no hunks and `truncated=True`. Hunks above `MAX_HUNKS` or lines above `MAX_HUNK_LINES` are cut and set `truncated=True`.
  - `same_file` is true when `(st_dev, st_ino)` match. The comparison still runs, so the hashes are reported.
- **empty-folders (bottom-up).** Each directory gets a state from its children, computed after its children (post-order, iterative, so there is no recursion limit):
  - Each child folder is opened by name under a no-follow parent (`open_parent`, `O_NOFOLLOW`), its device, inode and directory type are compared with the signature recorded at the parent listing, and it is listed through that descriptor. A child changed after the parent listing (swapped, replaced or removed) fails the job closed with `FileExistsError('Folder changed during scan')` (CR-2). mtime and ctime are not compared, so an entry written into a child while the walk is pending does not fail the job (CR-8).
  - **Windows limit (CR-9).** There is no no-follow open on Windows and `DirEntry.is_symlink()` does not report directory junctions. The walk therefore refuses on Windows (`DESCRIPTOR_WALK` is false) with the fixed job failure `Folder checks need macOS or Linux.`, and never descends. The refusal is tested by `test_folder_walk_refuses_where_no_descriptor_open_is_available`.
  - A link, special entry, visible regular file, bundle, other-device directory, protected directory or denied directory makes the folder `content`. Each of these is counted in its own counter, and the first three also appear as content.
  - A hidden regular file (name starts with `.`) sets `has_hidden`.
  - A child directory whose state is `empty` is transparent and adds `1 + child.nested` to `nested_empty_folders`.
  - A hidden-named child whose state is `hidden-files-only` is transparent and sets `has_hidden`. A visible child that is not `empty` makes the folder `content`.
  - Result: `content` if any visible content exists; `hidden-files-only` if `has_hidden`; otherwise `empty`.
  - Rows are emitted for every directory (root included) whose state is `empty` or `hidden-files-only`. Rows sort by name casefold.
  - Deduplicate by canonical path across roots, so overlapping roots count once (P-170). Recheck each reported folder's identity against the scan signature before returning (`FileExistsError('Folder changed during scan')` otherwise). Protected names (`PROTECTED`) are excluded and counted as `excluded_protected`, which also makes the parent `content`. Scan entries are bounded by `MAX_ENTRIES`.

### 4.3 Release guard (private-beta)

- `release-profile.json` route rules gate by path only, so `POST /api/file-jobs` is allowed in beta for every kind. The guard therefore lives in the job store.
- `FileJobStore.submit` checks `request.kind in DEVELOPMENT_ONLY_KINDS and self.release_profile == 'private-beta'` before any queue or selection work, and raises `ReleaseScopeError('This operation is not available in the OfficeKit private beta.')`.
- The route maps `ReleaseScopeError` to HTTP 403 with that `detail`. This is the only `app.py` change beyond the store construction. The generic `direct_file_error` would otherwise return the authority-denied text.
- `app.py` passes `release_profile=RELEASE_PROFILE.name` when constructing the store. The default `'development'` keeps the existing tests unchanged.
- Development profile: every kind runs. Unknown profile names are already rejected by `load_release_profile`.

### 4.4 Errors

- 422: DTO violations (unknown fields, wrong types, out-of-range epochs, reversed bounds, no bound, two selections for a one-selection kind).
- 403 with the beta message: development-only kind under `private-beta`.
- Job `failed`, with fixed strings: "Permission denied…" (root unreadable, for any kind), "Selection exceeds scan entry limit", "Selected file changed; select it again", "Choose two single files to compare", "Choose a folder to check for empty folders", "Protected folders cannot be checked" (a selected root whose name is in the protected set), "Folder changed during scan", "Result exceeds report retention limit".
- A denied subfolder below the root is not a job failure. It is counted in `denied_folders`, listed as a `denied` row for `file-info`, and makes `complete` false.
- Host paths never appear in errors or rows. Rows carry selection-relative `name`. Absolute paths reach the native side only through `reveals`, which stores the reveal items.

## 5. Test hooks

- `iter_files(stats=...)` and `_walk` are tested directly with a `stats` dict, and the no-`stats` behaviour is covered by the existing `tests/test_file_selections_unittest.py`.
- Engine tests call the compute functions through `FileJobStore` on real temp directories (`tmp_path`), with `await_job` from `tests/test_file_jobs_unittest.py`. Permission-denied cases use `chmod 000` and skip when running as root.
- Time-sensitive behaviour is tested with explicit epoch values, and the file mtime is set with `os.utime(path, ns=...)`. No test depends on the current date.
- Birth-time absence is simulated by monkeypatching `_file_dates`' input signature (`signature[5] = None`), not by changing the platform.
- Route tests use `TestClient(api.app)` with `FileJobStore(selections, release_profile=...)` injected through `monkeypatch`, the same pattern as `tests/test_direct_file_api.py`.
- Tracemalloc bounds the compare peak on a 3 MiB pair.

## 6. Test plan (summary, per ID)

| ID | Engine cases (`tests/test_file_inspect_unittest.py`) | Route cases (`tests/test_file_inspect_api.py`) |
|---|---|---|
| F02 | NFC and NFD names, a 255-byte name, a nested path of seven 100-character folders (about 700 characters); `chmod 000` subfolder gives `denied_folders=1`; a symlink row with no target stat (target is outside the root and never opened); `created_at` None under a monkeypatched signature; source identity unchanged | 422 for unknown or non-bool options; `skipped` pagination |
| F05 | Equal 3 MiB binaries; one-byte difference at offset 0, mid and last; length-only difference; UTF-8 BOM vs none; LF vs CRLF gives `equal_ignoring_line_endings`; Latin-1 is binary; text over 2 MiB is `text-too-large`; same inode gives `same_file`; tracemalloc bound; hunk and line truncation | Two selections required; a folder selection is rejected with the fixed message |
| F09 | Inclusive at `notBefore` and at `notAfter` with ns precision; one-sided ranges; reversed bounds rejected; unavailable created date counted; recursion off vs on; denied subfolder sets `complete=false` | Bounds 0…MAX_EPOCH; strict ints (bool and float rejected) |
| F10 | 0 bytes vs `" "` and `"\n"`; link to an empty file skipped and counted; denied folder; source unchanged | Strict DTO |
| S05 | Nested empties counted bottom-up; `.DS_Store`-only gives `hidden-files-only`; a link inside keeps the folder non-empty; other-device skip (monkeypatched `st_dev`); `.app` bundle not descended; protected subtree excluded; denied child makes ancestor non-empty and `complete=false`; overlapping roots counted once | Folder-only selection rejected otherwise |
| Guard | Submitting each of the five kinds under `private-beta` raises `ReleaseScopeError`; development profile runs them | 403 with the beta message under `private-beta`; 202 under development; existing `hash` kind still 202 under beta |
| All | Cancellation mid-scan; `MAX_ENTRIES` boundary; changed root; result over 32 MiB rejected | Route 422 and 403 cases |

Synthetic temporary trees only. The developer's Downloads and Trash are never touched (`docs/TESTING.md` :139).

## 7. Pitfalls check

- **P-001, P-042:** no catalogue entries in phase 1. Phase 2 must add transport tests for each mapped kind.
- **P-150:** no tool counts are added here. Phase 2 derives counts from the registry.
- **P-170:** bottom-up ordering; roots deduplicated by canonical path; identity recheck before reporting.
- **P-034:** protected names excluded in S05; the walker never enters them.
- **P-157, P-027, P-026:** file reads go through `open_file` (no-follow, identity); metadata-only reads go through the parent opened per call by `open_parent`, with `follow_symlinks=False` and an identity check. The S05 walker opens each child folder by name under a no-follow parent and fails closed on any change after the parent listing (CR-2).
- **P-020, P-033:** archive code and split/join are untouched.
- **P-163, P-155:** no external tools, no new HTTP client.

## 8. Commit plan

1. `docs(files): LLD 1.0.0 for pending file tools track A` (this file, plus the `VERSION-HISTORY.md` row).
2. `feat(files): optional skip stats on the selection walker` (shared `engine_file_selections.py`, with tests proving the default path is unchanged).
3. `feat(files): file info, file age and empty-file engine kinds` (`engine_file_inspect.py` part 1, registrations in `engine_file_jobs.py`, engine tests).
4. `feat(files): compare-files engine kind` (`compare_files`, tests for bytes, text, bounds and memory).
5. `feat(files): empty-folder engine kind` (bottom-up walker, tests for nested, hidden, links, bundles, protected, overlap).
6. `feat(files): development-only guard and API routes for the five kinds` (`release_profile` in the store, `ReleaseScopeError`, three `app.py` lines, `tests/test_file_inspect_api.py`).

Each commit ends with the Co-Authored-By and Claude-Session trailers from the session instructions.

## 9. Phase 3 placeholder (track B, not built here)

Track B covers F11 (symlink inspector, option B1 first) and S06 (restore with a Trash ledger, native restore grant and no-replace rename). Both need separate owner approval before any code. Per the HLD (sections 4 and 6), they add `engine_trash_ledger.py`, a trash router, and Rust changes in `src-tauri/src/workspace_native.rs`. Nothing in this phase depends on them. The F11 link-walk stats hook in section 3.1 is designed so B1 can reuse it.

## 10. Open items carried from the HLD

- HLD open question 2 (private-beta reveal route is missing from `release-profile.json`) is out of scope for this phase and stays with the owner.
- HLD open question 3 (showing host paths in local-only views) affects only the reveal behaviour in phase 2 and track B. Phase 1 returns no host paths.

## 11. S06 restore (track B, option R1)

Scope: HLD section 4 “S06 restore”, R1, and the approved S06 mock (owner “approved”, 2026-10-23). Owner answers recorded in the HLD: “Approve as designed”, “Show paths”, “F11 then S06 PR” (2026-10-22).

### 11.1 File-by-file map

| File | Change |
|---|---|
| `officekit/engines/engine_trash_ledger.py` | **new.** `TrashLedger`: 0600 atomic JSON file, bounded (`MAX_RECORDS` 10,000, oldest dropped first), TTL 30 days, `add`, `page`, `get`, `forget`, `remove`. |
| `officekit/engines/engine_trash_restore.py` | **new.** `TrashRestorer` (page states, native grant mint and single-use consume, restore, forget), the strict request DTOs, and the held-descriptor helpers. |
| `officekit/engines/engine_storage_cleaner.py` | `StorageCleaner(ledger=None)`: default ledger under `<home>/Library/Application Support/OfficeKit/trash-ledger.json`. `_trash(path, expected, size_bytes=None)` records the move and returns whether the record was kept. `_remember` never raises. `execute` reports `UNRECORDED_TRASH_MESSAGE` when the record was not kept. |
| `officekit/engines/engine_file_jobs.py` | `duplicate-trash` outcomes carry `restorable`, which is False when the mover reports an unrecorded move. |
| `app.py` | `trash_restorer` instance; four routes; `_trash_development_only` (403 under private-beta); body caps. |
| `release-profile.json` | The four trash routes are listed so the beta guard answers 403 instead of 404. |
| `src-tauri/src/workspace_native.rs`, `src-tauri/src/lib.rs` | Native commands `trash_restore_confirm`, `trash_restore_apply`, `trash_record_forget`, `trash_restore_reveal`; `trash-restore` job kind for `file_output_choose`. |
| `officekit/tool_catalog/files.py`, `assets/officekit-files.js`, `assets/officekit-storage.js` | Catalogue entry `trash_restore`, the Restore screen, and the disclosure in the storage review and the duplicate result. |

Tests: `tests/test_trash_ledger_unittest.py`, `tests/test_trash_recording_unittest.py`, `tests/test_trash_restore_unittest.py`, `tests/test_trash_api.py`, the Rust tests in `workspace_native.rs`, and the UI tests named in the approval record.

### 11.2 Interfaces

```python
class TrashLedger:
    def __init__(self, path, clock=time.time)
    def add(*, trash_name, trash_identity, original_parent_path, original_parent_identity, original_name, size) -> dict
    def page(offset, limit) -> {records, total, hasMore}   # newest first; a read: expired and over-cap records are filtered in memory, the file is never rewritten
    def get(record_id) -> dict | None
    def forget(record_id) -> bool       # the user's Forget
    def remove(record_id) -> bool       # restored items leave the list

class TrashRestorer:
    def __init__(self, ledger, trash_dir, selections, *, native_token, clock=time.monotonic)
    def page(offset, limit) -> {records[{id,name,original_folder_display,moved_at,size_bytes,state}], total, hasMore}
    def mint(TrashRestoreGrantRequest, credential) -> TrashRestoreGrant {id, expiresIn}   # native only
    def restore(TrashRestoreRequest, credential) -> TrashRestoration {items[{id,state,reason,restored_to}], restored_bytes}   # native only
    def forget(record_id, credential) -> None                         # native only
```

Grant rules: `mint` consumes the destination output grant (`consume_output(id, 'trash-restore')`) when one is given, and it refuses more than one item with a destination. The capacity check (32 waiting approvals) runs before the output grant is consumed, so a refused approval leaves the destination grant usable. `restore` validates the grant before spending it: an unknown, expired or mismatched grant raises `PermissionError(APPROVAL_MESSAGE)` and leaves a live grant unspent. A matching grant is removed before any work starts, so it is single use. Waiting grants are bounded by `MAX_RESTORE_GRANTS` (32).

Ledger shape: `{version: 1, records: [{record_id, trash_name, trash_identity: [dev, ino], original_parent_path, original_parent_identity: [dev, ino], original_name, moved_at, size}]}`. A malformed record is dropped on load, and an unreadable file reads as empty. `moved_at` is epoch seconds. Each write is atomic (a 0600 temporary file, then `os.replace`) and sets the folder to 0700 first, so a folder another store created with a looser mode is tightened. Pruning (30 days, then the 10,000 cap oldest first) runs after the append and before the save, so the stored file never holds more than the cap. Reads filter in memory and do not write.

Routes (`app.py`):

| Route | Auth | Body | Response |
|---|---|---|---|
| `GET /api/trash-records?offset&limit≤200` | none (read-only) | — | 200 `TrashRecordPage` |
| `POST /api/trash-restore-grants` | native header | `{recordIds[1..100], destinationGrantId?}` | 201 `TrashRestoreGrant` `{id, expiresIn}` |
| `POST /api/trash-restorations` | native header | `{recordIds[1..100], restoreGrantId}` | 201 `TrashRestoration` `{items, restored_bytes}` |
| `DELETE /api/trash-records/{id}` | native header | — | 204 |

### 11.3 Restore algorithm (per record)

1. Hold the Trash folder (`_open_directory`, every component no-follow). `lstat` the trash name (single component only) and compare `(dev, ino)` with `trash_identity`. A mismatch or an absent name is `missing`.
2. Choose the folder: the original parent, or the folder of the granted output path, with the final name taken from that path.
3. Refuse a relative folder or name (`changed`), and a folder whose components include a protected name (`protected`, P-034).
4. Open the folder no-follow. A failure is `changed`. Its identity must match the ledger (or the grant), its device must match the Trash device, and its owner must be the current user. Otherwise `changed`.
5. `lstat` the target name. If it exists, the item is `name-taken`.
6. `renameatx_np` (darwin, `RENAME_EXCL`) or `renameat2` (linux, `RENAME_NOREPLACE`) between the two held descriptors. An `EEXIST` maps to `name-taken`, `ENOENT` to `missing`, and anything else to `changed`.
7. Re-stat the target. If the identity no longer matches, report `changed` and leave the name alone.
8. Remove the ledger record. A failure here is ignored, because the file is already restored.

The listing runs steps 1–5 without moving anything and maps them to `restorable`, `name-taken`, `missing` or `changed`.

### 11.4 Errors

- 422: DTO violations (unknown fields, empty or more than 100 ids, a non-UUID, duplicates, or a destination with more than one id).
- 403: missing or wrong native header (`Native restore authorization required`); a missing, expired, reused or mismatched grant (`Restore approval is missing, expired or does not match these items. Choose them again.`); any trash route under private-beta (`This operation is not available in the OfficeKit private beta.`).
- 404: an unknown record at grant time, an unknown output grant, or forgetting an absent record.
- 503 (`RuntimeError`): too many waiting grants.
- Item results never carry host paths in errors. The `name` and `original_folder_display` fields are returned only by the local listing and are never logged.

### 11.5 Test hooks

- Synthetic trees under `tmp_path`: a fake `.Trash` and `Documents` are injected into `TrashRestorer` and `StorageCleaner(home=...)`. No test touches the real Trash.
- The races are exercised by changing the tree between `mint` and `restore`, not by hooks: a swapped trash item (`missing`), a folder replaced by a link (`changed`), and a folder swapped after approval (`changed`). The after-move swap is simulated by monkeypatching `_exclusive_move`.
- Ownership and volume checks are tested by monkeypatching `os.getuid` and by comparing device numbers through `_same_volume`.
- The ledger is tested for 0600, atomic replace failure, cleanup failure, TTL, bounds and the absence of any log output.

### 11.6 Pitfalls checked

- **P-034:** protected names refused on restore and in the listing.
- **P-157:** the moved item is checked again after the rename.
- **P-026, P-027:** descriptor-relative no-replace rename; no path re-resolution after the holds open.
- **P-001, P-042:** the catalogue entry maps to the reachable screen, with a routing test.
- **P-150:** counts derived from the registry.

### 11.7 Deviations for the owner

- Freed space is not measured with `statvfs`. R1 reports `restored_bytes` and makes no space claim.
- The Show in Finder action on a restored item uses `trash_restore_reveal(path)`, not `file_job_reveal`, because a restore has no job.
