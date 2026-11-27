# Contributing to OfficeKit

Thanks for helping. OfficeKit is a privacy-first desktop toolkit: files are processed on the user's Mac and nothing is
uploaded unless the user chooses to send it. Please keep that true in every change.

## Before you start

- For anything beyond a small fix, open an issue first so we can agree on the approach.
- Read [BUILDING.md](BUILDING.md) to build and test, and [AGENTS.md](AGENTS.md) for the repository layout and style.
- Security problems go through [SECURITY.md](SECURITY.md), not a public issue.

## Licence of your contribution

OfficeKit is licensed under GPL-3.0-only. By submitting a pull request you agree that your contribution is licensed
under the same terms. We ask you to sign off each commit (`git commit -s`) to confirm you have the right to submit it,
following the [Developer Certificate of Origin](https://developercertificate.org/).

## Making a change

1. Fork, branch from `main`, and keep the change focused.
2. Follow the existing patterns: four spaces and `snake_case` in Python, two spaces and `camelCase` in JavaScript,
   `rustfmt` defaults in Rust.
3. Keep API inputs and outputs typed, validated and bounded, and be explicit about errors. Never log file contents
   or secrets. Validate paths and archive contents; do not build shell commands from user input.
4. Add tests with every fix or feature: invalid input, boundaries, failures and the normal case. Python tests end in
   `_unittest.py` or live in `test_*.py`; JavaScript tests end in `.test.mjs`.
5. Run `npm test` and, for native changes, `cargo test --manifest-path src-tauri/Cargo.toml --locked`.
6. Use a Conventional Commit title: `feat:`, `fix:`, `docs:`, `test:`, `chore:`.
7. In the pull request, say what the user will see, link the issue, and list what you tested.

## Changes to what users see

UI changes start from an agreed design, not from code. Open an issue with a before-and-after mock (a standalone HTML
file is fine) and wait for a maintainer to approve it. Two rules the project holds to:

- No screen shows more than three buttons at once (tabs, toggles, list-row actions and in-text links are not counted).
- "Choose files…" and "Choose folder…" belong in the work area, never in the bottom action bar.

See [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md).

## Working on paid tools without a licence

You do not need a licence or any backend. Run `OFFICEKIT_DEV_UNLOCK=1 npm run dev` to open every tool in a debug build
(details in [BUILDING.md](BUILDING.md)). Tests build their own signed test entitlements and need no switch.

## What CI does

Every pull request runs `.github/workflows/ci.yml` on GitHub-hosted macOS with no secrets. A first-time contributor's
run needs a maintainer's approval. Release signing, notarization and the licensing service are maintained privately
and are not part of this repository.

## Conduct

Be kind and assume good faith. Harassment is not tolerated, and maintainers may remove comments, issues or pull
requests that cross that line.
