# Open-sourcing OfficeKit: plan

**Version:** 1.4.0 · 2026-11-27 · Approved by the owner. Phases 1 to 3 are done and Phase 4 is ready for the owner's review on branch `chore/open-source-phase-1` (this tree becomes the public repo's seed; it is not merged into the private `main`). Nothing is pushed or published.

## Phase 1 result

- Untracked `review/`, `todo.txt` and `.coverage`; home paths and the personal email scrubbed. `PERFORMANCE_REPORT.md` is kept with relative links, because the README links to it.
- The licence test RSA key is generated per test run (`src-tauri/src/test_keys.rs`); no private key is committed.
- Removed `services/`, `infra/`, 36 backend tests, the licence-issuing script and the AWS/CDK dependencies. `npm test` runs `node --test`; the 100% c8 gate covered only the backend.
- Fresh clone proof: `npm ci`, `build:ui`, `npm test` (1,289 Node and 3,764 Python tests) and `cargo test` (575) all pass. It found one real coupling, a UI test that read `review/`, now fixed.
## Phase 2 result

- `ci.yml` runs on `macos-latest`, read-only token, no secrets, concurrency-cancelled. The full job (Python 3.14 and Node 24 setup, `npm test`, locked-app UI tests, media launcher, `cargo test`) passed on a GitHub-hosted runner on the third dispatch. The first two runs found three clean-runner problems, all fixed: the headphone-motion test forced `cargo --offline`, and the UI test static server had a 15 s start limit.
- `build-installers.yml`, `notarize-submit.yml`, `notarize-finish.yml`, `scripts/ci/macos-signing.sh` and the tests that assert their content stay in the private repo. The generic signing and notarization scripts stay public.
- `version-bump.yml` stays public on `ubuntu-latest` (it needs only `GITHUB_TOKEN`), a change from the first draft: the private repo could not push to a public `main` without a personal access token.
- Not yet checked: a real fork pull request. That needs the repo to be public (or a second account); the setting "require approval for first-time contributors" must be on. Both are Phase 4 items.

## Phase 3 result

- Added `BUILDING.md`, `CONTRIBUTING.md`, `SECURITY.md`, `TRADEMARKS.md` and a generated `THIRD-PARTY-NOTICES.md` (138 npm, 867 Rust, 100 Python packages; `scripts/generate-third-party-notices.mjs`), all linked from the README.
- The Parakeet CC BY 4.0 credit line in the Speech model card was changed after an approved mock (`model-attribution`, 2026-11-27): it names NVIDIA, the Core ML conversion by FluidInference and the licence link. Test: `tests/dictation-ui.test.mjs`. `DESIGN_SYSTEM.md` 1.9.24.
- Still open: the full licence text of each package must travel with the installer (the notices list names and licences only); a security contact address if it is not `support@officekit.app`; whether to require DCO sign-off (currently asked for in `CONTRIBUTING.md`).
- Found, not caused by this work: `ui-tests/csp-navigation.spec.mjs` fails two tests on `origin/main` too (the Favorites tab stays hidden after a click; Quick Search does not show "PDF Pages to PNG / JPEG"). CI does not run that spec. It needs its own fix before the public repo advertises `npm run test:ui`.

## Phase 4 result (scan and export; nothing published)

- Exported the tracked tree of `chore/open-source-phase-1` as one squashed commit (1,602 files, about 76 MB) into a scratch directory. `gitleaks` 8.30.1 over that commit: no leaks, after a reviewed allowlist (`.gitleaks.toml`) for 17 false positives: published model checksums, a git revision, two jwt.io-style sample tokens, test passwords and a sample licence key.
- Greps over the export for the AWS account and API IDs, ARNs, `.p8`/`.p12`/`.pem`/`.key` files, the owner's email and home path: nothing.
- Found real data from a bank statement in tests and mocks (three personal names, an address, account numbers, references). Replaced everywhere with invented values of the same length; the statement tests pass as before.
- OCR of all 174 tracked screenshots for names, emails, home paths and key words found nothing beyond the plain words "password" and "token" in UI labels. OCR is not a proof: the owner should skim `docs/verification/` before it goes public, or drop it.
- Not changed: the owner's first name appears in dictation dictionary tests, and the `docs/` folder holds internal planning material. Both are the owner's call.
- Found, not caused by this work: the browser UI suite has pre-existing failures on `origin/main` (two in `csp-navigation`, three in the statement specs). CI runs only `locked-app`.

## Before the public push (owner)

1. Choose the organisation and repository name; create it empty and private first, push the export, check it, then switch it to public.
2. Settings to turn on: private vulnerability reporting, "require approval for first-time contributors", read-only default workflow token, branch protection on `main` (CI must pass).
3. Run one fork pull request from a second account to confirm that it has no secrets.
4. Decide on `docs/verification/`, the internal docs, the DCO sign-off and the security contact address.

- Build order to document in `BUILDING.md`: run `npm test` first, then build the media launcher (`rustc --edition=2021 src-tauri/media-cli-launcher.rs -o src-tauri/binaries/officekit-media`) before `cargo test`. A launcher built without the backend sidecar makes one Python test fail.

## Decisions (owner)

- The desktop app (UI, Tauri shell, Python engines) is published under GPL-3.0-only.
- The public repo is created fresh with a squashed history, not by rewriting this one.
- The public repo is the home of day-to-day development after the split.
- Private: `services/licensing/`, `infra/licensing/`, `services/support/`, the signing and release workflows, and every secret.

Background: `docs/THIRD-PARTY-LICENSE-AUDIT.md` (dependencies and history scan).

## Honest limit

A GPL client check can be removed by anyone who forks it. The licence gate protects the official signed build and the server-side value (activation, updates, support), not the source.

## Two repos after the split

| Repo | Holds | Visible |
|---|---|---|
| `office-tools` (public, new) | app, UI, Rust shell, engines, tests, hosted-runner CI, docs, public verification key | public |
| `office-tools-private` (this repo, renamed) | `services/`, `infra/`, release and notarization workflows, signing and issuing scripts | private |

A release is built by a private workflow that checks out a tagged commit of the public repo, so signing secrets and the self-hosted Mac never touch public code or pull requests.

## Phases

### 1. Make the tree publishable (this repo, on branches, reversible)
1. Stop tracking `review/`, `todo.txt`, `PERFORMANCE_REPORT.md`, `.coverage` and any screen recordings; add them to `.gitignore`.
2. Replace `/Users/sedhu` in the README, docs and four UI tests with a neutral path; replace the personal address in `tests/tauri-dmg-build.test.mjs`.
3. Move `src-tauri/tests/fixtures/license-test-private.pem` out of the tree: tests generate a key at run time.
4. Cut the licensing backend out of the build graph: drop the `services/*` and `infra/*` entries from `npm test`, the `synth:*` scripts and the 28 `tests/license-*.test.mjs` and `tests/support-*.test.mjs` files into the private repo. `npm test` must stay green with the 100% coverage gate on what remains.
5. Prove that a fresh clone builds and runs unlicensed with no backend (`license_client.rs` degrades to Free).

### 2. CI that is safe on a public repo
1. `ci.yml` moves from the self-hosted runner to GitHub-hosted runners, trigger `pull_request` (never `pull_request_target`), read-only token, no secrets.
2. `build-installers.yml`, `notarize-submit.yml`, `notarize-finish.yml` and `version-bump.yml` move to the private repo.
3. A fork pull request run is checked once to show that it has no secrets and cannot reach the runner.

### 3. Public documents
`THIRD-PARTY-NOTICES`, `CONTRIBUTING.md`, `SECURITY.md`, a trademark note for the OfficeKit name and logo, a `BUILDING.md` for unsigned builds, and the CC-BY attribution for Parakeet in the About screen (UI change: mock first).

### 4. Scan, then publish (owner's go required)
1. Export the tree to an empty directory, squash into one commit, run `gitleaks` over it, and grep for `APPLE_`, `.p8`, `.p12`, KMS ARNs, account and API IDs.
2. Owner reviews the exported tree.
3. Create the public repo and push. This step is outward-facing and irreversible in practice, so it waits for an explicit go.

## Not decided yet
- Public repo name and organisation, and whether to enable GitHub Discussions.
- Contributor policy (a DCO sign-off or none).
- Whether hosted macOS runners are acceptable for CI cost, or CI stays Linux-only for the non-native suites.

## Done when
A fresh clone of the public repo builds unsigned, its tests pass, a fork pull request runs without secrets, and the private repo can still build, sign and notarize a release from a tagged public commit.
