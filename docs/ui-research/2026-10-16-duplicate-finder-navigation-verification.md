# Duplicate Finder navigation and folder matching verification

2026-10-16. Approved decision: `2026-10-16-approved-duplicate-finder-navigation.md`; user approval “lgtm”.

## Delivered

- Desktop duplicate scans always include subfolders. Files/folders match mode replaces the former scope selector.
- Full authenticated local paths appear on name/location hover; each row has Show in Finder. The webview sends only scan/item IDs. The private native bridge resolves those IDs against current selection/root/item identities and invokes Finder with one literal absolute path; no shell or arbitrary webview path.
- Identical folders match relative filenames, complete subtree structure (including empty directories) and SHA-256 file contents. Top-level folder names may differ. Skipped links/special entries invalidate containing folders and mark the report incomplete; permission/read/identity/work-limit failures do not produce exact-match claims. Recheck hashed files and directory identities; compute fingerprints by descending depth to support overlapping selected roots without double-counting paths.
- Folder matches are inspection-only. File cleanup retains its scan-bound IDs, stable keepers, all-page selection and explicit Trash confirmation.
- Accessible Name/Date modified/Size header buttons toggle order and expose aria-sort; sorting preserves selection and whole groups. Existing pagination/page sizes and bounded list remain.

## Evidence

- `npm test`: 592 Node passed, one skipped; 1,550 Python passed, four skipped; 1,653 subtests passed; configured Node coverage gates and native hotkey harness pass.
- `cargo test --manifest-path src-tauri/Cargo.toml`: 81 passed; three opt-in runtime integration tests ignored. Finder tests cover canonical IDs and separate literal argv without running a shell.
- Focused API/selection/jobs/duplicate tests passed. New folder tests first failed for absent matching, recursive default and reveal support. Additional red regressions caught post-hash file changes and overlapping-root ordering.
- Focused coverage.py run: 65 passed; new `_duplicate_folders` and `reveal_path` helpers have no missing statements or branches.
- `npx playwright test ui-tests/workspace-files.spec.mjs ui-tests/csp-navigation.spec.mjs`: 20 passed across desktop/compact WebKit. Browser tests verify path hover attributes, opaque reveal payloads, header sorting/aria-sort, recursive scans, mode invalidation, all-page selections and absence of folder cleanup. Light/dark result screenshots for both modes were visually inspected. Finder bridge delivery is mocked in browser tests.
- `npm run build:ui` and `npm run build:sidecar`: pass.
- `node scripts/smoke-duplicate-finder.mjs`: pass against the rebuilt packaged binary. Disposable originals verify recursive file scanning, exact folder matches, absolute result paths, native-only reveal resolution and unchanged input bytes; no Finder window or Trash mutation is invoked. A cold-start timeout prompted a bounded 45-second startup window with diagnostic capture.
- `cargo fmt --manifest-path src-tauri/Cargo.toml -- --check` and `git diff --check`: pass.

## Review and limits

Self-review checked strict input validation and native credentials; stable scan/root/item identity; read-only folder behavior; bounded traversal, hashing/report/selection resources; no network calls, new dependencies or database/tenant surface; accessible sorting, preserved keepers and selections; and no overlapping controls. Existing unrelated worktree changes were preserved. Approved temporary mock/preview files were removed and the preview server was stopped.

The backend package is rebuilt. No developer documents were moved or deleted.

## Requested desktop rebuild

2026-10-16 — User: “yes rebuild it”. `npm run build` completed and produced the Apple Silicon `src-tauri/target/release/bundle/macos/OfficeKit.app` and `src-tauri/target/release/bundle/dmg/OfficeKit_1.0.0_aarch64.dmg`.

- Local Apple Development signing completed; notarization was skipped because release notarization credentials were not configured.
- `codesign --verify --deep --strict` passed for the rebuilt app.
- `node scripts/smoke-duplicate-finder.mjs src-tauri/target/release/bundle/macos/OfficeKit.app/Contents/MacOS/officekit-backend` passed: recursive files, identical folders, full paths and native reveal resolution were verified from the actual app bundle.
- `npm run test:macos-dmg` passed: DMG verification, mounted signature/entitlements/resources checks and packaged-sidecar smoke succeeded. The image was ejected after verification.
- Installer SHA-256: `dabb4b5d0a6a9d1a171f3b3c028b64d3e402d8ba393909dcfcd06f1e3f0c7930`.

The running `/Applications/OfficeKit.app` was not replaced or quit. Install the rebuilt DMG after fully quitting the old app. Actual Finder-window interaction remains separate installed acceptance.
