# Third-party licence and history audit

**Version:** 1.0.0 · 2026-11-20 · Milestone 6c, groundwork for publishing the source under GPL-3.0-only. Nothing here is pushed or published.

## Verdict

- **Dependencies:** no dependency blocks a GPL-3.0-only release of the app. The only copyleft-style licences are file-level (MPL-2.0) or carry an exception (PyInstaller), and both are compatible with GPLv3.
- **Git history:** no real secret was found. Two things must not reach a public repository as they are: `node_modules/` committed once in the first week, and a test-only private key fixture. Publish from a fresh, squashed history (the plan already says so) rather than pushing this one.

## Dependencies (counted 2026-11-20, from the lockfiles and the build environment)

| Ecosystem | Count | Licences | Needs attention |
|---|---|---|---|
| npm, production tree | 32 | Apache-2.0 (28), MIT (3), 0BSD (1) | None |
| cargo crates, full resolved graph | 863 | MIT, Apache-2.0, `MIT OR Apache-2.0`, Unicode-3.0, BSD, ISC, Zlib | MPL-2.0: `colored`, `cssparser`, `cssparser-macros`, `dtoa-short`, `option-ext`, `selectors`. `r-efi` is `MIT OR Apache-2.0 OR LGPL-2.1-or-later`: use it under MIT. |
| Python distributions in the build environment | 111 | MIT, BSD, Apache-2.0, PSF-2.0 | MPL-2.0: `pikepdf`, `certifi`, `tqdm` (MPL-2.0 AND MIT). `pyinstaller` and `pyinstaller-hooks-contrib` are GPLv2 with the PyInstaller exception, which allows bundled applications under any licence. |

- **MPL-2.0** is file-level copyleft and may be combined with GPLv3. Keep each MPL-covered file's notice and offer its source (the upstream crate or wheel).
- **Not Python dependencies:** PyMuPDF (AGPL) is not used. `pytesseract` is an Apache-2.0 wrapper; the Tesseract binary is the user's system install, not bundled.

## Models

| Model | Licence | Note |
|---|---|---|
| Whisper family (whisper.cpp ggml files) | MIT | Downloaded on demand from a pinned Hugging Face commit, size and SHA-256 verified |
| Parakeet and the FluidAudio runtime | CC-BY-4.0 model, Apache-2.0 runtime | Needs an attribution line in the app's About screen before it ships beyond the vendored 0.14.8 models |
| SenseVoice (FunASR) | FunASR model licence | Not shipped; needs its own review before it is added |

## Still to do before a public push

1. Add `THIRD-PARTY-NOTICES` generated from the three lists above (names, versions, licence text) to the installer and the repository.
2. Attribution for CC-BY models in the About screen (UI change, mock first).
3. Review `services/licensing/` and `infra/licensing/` ownership: they stay private per the plan, so they are removed from the public tree.
4. Reserve the OfficeKit name and logo (trademark) and add `CONTRIBUTING.md` and `SECURITY.md`.

## Git history scan

Every added line in all 1,396 commits was matched against private-key blocks, AWS access key ids, GitHub, Slack and `sk-` tokens, KMS and AWS ARNs, hard-coded secret assignments and personal email addresses. Every committed path was matched against key, certificate, environment and installer file names.

| Finding | Assessment | Action |
|---|---|---|
| No AWS access keys, GitHub or Slack tokens, `sk-` keys, Apple `.p8` or `.p12` files | Clean | None |
| `src-tauri/tests/fixtures/license-test-private.pem` (RSA private key) | Test fixture paired with `license-test-public.pem`; not a production key (production signing uses KMS) | Keep out of the public history; regenerate fixtures in the test run when the history is squashed |
| ARNs with account `123456789012`, emails `Buyer@Example.com` | AWS and RFC documentation placeholders | None |
| `node_modules/` committed in `77c26bb9` (2026-10-04) and removed in `2b6987b9` | Third-party code and personal emails from package metadata live in history; bloats the repository | Publish from a fresh squashed history |
| A few personal-looking addresses in test strings and one mock | Sample data | Review while squashing |

The scan is a pattern search, not a replacement for a dedicated scanner. Run `gitleaks` over the squashed history once before the public push; it is not installed on this machine.
