# macOS signing and notarization

Version: 2.0.0 · 2026-11-27 · The signing and notarization pipeline is private; this page says what the public repository contains.

Official OfficeKit releases are signed with an Apple Developer ID certificate and notarized by Apple. That happens in a separate private pipeline that checks out a tagged commit of this repository. No signing key, certificate or Apple credential is stored here, and pull requests never run the release pipeline.

## What is public

- `scripts/sign-macos-helpers.mjs` signs the native helper binaries inside the app bundle.
- `scripts/macos-notarize.mjs` wraps `notarytool`.
- `src-tauri/Entitlements.plist` lists the hardened-runtime entitlements.

## Building without signing

Follow [BUILDING.md](../BUILDING.md). An unsigned or ad hoc signed build runs on the Mac that built it. macOS asks you to approve the permissions again for each differently signed build.
