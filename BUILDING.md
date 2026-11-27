# Building OfficeKit

OfficeKit is a Tauri 2 desktop app (Rust shell, HTML/JavaScript UI) with a local Python API. This page builds an
**unsigned** copy on your own Mac. Official signed and notarized releases are built by the maintainers in a private
pipeline; you do not need it to build, run or change the app.

## What you need

| Tool | Version | Why |
|---|---|---|
| macOS | 14 or later | The native shell uses Swift and macOS frameworks. Other platforms are not supported yet. |
| Xcode command line tools | current | `swiftc` compiles the native bridges. |
| Node.js and npm | 24 | UI build, scripts, tests. |
| Python | 3.14 | The local API, engines and sidecar. |
| Rust | stable | The Tauri shell. Install with [rustup](https://rustup.rs). |

## Get set up

```bash
git clone <this repository>
cd office-tools
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-build.txt
npm ci
```

## Run it

```bash
npm run dev
```

This starts the desktop app against the local API. `npm run build` produces an unsigned `.app` and `.dmg` under
`src-tauri/target/release/bundle/`. With no signing identity in your keychain the build is signed ad hoc, which is
enough to run it on the Mac that built it. macOS will ask for microphone, calendar and similar permissions again each
time the signature changes.

## Licensing in a source build

A build made without release keys is a **development build**. Its licence keyring is empty, so it cannot verify a paid
licence, and it does not contact the licensing service to activate one. Which tools the licence gate covers is listed
in `src-tauri/src/license_gate.rs`. The licensing service itself is not part of this repository.

## Run the tests

Order matters on a clean checkout:

```bash
npm test                       # builds the UI, then the Node and Python suites
npx playwright install webkit  # once, for the browser UI tests
npm run test:ui                # browser UI tests (optional, slow)
mkdir -p src-tauri/binaries
rustc --edition=2021 src-tauri/media-cli-launcher.rs -o src-tauri/binaries/officekit-media
cargo test --manifest-path src-tauri/Cargo.toml --locked
```

Run `npm test` before you build the media launcher. A launcher built without the packaged backend sidecar makes one
Python test fail; with no launcher that test is skipped.

`.github/workflows/ci.yml` runs the same steps on GitHub-hosted macOS for every pull request.

## Speech models

Speech models are not in the repository and not in the installer. They download on first use from pinned sources and
are checked by size and SHA-256. Their licences are listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Troubleshooting

- **`resource path binaries/officekit-media doesn't exist`:** build the media launcher as shown above.
- **`externally-managed-environment` from pip:** use the virtual environment from the setup step.
- **Swift deprecation warnings during the Rust build:** expected; they do not fail the build.
