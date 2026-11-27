# Repository Guidelines

## Project Structure & Module Organization

OfficeKit is a Tauri 2 desktop app with a local Python API. `app.py` defines API routes; reusable Python engines live in `officekit/engines/`. `backend_main.py` launches the packaged API sidecar, while `desktop_main.py` is the optional Python desktop launcher. The Tauri shell and Rust commands are in `src-tauri/`; `index.html` and `assets/` provide the UI and shared resources. Node, Python, Rust, and browser tests live in `tests/` and `ui-tests/`. Build, smoke-test, and benchmark helpers are in `scripts/`; the licensing and support backend lives in a separate private repository. Treat `dist-ui/`, `src-tauri/resources/`, and build outputs as generated artifacts. Product and UX guidance is in `docs/`, `design/`, and `DESIGN_SYSTEM.md`.

## Build, Test, and Development Commands

- `npm ci` installs the locked JavaScript dependencies.
- `npm run dev` starts the Tauri desktop app with the local development setup.
- `npm test` runs Node and Python suites and enforces configured coverage gates.
- `cargo fmt --manifest-path src-tauri/Cargo.toml -- --check` checks Rust formatting.
- `cargo test --manifest-path src-tauri/Cargo.toml` runs native Rust and bridge tests.
- `npm run build` builds UI assets, the Python sidecar, and desktop installers.
- `npm run test:sidecar` and `npm run test:macos-dmg` smoke-test packaged components; the DMG test requires macOS.

## Coding Style & Naming Conventions

Use four spaces and `snake_case` in Python, two spaces and `camelCase` in JavaScript, and `rustfmt` defaults in Rust. Keep API inputs and outputs typed, validated, bounded, and explicit about errors. Preserve local-first processing; never log file contents or secrets. Follow existing module patterns.

## Testing Guidelines

Add regression tests with bug fixes, covering invalid input, boundaries, failures, and normal behavior. Python tests use `pytest` and commonly end in `_unittest.py`; JavaScript tests use Node's test runner and end in `.test.mjs`. Base UI changes on approved design guidance and add UI/search/routing tests. Run focused tests, then `npm test`; run Rust and packaged smoke tests for native or packaging changes.

## Commits and Pull Requests

Use Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`, or `chore(tauri):`. Pull requests should explain user-visible behavior, link an issue, list tests/platforms checked, and include UI screenshots. Call out packaging, permission, and configuration changes.

## Security & Configuration

Never commit signing credentials, license secrets, private files, or installers. Keep network use explicit; validate paths and archive contents, and avoid shell-interpolated input. Review `docs/TESTING.md` before changing file-processing or licensing boundaries.

## Mock Review Workflow

Always open HTML design mocks in the Superset Browser and inspect them there before presenting them for review or asking for approval. Use a new browser tab when opening a mock so existing browser work is preserved.
After approval, remove temporary Superset preview files and mock HTML from the worktree; retain the approved decision in the relevant durable documentation.

## Button Limit

No page may show more than 3 buttons at once, counting the bottom action bar and any buttons in the page body (tabs, segmented toggles, list-row actions and in-text links are not counted). Run `node scripts/check-mock-buttons.mjs <mock.html>` on every mock before asking for approval. Prefer one primary action, with at most one Copy and one Download for the result; load data on open instead of adding a Load or Refresh button per section. Hide or remove the rest rather than shrinking them. Every UI mock must show the button count, and UI tests must assert it for new or changed screens. Screens that exceed this today (for example Network diagnostics after a lookup and a ping) are to be brought under it as they are touched.

## File and Folder Selection

"Choose files…" and "Choose folder…" belong in the work area (the drop zone), never in the bottom action bar. The bar holds the action on the chosen input (run, copy, download). Owner rule, 2026-11-05; tools that still put them in the bar are fixed when touched.

## Approved Privacy and Image Annotation Behavior
- The PII file-preparation flow defaults to partial Mask, retaining only limited hints; explicit Redact fully replaces selected values.
- Screenshot Editor supports Text, translucent Highlight, Circle, and Rectangle annotations alongside crop, blur, and opaque mask tools.
