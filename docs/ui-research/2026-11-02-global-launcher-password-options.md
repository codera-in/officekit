# Global Launcher password options

## Decision

The Global Launcher password result uses a saved default length (20, bounded to 8–128) and a saved set of up to 32 unique ASCII punctuation characters (default `!@#$%&*?-_+=`). An empty symbol set produces an alphanumeric password. Uppercase, lowercase and digit characters remain required. Typing `pw 32` or `password 32` continues to override the configured length.

The settings sit beneath the existing Password generator switch. Length and symbol fields remain editable even when quick password results are switched off, so a user can prepare settings before enabling the result. The source is the existing Global Desktop settings object; the native panel receives only the generator configuration, never generated secrets.

## Mock review

Mock: `docs/verification/tool-unification/mock/global-launcher-password-options.png`. It was opened in a new Superset Browser tab and visually inspected. The mock shows before/after states, follows the existing muted card and input styles, and passes `node scripts/check-mock-buttons.mjs` at 0/3 counted buttons per state.

Implementation proceeded under the user's instruction: “dont wait for my approval, just goahead and start with chanages to complete the goal. just make sure mock follows our guidelines.” The later milestone instruction is “1 commit per tool and track the progress.”

## Progress record

| Milestone | Status | Evidence |
| --- | --- | --- |
| Global Launcher password options | Complete | Rust settings and panel tests, Swift native tests, UI contract test, asset build and formatting all pass; scoped commit prepared |
| Remaining tool UX audit | Pending | Existing audit ledger remains the source of remaining checks |

## Verification

Verification passed: `node --test tests/global-launcher-password-options.test.mjs`; focused Rust settings and panel tests; `node scripts/run-macos-global-tests.mjs` (including the existing native sensor/hardware suites); `npm run build:ui`; `cargo fmt --check`; and `git diff --check`. The scoped commit contains only Global Launcher files and its decision/evidence record.
