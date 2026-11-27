# OfficeKit (`officekit.app`) 🚀

## Product and design planning

The next product direction is documented in the [complete product plan](docs/PRODUCT-PLAN.md), [design system](DESIGN_SYSTEM.md), [component structure](design/COMPONENT_STRUCTURE.md), and [testing guidelines](docs/TESTING.md). Start with the [design walkthrough](design/README.md) and [interactive flow mock](design/mocks/officekit-final-flow.html). These are review artifacts, not implemented features; the specific brand and screens await approval.

> **The Privacy-First, All-in-One Office, Document & Financial Toolkit for Mac, Windows, and Linux.**
> Built for solopreneurs, accountants, freelancers, and businesses. Pay once, own it forever. 100% offline processing with zero subscription fees.

---

## 🌟 Highlights & Capabilities

Development builds include **Meeting Countdown**: opt into selected calendars from macOS Calendar to show the animated companion and a countdown during the 30 minutes before a meeting. Calendar data stays on the Mac. See the [tool guide](docs/TOOL-GUIDE.md) for setup and [testing notes](docs/TESTING.md) for native acceptance limits; the feature is excluded from private beta.

**System Stats** shows local CPU, GPU, memory, disk and network activity, per-core load, and available sensor readings. The title bar shows live network rates, traffic history and an optional router-versus-internet check for Wi-Fi or wired links, with a shortcut to Cloudflare Speed Test. Laptops also show battery charge and, when macOS exposes them, battery health and cycle count. Recent graphs stay in memory; matching CPU, GPU, memory, disk, network and battery details are available from the menu bar.

The requested public feature-directory categories and tool labels are listed in [docs/FEATURE-LIST.md](docs/FEATURE-LIST.md). That directory is a navigation list; current implementation and availability are tracked separately in [docs/TOOL-GUIDE.md](docs/TOOL-GUIDE.md).

> **💡 Zero Heavy Bloat / Models Downloaded On-Demand:**
> The installer stays ultra-lightweight (< 85 MB). Heavy AI models (such as local Whisper STT weights or specialized OCR language packs) are never bundled into the initial installer download. The app runs immediately out of the box using built-in system speech APIs and local parsing algorithms, with optional local model downloads available on-demand inside the app settings.

1. **Bank Statement to Excel / CSV / QBO Engine**
   - High-precision PDF & image table extraction (`pdfplumber`, OCR).
   - **Automatic Balance Reconciliation Checksum**: Mathematical validation ensuring $(\text{Previous Balance} + \text{Deposits} - \text{Withdrawals} = \text{Ending Balance})$ across every statement row.
   - 1-Click exports to Excel (`.xlsx`), CSV (`.csv`), QuickBooks (`.qbo`), and Xero (`.ofx`).

2. **Local Dictation, Meeting Minutes & Speech Coach**
   - Local dictation and voice recording, with automatic extraction of Markdown action items (`- [ ]`), key decisions, and formatted minutes.
   - On macOS, Speech Coach adds a configurable floating HUD for pace and pitch feedback, common-mistake notes, and session retrospectives. Menu bar Quick Controls includes Listen In for solo practice and toggles for the OfficeKit speech tools.
   - Live Workspace uses available Apple Intelligence to suggest clearer, simpler sentences, including fewer fillers and smoother structure; basic grammar checks remain available without it. Optional 5- or 10-minute inactivity auto-clear keeps transcript and fixes temporary; all speech processing stays on the Mac.
   - Audio processing stays on the Mac; raw audio is not saved in coaching history.

3. **PDF Password Remover & AES-256 Protector**
   - Remove passwords from bank statements and locked legal documents.
   - Encrypt confidential documents with AES-256 offline security via `pikepdf`.

4. **Universal Media & Data Converter**
   - **Images:** PNG, JPG, WebP, ICO, TIFF, BMP, PDF cross-conversion with aspect-ratio preserving batch resizing.
   - **Data:** JSON $\leftrightarrow$ CSV $\leftrightarrow$ Excel $\leftrightarrow$ YAML $\leftrightarrow$ SQL `INSERT` statements.

5. **Financial & Business Decision Calculators**
   - Loan EMI & Full Amortization schedules.
   - Compound Interest & Future Value simulator.
   - VAT & Sales Tax (forward and reverse inclusive calculations).
   - Freelancer Rate Calculator (hourly/daily targets with tax & sick leave factoring).
   - Break-Even Analysis, Depreciation (Straight-Line & Declining), Margin vs. Markup.

6. **Apple-Style Diagnostic Crash Reporter**
   - If an unexpected error occurs during parsing or conversion, an Apple-styled problem dialog appears with full Python & client stack traces, thread backtrace, and 1-click developer reporting to ensure rapid bug turnaround.

7. **AppSumo Cryptographic Offline Licensing**
   - HMAC-SHA256 offline license key validator for seamless LTD activation without needing remote DRM servers.

---

## 🛠️ Architecture

- **Backend:** Python 3.11+ / FastAPI / Uvicorn / `pdfplumber` / `pikepdf` / `Pillow` / `pandas` / `openpyxl` / `PyYAML`.
- **Frontend UI:** Modern responsive web application built with Tailwind CSS, Plus Jakarta Sans typography, JetBrains Mono, and FontAwesome.
- **Desktop Runtime:** Tauri 2 shell in `src-tauri/`, with a local Python API sidecar. API routes are in `app.py`; reusable engines are grouped under `officekit/engines/`.
- **Packaging:** Tauri and PyInstaller build platform installers and bundle the API sidecar. `npm run build` runs the desktop packaging pipeline; generated files belong under `src-tauri/binaries/`, `src-tauri/resources/`, and `.build/`.

## ⚡ Performance & Benchmarks

Full multi-core audit results are documented in [**`PERFORMANCE_REPORT.md`**](PERFORMANCE_REPORT.md):
- **Batch Worker Pool:** **131,379 items/sec** with CPU & RAM dynamic concurrency allocation.
- **PDF Merging:** **24,709 pages/sec** (pikepdf / C++ QPDF native core).
- **PDF Stream Compression:** **32.2% of original size** (67.8% file size reduction).
- **Fast Duplicate Scanner:** **34,420 files/sec** (two-phase 4KB chunk hashing).
- **Safe AST Math Evaluator:** **124,475 evaluations/sec** with zero code-injection risk.
- **Lightweight Footprint:** Peak memory usage capped at **~120 MB RAM** under heavy load.

---

## 🧪 Testing & Verification

The codebase follows strict Test-Driven Development (TDD) with 100% test pass rate across unit and end-to-end integration tests:

```bash
source .venv/bin/activate
PYTHONPATH=. pytest tests/ -v
```

Run the optional local performance suite with `python scripts/benchmark_suite.py`.

**Results:**
- `tests/test_module1_bank_statement.py`: 5 passed
- `tests/test_module2_dictate.py`: 2 passed
- `tests/test_module3_pdf_security.py`: 3 passed
- `tests/test_module4_image_converter.py`: 2 passed
- `tests/test_module5_data_converter.py`: 3 passed
- `tests/test_module6_calculators.py`: 7 passed
- `tests/test_e2e_api.py`: 7 passed
- **Total: 29 / 29 PASSED (100%)**

---

## 🚀 Running Locally

### 1. Start Python API Backend:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8000
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your web browser.

### 2. Run Desktop Window:
```bash
npm install
npm start
```

---

## 📦 Building Installers

### Local Mac Build:
```bash
npm run build:mac
```
The output `.dmg` and `.zip` binaries will be generated inside the `dist/` directory.

### Continuous integration and releases:
`.github/workflows/ci.yml` runs the tests on GitHub-hosted macOS for every pull request. It uses no secrets.
Official signed and notarized releases are built by the maintainers in a private pipeline, which checks out a tagged commit of this repository. You can build an unsigned copy yourself with `npm run build`.

---

## 🤝 Build, contribute, report

- [BUILDING.md](BUILDING.md): build and test an unsigned copy yourself.
- [CONTRIBUTING.md](CONTRIBUTING.md): how to propose a change.
- [SECURITY.md](SECURITY.md): how to report a vulnerability privately.
- [TRADEMARKS.md](TRADEMARKS.md): the OfficeKit name and logo are not covered by the GPL.
- [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md): the open-source packages OfficeKit is built from.

## 📄 License
The OfficeKit source code is licensed under the [GNU General Public License v3.0](LICENSE) (`GPL-3.0-only`). © 2026 OfficeKit.

The official signed and notarized builds, the OfficeKit name and logo, and the activation service are not part of the GPL grant; see the project's trademark and release notes.
