# Version history

| 2026-11-21 | DESIGN_SYSTEM.md | 1.9.19 → 1.9.20 | Deactivate this Mac: text link in the licence details and a confirm step (approved mock). |
| 2026-11-21 | API-CONTRACT.md | 1.95.0 → 1.96.0 | Native `license_deactivate` command frees this Mac's seat, then locks. |
| 2026-11-20 | DESIGN_SYSTEM.md | 1.9.18 → 1.9.19 | Activated chip opens a licence-details dialog instead of the activation form (approved mock). |
| 2026-11-20 | API-CONTRACT.md | 1.94.6 → 1.95.0 | Merge the paid-activation licence gate onto main; keep the release-profile gating. |
| 2026-11-20 | DESIGN_SYSTEM.md | 1.9.17 → 1.9.18 | Merge the paid-activation licence gate onto main; keep the release-profile gating. |
| 2026-11-20 | docs/TESTING.md | 1.12.416 → 1.12.417 | Merge the paid-activation licence gate onto main; keep the release-profile gating. |
| 2026-11-20 | docs/TOOL-GUIDE.md | 1.199.152 → 1.199.153 | Merge the paid-activation licence gate onto main; keep the release-profile gating. |
| 2026-11-20 | docs/THIRD-PARTY-LICENSE-AUDIT.md | new → 1.0.0 | Record the dependency licence audit and git-history secret scan ahead of the GPL-3.0-only release. |
| 2026-10-28 | docs/hld/invoices.md | 1.6.2 → 1.6.3 | Label recurring line rates with the configured currency code. |
| 2026-10-28 | docs/lld/invoices.md | 1.6.2 → 1.6.3 | Map configured currency codes beside recurring invoice line rates. |
| 2026-10-28 | docs/TEST-PLAN.md | 1.0.28 → 1.0.29 | Assert recurring schedule rates show configured currency codes. |
| 2026-10-28 | docs/PRD-invoices.md | 1.6.1 → 1.6.2 | Identify the currency beside each formatted recurring line rate. |
| 2026-10-28 | docs/hld/invoices.md | 1.6.1 → 1.6.2 | Include explicit ISO currency codes in the recurring invoice summary. |
| 2026-10-28 | docs/lld/invoices.md | 1.6.1 → 1.6.2 | Map the summary's currency code to the selected draft currency. |
| 2026-10-28 | docs/TEST-PLAN.md | 1.0.27 → 1.0.28 | Assert the recurring schedule summary identifies each formatted rate's currency. |
| 2026-10-28 | docs/PRD-invoices.md | 1.6.0 → 1.6.1 | Require the recurring schedule step to show the invoice line items before saving. |
| 2026-10-28 | docs/hld/invoices.md | 1.6.0 → 1.6.1 | Specify visible line descriptions, quantities and formatted rates beside schedule settings. |
| 2026-10-28 | docs/lld/invoices.md | 1.6.0 → 1.6.1 | Map recurring schedule summary rows to the draft line descriptions, quantities and currency-formatted rates. |
| 2026-10-28 | docs/TEST-PLAN.md | 1.0.26 → 1.0.27 | Assert every recurring schedule line is visible with description, quantity and formatted rate before save. |
| 2026-10-28 | docs/PRD-invoices.md | 1.5.0 → 1.6.0 | Record the approved preview freshness, recurring invoice review, report refresh and inline client validation behavior. |
| 2026-10-28 | docs/hld/invoices.md | 1.5.0 → 1.6.0 | Record the approved preview freshness, recurring invoice review, report refresh and inline client validation behavior. |
| 2026-10-28 | docs/lld/invoices.md | 1.5.0 → 1.6.0 | Record the approved preview freshness, recurring invoice review, report refresh and inline client validation behavior. |
| 2026-10-28 | docs/TEST-PLAN.md | 1.0.25 → 1.0.26 | Add regression coverage for preview staleness, recurring invoice contents, report failure clearing and focused client validation. |
| 2026-10-28 | docs/ui-research/2026-10-26-approved-invoices.md | 1.1.0 → 1.2.0 | Record approval of invoice preview freshness, recurring invoice review, report refresh and inline client validation behavior. |
| 2026-10-28 | docs/TEST-PLAN.md | 1.0.24 → 1.0.25 | Add the combined speech-model first-use and Live Workspace correction de-duplication coverage. |
| 2026-10-28 | docs/PITFALLS.md | 1.0.13 → 1.0.14 | Record P-277 and its desktop/compact regression guard against repeated Live Workspace corrections. |
| 2026-10-27 | docs/PITFALLS.md | 1.0.12 → 1.0.13 | CR-335: P-273–P-276 record lock ordering, cached integrity, first-load error flow and installed-model feedback catches with observed regressions. |
| 2026-10-27 | docs/hld/speech-model-lifecycle.md | 1.0.0 → 1.0.1 | Add failure shutdown, pinned integrity and cross-runtime lock-order requirements from review. |
| 2026-10-27 | docs/lld/speech-model-lifecycle.md | 1.0.0 → 1.0.1 | Map reviewed cached validation and first-load failure publication/cleanup. |

| 2026-10-27 | docs/PITFALLS.md | 1.0.11 → 1.0.12 | CR-335 / P-272: first-use loading supersedes enabled-shortcut launch loading; record real cached Whisper footprint evidence. |
| 2026-10-27 | docs/verification/speech-model-memory.md | new → 1.0.0 | Record process baseline and measured deferred/first/second native decode footprints with scope limits. |

| 2026-10-27 | docs/hld/speech-model-lifecycle.md | new → 1.0.0 | CR-335: user-selected first-use ASR loading with immediate capture and shared cached engine. |
| 2026-10-27 | docs/lld/speech-model-lifecycle.md | new → 1.0.0 | CR-335: map deferred holder, cached bridges, native entry points and regression checks. |

| 2026-10-27 | docs/PITFALLS.md | 1.0.10 → 1.0.11 | CR-335 / P-272: prevent loading unused downloaded speech models at launch and record physical-footprint measurement limits. |

| 2026-10-27 | docs/TEST-PLAN.md | 1.0.20 → 1.0.21 | Add regression coverage for in-drawer quit/cancel, preserved Top applications ordering, collapsed CPU/RAM details, native focus/accessibility state and quit feedback parsing bounds. |
| 2026-10-27 | docs/PRD.md | 1.0.40 → 1.0.41 | Keep Top applications at the bottom of CPU/RAM drawers, collapse advanced sections by default, and keep confirmed app quit in the native drawer without foregrounding OfficeKit. |
| 2026-10-27 | docs/hld/system-stats-dashboard.md | 1.0.4 → 1.0.5 | Record collapsed CPU/RAM detail groups and in-place quit confirmation while preserving the application list. |
| 2026-10-27 | docs/lld/system-stats-dashboard.md | 1.0.4 → 1.0.5 | Document native disclosure and quit feedback bridges for system-stat drawers. |
| 2026-10-27 | docs/PRD.md | 1.0.39 → 1.0.40 | Move Network diagnostics into the existing macOS menu-bar drawer, remove the duplicate app-header widget, and document the revised gauge/history layout. |
| 2026-10-27 | docs/hld/network-health.md | 1.0.3 → 1.0.4 | Update the health view location and native event flow. |
| 2026-10-27 | docs/lld/network-health.md | 1.0.3 → 1.0.4 | Document native drawer rendering, keyboard access and opt-in checks. |
| 2026-10-27 | docs/TEST-PLAN.md | 1.0.22 → 1.0.23 | Record timer, DOM identity and selector sizing mutation evidence. |
| 2026-10-27 | docs/PITFALLS.md | 1.0.9 → 1.0.10 | Record mutation evidence for the Live Workspace timer reset, stable dismissal rows and standard selector sizing. |
| 2026-10-27 | docs/TEST-PLAN.md | 1.0.21 → 1.0.22 | Cover local auto-clear preference, speech-based timer resets, memory-only clearing and stable dismissal rows. |
| 2026-10-27 | docs/PITFALLS.md | 1.0.8 → 1.0.9 | Record the completed recurring-render blink prevention and DOM identity regression. |
| 2026-10-27 | docs/hld/speech-coach.md | 1.11.0 → 1.12.0 | Add the approved Live Workspace inactivity auto-clear behavior and local preference boundary. |
| 2026-10-27 | docs/lld/speech-coach.md | 1.11.0 → 1.12.0 | Add the approved Live Workspace inactivity auto-clear behavior and local preference boundary. |

| 2026-10-27 | docs/PITFALLS.md | 1.0.7 → 1.0.8 | CR-331: record mutation-proven production bridge wiring and supported-SDK compatibility catches (P-267/P-268). |

| 2026-10-27 | docs/TEST-PLAN.md | 1.0.19 → 1.0.20 | CR-331: cover full brainstorm, workspace validation/Copy/fallback, production wiring and live local-model contrasts. |

| 2026-10-27 | docs/hld/speech-coach.md | 1.10.0 → 1.11.0 | CR-331: distinguish workspace sentence rewrites from short HUD cues. |
| 2026-10-27 | docs/lld/speech-coach.md | 1.10.0 → 1.11.0 | CR-331: document model bridge bounds, fallback and regressions. |

| 2026-10-27 | docs/PITFALLS.md | 1.0.6 → 1.0.7 | CR-331: record sentence coaching regression prevention. |
| 2026-10-27 | docs/verification/speech-coach-clarity.md | new → 1.0.0 | CR-331: record full brainstorm regressions and explicit on-device model acceptance. |

| 2026-10-27 | docs/TEST-PLAN.md | 1.0.18 → 1.0.19 | Remove a duplicated history phrase after rebasing the process-resource feature onto the invoice profile changes. |

| 2026-10-27 | docs/TEST-PLAN.md | 1.0.17 → 1.0.18 | Add a repeatable process-manager test and coverage command with statement and branch thresholds at 100%. |
| 2026-10-27 | docs/PITFALLS.md | 1.0.5 → 1.0.6 / P-264–P-265 | Record fail-closed GPU snapshots and maximum-edge coverage for bounded API DTOs, with mutation-verified regressions. |

| 2026-10-27 | API-CONTRACT.md, docs/hld/system-stats-dashboard.md, docs/lld/system-stats-dashboard.md, docs/TEST-PLAN.md, docs/ui-research/2026-10-27-approved-process-resource-drawers.md | 1.94.1 → 1.94.2 / 1.0.3 → 1.0.4 / 1.0.3 → 1.0.4 / 1.0.16 → 1.0.17 / new 1.0.0 | Group menu-bar CPU/GPU/RAM usage under app display names, include combined helper-process totals and best-effort Apple GPU activity, add focused regressions, and record the approved title-bar overlay mock. |

| 2026-10-27 | docs/PITFALLS.md | 1.0.4 → 1.0.5 | Add invoice profile setup cleanup, shared modal, mutation evidence, logo-preview geometry and synchronous spawn failure pitfalls (P-259–P-263). |
| 2026-10-27 | docs/TESTING.md | 1.12.415 → 1.12.416 | Add synchronous UI API server spawn-failure cleanup regression and final invoice profile setup verification. |
| 2026-10-27 | docs/TEST-PLAN.md | 1.0.15 → 1.0.16 | Add invoice profile wizard defaults, logo preview geometry, isolated test-server cleanup and synchronous startup failure regression coverage. |
| 2026-10-27 | docs/TESTING.md | 1.12.414 → 1.12.415 | Record mutation-proven profile guards, cleanup tests, and stable logo-preview geometry. |
| 2026-10-27 | docs/TESTING.md | 1.12.413 → 1.12.414 | Record profile wizard, logo preview and isolated UI-test data cleanup. |
| 2026-10-27 | docs/PRD-invoices.md | 1.4.0 → 1.5.0 | Document first-run profile wizard, shared create/edit flow, immediate logo preview, and one-action settings bar. |
| 2026-10-27 | docs/hld/invoices.md | 1.4.0 → 1.5.0 | Record the approved first-run profile wizard and its user-visible flow. |
| 2026-10-27 | docs/lld/invoices.md | 1.4.0 → 1.5.0 | Map profile setup and editing to the wizard implementation and test-data isolation. |
| 2026-10-27 | API-CONTRACT.md, docs/PRD.md, docs/hld/network-health.md, docs/lld/network-health.md, docs/TEST-PLAN.md, docs/PITFALLS.md | 1.94.0 → 1.94.1 / 1.0.38 → 1.0.39 / 1.0.0 → 1.0.1 each / 1.0.14 → 1.0.15 / 1.0.0 → 1.0.1 | Address review: document error statuses and macOS/Linux/Windows route support, select the lowest route metric, clear stale diagnosis on failed checks, add keyboard dismissal and focused regressions. |
| 2026-10-27 | design/officekit-tokens.css | v1.8.9 → v1.8.10 | Add shared pill-radius and emphasis-border tokens for Network Stats controls and rate rings. |
| 2026-10-27 | docs/hld/network-health.md, docs/lld/network-health.md, docs/PITFALLS.md | 1.0.1 → 1.0.2 / 1.0.1 → 1.0.2 / 1.0.1 → 1.0.2 | Use locale-independent Windows ActiveStore route discovery and JSON output; record the wrong-gateway regression. |
| 2026-10-27 | docs/hld/network-health.md, docs/lld/network-health.md, docs/PITFALLS.md | 1.0.2 → 1.0.3 / 1.0.2 → 1.0.3 / 1.0.2 → 1.0.3 | Cap Windows ActiveStore JSON output to the 512 lowest-metric routes before Python buffers and parses it. |
| 2026-10-27 | docs/PITFALLS.md | 1.0.3 → 1.0.4 | Record and fix a parallel Rust unit-test race in global headphone-motion state exposed by the full shipping gate. |

| 2026-10-26 | docs/PRD-invoices.md, docs/hld/invoices.md, docs/lld/invoices.md | 1.3.0 → 1.4.0 each | Record final invoice review sign-offs, the passing full repository gate, measured 100% module coverage and desktop/compact browser workflows. |
| 2026-10-26 | docs/invoices/API-CONTRACT.md | 1.2.0 → 1.2.1 | Remove duplicate schedule, recurring and report rows; align route DTO names and report query descriptions with the implemented router. |
| 2026-10-26 | docs/FIRST-MAC-RELEASE.md, docs/TOOL-GUIDE.md | 1.0.212 → 1.0.213 / 1.199.146 → 1.199.147 | Record the successful full macOS app/DMG build and mounted-package smoke while keeping invoice-specific packaged and installed acceptance open. |
| 2026-10-26 | API-CONTRACT.md, docs/TESTING.md, docs/TOOL-GUIDE.md | 1.92.0 → 1.93.0 / 1.12.412 → 1.12.413 / 1.198.145 → 1.199.146 | Record the implemented invoice API link, cross-language coverage/mutation commands, platform boundary and development catalogue entry. |
| 2026-10-26 | docs/PRD-invoices.md, docs/hld/invoices.md, docs/lld/invoices.md, docs/invoices/API-CONTRACT.md | 1.2.0 → 1.3.0 / 1.2.0 → 1.3.0 / 1.2.0 → 1.3.0 / 1.1.0 → 1.2.0 | Record implementation and 100% source coverage evidence, align recurring draft timing to opening the invoice tool, and update final verification status. |
| 2026-10-26 | docs/FIRST-MAC-RELEASE.md | 1.0.211 → 1.0.212 | Add Invoice Manager to the development-only release hold-back list with current source/browser evidence and explicit packaged/platform acceptance still open. |
| 2026-10-26 | docs/PRD-invoices.md, docs/hld/invoices.md, docs/lld/invoices.md, docs/ui-research/2026-10-26-approved-invoices.md, docs/ARCHITECTURE.md | 1.0.2 → 1.1.0 / 1.0.0 → 1.1.0 / 1.0.0 → 1.1.0 / 1.0.0 → 1.1.0 / 1.1.8 → 1.1.9 | Record accepted independent profiles and SQLite workspace with full history, verified backup/restore, dated documents and native path boundaries. |
| 2026-10-26 | docs/lld/invoices.md | new → 1.0.0 | Map accepted profile/catalogue/global settings refinements to module files, shared storage interface and 100% coverage verification checkpoints. |
| 2026-10-26 | docs/PRD-invoices.md | 1.0.1 → 1.0.2 | Confirm business identity in settings and reusable catalogue items with editable invoice-specific details; owner excludes stock quantities. |
| 2026-10-26 | docs/PRD-invoices.md, docs/ARCHITECTURE.md, API-CONTRACT.md | 1.0.0 → 1.0.1 / 1.1.7 → 1.1.8 / 1.91.6 → 1.92.0 | Record initial mock approval, selected direct working folder and global currency/tax/payment refinements; link the proposed invoice contract without claiming implementation. |
| 2026-10-26 | docs/hld/invoices.md, docs/invoices/API-CONTRACT.md, docs/ui-research/2026-10-26-approved-invoices.md | new → 1.0.0 | Proposed bounded direct-folder architecture, complete resource/DTO contract, coverage gate and durable owner decision record. |
| 2026-10-25 | docs/PRD-invoices.md | new → 1.0.0 | Record the proposed invoice scope, customizable branding/templates, manual-sync alternatives, delivery gates and owner 100% module coverage requirement. |
| 2026-10-26 | docs/TEST-PLAN.md | 1.0.13 → 1.0.14 | Cover synchronized eye-exercise cues and pose frames. |
| 2026-10-26 | docs/TESTING.md | 1.12.411 → 1.12.412 | Record desktop and compact WebKit checks for cue-matched eye poses and the full coverage gate result. |
| 2026-10-26 | docs/hld/pending-tools-and-ergonomics.md | 1.0.8 → 1.0.9 | Eye-rest prompts guide far focus, slow blinking and side-to-side gaze with cue-matched poses. |
| 2026-10-26 | docs/lld/pending-tools-and-ergonomics.md | 1.1.1 → 1.1.2 | Document the eye cue frame groups and still-pose behavior under reduced motion. |
| 2026-10-26 | API-CONTRACT.md | 1.90.0 → 1.92.0 | Rebase onto main (1.91.6): the new Files, trash, Live Workspace, menu-bar stats and calculator/developer/image/PDF routes are classified in the licence gate; no route or DTO changed. |
| 2026-10-26 | docs/TESTING.md | 1.12.392 → 1.12.412 | Rebase onto main (1.12.411): the licence-gate classification tests cover main's new commands and routes; profile-gated file-job and trash tests removed with the profile. |
| 2026-10-26 | docs/FIRST-MAC-RELEASE.md | 1.0.206 → 1.0.212 | Rebase onto main (1.0.211): the private-beta removal note, rebased above main. |
| 2026-10-26 | docs/TOOL-GUIDE.md | 1.198.137 → 1.198.146 | Rebase onto main (1.198.145): the private-beta removal note, rebased above main. |
| 2026-10-26 | DESIGN_SYSTEM.md | 1.9.12 → 1.9.17 | Rebase onto main (1.9.16): the locked-app state, rebased above the calculator work area. |
| 2026-10-23 | API-CONTRACT.md | 1.77.1 → 1.90.0 | Rebase onto main (1.89.2): Quick Controls and Speech Coach native commands are Paid in the licence gate; no route or DTO changed. |
| 2026-10-23 | docs/TESTING.md | 1.12.384 → 1.12.392 | Rebase onto main (1.12.391): licence-gate test notes: the Quick Controls and Speech Coach commands are classified Paid. |
| 2026-10-23 | docs/FIRST-MAC-RELEASE.md | 1.0.200 → 1.0.206 | Rebase onto main (1.0.205): the private-beta removal note, rebased above main. |
| 2026-10-23 | docs/TOOL-GUIDE.md | 1.197.120 → 1.198.137 | Rebase onto main (1.198.136): the private-beta removal note, rebased above main. |
| 2026-10-23 | DESIGN_SYSTEM.md | 1.9.3 → 1.9.12 | Rebase onto main (1.9.11): the locked-app state, rebased above the Voice section-list screen. |
| 2026-10-22 | API-CONTRACT.md | 1.77.0 → 1.77.1 | Rebase onto main (meeting countdown 1.77.0): renumber the S3 licence-gate contract above it; ergonomics_calendar_action is Paid like the other ergonomics commands. |
| 2026-10-22 | docs/TESTING.md | 1.12.383 → 1.12.384 | Rebase onto main (search no-results request 1.12.383): renumber the S3 licence-gate test notes above it. |
| 2026-10-22 | docs/FIRST-MAC-RELEASE.md | 1.0.199 → 1.0.200 | Rebase onto main (meeting countdown 1.0.199): renumber the S3 private-beta removal note above it. |
| 2026-10-22 | docs/TOOL-GUIDE.md | 1.197.119 → 1.197.120 | Rebase onto main (meeting countdown 1.197.119): renumber the S3 private-beta removal note above it. |
| 2026-10-22 | API-CONTRACT.md | 1.76.11 → 1.76.12 | S3 review round 1: Clipboard & Snippets Studio gated, CORS outermost on gate rejections, typed OpenAPI for release/status/entitlement, Settings and Updates locked wording, `license-state-changed` event, launch-time receipt check, fail-closed clock, push retry schedule, ergonomics ships in every build as a paid feature, free set 16 of 57 |
| 2026-10-22 | docs/hld/paid-activation.md | 1.2.5 → 1.2.6 | S3 review round 1: webhook secret is a `NoEcho` parameter (DEVOPS-3); free set 16 of 57 with Clipboard & Snippets Studio locked; ergonomics paid in every build |
| 2026-10-22 | docs/lld/paid-activation.md | 1.4.1 → 1.4.2 | S3 review round 1: track A notes (CORS, typed OpenAPI, sleep-aware clock, release licence-config guard, `start:python` is locked) and the "As built (S3 round 1)" subsection (launch-time receipt check, `license-state-changed`, fail-closed clock, push retry, ergonomics paid in every build, release prerequisite variables) |
| 2026-10-22 | docs/TESTING.md | 1.12.380 → 1.12.381 | S3 review round 1: licence-gate test notes, sidecar smoke probe, release licence-config check, `start:python` is locked, ergonomics gating note |
| 2026-10-22 | DESIGN_SYSTEM.md | 1.9.2 → 1.9.3 | S3 review round 1: owner-refined locked-app state (Clipboard studio locked, approved banner copy only, App Tour keeps paid steps without switching tabs, converter sub-modes, chip row) |

| 2026-10-22 | docs/TESTING.md | 1.12.379 → 1.12.380 | Rebase onto main: renumber the S3 private-beta-profile removal notes above main's ergonomics version. |
| 2026-10-22 | docs/FIRST-MAC-RELEASE.md | 1.0.198 → 1.0.199 | Rebase onto main: renumber the S3 private-beta-profile removal notes above main's ergonomics version. |
| 2026-10-22 | docs/TOOL-GUIDE.md | 1.197.118 → 1.197.119 | Rebase onto main: renumber the S3 private-beta-profile removal notes above main's ergonomics version. |

| 2026-10-21 | DESIGN_SYSTEM.md | 1.9.1 → 1.9.2 | S3 commit 3b: record the locked-app UI (licence notice in the announcement slot, Locked chips, header badge words, hidden update controls) built from the approved mock; the mock file is removed, the decision stays in `review/paid-activation/requirements.md` |

| 2026-10-21 | API-CONTRACT.md, docs/TESTING.md, docs/TOOL-GUIDE.md, docs/FIRST-MAC-RELEASE.md, docs/MCP-AGENT-SUPPORT.md, docs/lld/media-toolkit.md, docs/hld/media-toolkit.md, docs/lld/workspace-and-annotation-refresh.md | 1.76.10 → 1.76.11 / 1.12.376 → 1.12.377 / 1.197.117 → 1.197.118 / 1.0.196 → 1.0.197 / 1.1 → 1.1.1 / 1.0.124 → 1.0.125 / 1.1.55 → 1.1.56 / 1.0.2 → 1.0.3 | S3 commit 3a: the `private-beta` release profile is removed. `GET /api/release` returns `{version, edition}`; `GET /api/tools/search` is unfiltered; `/docs`, `/redoc` and `/openapi.json` are always served; `release-profile.json`, `engine_release_profile.py`, `build:beta`, `test:macos-dmg:beta` and the UI profile client are gone; beta-era log entries in TOOL-GUIDE and FIRST-MAC-RELEASE are marked historical |

| 2026-10-21 | API-CONTRACT.md, docs/hld/paid-activation.md | 1.76.9 → 1.76.10 / 1.2.4 → 1.2.5 | `GET /api/tools/search` is a free route (a locked app needs the catalog to render free tools and Locked chips); HLD locked-state text now matches the owner decisions and the approved mock |
| 2026-10-21 | API-CONTRACT.md, docs/lld/paid-activation.md | 1.76.8 → 1.76.9 / 1.4.0 → 1.4.1 | S3 owner decisions: new `FREE_ROUTES` classification (36 routes of the Calculators, Converters and Developer & Data tools work with no, expired or revoked entitlement); `GET /api/system/check-update` leaves the exempt set and is gated (updates disabled while locked); Settings uses no sidecar route; routes shared with paid tools stay gated; the LLD S3 `index.html` row now locks Settings and Updates. |
| 2026-10-21 | API-CONTRACT.md | 1.76.7 → 1.76.8 | S3 commit 1 (Python sidecar gate): `GET /api/license/status` reads the in-memory entitlement, `PUT`/`DELETE /api/license/entitlement` guarded by the native grant header, `license_required` and `feature_not_licensed` use the `{ "error": { code, message } }` envelope. |
| 2026-10-22 | DESIGN_SYSTEM.md / index.html / assets/officekit-workspace.js / ui-tests/voice-section-nav.spec.mjs / ui-tests/speech-coach.spec.mjs / ui-tests/workspace-refresh.spec.mjs / ui-tests/focus-consistency.spec.mjs / tests/section-nav.test.mjs / docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md | 1.9.10 → 1.9.11 / 1.0.4 → 1.0.5 | Voice: Speech Coach is a section beside Dictation (approved mock), tab bar removed; Home search field removed (owner approval). Decisions 15 and 16. |
| 2026-10-25 | API-CONTRACT.md | 1.91.5 → 1.91.6 | System metrics add network details, Bluetooth batteries, GPU model and cores, disk totals and volumes, battery power readings. |
| 2026-10-25 | API-CONTRACT.md | 1.91.4 → 1.91.5 | System metrics add `cpu_topology`; headline CPU follows the System + User split. |
| 2026-10-24 | DESIGN_SYSTEM.md, docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md | 1.9.15 → 1.9.16 / 1.0.10 → 1.0.11 | Calculator work area approved (decision 20, option A): the card names the calculator, Calculate, Save result and Download sit in the card, calculator screens show no bottom bar, and the card fills the work area above the version footer. The bottom row (status left, Calculate right, inside the card) is built on all 27 calculator forms, and All tools is a text link. Calculator-flow Playwright spec updated to current behaviour (list fields restore one value per line; Save precedes Download; formatter uses its Download control; VAT Calculate returns after an input change): 47 of 47 pass. |
| 2026-10-25 | API-CONTRACT.md, docs/hld/file-intake.md, docs/lld/file-intake.md | 1.91.3 → 1.91.4 / 1.0.7 → 1.0.8 / 1.0.7 → 1.0.8 | Declare binary OpenAPI content and pre-stream file validation; record chooser error, filtering, and native intake queue regressions. |
| 2026-10-25 | docs/ARCHITECTURE.md, docs/PRD.md | 1.1.6 → 1.1.7 / 1.0.36 → 1.0.37 | Merge System Stats and shared file-intake decisions and requirements. |
| 2026-10-25 | docs/TEST-PLAN.md | 1.0.12 → 1.0.13 | Merge System Stats and shared file-intake regression coverage. |

| 2026-10-24 | API-CONTRACT.md, docs/PRD.md, docs/ARCHITECTURE.md, docs/hld/system-stats-dashboard.md, docs/lld/system-stats-dashboard.md, docs/ui-research/2026-10-24-approved-systemstats.md | 1.90.9 → 1.91.0 / 1.0.34 → 1.0.35 / 1.0.9 → 1.0.10 / new docs 1.0.0 → 1.0.1 | Add the approved Stats-inspired System Stats dashboard and optional local per-core, GPU, sensor, and laptop battery fields; retain current sampling and tray preference surfaces. |
| 2026-10-25 | README.md, docs/TEST-PLAN.md, docs/hld/system-stats-dashboard.md, docs/lld/system-stats-dashboard.md | new System Stats overview / 1.0.10 → 1.0.11 / 1.0.1 → 1.0.2 / 1.0.1 → 1.0.2 | Document live System Stats availability, add provider/UI regression coverage, and record the passing whole-repository gate and native build limitation. |
| 2026-10-25 | docs/PRD.md, docs/TEST-PLAN.md, docs/hld/system-stats-dashboard.md, docs/lld/system-stats-dashboard.md | 1.0.35 → 1.0.36 / 1.0.11 → 1.0.12 / 1.0.2 → 1.0.3 / 1.0.2 → 1.0.3 | Clarify GPU and battery tray scope, add native Apple HID temperature support, and cover sensor and battery edge cases. |
| 2026-10-25 | docs/ARCHITECTURE.md | 1.0.10 → 1.0.11 | Record native Mac HID temperature collection in the System Stats architecture decision. |

| 2026-10-25 | docs/lld/file-intake.md | 1.0.6 → 1.0.7 | Replace planned test and smoke-script paths with the implemented intake tests and package checks. |

| 2026-10-25 | docs/TEST-PLAN.md | 1.0.10 → 1.0.11 | Add shared file-intake API, native queue, chooser handoff, and packaged macOS verification rows. |

| 2026-10-24 | docs/ARCHITECTURE.md, docs/hld/file-intake.md, docs/lld/file-intake.md, review/file-open-and-drop/requirements.md | 1.1.5 → 1.1.6 / 1.0.6 → 1.0.7 / 1.0.5 → 1.0.6 | Record passing full application suites, desktop and compact WebKit intake flow, signed ARM64 DMG smoke test, and six alternate-rank Finder associations; retain native installed Finder delivery and physical drop as manual acceptance. |

| 2026-10-24 | docs/lld/file-intake.md | 1.0.4 → 1.0.5 | Add the generated capability asset copy path and subset contract to the implementation map. |

| 2026-10-24 | docs/hld/file-intake.md | 1.0.5 → 1.0.6 | Specify explicit per-file chooser selection and path-free subset derivation. |

| 2026-10-24 | API-CONTRACT.md, docs/ARCHITECTURE.md, docs/hld/file-intake.md, docs/lld/file-intake.md | 1.91.2 → 1.91.3 / 1.1.4 → 1.1.5 / 1.0.4 → 1.0.5 / 1.0.3 → 1.0.4 | Record initial native intake, selection content/subset APIs, capability chooser, generated UI and pending application/package acceptance. |

| 2026-10-24 | docs/ARCHITECTURE.md, docs/hld/file-intake.md, docs/lld/file-intake.md | 1.1.3 → 1.1.4 / 1.0.3 → 1.0.4 / 1.0.2 → 1.0.3 | Record owner HLD agreement (“agreed”) and implementation authorization. |

| 2026-10-23 | docs/hld/file-intake.md, docs/lld/file-intake.md | 1.0.2 → 1.0.3 / 1.0.1 → 1.0.2 | Clarify that mock validation ran while application tests and implementation remain pending. |

| 2026-10-23 | docs/hld/file-intake.md | 1.0.1 → 1.0.2 | Link the official Tauri file-association configuration and Opened event references. |

| 2026-10-23 | docs/hld/file-intake.md, docs/lld/file-intake.md | 1.0.0 → 1.0.1 / 1.0.0 → 1.0.1 | Clarify file-only native intake, explicit capability bounds and FIFO behavior for separate pending batches. |

| 2026-10-23 | docs/ARCHITECTURE.md | 1.1.0 → 1.1.1 | Record the initial mock direction for shared native file intake and the approval gate. |

| 2026-10-23 | docs/ARCHITECTURE.md | 1.1.1 → 1.1.2 | Refine shared intake around a grouped searchable catalog filtered by input capabilities, prerequisites and release profile. |

| 2026-10-23 | docs/hld/file-intake.md, docs/lld/file-intake.md | 0.0.0 → 1.0.0 / 0.0.0 → 1.0.0 | Draft the approved shared intake architecture and buildable file-by-file plan; implementation awaits HLD agreement. |

| 2026-10-23 | docs/PRD.md | 1.0.34 → 1.0.35 | Add owner-approved shared native file intake requirements for app-window drops and Finder Open With. |

| 2026-10-23 | API-CONTRACT.md | 1.91.1 → 1.91.2 | Mark the selection-scoped content stream contract as owner-approved mock scope and align its safe response headers/statuses. |

| 2026-10-23 | docs/ARCHITECTURE.md | 1.1.2 → 1.1.3 | Record the approved grouped file-tool mock and link the HLD/LLD drafts awaiting HLD agreement. |

| 2026-10-23 | API-CONTRACT.md | 1.90.9 → 1.91.0 / 1.91.0 → 1.91.1 | Draft the selection-scoped binary content read needed to feed native file selections into existing file-input workflows; label the contract draft pending revised mock approval. |

| 2026-10-23 | docs/ARCHITECTURE.md | 1.1.1 → 1.1.2 | Refine the shared file intake decision around a grouped, searchable catalog of compatible tools, with file-count, prerequisite and release-profile filtering; revised mock approval pending. |

| 2026-10-23 | docs/ARCHITECTURE.md | 1.0.9 → 1.1.0 | Record the owner-selected shared intake architecture for native window drops and macOS Finder Open With; mock approval remains pending. |

>| 2026-10-23 | .claude/se-rules/conventions.md | 1.0.0 → 1.1.0 | Retro of the pending-tools slices: mocks are checked with `scripts/check-mock-buttons.mjs` before approval (segmented toggles are not counted; owner answer “Not counted (Recommended)”), and doc conflicts from rebasing parallel branches go through `scripts/resolve-doc-conflicts.mjs` first. |
| 2026-10-23 | API-CONTRACT.md | 1.90.8 → 1.90.9 | S06 Restore from Trash, round 3 review: the Forget route lists the generic 422 returned when the ledger cannot be saved (ARCH-6). |
| 2026-10-23 | API-CONTRACT.md, docs/ui-research/2026-10-22-approved-pending-tools.md | 1.90.7 → 1.90.8 / 1.14.0 → 1.14.1 | S06 Restore from Trash, round 2 review fixes: the contract lists the generic 422 for the listing and restorations routes (ARCH-4) and names the DTOs in the route table without shapes (ARCH-5); the approval record notes the owner's answer “New wording (Recommended)” to the Restore result note (PM-3, UX-9, UX-11, UX-12). |
| 2026-10-23 | API-CONTRACT.md, docs/lld/pending-tools-files.md, docs/ARCHITECTURE.md | 1.90.6 → 1.90.7 / 1.0.4 → 1.0.5 / 1.0.8 → 1.0.9 | S06 Restore from Trash, round 1 review fixes: the listing is a read and never rewrites the ledger; the 10,000 cap holds in the stored file after each write; the ledger folder is set to 0700 on every write; the three success bodies are named DTOs (`TrashRecordPage`, `TrashRestoreGrant`, `TrashRestoration`); every trash status and its message is listed; the mint capacity check precedes the destination grant spend; the ARCHITECTURE constraint records the four native commands (DEVOPS-3). |
| 2026-10-23 | docs/hld/pending-tools-files.md, docs/lld/pending-tools-files.md, API-CONTRACT.md, docs/ui-research/2026-10-22-approved-pending-tools.md, docs/FIRST-MAC-RELEASE.md | 1.0.9 → 1.0.10 / 1.0.3 → 1.0.4 / 1.90.5 → 1.90.6 / 1.13.0 → 1.14.0 / 1.0.208 → 1.0.209 | S06 Restore from Trash built as option R1 on the owner's approval “approved” (2026-10-23): HLD section 4 status and the amended disclosure placement (before each move, plus the Restore screen); LLD section 11; the trash routes in the API contract; the approval record with its defaults and button counts; the development-only release row. |
| 2026-10-23 | docs/TESTING.md | 1.12.392 → 1.12.393 | S06 Restore from Trash gate evidence (`gate-2`): 1,000 Node tests and 3,391 Python tests pass; c8 reports 100%. |
| 2026-10-23 | docs/TOOL-GUIDE.md | 1.198.142 → 1.198.143 | S06 Restore from Trash row (`trash_restore`), development-only; catalogue counts regenerated (111 search entries, 50 pending-slice entries). |
| 2026-10-23 | docs/hld/pending-tools-files.md | 1.0.8 → 1.0.9 | F11 review round 2 (UX-5): the symlink inspector selection line shows the folder name alone and an empty selection reads “Choose a folder to begin.”, as the approved mock shows; other Files tools keep the shared “Selected: ” line. |
| 2026-10-23 | docs/hld/pending-tools-files.md | 1.0.7 → 1.0.8 | F11 review round 1: amend section 4 B1 wording and the threat-model row to the built walk (owner answer “Amend the design text (Recommended)”, ARCH-1/PM-1); coordinator decision ARCH-2/CR-4/PM-7 (relative and absolute targets walked the same way); copy trim “Keep shared, trim F11-only (Recommended)” (UX-4/PM-2). |
| 2026-10-23 | docs/ARCHITECTURE.md | 1.0.7 → 1.0.8 | F11 needs no new native authority; it uses the existing folder selection (DEVOPS-1). S06 restore remains the only tool that needs its own native authority. |
| 2026-10-23 | API-CONTRACT.md | 1.90.4 → 1.90.5 | Symlink report carries `entry_limit` (QA-5/CR-6/PM-9.3); hops walk real directories inside the roots for relative and absolute targets (ARCH-2). |
| 2026-10-23 | docs/hld/pending-tools-files.md, docs/ui-research/2026-10-22-approved-pending-tools.md, docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md | 1.0.6 → 1.0.7 / 1.12.0 → 1.13.0 / 1.0.9 → 1.0.10 | Record the owner answers of 2026-10-23, quoted as given: “Keep it (Recommended)” for the F11 `denied` state, “Folder name (Recommended)” for the F11 selection line, and “Accept the exception (Recommended)” for the Archive screen title “Archive tools” against the catalogue name “Compress & Extract ZIP” (navigation decision 1). |

| 2026-10-23 | docs/hld/pending-tools-files.md, API-CONTRACT.md, docs/TOOL-GUIDE.md, docs/FIRST-MAC-RELEASE.md | 1.0.5 → 1.0.6 / 1.90.3 → 1.90.4 / 1.198.141 → 1.198.142 / 1.0.207 → 1.0.208 | Add the F11 symlink inspector (`symlinks`, option B1): HLD section 4 records the built design and its two owner questions; the API contract row; the TOOL-GUIDE F11 row with regenerated counts (110 search entries, 49 pending-slice entries); and the development-only release row. |

| 2026-10-23 | docs/ui-research/2026-10-22-approved-pending-tools.md | 1.11.0 → 1.12.0 | Record the owner approval “Approve (Recommended)” of the F11 symlink inspector mock (2026-10-23), with its button counts, the earlier owner answers it relies on, and the two copy questions awaiting confirmation. |
| 2026-10-23 | DESIGN_SYSTEM.md / index.html / assets/officekit-media.js / tests/media-toolkit-ui.test.mjs / ui-tests/media-parity.spec.mjs / docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md | 1.9.14 → 1.9.15 / 1.0.8 → 1.0.9 | Media toolkit: a mixed batch lists operations under one labelled group per type; Settings for a file selects its type. Decision 19. |

| 2026-10-23 | DESIGN_SYSTEM.md / assets/officekit-pdf-editor.css / docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md | 1.9.13 → 1.9.14 / 1.0.7 → 1.0.8 | PDF editor: inspector column capped so the sign panel stays inside the window (defensive; overflow not reproduced in harness). Decision 18. |

| 2026-10-23 | DESIGN_SYSTEM.md / index.html / assets/officekit-media.js / assets/officekit.input.css / tests/media-toolkit-ui.test.mjs / ui-tests/media-action-bar.spec.mjs / docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md | 1.9.12 → 1.9.13 / 1.0.6 → 1.0.7 | Media toolkit: type from the chosen files, JPEG hidden as a convert target for JPEG batches, Select files as a link, labelled operation select. Decision 17. |

| 2026-10-23 | DESIGN_SYSTEM.md / index.html / assets/officekit.input.css / ui-tests/screenshot-editor.spec.mjs / tests/screenshot-editor-ui.test.mjs / docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md | 1.9.11 → 1.9.12 / 1.0.5 → 1.0.6 | Screenshot editor: Save and More in the action bar; Copy and Optimize under More; Capture area and paste as text links; Choose image is the only source button. Decision 12. |

| 2026-10-23 | docs/ui-research/2026-10-22-approved-pending-tools.md, docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md | 1.10.0 → 1.11.0 / 1.0.5 → 1.0.6 | Owner answer “Files v3 mock” on the archive screen copy after the files rebase onto the tool template: title “Archive tools”, Operation picker with Format shown, Run “Extract selected or all” / “Create ZIP”, “Reset selection” in-text link; decision 11's archive half is superseded, its renamer half stands. The archive UI tests follow. |

| 2026-10-22 | docs/ui-research/2026-10-22-approved-pending-tools.md | 1.9.0 → 1.10.0 | Record the owner answer “Refuse (Recommended)” for archive output inside the selected folder (PM-10): archive create refuses before any read, with the fixed message, and no ZIP is written.

| 2026-10-22 | docs/hld/pending-tools-files.md | 1.0.4 → 1.0.5 | Record the owner answer “Refuse (Recommended)” in section 9 for archive output inside the selected folder (PM-10).

| 2026-10-22 | docs/ui-research/2026-10-22-approved-pending-tools.md | 1.8.0 → 1.9.0 | Record the round 3 owner answers on the Files screens, quoted as given: UX-12 “Keep, same pattern (Recommended)”, UX-13 “Primary (Recommended)”, UX-7 “Accept as built (Recommended)” and UX-14 “Empty header (Recommended)”. Replace the earlier proposal wording with these answers, and record the PM-9 Superset Browser inspection and the PM-8 storage analyser check as coordinator notes.

| 2026-10-22 | docs/hld/pending-tools-files.md / API-CONTRACT.md / docs/TOOL-GUIDE.md | 1.0.3 → 1.0.4 / 1.90.2 → 1.90.3 / 1.198.140 → 1.198.141 | Round 3 of files track A: the empty-folders row records the Windows refusal `Folder checks need macOS or Linux.` (ARCH-6); the HLD points to the approval record instead of the unapproved mock (ARCH-7, CR-11); TOOL-GUIDE notes the 7zz skip condition on the F12 tests (QA-12) and cites the renamed F06 output-in-source test, which fails closed with the output-inside-selection message (QA-10).

| 2026-10-22 | docs/ui-research/2026-10-22-approved-pending-tools.md | 1.7.0 → 1.8.0 | Record the owner's answers on the Files re-mock v3 (“Approve (Recommended)”, UX-11: Duplicates 12 → 3, archive inspector 3 → 1, File checksum 3 → 2, read-only Folder compare and Similar images 3 → 2) and on the single SHA-256 row (“Accept all as built (Recommended)”, UX-9). Author: Claude (files track A fix round 3). |

| 2026-10-22 | docs/lld/pending-tools-files.md, docs/hld/pending-tools-files.md | 1.0.2 → 1.0.3 / 1.0.2 → 1.0.3 | Round 2 of files track A: the walker's open-time check compares device, inode and directory type only (CR-8, with a regression test); Windows refuses the folder walk, documented in LLD section 7 and tested (CR-9); the `_open_listed_folder` docstring matches the code (CR-10); HLD section 9 records three deviations for the owner (compare headline, Windows refusal, duplicate member paths). Author: Claude (files track A fix round 2). |

| 2026-10-22 | docs/TOOL-GUIDE.md | 1.198.139 → 1.198.140 | Cite the named tests for the PM-3 cases (F06 output in source scope and cancellation, F07 absolute paths and symlinks, F12 nested and duplicate paths); rename the archive_inspector name to "Archive inspector" to match the approval record (UX-7). Author: Claude (files track A fix round 2). |

| 2026-10-22 | docs/TOOL-GUIDE.md | 1.198.138 → 1.198.139 | Development scope count set to 81 to match the merged catalogue (calculators and files rows) after the rebase onto main; the generated count table is unchanged in meaning. |

| 2026-10-22 | docs/hld/pending-tools-files.md | 1.0.1 → 1.0.2 | Record the owner decisions on section 9: add `POST /api/file-jobs/*/reveals` to the private-beta release profile so the beta dup_finder Show in Finder works (release-profile change, regression test added), converter Extract ZIP panel kept, host paths shown in local-only F11 and restore views, track B order F11 then S06, and the PM-6 build choices accepted as built. Author: Claude (files track A fix round 1). |

| 2026-10-22 | docs/TOOL-GUIDE.md, docs/FIRST-MAC-RELEASE.md, docs/hld/pending-tools-files.md | 1.198.137 → 1.198.138 / 1.0.206 → 1.0.207 / 1.0.0 → 1.0.1 | Owner answer UX-4: add the zip_extract and archive_inspector search IDs to the guide and release audit; name the F06, F07 and F12 tests (QA-5); HLD release guard is the engine constant (ARCH-4), QA-7 resolved by the owner answer, PM-6 build choices listed for the owner; counts regenerated by scripts/tool-counts.mjs. Author: Claude (files track A fix round 1). |

| 2026-10-22 | docs/lld/pending-tools-files.md | 1.0.1 → 1.0.2 | Correct the file_info signature, the walker and descriptor wording (child folders opened by no-follow descriptor, CR-2), the not-touched list, the F02 nested-path row (QA-6) and skipped_truncated (CR-1, CR-5, QA-6). Author: Claude (files track A fix round 1). |

| 2026-10-22 | API-CONTRACT.md | 1.90.1 → 1.90.2 | Correct the file-job operation count from thirteen to eighteen and add the development-only private-beta note to all five files kinds (ARCH-1, ARCH-2, pending-files round 1). Author: Claude (files track A fix round 1). |

| 2026-10-22 | API-CONTRACT.md | 1.90.0 → 1.90.1 | File info reports skipped_truncated so a capped skipped list is never silently short (CR-1, pending-files round 1). Author: Claude (files track A fix round 1). |

| 2026-10-22 | API-CONTRACT.md, docs/TOOL-GUIDE.md, docs/FIRST-MAC-RELEASE.md | 1.89.2 → 1.90.0 / 1.198.136 → 1.198.137 / 1.0.205 → 1.0.206 | Files slice (phase 2): document the five read-only file-job kinds in the pending files section; add ZIP create, file info, file compare, file age, empty files and empty folders to the guide and release audit (F07 and F12 covered by archive_manager). Author: Claude (files track A UI). |
>| 2026-10-22 | DESIGN_SYSTEM.md / index.html / assets/officekit-workspace.js / ui-tests/voice-section-nav.spec.mjs / ui-tests/speech-coach.spec.mjs / ui-tests/workspace-refresh.spec.mjs / ui-tests/focus-consistency.spec.mjs / tests/section-nav.test.mjs / docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md | 1.9.10 → 1.9.11 / 1.0.4 → 1.0.5 | Voice: Speech Coach is a section beside Dictation (approved mock), tab bar removed; Home search field removed (owner approval). Decisions 15 and 16. |

| 2026-10-22 | docs/hld/speech-coach.md / docs/lld/speech-coach.md / docs/TEST-PLAN.md / docs/PITFALLS.md | 1.9.0 → 1.10.0 / 1.9.0 → 1.10.0 / 1.0.9 → 1.0.10 / P-251 | Discard stale standalone analysis after session or capture-mode changes; bind delayed feedback to its originating coach epoch and add regression coverage. |
| 2026-10-22 | docs/TEST-PLAN.md | 1.0.8 → 1.0.9 | Add deterministic concurrent-caller regression coverage for shared Speech Coach and dictation lifecycle serialization. |
| 2026-10-22 | docs/PITFALLS.md | P-248–P-250 | Record prevention and regression checks for serialized shared microphone capture, stale asynchronous coaching cues, and native Quick Controls toggle arguments. |
| 2026-10-22 | docs/hld/speech-coach.md / docs/lld/speech-coach.md / docs/TEST-PLAN.md | 1.8.0 → 1.9.0 / 1.8.0 → 1.9.0 / 1.0.7 → 1.0.8 | Record serialized shared capture lifecycle, reject stale language cues across dictation generations, allow repeated pace cues after cooldown, and cover Listen In Practice context and exact UI enable/disable calls. |

| 2026-10-22 | docs/hld/speech-coach.md | new → 1.0.0 | Consolidate approved HUD, quick controls, notes and progress; prioritize reliable coaching/STT coexistence, define pause/disable/hide and safe Disable all, phase language coaching and automatic activation behind evidence. Record mock approvals and remove temporary approved mock HTML. |
| 2026-10-22 | docs/lld/speech-coach.md | new → 1.0.0 | Define shared native capture, local bounded metrics/history, menu actions, safe Disable all coordination, HUD placement, in-app notes UI, file map and acceptance tests. |
| 2026-10-22 | docs/hld/speech-coach.md / docs/lld/speech-coach.md | 1.0.0 → 1.1.0 / 1.0.0 → 1.1.0 | Make the session learning loop explicit: context and focus selection, concise evidence-backed recap, useful/dismiss feedback, carry-forward practice goal, optional history trends, and no unvalidated score/streak mechanics. |
| 2026-10-22 | docs/hld/speech-coach.md / docs/lld/speech-coach.md | 1.1.0 → 1.2.0 / 1.1.0 → 1.2.0 | Record the implemented boundary: live pace currently requires OfficeKit STT finalized words; coach-only ASR, coach-only recaps, pitch and language coaching remain gated next work. |
| 2026-10-22 | docs/hld/speech-coach.md / docs/lld/speech-coach.md | 1.2.0 → 1.3.0 / 1.2.0 → 1.3.0 | Add bounded local ASR for coach-only pace cues and aggregate recaps; document confidence, overlap and real-device validation limits, plus unimplemented pitch/language cues. |
| 2026-10-22 | docs/TEST-PLAN.md | 1.0.1 → 1.0.2 | Cover coach-only metric aggregation and native ASR window bounds, STT yielding, and model-readiness state. |
| 2026-10-22 | docs/hld/speech-coach.md / docs/lld/speech-coach.md | 1.3.0 → 1.4.0 / 1.3.0 → 1.4.0 | Update the offering plan for implemented descriptive pitch median/variation, clarify the personal-baseline and installed-device validation gates, and preserve the context/focus → evidence-backed recap → carry-forward goal retrospective loop. |
| 2026-10-22 | docs/TEST-PLAN.md | 1.0.2 → 1.0.3 | Add synthetic pitch estimator coverage to the focused suite map and real microphone pitch accuracy to installed acceptance. |
| 2026-10-22 | docs/hld/speech-coach.md / docs/lld/speech-coach.md | 1.4.0 → 1.5.0 / 1.4.0 → 1.5.0 | Include the approved speaking-zone meter, shared-STT pitch measurements and optional on-device grammar/vocabulary suggestions; persist only bounded issue categories/counts and document accuracy/privacy gates. |
| 2026-10-22 | docs/TEST-PLAN.md | 1.0.3 → 1.0.4 | Add language-suggestion parser/recall safeguards, shared-STT pitch behavior and Speech Coach UI coverage to the focused test map. |
| 2026-10-22 | docs/hld/speech-coach.md / docs/lld/speech-coach.md | 1.5.0 → 1.6.0 / 1.5.0 → 1.6.0 | Stage optional calibration and context-specific baselines after first-release reliability; make user-confirmed patterns, low-distraction cues and usefulness feedback explicit in the session-informed improvement loop. |
| 2026-10-22 | docs/TEST-PLAN.md | 1.0.4 → 1.0.5 | Add isolated dynamic loopback-port origin policy coverage used by Speech Coach browser tests. |
| 2026-10-22 | docs/hld/speech-coach.md / docs/lld/speech-coach.md | 1.6.0 → 1.7.0 / 1.6.0 → 1.7.0 | Add Quick Controls Listen In mode for intentional solo practice, backed by the existing coach capture and Practice context; specify synchronized state and start/stop behavior. |
| 2026-10-22 | docs/TEST-PLAN.md | 1.0.5 → 1.0.6 | Add Quick Controls Listen In synchronization and solo-practice start/stop coverage. |
| 2026-10-22 | docs/hld/speech-coach.md / docs/lld/speech-coach.md | 1.7.0 → 1.8.0 / 1.7.0 → 1.8.0 | Record the approved Dictate, Speech Coach, and Setup & history layout; document exclusive setup disclosures and the per-panel three-action acceptance check. |
| 2026-10-22 | docs/TEST-PLAN.md | 1.0.6 → 1.0.7 | Assert each Audio & Dictation panel stays within three visible actions while preserving Listen In coverage. |

| 2026-10-22 | DESIGN_SYSTEM.md / index.html / assets/officekit-ergonomics.js / assets/officekit-global-desktop.js / assets/officekit-workspace.js / tests/calculators-slice-ui.test.mjs / tests/calculators-round1-ui.test.mjs | 1.9.9 → 1.9.10 | Merge of origin/main (v1.0.31) into PR 59: calculators keep the approved one-per-screen layout (mock 02) instead of main's grouped dropdown; titles added for the 13 forms main brought in; main's meeting calendar loading state and developer download gating kept; Ergonomics Preview stays a link. |

| 2026-10-22 | docs/hld/pending-tools-pdf.md, docs/ui-research/2026-10-22-approved-pending-tools.md | 1.0.3 → 1.0.4 / 1.6.0 → 1.7.0 | PDF slice review round 4: dock status after a result follows the owner's answer of 2026-10-22, "Match the mock (Recommended)" (PM-9, UX-21): bare "Done" for Images to PDF, Grayscale and Flatten; page numbers "Done · N of M pages numbered" (N from the selection, M from the page count); the page-numbers deviation is dropped; HLD §5 `doneLine` entry updated; the image-pdfs budget wording is fixed (CR-10). |

| 2026-10-22 | docs/hld/pending-tools-pdf.md, docs/lld/pending-tools-pdf.md, API-CONTRACT.md, docs/ui-research/2026-10-22-approved-pending-tools.md | 1.0.2 → 1.0.3 / 1.0.2 → 1.0.3 / 1.89.1 → 1.89.2 / 1.5.0 → 1.6.0 | PDF slice review round 3: the images file-limit line comes from the slice (`limitFor`), so index.html keeps no copy of the 200 cap (ARCH-5); the dock status after a result is "Done · <name> · <count>" in the approved frames, with the trailing sentence dropped (UX-20); the image batch budget is 150 M pixels, not 400 MP, in HLD, LLD and API-CONTRACT (code-reviewer); HLD §5 names `limitFor` and `doneLine`; approval record: Select PDFs is a button styled as an in-text link (PM-8), and the status frames and the page-number count gap are recorded. |

| 2026-10-22 | docs/hld/pending-tools-pdf.md, API-CONTRACT.md, docs/ui-research/2026-10-22-approved-pending-tools.md | 1.0.1 → 1.0.2 / 1.89.0 → 1.89.1 / 1.4.4 → 1.5.0 | PDF slice review round 2: HLD §5 rewritten as the implemented shell and slice contract, with hand-written nav (ARCH-9, PM-4); 413 output cap named on every binary PDF route row (ARCH-10); approval record: Select PDFs is an in-text link (owner “Make it a link”), segmented toggles counted in the button limit (PM-7), PDF nav, metadata copy and status, and pages-error copy accepted as built (owner “Accept all as built”), generic output preview hidden for slice tasks (UX-8). |

| 2026-10-22 | API-CONTRACT.md, docs/TOOL-GUIDE.md, docs/hld/pending-tools-pdf.md, docs/lld/pending-tools-pdf.md | 1.88.0 → 1.89.0 / 1.198.135 → 1.198.136 / 1.0.0 → 1.0.1 / 1.0.1 → 1.0.2 | PDF slice review round 1: plural-noun routes (page-rotations, image-pdfs, inspections, watermarks/previews, page-numbers/previews, page-sizes, grayscale-conversions, flattenings); `preview_page` 0 = first landscape page; `encrypted` in the inspection report; Tamil removed from watermark scope per owner decision (Latin, Greek, Cyrillic only; fixed 422 otherwise); nav and glue contract recorded (ARCH-4). |

| 2026-10-22 | API-CONTRACT.md, docs/TOOL-GUIDE.md, docs/FIRST-MAC-RELEASE.md | 1.87.1 → 1.88.0 / 1.198.134 → 1.198.135 / 1.0.204 → 1.0.205 | PDF slice phase 2: eight pending operation rows in each doc's own section, development-only; grouped PDF nav and the eight workbench operations; shared upload helpers; bundled Noto Sans for watermark and page-number text. |
| 2026-10-22 | docs/ui-research/2026-10-22-approved-pending-tools.md | 1.4.3 → 1.4.4 | Image review round 5: records that the compare stat tiles show under every comparable mode (the approved mock places `.stats` beside the three mode panels) and where the Save difference dock shows, including its disabled mismatch state (PM-10). |

| 2026-10-22 | docs/ui-research/2026-10-22-approved-pending-tools.md | 1.4.2 → 1.4.3 | Owner answer on image PM-7: the Rotate overlap with the Screenshot Editor is "Accept overlap (Recommended)"; the approved doc now quotes that answer in place of "Approve all five". |

| 2026-10-22 | docs/ui-research/2026-10-22-approved-pending-tools.md, docs/hld/pending-tools-image.md, docs/TOOL-GUIDE.md | 1.4.1 → 1.4.2 / 1.0.1 → 1.0.2 / 1.198.133 → 1.198.134 | Owner answer on image PM-6: the I14 border batch stays API-only for now; the batch UI or MCP agent is slice 7 work. The approved doc scope calls, HLD I14 row and TOOL-GUIDE I14 row say the same. |

| 2026-10-22 | API-CONTRACT.md, docs/lld/pending-tools-image.md, docs/ui-research/2026-10-22-approved-pending-tools.md | 1.87.0 → 1.87.1 / 1.1.1 → 1.1.2 / 1.4.0 → 1.4.1 | Image review round 2: data-URI route declares `X-Content-Type-Options` in OpenAPI and the success-header sentence is narrowed (ARCH-3); LLD font sentence drops the stale "until then" wording (DEVOPS-2); approved doc records the Rotate overlap and I12 preview-scale acceptances (PM-5). |

| 2026-10-22 | API-CONTRACT.md, docs/hld/pending-tools-image.md, docs/lld/pending-tools-image.md, docs/PITFALLS.md | 1.86.0 → 1.87.0 / 1.0.0 → 1.0.1 / 1.1.0 → 1.1.1 / P-190 → P-197 added (no version line) | Image review round 1: contract gains the framework-422 code, declared success headers, data-URI TIFF, contact-sheet first-page preview and PDF ceiling, visible-pixel compare policy and DTO bounds; HLD records the Rotate scope (PM-1) and the built file name (ARCH-6); LLD records the bundled font (DEVOPS-2) and the PDF ceiling (CR-6). |

| 2026-10-22 | API-CONTRACT.md, docs/TOOL-GUIDE.md, docs/FIRST-MAC-RELEASE.md | 1.85.2 → 1.86.0 / 1.198.132 → 1.198.133 / 1.0.203 → 1.0.204 | Pending image tools phase 2: image route contract, development-only tool rows and first-Mac acceptance notes for the twelve I06–I20 tools. |
| 2026-10-22 | docs/ui-research/2026-10-22-approved-pending-tools.md | 1.3.0 → 1.4.0 | Round-3 PM-8: the owner's answer “Keep 18px / 12px (Recommended)” is recorded as an approved deviation for the developer stat value (18px) and badge (12px) sizes; no code change |

| 2026-10-22 | docs/ui-research/2026-10-22-approved-pending-tools.md | 1.2.0 → 1.3.0 | Round-2 PM-5 and UX-6: the timestamp target zones are chips with Add zone, as the approved v2 mock shows; the comma-separated deviation is removed and the chips are recorded as the approved shape |

| 2026-10-22 | docs/hld/pending-tools-developer.md | 1.1.0 → 1.1.1 | Round-2 ARCH-1: the POST /uuids row states the 8 KiB body cap that the contract and code use |

| 2026-10-22 | API-CONTRACT.md | 1.85.0 → 1.85.1 | Round-2 ARCH-3 and ARCH-8: json-diffs row states the 256-character preview cap and omitted before/after; QR size row covers the clamp at both ends |

| 2026-10-22 | docs/hld/pending-tools-developer.md | 1.0.0 → 1.1.0 | Round-1 ARCH-5: per-level QR capacity replaces the single 2,953 bound; record the round-1 decisions (text bytes, budgets, UUID cap, QR side, line model) |

| 2026-10-22 | API-CONTRACT.md | 1.84.0 → 1.85.0 | Round-1 ARCH-3: add the nesting and node caps, the 50,000-line cap, the 1 MiB case result cap, the DST-gap 422, the warning codes and the nullable local_zone to the developer rows |

| 2026-10-22 | docs/TOOL-GUIDE.md | 1.198.130 → 1.198.131 | Round-1 CR-7: document one line model (CRLF, CR, LF) for text metrics and text diff; U+2028 and U+2029 are not breaks |

| 2026-10-22 | API-CONTRACT.md | 1.83.0 → 1.84.0 | Round-1 CR-6 and ARCH-4: QR side is the module multiple clamped into 128–2,048 px, and the response documents the returned size_px |

| 2026-10-22 | docs/TOOL-GUIDE.md | 1.198.129 → 1.198.130 | Round-1 CR-4 and PM-3: repair the developer table separator and trailing cell; remove the stray blockquote line from this history (CR-5, ARCH-7) |

| 2026-10-22 | API-CONTRACT.md | 1.82.0 → 1.83.0 | Round-1 ARCH-2: state the text limit in UTF-8 bytes to match the engine; ARCH-1: UUID body cap 8 KiB |

| 2026-10-22 | API-CONTRACT.md | 1.81.0 → 1.82.0 | Round-1 CR-1..CR-3: name the search-work, inline-span and JSON-output budgets; text-diffs responds with spans_omitted |

| 2026-10-22 | API-CONTRACT.md | 1.80.0 → 1.81.0 | Add the developer slice routes (JSON and text compare, text metrics and case, timestamps and time zones, UUIDs, QR codes) to the pending-tools developer section |

| 2026-10-22 | docs/TOOL-GUIDE.md | 1.198.128 → 1.198.129 | Add developer-slice rows for the seven pending developer tools |

| 2026-10-22 | docs/FIRST-MAC-RELEASE.md | 1.0.202 → 1.0.203 | Add development-only rows for the seven pending developer tools |

| 2026-10-22 | docs/lld/pending-tools-developer.md | 1.0.0 → 1.1.0 | Record phase 2 status: grapheme route, catalogue, UI asset and UI tests shipped; close section 8 items |

| 2026-10-22 | docs/PITFALLS.md | added P-188 (pytest skipped `*_unittest.py` files) | Collect every repo test naming pattern in pytest.ini, with a guard test |

| 2026-10-22 | docs/PITFALLS.md | added P-187 (calculators review round 3 root cause) | se-senior-engineer review round 3 (calculators, UX-16, UX-17): a field error moves focus, is announced and draws the error border; segmented pills carry the focus outline |

| 2026-10-22 | docs/PITFALLS.md | added P-182 · P-183 · P-184 · P-185 · P-186 (calculators review round 1 root causes) | se-senior-engineer review round 1 (calculators): one Active retro entry per root cause, each naming its regression test |

| 2026-10-22 | docs/hld/pending-tools-calculators.md | 1.0.1 → 1.0.2 | se-senior-engineer review round 2 (calculators, ARCH-6): the quadratic discriminant is documented as null for the linear, all-numbers and no-solution kinds, as the route and contract already return. |

| 2026-10-22 | API-CONTRACT.md, docs/TOOL-GUIDE.md, docs/hld/pending-tools-calculators.md | 1.79.0 → 1.79.1 / 1.197.126 → 1.197.127 / 1.0.0 → 1.0.1 | se-senior-engineer review round 1 (calculators): contract aligned with the routes (date-differences and business-days `inclusive`, fixed 422 messages, weight sign enforced by the engine, zone names ≤64, quadratic discriminant null for non-quadratic kinds); TOOL-GUIDE header count 73 (CR-4, PM-4); HLD weight and zone wording (ARCH-2/3/4/5, PM-5) |

| 2026-10-22 | API-CONTRACT.md, docs/TOOL-GUIDE.md, docs/FIRST-MAC-RELEASE.md | 1.78.3 → 1.79.0 / 1.197.125 → 1.197.126 / 1.0.201 → 1.0.202 | se-senior-engineer phase 2: pending calculators API table, development-only TOOL-GUIDE and first-release rows for the 13 catalogue IDs (C06–C07, C15–C25); the grouped calculator selector and result actions follow the approved mock |

| 2026-10-22 | docs/ui-research/2026-10-22-approved-pending-tools.md | 1.1.0 → 1.2.0 | Owner decisions during review: calculators time-field focus, developer and PDF deviations from the v2 mocks, and the four files open questions (beta reveal route fixed in the files slice). |

| 2026-10-22 | docs/ui-research/2026-10-22-approved-pending-tools.md | 1.0.0 → 1.1.0 | Owner re-approved the developer, calculators, files and PDF re-mocks at ≤3 buttons; Latin/Greek/Cyrillic-only PDF stamps; zip_extract and archive_inspector search IDs kept; as-built scope calls accepted. |

| 2026-10-22 | docs/hld/pending-tools-and-ergonomics.md | 1.0.7 → 1.0.8 | Owner request: slice 7 promotes each pending tool to MCP agents and the agent skill in the same PR that adds it to the release profile; dev-only tools stay unexposed. |

| 2026-10-22 | API-CONTRACT.md / docs/TOOL-GUIDE.md / docs/FIRST-MAC-RELEASE.md / docs/hld/pending-tools-foundation.md | 1.77.1 → 1.78.0 / 1.197.121 → 1.197.122 / 1.0.200 → 1.0.201 / 1.1.0 → 1.2.0 | Foundation PR: per-slice router and catalogue slots, generated catalogue counts (fixes the stale 57), per-slice doc sections, slice UI extension hook. |

| 2026-10-22 | docs/lld/pending-tools-files.md | 1.0.0 → 1.0.1 | Align the files track A LLD with the built engine: empty-folder signature, reveal items for file kinds, protected-root refusal, denied-subfolder behaviour. Author: Claude (files track A build, phase 1). |

| 2026-10-22 | docs/lld/pending-tools-files.md | new → 1.0.0 | Phase 1 track A back end LLD for the files slice: five read-only file-job kinds (file info, compare files, file age, empty files, empty folders), the development-only private-beta guard, and the shared walker stats hook. Track B is a phase 3 placeholder. |
| 2026-10-22 | docs/lld/pending-tools-pdf.md | 1.0.0 → 1.0.1 | Correct the watermark body cap to 76 MiB (72 MiB parts plus 4 MiB overhead) so the LLD matches the router's BODY_LIMITS. |

| 2026-10-22 | docs/lld/pending-tools-pdf.md | new → 1.0.0 | Back-end LLD for the pending PDF slice (P06, P08, P10, P12, P13, P15, P16, P17): file map, engine interfaces, route contract, error and test hooks, commit plan. Phase 1 only. |
| 2026-10-22 | docs/lld/pending-tools-image.md | 1.0.0 → 1.1.0 | Record the back-end deviations settled during the build: platform list format, decode MIME check, density header units, batch and count bounds, icon ZIP folders, comparison dimension keys, palette sample count, and the open GPS-retention decision on renditions. |

| 2026-10-22 | docs/lld/pending-tools-image.md | new → 1.0.0 | Back-end LLD for the pending image tools (I06–I07, I10–I12, I14–I20): file map, interfaces, route and error contract, test hooks and commit plan, each step referencing the HLD contract rows. |
| 2026-10-22 | docs/lld/pending-tools-developer.md | new → 1.0.0 | Back-end LLD for the developer slice (D04, D10, D11, D15–D17, phase 1): file map, engine and route interfaces, fixed error messages, test hooks and commit plan; D16 graphemes and the text-analyses route deferred until the regex package is pinned. |

| 2026-10-22 | docs/lld/pending-tools-calculators.md | new → 1.0.0 | se-senior-engineer phase 1: low-level design for the calculators back end (C06–C07, C15–C25): file map, engine and route interfaces, error handling, test hooks and checkpoint commits. |

| 2026-10-22 | docs/ui-research/2026-10-22-approved-pending-tools.md | new → 1.0.0 | Record the owner's approval of the five pending-tools slice mocks. |

| 2026-10-22 | docs/hld/pending-tools-foundation.md / docs/hld/pending-tools-calculators.md / docs/hld/pending-tools-developer.md / docs/hld/pending-tools-files.md / docs/hld/pending-tools-image.md / docs/hld/pending-tools-pdf.md | new → 1.1.0 (foundation) / new → 1.0.0 (slices) | se-plan stage 4: foundation slot design plus five slice HLD drafts for owner review. |

| 2026-10-22 | docs/ARCHITECTURE.md | 1.0.6 → 1.0.7 | se-plan stage 3: owner chose foundation-first parallel delivery for pending tool slices 2–6. |

| 2026-10-22 | DESIGN_SYSTEM.md / index.html / assets/officekit-media.js / assets/officekit-storage.js / assets/officekit-files.js / assets/officekit-media-preview.js / assets/officekit-agents.js / assets/officekit-global-desktop.js / assets/officekit-ergonomics.js / tests/*-ui.test.mjs / tests/helpers/vm.mjs | 1.9.8 → 1.9.9 | Remaining status writers (about 620 across the app, batch 4 by script and batch 5 by hand) use the shared outcome slot; Ergonomics calendar and motion status, Voice dictation status lines and calculator result actions included (decision 13). Sandbox tests load the helper through tests/helpers/vm.mjs. |

| 2026-10-22 | DESIGN_SYSTEM.md / index.html / assets/officekit-outcome.js / assets/officekit-workspace.js / assets/officekit-results.js / assets/officekit-storage.js / assets/officekit-pdf-editor.js / ui-tests/pdf-editor.spec.mjs | 1.9.7 → 1.9.8 | Shared outcome slot extended to window snap, support, storage, PDF editor, process list and result actions (decision 13); errors use role="alert"; the helper is also attached to the global object for sandboxes. |

| 2026-10-22 | DESIGN_SYSTEM.md / index.html / assets/officekit-outcome.js / tests/outcome-helper.test.mjs | 1.9.6 → 1.9.7 | Bottom-bar status helpers for PII, PDF workbench, workspace, ZIP workspace, screenshot export and developer tools use the shared outcome slot (decision 13); the outcome helper now toggles only its own class and loads before inline scripts. |

| 2026-10-22 | DESIGN_SYSTEM.md / assets/officekit-media.js / tests/outcome-helper.test.mjs | 1.9.5 → 1.9.6 | Media toolkit run, submit, progress, result and cancel messages use the shared outcome slot (decision 13). |

| 2026-10-22 | DESIGN_SYSTEM.md / assets/officekit-outcome.js / assets/officekit-section-nav.js / index.html / assets/officekit-ergonomics.js / assets/officekit.input.css / scripts/build-ui-assets.mjs / tests/outcome-helper.test.mjs / tests/section-nav.test.mjs / ui-tests/voice-section-nav.spec.mjs | 1.9.4 → 1.9.5 | Universal action outcome slot (decision 13) on Ergonomics save, converter and image resize; section list on Voice transcription (decision 14). |

| 2026-10-22 | docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md | 1.0.3 → 1.0.4 | Record owner approval of the section list for long screens (decision 14); mock HTML removed after approval. |

| 2026-10-22 | docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md | 1.0.2 → 1.0.3 | Record owner approval of the universal success and failure feedback mock (decision 13); mock HTML removed after approval. |

| 2026-10-22 | docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md | 1.0.1 → 1.0.2 | Record owner approval of the four over-limit screen mocks (Voice transcription, Media toolkit, Screenshot editor, Ergonomics); mock HTML removed after approval. |

| 2026-10-22 | DESIGN_SYSTEM.md / assets/officekit-files.js / ui-tests/tool-screen-template.spec.mjs / ui-tests/compress-entries.spec.mjs | 1.9.3 → 1.9.4 | Batch renamer and archive screens follow the approved tool template: plain "How to rename" and "What to do" choices, only the fields the chosen rule uses, Compress & Extract ZIP title, Reset removed; three buttons or fewer. |

| 2026-10-22 | docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md | 1.0.0 → 1.0.1 | Owner decision: keep the six-row sidebar and drop sidebar tool groups; tools are found by search and All Tools. |

| 2026-10-22 | DESIGN_SYSTEM.md / index.html / tests/calculator-api-tools-ui.test.mjs / tests/everyday-percentages-ui.test.mjs | 1.9.2 → 1.9.3 | Calculators: one screen per calculator named as in the catalogue, with an All tools back action; remove the eleven-pill selector. |

| 2026-10-22 | DESIGN_SYSTEM.md / assets/officekit-tool-actions.js / ui-tests/persistent-tool-actions.spec.mjs / ui-tests/agent-settings.spec.mjs | 1.9.1 → 1.9.2 | Hide the bottom action bar on browsing screens and on tool screens with no task action; tests assert the bar appears only with actions. |

| 2026-10-22 | docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md (new) | — → 1.0.0 | Record owner approval of one-name-per-tool, seven sidebar groups, one screen per tool and the standard tool-screen template. |

| 2026-10-22 | docs/TESTING.md / docs/ui-research/2026-10-22-approved-search-no-results-request-tool.md / index.html / assets/officekit.input.css / dist-ui/index.html / dist-ui/assets/officekit.css / src-tauri/tauri.conf.json / tests/ui-search-routing.test.mjs | 1.12.382 → 1.12.383 / initial → 1.0.0 | Reconcile the approved Quick Search no-results request flow with current main and preserve the latest generated UI/CSP configuration. |

| 2026-10-22 | docs/TESTING.md | 1.12.381 → 1.12.382 | se-ship: record rebased coverage, Rust/WebKit, fresh 1.0.15 packaging/smoke and final review evidence. |

| 2026-10-22 | docs/TEST-PLAN.md | new → 1.0.0 | Map meeting-countdown regression suites, packaging and installed acceptance. |

| 2026-10-22 | docs/TOOL-GUIDE.md / docs/FIRST-MAC-RELEASE.md | 1.197.119 → 1.197.120 / 1.0.199 → 1.0.200 | Add `archive_manager` and `image_compress` catalogue entries (60 total with the calendar countdown); no new engine, both open existing screens. |
| 2026-10-21 | .claude/se-rules/** (new), AGENTS.md | initial → 1.0.0 | /se-init scaffold: repo rules, personas and `rules.json` customised for the desktop app (no tenancy, pydantic, AWS only for licensing); AGENTS.md gains the "no more than 3 buttons per page" rule. |
| 2026-10-21 | docs/ARCHITECTURE.md | 1.0.5 → 1.0.6 | Record owner-approved local EventKit/shared animated companion decision and alternatives. |

| 2026-10-21 | docs/TESTING.md | 1.12.380 → 1.12.381 | Record signed app/DMG, mounted installer smoke, mutation-backed review sign-offs and native acceptance limits. |

| 2026-10-21 | docs/TESTING.md | 1.12.379 → 1.12.380 | Record full automated meeting-calendar results, sidecar smoke and separate installed acceptance checklist. |

| 2026-10-21 | docs/TOOL-GUIDE.md / docs/PRD.md | 1.197.118 → 1.197.119 / 1.0.33 → 1.0.34 | Discovery instructions and approved animated calendar acceptance criteria. |

| 2026-10-21 | docs/FIRST-MAC-RELEASE.md | 1.0.198 → 1.0.199 | Classify Meeting Countdown as development-only until native acceptance. |

| 2026-10-21 | API-CONTRACT.md | 1.76.2 → 1.77.0 | Local calendar settings, permission command, selected meeting state and animated countdown. |
| 2026-10-21 | docs/hld/meeting-countdown.md / docs/lld/meeting-countdown.md / docs/ui-research/2026-10-21-approved-meeting-countdown.md | new → 1.0.0 | Record approved full-animation direction, local EventKit design and verification plan. |

| 2026-10-21 | docs/TESTING.md | 1.12.378 → 1.12.379 | Record the final 2,381-test, Rust coverage, review and platform limitation evidence. |
| 2026-10-21 | API-CONTRACT.md | 1.76.1 → 1.76.2 | Specify platform availability and posture cooldown fields in ErgonomicsState. |
| 2026-10-21 | docs/lld/pending-tools-and-ergonomics.md | 1.1.0 → 1.1.1 | Keep posture cooldown copy subordinate to sensor calibration readiness. |
| 2026-10-21 | docs/hld/pending-tools-and-ergonomics.md / docs/lld/pending-tools-and-ergonomics.md | 1.0.6 → 1.0.7 / 1.0.9 → 1.1.0 | Disclose macOS-only activity detection and show posture cooldown eligibility. |

| 2026-10-21 | API-CONTRACT.md | 1.76.0 → 1.76.1 | Restrict the companion to narrow state/action commands, document session-only AirPods opt-in and record activity-gate behavior. |
| 2026-10-21 | docs/TESTING.md | 1.12.377 → 1.12.378 | Record final ergonomics test results, coverage and the owner-approved exception. |
| 2026-10-21 | docs/hld/pending-tools-and-ergonomics.md | 1.0.5 → 1.0.6 | Require recent audio activity from an already-authorized OfficeKit capture for mic-based presence. |
| 2026-10-21 | docs/lld/pending-tools-and-ergonomics.md | 1.0.8 → 1.0.9 | Record the inactive prompt countdown fix and final verification evidence. |
| 2026-10-21 | docs/FIRST-MAC-RELEASE.md | 1.0.197 → 1.0.198 | Record the approved development-only ergonomics implementation and source evidence. |
| 2026-10-21 | docs/TOOL-GUIDE.md | 1.197.117 → 1.197.118 | Add the approved development-only ergonomics modes to the source catalogue and depth audit. |
| 2026-10-21 | docs/lld/pending-tools-and-ergonomics.md / docs/TESTING.md | 1.0.8 → 1.0.9 / 1.12.377 → 1.12.378 | Record the inactive prompt countdown fix, final 252-test Rust result, focused browser matrix, and updated scheduler coverage. |
| 2026-10-21 | docs/TESTING.md | 1.12.376 → 1.12.377 | Record development-only ergonomics tests, activity-gated reminder behavior, and the owner-approved coverage exception. |
| 2026-10-21 | docs/hld/pending-tools-and-ergonomics.md / docs/lld/pending-tools-and-ergonomics.md / docs/ui-research/2026-10-21-approved-ergonomics.md / docs/FIRST-MAC-RELEASE.md | initial → 1.0.0 / 1.0.3 → 1.0.4 / 1.0.0 → 1.0.1 / 1.0.197 → 1.0.198 | Record the approved companion design, ergonomics implementation and remaining installed/hardware acceptance. |
| 2026-10-21 | docs/MCP-AGENT-SUPPORT.md, docs/TESTING.md, docs/ui-research/2026-10-21-approved-settings-ai-agents.md | 1.0.0 → 1.1.0 / 1.12.375 → 1.12.376 / 1.0.0 → 1.0.1 | Settings screen implemented skill-first: saved agent settings file, `--agent-mcp`/`--agent-cli` launcher flags, native Settings commands, install and tests; resolve the skill-first open item and record the action-bar and rail fixes. |

| 2026-10-21 | DESIGN_SYSTEM.md, docs/MCP-AGENT-SUPPORT.md, docs/ui-research/2026-10-21-approved-settings-ai-agents.md | 1.9.0 → 1.9.1 / initial → 1.0.0 / initial → 1.0.0 | Record the approved Settings screen with Connect AI agents; document the local MCP server, CLI mode, sensitive-data rules and the removal of password/passphrase generators. |

| 2026-10-19 | docs/TESTING.md, docs/ui-research/2026-10-19-approved-media-toolkit.md | 1.12.372 → 1.12.373 / initial → 1.0.0 | Record committed main reconciliation, clean preflight, passing post-merge Python suite, actual 83% media coverage and the unresolved owner-only coverage exception gate. |

| 2026-10-19 | docs/TESTING.md, review/clop-media-toolkit/requirements.md | 1.12.371 → 1.12.372 / 1.0.122 → 1.0.123 | Record passing current UI package, 28-operation mounted acceptance, gate-6 and browser evidence; disclose dirty-tree and two-commit main divergence before formal review. |

| 2026-10-19 | API-CONTRACT.md, docs/lld/media-toolkit.md, docs/TESTING.md, review/clop-media-toolkit/requirements.md | 1.74.176 → 1.74.177 / 1.0.123 → 1.0.124 / 1.12.370 → 1.12.371 / 1.0.121 → 1.0.122 | Record consolidated mock approval; merge per-type batch settings, independent retry, logo staging, optional formats and explicit native handoffs; distinguish source UI acceptance from the passing earlier audio package. |

| 2026-10-19 | API-CONTRACT.md, docs/lld/media-toolkit.md, docs/TESTING.md, review/clop-media-toolkit/requirements.md | 1.74.175 → 1.74.176 / 1.0.122 → 1.0.123 / 1.12.369 → 1.12.370 / 1.0.120 → 1.0.121 | Measure final decoded normalized audio, enforce encoded peak ceilings with bounded source-based retries, and document real transient/surround regression evidence. |

| 2026-10-19 | docs/TESTING.md, review/clop-media-toolkit/requirements.md | 1.12.368 → 1.12.369 / 1.0.119 → 1.0.120 | Record 397 focused checks, 100% shared geometry coverage, passing packaged saved smart crop/current-stage sizing and audio retention, 4K analysis source dimensions, and the exact native-window acceptance limits. |

| 2026-10-19 | API-CONTRACT.md, docs/lld/media-toolkit.md, docs/TESTING.md, review/clop-media-toolkit/requirements.md | 1.74.174 → 1.74.175 / 1.0.121 → 1.0.122 / 1.12.367 → 1.12.368 / 1.0.118 → 1.0.119 | Extend existing image/video crop operations with exclusive runtime aspect/smart targets; share geometry with CLI, bound and cancel saliency analysis, verify typed API/MCP/persistence, and record actual native-window and handoff evidence. |

| 2026-10-19 | docs/TESTING.md, review/clop-media-toolkit/requirements.md | 1.12.366 → 1.12.367 / 1.0.117 → 1.0.118 | Record passing mounted-DMG capture-based fork/final publication and source preservation, with the 2,107-test Python suite and 100% naming-module coverage; replace the stale missing-tooling review blocker with actual preflight findings. |

| 2026-10-19 | docs/lld/media-toolkit.md, docs/TESTING.md, review/clop-media-toolkit/requirements.md | 1.0.120 → 1.0.121 / 1.12.365 → 1.12.366 / 1.0.116 → 1.0.117 | Add bounded positive-regex capture tokens to inline output templates through shared safe naming and staged publication; verify source tests, full suite, signed build, and locate/run the local review preflight. |

| 2026-10-19 | docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.12.364 → 1.12.365 / 1.0.115 → 1.0.116 | Record 281 focused tests, passing full repository checks, fresh signed Apple Silicon app/DMG, and mounted package verification of PDF DPI filters and two-file sequence naming; distinguish method/module coverage from full PDF-engine coverage. |

| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.119 → 1.0.120 / 1.12.363 → 1.12.364 / 1.0.114 → 1.0.115 | Add bounded effective placed-image PDF DPI filters with nested-form and UserUnit handling; complete batch and watched-folder sequence naming, preserve source template characters, and add source/package regression coverage. |

| 2026-10-19 | docs/TESTING.md | 1.12.362 → 1.12.363 | Record passing full repository tests after smart-crop integration and refresh the packaged build evidence. |

| 2026-10-19 | docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.12.361 → 1.12.362 / 1.0.113 → 1.0.114 | Record the fresh signed Apple Silicon build and passing mounted-DMG smart-crop pipeline/source-preservation check; update the Clop parity ledger. |

| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.118 → 1.0.119 / 1.12.360 → 1.12.361 / 1.0.112 → 1.0.113 | Add local macOS Vision saliency smart crop to the image/video CLI and inline DSL; stage no-follow source copies, validate bounds, fall back to centered crop without saliency, and retain source files. |

| 2026-10-19 | API-CONTRACT.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.173 → 1.74.174 / 1.0.117 → 1.0.118 / 1.12.359 → 1.12.360 / 1.0.111 → 1.0.112 | Support bounded Clop source-name, extension, date/time, random, and sequence tokens in safe single-filename output templates while rejecting destination paths. Focused pipeline, job, folder automation, CLI, and MCP coverage passes (130 tests). |

| 2026-10-19 | docs/FIRST-MAC-RELEASE.md | 1.0.194 → 1.0.195 | Align the release audit catalogue count with the current 53-tool source registry. |

| 2026-10-19 | docs/TESTING.md | 1.12.344 → 1.12.345 | Record the rebased full suite, native UI matrix and Rust verification, and refresh the source catalogue count. |

| 2026-10-19 | docs/TESTING.md | 1.12.345 → 1.12.346 | Record the rebased signed Apple Silicon app build and passing mounted DMG Media Toolkit smoke. |

| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md | 1.0.103 → 1.0.104 / 1.12.343 → 1.12.344 | Add a bounded Clop-style `capFps` DSL step on typed video resize, preserve audio, verify 30→15 fps in the rebuilt macOS package, and record the full suite and native test evidence. |

| 2026-10-19 | review/clop-media-toolkit/requirements.md | 1.0.96 → 1.0.97 | Reconcile the parity ledger with implemented inline DSL crop/downscale, target size, watermark, conditional filters, and typed saved pipelines; retain the remaining unsupported action and filter gaps. |

| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.102 → 1.0.103 / 1.12.342 → 1.12.343 / 1.0.95 → 1.0.96 | Resolve inline per-file aspect-ratio crop and factor-downscale steps through bounded source probes and the existing typed operations; add source and packaged checks. |

| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.101 → 1.0.102 / 1.12.341 → 1.12.342 / 1.0.94 → 1.0.95 | Map bounded Clop-style `targetSize` DSL values to the typed image/video/PDF/audio fit-size operations and add source and packaged smoke coverage. |

| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.100 → 1.0.101 / 1.12.340 → 1.12.341 / 1.0.93 → 1.0.94 | Support Clop-style positional typed DSL pipeline creation, reject recipes with transient filters or local logo paths, and record passing full-suite, smoke-wiring, and packaged lifecycle verification. |

| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.99 → 1.0.100 / 1.12.339 → 1.12.340 / 1.0.92 → 1.0.93 | Add bounded first-step filename and media-type conditions to inline `pipeline run`, report skipped inputs, and record passing full-suite/source tests while packaged verification runs. |

| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.98 → 1.0.99 / 1.12.338 → 1.12.339 / 1.0.91 → 1.0.92 | Add bounded local image watermark steps to inline `pipeline run`, retain typed overlay validation and copy-only publication, and record passing full-suite tests and fresh packaged conversion/watermark smoke. |

| 2026-10-19 | docs/TESTING.md | 1.12.337 → 1.12.338 | Record 58 focused CLI tests, the passing 1,946-test Python suite, and successful signed Apple Silicon DMG smoke for the safe inline pipeline DSL. |

| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.97 → 1.0.98 / 1.12.336 → 1.12.337 / 1.0.90 → 1.0.91 | Add a bounded, typed inline Clop DSL subset to `pipeline run`; reject scripts and unsupported steps, exercise source-preserving output in the mounted-DMG smoke, and record the focused CLI results. |

| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.96 → 1.0.97 / 1.12.335 → 1.12.336 / 1.0.89 → 1.0.90 | Add Clop-style CLI settings schema/get/set forms over OfficeKit's shared typed defaults store; verify 55 focused CLI tests, 32 desktop/compact WebKit checks, the rebuilt Apple Silicon DMG smoke, and full-suite results. |

| 2026-10-19 | docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TOOL-GUIDE.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.1.53 → 1.1.54 / 1.0.92 → 1.0.93 / 1.197.114 → 1.197.115 / 1.12.331 → 1.12.332 / 1.0.84 → 1.0.85 | Record passing full repository, Rust, desktop/compact WebKit, and freshly built mounted-DMG verification for image/video/audio factor downscaling, including M4A decode, factor-one identity and source preservation. |
| 2026-10-19 | docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TOOL-GUIDE.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.1.54 → 1.1.55 / 1.0.93 → 1.0.94 / 1.197.115 → 1.197.116 / 1.12.332 → 1.12.333 / 1.0.85 → 1.0.86 | Add bounded centered image/video aspect-ratio crop to CLI and MCP, then record passing full suite and packaged image/video crop checks with source preservation. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md | 1.0.86 → 1.0.87 | Reinspect the installed Clop 3.6.0 CLI command tree and record the floating-result clear and persistent debug-log controls as explicit parity gaps. |
| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.94 → 1.0.95 / 1.12.333 → 1.12.334 / 1.0.87 → 1.0.88 | Replace the watched-folder `_prepared` filename exclusion with session-local output identity tracking, add a regression for legitimate input names and output-loop prevention, and record the passing folder suite. |
| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.95 → 1.0.96 / 1.12.334 → 1.12.335 / 1.0.88 → 1.0.89 | Add CLI commands for preset-zone binding list/create/rename/rebind/remove using the shared private store, and verify enablement remains session-only. |
| 2026-10-19 | docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/PRD.md / docs/TOOL-GUIDE.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.1.52 → 1.1.53 / 1.0.91 → 1.0.92 / 1.0.30 → 1.0.31 / 1.197.113 → 1.197.114 / 1.12.330 → 1.12.331 / 1.0.83 → 1.0.84 | Add bounded audio duration probing and the typed `downscale-audio` CLI/MCP preset, extend source and packaged smoke coverage, and update the parity ledger. Tests and packaged smoke have not yet been run for this addition. |
| 2026-10-19 | docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/PRD.md / docs/TOOL-GUIDE.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.1.51 → 1.1.52 / 1.0.90 → 1.0.91 / 1.0.29 → 1.0.30 / 1.197.112 → 1.197.113 / 1.12.327 → 1.12.328 / 1.0.82 → 1.0.83 | Add typed video metadata removal through the macOS pass-through adapter and homogeneous CLI batches; add a packaged marker-removal and track-preservation check, correct PDF fit-size DPI and CLI downscale parity entries, and record the green full test run and 32-case desktop/compact media UI run. |
| 2026-10-19 | docs/lld/media-toolkit.md | 1.0.89 → 1.0.90 | Record user approval of the inspected Automation-center design and the implemented controls covered by UI tests. |
| 2026-10-19 | docs/TESTING.md | 1.12.326 → 1.12.327 | Record passing full Node/Python repository tests and Rust format/test checks after aligning the media CLI dispatch assertion with current help output. |
| 2026-10-19 | docs/lld/media-toolkit.md | 1.0.88 → 1.0.89 | Correct the inventory to eleven CLI presets and ten MCP presets after adding `downscale-video` to both interfaces. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md | 1.0.81 → 1.0.82 / 1.0.87 → 1.0.88 / 1.12.325 → 1.12.326 / 1.197.111 → 1.197.112 | Expose factor-based video downscaling in the MCP preset schema, document shared CLI/MCP behavior, and record passing source and mounted-DMG checks against real audio/video fixtures. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md | 1.0.80 → 1.0.81 | Record video factor downscaling in the typed local CLI and leave MCP/GUI parity, audio factor downscaling, and cursor controls open. |
| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md | 1.0.85 → 1.0.86 / 1.12.324 → 1.12.325 | Add bounded factor-based video downscaling through the existing typed `video-resize` operation and record successful mounted-DMG validation of dimensions, audio retention, unchanged sources, and factor-one identity copies. |
| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md | 1.0.84 → 1.0.85 / 1.12.323 → 1.12.324 | Record a fresh Apple Silicon build signed with the local Apple Development identity and passing mounted-DMG coverage for the bundled typed `convert` verb; note that notarization and interactive installed-app checks remain outstanding. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md | 1.0.79 → 1.0.80 | Clarify that the typed CLI has video audio removal while Clop's combined optimize controls and UI toggle remain open. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/TESTING.md | 1.0.78 → 1.0.79 / 1.12.322 → 1.12.323 | Map the Clop-style `optimise --remove-audio` option to typed video optimization followed by audio-track removal; reject non-video input before processing. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/TESTING.md | 1.0.77 → 1.0.78 / 1.0.83 → 1.0.84 / 1.12.321 → 1.12.322 | Add a packaged DMG CLI check for typed `convert`; distinguish smoke wiring coverage from the installed-app run, which requires a fresh DMG and remains outstanding. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/TESTING.md | 1.0.76 → 1.0.77 / 1.0.82 → 1.0.83 / 1.12.320 → 1.12.321 | Add Clop-style `optimise`, `convert`, `crop`, `downscale`, and `strip-exif` CLI verbs over the shared typed operation contract; verify copy-only conversion, image factor downscale, and metadata removal. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/TESTING.md | 1.0.75 → 1.0.76 / 1.0.81 → 1.0.82 / 1.12.319 → 1.12.320 | Add local CLI saved-pipeline list/show/add/rename/run/attach/detach/prompt commands through the typed stores and copy-only job path; document why subprocess deletion cannot safely inspect live folder grants. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/hld/media-toolkit.md / docs/TESTING.md | 1.0.68 → 1.0.69 / 1.0.75 → 1.0.76 / 1.1.48 → 1.1.49 / 1.12.307 → 1.12.308 | Record the approved Automation center and desktop/compact UI evidence; document bounded native handoff commands for six external destinations while leaving their UI and installed-app checks pending. |
| 2026-10-19 | API-CONTRACT.md | 1.74.160 → 1.74.161 | Bound the authenticated local handoff artifact fetch to 30 seconds and disable redirects so credentials remain on the local API request. |
| 2026-10-19 | docs/TESTING.md | 1.12.311 → 1.12.312 | Record the fresh signed Apple Silicon app/DMG build and packaged Media Toolkit smoke, including notarization status. |
| 2026-10-19 | docs/TESTING.md | 1.12.312 → 1.12.313 | Add loopback proof that the authenticated handoff artifact fetch obeys its total timeout; update Rust test totals. |
| 2026-10-19 | docs/lld/media-toolkit.md | 1.0.76 → 1.0.77 | Document the 30-second no-redirect local artifact fetch, bounded Shortcut discovery, and dispatch-only handoff result. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/TESTING.md | 1.0.67 → 1.0.68 / 1.0.74 → 1.0.75 / 1.12.306 → 1.12.307 | Require five unchanged snapshots before video folder automation submits a recording; cover write pauses with a regression and update the Clop parity ledger. |
| 2026-10-19 | docs/TESTING.md | 1.12.305 → 1.12.306 | Record user approval and focused desktop/compact automation UI verification. |
| 2026-10-19 | docs/TESTING.md | 1.12.304 → 1.12.305 | Add shared API job coverage and update the full Python regression total. |
| 2026-10-19 | docs/TESTING.md | 1.12.303 → 1.12.304 | Record the final HEIC acceptance run and updated full Python suite total. |
| 2026-10-19 | docs/TESTING.md / docs/TOOL-GUIDE.md | 1.12.302 → 1.12.303 / 1.197.107 → 1.197.108 | Record local HEIC/HEIF decoding, safe-copy behavior, and packaged CLI acceptance. |
| 2026-10-19 | docs/TESTING.md | 1.12.301 → 1.12.302 | Remove duplicate evidence and retain the current desktop and compact WebKit result. |
| 2026-10-19 | docs/TESTING.md / docs/TOOL-GUIDE.md | 1.12.298 → 1.12.299 / 1.197.106 → 1.197.107 | Record the full current test run and fresh Apple Silicon DMG smoke, including packaged recursive PDF crop and catalog acceptance. |
| 2026-10-19 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.157 → 1.74.158 / 1.1.47 → 1.1.48 / 1.0.73 → 1.0.74 / 1.12.297 → 1.12.298 / 1.0.66 → 1.0.67 | Accept named device and paper targets through the shared typed PDF crop operation used by local API jobs, pipelines, and MCP. |
| 2026-10-19 | docs/TESTING.md | 1.12.296 → 1.12.297 | Add macOS DMG smoke coverage for packaged PDF device/paper catalogs, recursive crop, output-tree exclusion, and unchanged inputs. |
| 2026-10-19 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.156 → 1.74.157 / 1.1.46 → 1.1.47 / 1.0.72 → 1.0.73 / 1.12.295 → 1.12.296 / 1.0.65 → 1.0.66 | Add safe recursive PDF folder discovery that skips symlinks, excludes the output tree, and caps input files and directory entries. |
| 2026-10-19 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.155 → 1.74.156 / 1.1.45 → 1.1.46 / 1.0.71 → 1.0.72 / 1.12.294 → 1.12.295 / 1.0.64 → 1.0.65 | Normalize decimal custom PDF ratios such as 1.91:1 with bounded reduced dimensions and verify the crop path. |
| 2026-10-19 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.154 → 1.74.155 / 1.1.44 → 1.1.45 / 1.0.70 → 1.0.71 / 1.12.293 → 1.12.294 / 1.0.63 → 1.0.64 | Add 104 named PDF paper ratios, extension without clipping, and explicit page-layout controls to the local crop CLI and typed operation. |
| 2026-10-19 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.153 → 1.74.154 / 1.1.43 → 1.1.44 / 1.0.69 → 1.0.70 / 1.12.292 → 1.12.293 / 1.0.62 → 1.0.63 | Add Clop 3.5.1 device-name resolution and listing to the bounded PDF crop CLI while keeping paper-size aliases and extension mode on the parity ledger. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md | 1.0.61 → 1.0.62 | Record the Automation naming editor and custom PDF crop ratio CLI; keep device-name catalog parity open. |
| 2026-10-19 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md | 1.74.152 → 1.74.153 / 1.1.42 → 1.1.43 / 1.0.68 → 1.0.69 / 1.12.291 → 1.12.292 | Add strict custom PDF crop aspect ratios, a dedicated local CLI crop preset, and focused validation for vector preservation and unchanged originals. |
| 2026-10-19 | docs/PRD.md / docs/hld/media-toolkit.md | 1.0.26 → 1.0.27 / 1.1.41 → 1.1.42 | Expose safe output-name templates during saved-pipeline creation and show naming in pipeline summaries. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/PRD.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / API-CONTRACT.md | 1.0.60 → 1.0.61 / 1.0.25 → 1.0.26 / 1.1.40 → 1.1.41 / 1.0.67 → 1.0.68 / 1.12.290 → 1.12.291 / 1.74.151 → 1.74.152 | Add safe `{name}`, `{ext}`, and `{media}` pipeline output templates to local API, jobs, watched folders, CLI, and MCP while preserving legacy recipes and no-overwrite publication. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md | 1.0.58 → 1.0.59 / 1.0.65 → 1.0.66 | Reconcile the current seventeen-tool packaged MCP inventory, document shared operation-default tools, and remove a duplicate CLI/MCP capability row. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/PRD.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md | 1.0.57 → 1.0.58 / 1.0.24 → 1.0.25 / 1.1.38 → 1.1.39 / 1.0.64 → 1.0.65 / 1.12.288 → 1.12.289 / 1.197.105 → 1.197.106 | Add a typed video-resize operation backed by the bundled macOS AVFoundation helper; preserve aspect ratio and audio, disallow upscaling, and enforce maximum output dimensions. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md / API-CONTRACT.md | 1.0.56 → 1.0.57 / 1.0.63 → 1.0.64 / 1.12.287 → 1.12.288 / 1.197.104 → 1.197.105 / 1.74.148 → 1.74.149 | Share operation-default options between the desktop Automation view, local API, and MCP using a private typed bounded store; add list/set/clear MCP tools and strict route coverage. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md | 1.0.55 → 1.0.56 / 1.0.62 → 1.0.63 / 1.12.286 → 1.12.287 / 1.197.103 → 1.197.104 | Match Clop's audio preset default by converting WAV inputs to MP3 through the existing typed native operation; preserve M4A output for other audio inputs and extend routing coverage. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md | 1.0.54 → 1.0.55 / 1.0.61 → 1.0.62 / 1.12.285 → 1.12.286 / 1.197.102 → 1.197.103 | Add typed audio-to-MP3, video-to-GIF, and 2x-silent video presets to the shared CLI/MCP contract; pin their operation mappings and extension guards. |
| Date | Document | Version | Change |
| --- | --- | --- | --- |
| 2026-10-19 | docs/ARCHITECTURE.md | 1.0.4 → 1.0.5 | Record the global desktop layer decision (clipboard, snippets, window manager). |
| 2026-10-19 | docs/hld/global-desktop-tools.md / docs/lld/global-desktop-tools.md | New 1.0.0 / New 1.0.0 | Specify the shared global shortcut and panel layer, global clipboard history and snippets with keyword expansion, and the global window manager. |
| 2026-10-20 | API-CONTRACT.md | 1.74.177 → 1.74.178 | Renumber the dictation quality contract rows (cleanup mode and language, vocabulary, context options, faster results, optional on-device polish) after merging main. |
| 2026-10-20 | API-CONTRACT.md | 1.74.124 → 1.74.125 | Add dictation_polish_available and dictation_set_llm_polish for the optional guarded on-device rewrite. |
| 2026-10-19 | API-CONTRACT.md | 1.74.123 → 1.74.124 | Add the dictation_set_streaming_commit command for pause-aligned background decoding. |
| 2026-10-19 | API-CONTRACT.md | 1.74.122 → 1.74.123 | Add smart cleanup mode, language and focus context to the dictation cleanup route, plus vocabulary and context-option commands. |
| 2026-10-20 | docs/hld/dictation-quality.md | 1.1.1 → 1.2.0 | Describe the system as built: OS on-device model instead of a downloaded LLM, no provider seam or model lifecycle, field text kept out of the sidecar, pause-aligned commit, `smart_rules` engine value. |
| 2026-10-20 | API-CONTRACT.md | 1.74.178 → 1.74.179 | Clarify that the stored boolean is returned by the speed and polish commands and that field text never reaches the cleanup sidecar. |
| 2026-10-20 | docs/lld/dictation-quality.md | 1.0.0 → 1.1.0 | Replace the planned design with the as-built one: pause-aligned commit, Swift bridges, Rust guards, lock rules. |
| 2026-10-20 | docs/hld/dictation-quality.md | 1.1.0 → 1.1.1 | State that the opt-in on-device rewrite sits before paste with a 4 s cap, and correct the cleanup response description. |
| 2026-10-20 | docs/hld/dictation-quality.md | 1.0.0 → 1.1.0 | Record the R4 Apple Foundation Models spike result and the as-built pause-aligned R2 and energy-gate R1 designs. |
| 2026-10-19 | docs/lld/dictation-quality.md | New 1.0.0 | Add the file map, interfaces, guards, commit plan and test plan for the dictation quality pipeline. |
| 2026-10-19 | docs/hld/dictation-quality.md | New 1.0.0 | Specify the local-first dictation quality pipeline: silence trimming, streaming commit, prompt biasing, Accessibility context, opt-in local LLM cleanup and edit-learned dictionary suggestions. |
| 2026-10-19 | docs/ARCHITECTURE.md | 1.0.4 → 1.0.5 | Record the local-first dictation quality pipeline decision (VAD, streaming commit, prompt biasing, AX context, opt-in LLM cleanup, edit learning). |
| 2026-10-18 | docs/lld/rectangle-window-snapping.md | 1.0.0 → 1.0.1 | Clarify restore from fullscreen/maximized state and record verified compact hit targets and full shortcut reset coverage. |
| 2026-10-18 | docs/hld/rectangle-window-snapping.md / docs/lld/rectangle-window-snapping.md | New 1.0.0 / New 1.0.0 | Specify Rectangle-style layouts, shortcut customization/reset, drag-edge snapping, fullscreen and display movement. |
| 2026-10-18 | docs/TESTING.md | 1.12.253 → 1.12.254 | Add window snapping desktop and compact E2E coverage and native display verification boundaries. |
| 2026-10-18 | API-CONTRACT.md | 1.74.121 → 1.74.122 | Clarify full versus partial 7-Zip extraction capability states. |
| 2026-10-18 | docs/hld/archive-manager.md / docs/lld/archive-manager.md | 1.0.4 → 1.0.5 / 1.0.4 → 1.0.5 | Distinguish fully supported 7-Zip extraction formats from browse-only partial variants. |
| 2026-10-18 | docs/ARCHITECTURE.md | 1.0.3 → 1.0.4 | Record the conservative full versus partial 7-Zip extraction boundary. |
| 2026-10-18 | docs/hld/archive-manager.md / docs/lld/archive-manager.md | 1.0.3 → 1.0.4 / 1.0.3 → 1.0.4 | Clarify that browsing reuses existing native selections and does not introduce archive sessions. |
| 2026-10-18 | docs/hld/archive-manager.md / docs/lld/archive-manager.md | 1.0.2 → 1.0.3 / 1.0.2 → 1.0.3 | Align the route and file map with 7-Zip staged extraction and selected-entry jobs; clarify nested browsing remains future work. |
| 2026-10-18 | API-CONTRACT.md | 1.74.120 → 1.74.121 | Document selected-entry extraction options and bundled 7-Zip read-format extraction. |
| 2026-10-18 | docs/hld/archive-manager.md / docs/lld/archive-manager.md | 1.0.1 → 1.0.2 / 1.0.1 → 1.0.2 | Record safe staged extraction for the enabled 7-Zip read set and keep ZIP creation capability explicit. |
| 2026-10-18 | docs/ARCHITECTURE.md | 1.0.2 → 1.0.3 | Update the first delivery’s extraction support boundary. |
| 2026-10-18 | API-CONTRACT.md | 1.74.119 → 1.74.120 | Document the archive capability registry and bounded entry-listing route. |
| 2026-10-18 | docs/hld/archive-manager.md / docs/lld/archive-manager.md | 1.0.0 → 1.0.1 / 1.0.0 → 1.0.1 | Record the implemented first slice and explicitly identify remaining engine, nested browsing and format coverage work. |
| 2026-10-18 | docs/ARCHITECTURE.md | 1.0.1 → 1.0.2 | Clarify that the initial delivery packages 7-Zip only and enables implemented operations only. |
| 2026-10-18 | docs/hld/archive-manager.md / docs/lld/archive-manager.md | New 1.0.0 / New 1.0.0 | Record the approved macOS/Windows archive manager design, engine choice, capability contract and implementation map. |
| 2026-10-18 | docs/ARCHITECTURE.md | 1.0.0 → 1.0.1 | Record the approved cross-platform Archive Manager decision and engine/licensing constraints. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md | 1.0.53 → 1.0.54 / 1.0.60 → 1.0.61 / 1.12.284 → 1.12.285 / 1.197.101 → 1.197.102 | Add the fixed-preset MCP tool for bounded `to-webp`, `sort-screenshots`, `optimize-image`, and `optimize-media` runs; verify tool discovery, typed preset rejection, output safety, and unchanged originals. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md | 1.0.52 → 1.0.53 / 1.0.59 → 1.0.60 / 1.12.283 → 1.12.284 / 1.197.100 → 1.197.101 | Add a typed `sort-screenshots` preset that files optimized screenshot copies under capture `YY/MM`, with safe names, no-overwrite publication, and original preservation. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md | 1.0.51 → 1.0.52 / 1.0.58 → 1.0.59 / 1.12.282 → 1.12.283 / 1.197.99 → 1.197.100 | Add a typed `to-webp` CLI preset for common image formats; verify WebP output, extension refusal, packaged execution and unchanged originals. |
| --- || 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/hld/media-toolkit.md / docs/PRD.md / docs/TESTING.md / docs/TOOL-GUIDE.md | 1.0.50 → 1.0.51 / 1.0.57 → 1.0.58 / 1.1.37 → 1.1.38 / 1.0.23 → 1.0.24 / 1.12.281 → 1.12.282 / 1.197.98 → 1.197.99 | Add a strict typed `optimize-media` CLI preset that dispatches common image, video, PDF and audio files to fixed allowlisted operations and verify unsupported-type rejection, mixed-format routing and unchanged originals. |
 --- | --- | --- |
| 2026-10-19 | review/clop-media-toolkit/requirements.md | 1.0.49 → 1.0.50 | Re-audit the current Clop product page and enumerate missing cursor/modifier behavior, pinned pipeline triggers, downscale/crop shortcuts, built-in recipes, external handoffs, and MCP settings controls. |
| 2026-10-19 | docs/TOOL-GUIDE.md | 1.197.97 → 1.197.98 | Record probed host-FFmpeg true-peak and multichannel normalization, with the sample-peak AVFoundation fallback and remaining UI/evidence gates. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md | 1.0.48 → 1.0.49 / 1.0.56 → 1.0.57 | Record rebuilt-DMG 5.1 audio acceptance with six-channel decode, measured LUFS/true peak, and source preservation. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / API-CONTRACT.md / docs/PRD.md / docs/TESTING.md | 1.0.47 → 1.0.48 / 1.1.36 → 1.1.37 / 1.0.55 → 1.0.56 / 1.74.147 → 1.74.148 / 1.0.22 → 1.0.23 / 1.12.280 → 1.12.281 | Add bounded optional FFmpeg EBU R128 loudness normalization with a -2 dBTP target, measured typed results, multichannel capability, explicit AVFoundation fallback semantics, and packaged 5.1 decode/source-preservation coverage. |
| 2026-10-19 | docs/lld/media-toolkit.md | 1.0.54 → 1.0.55 | Correct the packaged MCP discovery count and distinguish the existing watermark/Finder adapters from their pending UI approval and installed-app checks. |
| 2026-10-19 | docs/TOOL-GUIDE.md | 1.197.96 → 1.197.97 | Record optional host-FFmpeg MP3 output and change Finder Quick Action from unimplemented to awaiting installed-app verification. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md | 1.0.46 → 1.0.47 | Record API-level mixed-media per-item operation support with a real image/PDF batch and unchanged-source test; keep the new independent-settings workbench UI behind mock approval. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / API-CONTRACT.md / docs/PRD.md / docs/TESTING.md | 1.0.45 → 1.0.46 / 1.1.35 → 1.1.36 / 1.0.53 → 1.0.54 / 1.74.146 → 1.74.147 / 1.0.21 → 1.0.22 / 1.12.279 → 1.12.280 | Add optional host-FFmpeg MP3 output behind a bounded private encoder probe, strict typed audio formats, fixed local-file protocol arguments, lossy codec metadata, and source-preservation test coverage; keep the workbench selector pending its approved mock. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / API-CONTRACT.md / docs/PRD.md / docs/TESTING.md | 1.0.44 → 1.0.45 / 1.1.34 → 1.1.35 / 1.0.52 → 1.0.53 / 1.74.145 → 1.74.146 / 1.0.20 → 1.0.21 / 1.12.278 → 1.12.279 | Add capability-probed optional AV1-in-MP4 conversion through host-installed FFmpeg, restrict inputs to local media protocols, verify MP4 codec/signature and source preservation, and update the Clop feature comparison. |
| 2026-10-18 | docs/TESTING.md | 1.12.277 → 1.12.278 | Add native media output signature checks for MP4-family, FLAC, WAV, AIFF and GIF results before publication. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / API-CONTRACT.md / docs/PRD.md / docs/TESTING.md / docs/TOOL-GUIDE.md | 1.0.43 → 1.0.44 / 1.1.33 → 1.1.34 / 1.0.51 → 1.0.52 / 1.74.144 → 1.74.145 / 1.0.19 → 1.0.20 / 1.12.276 → 1.12.277 / 1.197.95 → 1.197.96 | Add probed FLAC conversion with honest lossless metadata and packaged MP3/FLAC input coverage; document that MP3 output needs an encoder not present in the system adapter. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / API-CONTRACT.md / docs/PRD.md / docs/TESTING.md / docs/TOOL-GUIDE.md | 1.0.42 → 1.0.43 / 1.1.32 → 1.1.33 / 1.0.50 → 1.0.51 / 1.74.143 → 1.74.144 / 1.0.18 → 1.0.19 / 1.12.275 → 1.12.276 / 1.197.94 → 1.197.95 | Add `video-hevc-convert` behind native preset detection; expose MOV output, show HEVC codec/container in results, and add codec/source-preservation packaged smoke coverage after approved UI mock. |
| 2026-10-18 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.141 → 1.74.142 / 1.1.30 → 1.1.31 / 1.0.48 → 1.0.49 / 1.12.273 → 1.12.274 / 1.0.40 → 1.0.41 | Add name-only preset-zone updates across the local API and MCP, preserving the bound pipeline and session enablement. |
| 2026-10-18 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.140 → 1.74.141 / 1.1.29 → 1.1.30 / 1.0.47 → 1.0.48 / 1.12.272 → 1.12.273 / 1.0.39 → 1.0.40 | Expose local MCP tools for saved pipeline deletion and durable preset-zone binding management, preserving dependency guards and desktop-only session grants/enablement. |
| 2026-10-18 | API-CONTRACT.md / docs/PRD.md / docs/ARCHITECTURE.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / review/clop-media-toolkit/requirements.md | 1.74.139 → 1.74.140 / 1.0.17 → 1.0.18 / 1.0.1 → 1.0.2 / 1.1.28 → 1.1.29 / 1.0.46 → 1.0.47 / 1.0.38 → 1.0.39 | Add the explicitly installed image-only Finder Quick Action, typed CLI preset, collision-safe numbered sibling output, and native status/install/remove contract. |
| 2026-10-18 | API-CONTRACT.md / docs/PRD.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.138 → 1.74.139 / 1.0.16 → 1.0.17 / 1.1.27 → 1.1.28 / 1.0.45 → 1.0.46 / 1.12.271 → 1.12.272 / 1.0.37 → 1.0.38 | Add capability-probed JPEG XL image preparation using the BSD-3-Clause optional Pillow plugin on supported macOS and Windows x64 targets; verify its operation outputs and packaged conversion. |
| 2026-10-18 | API-CONTRACT.md / docs/PRD.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.137 → 1.74.138 / 1.0.15 → 1.0.16 / 1.1.26 → 1.1.27 / 1.0.44 → 1.0.45 / 1.12.270 → 1.12.271 / 1.0.36 → 1.0.37 | Add runtime-probed AVIF conversion, optimization, fit-size, resize and metadata removal; advertise AVIF output only for operations that can produce it, with capability-driven UI choices and conditional packaged-sidecar acceptance. |
| 2026-10-18 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md / review/clop-media-toolkit/requirements.md | 1.74.136 → 1.74.137 / 1.1.25 → 1.1.26 / 1.0.43 → 1.0.44 / 1.12.269 → 1.12.270 / 1.197.93 → 1.197.94 / 1.0.35 → 1.0.36 | Add typed pipeline definition updates via API and MCP, preserving recipe IDs and paused state. |
| 2026-10-18 | docs/lld/media-toolkit.md / docs/TESTING.md | 1.0.42 → 1.0.43 / 1.12.268 → 1.12.269 | Document cross-process pipeline locking, path-free MCP job errors, and regression coverage for rename overflow and packaged run safety. |
| 2026-10-18 | docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md / review/clop-media-toolkit/requirements.md | 1.1.24 → 1.1.25 / 1.0.41 → 1.0.42 / 1.12.267 → 1.12.268 / 1.197.92 → 1.197.93 / 1.0.34 → 1.0.35 | Add MCP execution of stored pipelines by ID through the existing bounded local CLI path. |
| 2026-10-18 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md / review/clop-media-toolkit/requirements.md | 1.74.135 → 1.74.136 / 1.1.23 → 1.1.24 / 1.0.40 → 1.0.41 / 1.12.266 → 1.12.267 / 1.197.91 → 1.197.92 / 1.0.33 → 1.0.34 | Add typed saved-pipeline rename over API and MCP while preserving recipe ID, operations, paused state, and existing folder/preset bindings. |
| 2026-10-18 | API-CONTRACT.md / docs/PRD.md / docs/TOOL-GUIDE.md / review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md | 1.74.131 → 1.74.132 / 1.0.11 → 1.0.12 / 1.197.87 → 1.197.88 / 1.0.27 → 1.0.28 / 1.1.18 → 1.1.19 / 1.0.34 → 1.0.35 / 1.12.261 → 1.12.262 | Add a private preset-zone API that binds bounded names to existing pipelines, keeps activation session-only/off after restart, blocks deletion of referenced pipelines, and records the remaining UI approval gate. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md | 1.0.26 → 1.0.27 | Add a source-checked Clop capability parity ledger that separates implemented media operations from missing triggers, formats, Finder/hotkey support, external handoffs, and installed-app verification. |
| 2026-10-18 | API-CONTRACT.md / docs/PRD.md / docs/TOOL-GUIDE.md / review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md | 1.74.130 → 1.74.131 / 1.0.10 → 1.0.11 / 1.197.86 → 1.197.87 / 1.0.25 → 1.0.26 / 1.1.17 → 1.1.18 / 1.0.33 → 1.0.34 / 1.12.260 → 1.12.261 | Add macOS mono/stereo gated LUFS normalization through the packaged AVFoundation helper, report measured output and sample-peak ceiling honestly, and document limits, acceptance cases, and open UI approval. |
| 2026-10-18 | API-CONTRACT.md / docs/PRD.md / docs/TOOL-GUIDE.md / review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md | 1.74.129 → 1.74.130 / 1.0.9 → 1.0.10 / 1.197.85 → 1.197.86 / 1.0.24 → 1.0.25 / 1.1.16 → 1.1.17 / 1.0.32 → 1.0.33 / 1.12.259 → 1.12.260 | Implement bounded local image-watermark overlay processing and private logo staging; align API, product, test and tool-availability documentation while holding user-facing controls for mock approval. |
| 2026-10-18 | API-CONTRACT.md / review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md | 1.74.129 → 1.74.130 / 1.0.24 → 1.0.25 / 1.1.16 → 1.1.17 / 1.0.32 → 1.0.33 / 1.12.259 → 1.12.260 | Add a private 5 MiB, five-minute image watermark staging grant and a typed local overlay operation using placement, margin, scale, and opacity; test compositing, job privacy, and unchanged originals while the UI remains pending mock approval. |
| 2026-10-18 | API-CONTRACT.md / review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md | 1.74.128 → 1.74.129 / 1.0.23 → 1.0.24 / 1.1.15 → 1.1.16 / 1.0.31 → 1.0.32 / 1.12.258 → 1.12.259 | Add native session-scoped watched-folder automation using opaque pinned grants and saved pipelines, 10,000-entry bounds, stable-file triggering, pause/resume/remove controls, and exclusive no-replace sibling outputs; document API and packaged acceptance gaps. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/hld/media-toolkit.md | 1.0.13 → 1.0.14 / 1.0.21 → 1.0.22 / 1.1.5 → 1.1.6 | Patch Tauri's built-in drag/drop bridge so webview events contain no source paths or filesystem grants; scope drops to the visible idle Prepare view, make separate drops append safely under a 30-file cap, and record platform coordinate units and artifact status copy. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md | 1.0.12 → 1.0.13 / 1.0.20 → 1.0.21 | Scope native drops to the visible Prepare view and idle state, append separate drops up to 30 files without revoking active job grants, correct the latest-outcome and artifact-expiry copy, and distinguish available text watermarking from the planned image watermark overlay. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md | 1.0.11 → 1.0.12 / 1.0.19 → 1.0.20 | Implement read-only Media Toolkit drag/drop through native Tauri events and opaque file grants; document validation and preserve explicit unavailable states for remaining workflows. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md | 1.0.10 → 1.0.11 | Remove stale claim that the Voice Transcription audio handoff is outstanding; the read-only-grant Audio optimization handoff is implemented. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md | 1.0.9 → 1.0.10 / 1.0.18 → 1.0.19 | Mark image watermarking, drag/drop, result format bar, and searchable local defaults as planned in the Media Toolkit capability coverage. |
| 2026-10-18 | docs/lld/media-toolkit.md | 1.0.17 → 1.0.18 | Record passing focused native atomic-publication tests with packaged Save Copy UI evidence, and make remaining parity and cross-platform gaps explicit. |
| 2026-10-18 | docs/lld/media-toolkit.md | 1.0.16 → 1.0.17 | Extend packaged macOS media acceptance to decode image/audio/video outputs and state the remaining atomic Save Copy publication gap precisely. |
| 2026-10-18 | docs/lld/media-toolkit.md | 1.0.15 → 1.0.16 | Add reproducible packaged macOS media acceptance for real image/audio/video jobs, cancellation, resource limits, privacy, originals, and settings recovery; record the manual packaged Save Copy UI verification and 100% changed-line backend coverage. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md | 1.0.8 → 1.0.9 / 1.0.14 → 1.0.15 | Align visible operation controls with typed bounds, support exact one-byte size targets, and make image EXIF/profile retention an explicit opt-in without changing legacy conversion privacy behavior. |
| 2026-10-18 | docs/lld/media-toolkit.md | 1.0.13 → 1.0.14 | Add operation-specific validated settings and the Automation view, with explicit per-integration availability, paused manual pipelines, output naming, and recent outcomes. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md | 1.0.7 → 1.0.8 / 1.0.12 → 1.0.13 | Cap aggregate native workspaces at 192 MiB, delete superseded fit candidates, and remove prior pipeline-stage files after successful conversion. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md | 1.0.6 → 1.0.7 / 1.0.11 → 1.0.12 | Stream native audio/video job and HTTPS-import inputs to private files, retain native output files without loading them into memory, and route source-checkout CLI native recipes through the file-backed adapter. |
| 2026-10-18 | API-CONTRACT.md / docs/TESTING.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/PRD.md / docs/TOOL-GUIDE.md / review/clop-media-toolkit/requirements.md | 1.74.127 → 1.74.128 / 1.12.255 → 1.12.256 / 1.1.3 → 1.1.4 / 1.0.9 → 1.0.10 / 1.0.8 → 1.0.9 / 1.197.82 → 1.197.83 / 1.0.4 → 1.0.5 | Add explicit Voice Transcription handoff into Audio optimization through a filtered read-only native file grant; verify safe metadata display and preserve source authority. |
| 2026-10-18 | API-CONTRACT.md / docs/TESTING.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/PRD.md / docs/TOOL-GUIDE.md / review/clop-media-toolkit/requirements.md | 1.74.126 → 1.74.127 / 1.12.254 → 1.12.255 / 1.1.2 → 1.1.3 / 1.0.8 → 1.0.9 / 1.0.7 → 1.0.8 / 1.197.81 → 1.197.82 / 1.0.3 → 1.0.4 | Add private persisted typed media pipeline recipes that start paused and execute only via explicit job submission; record automation mock approval and pipeline regression evidence. |
| 2026-10-18 | API-CONTRACT.md / docs/TESTING.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/PRD.md / docs/TOOL-GUIDE.md / review/clop-media-toolkit/requirements.md | 1.74.124 → 1.74.125 / 1.12.253 → 1.12.254 / 1.1.0 → 1.1.2 / 1.0.6 → 1.0.8 / 1.0.6 → 1.0.7 / 1.197.80 → 1.197.81 / 1.0.2 → 1.0.3 | Add verified Screenshot Editor to Media Toolkit handoff using a bounded app-private image staging grant; add opaque staged-image job sources, cleanup lifecycle, contract/body-bound documentation and backend/desktop/compact acceptance. Keep direct transcription handoff outstanding. |
| 2026-10-18 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/PRD.md / docs/TOOL-GUIDE.md | 1.74.123 → 1.74.124 / 1.0.9 → 1.1.0 / 1.0.5 → 1.0.6 / 1.0.5 → 1.0.6 / 1.197.78 → 1.197.79 | Add source/output byte comparison and explicit size-target outcome to each media job result; wire approved PDF fidelity and crop disclosures, enable packaged PDF visual/crop operations, add approved URL preview UI, and record screenshot/transcription handoff gaps. |
| 2026-10-18 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/PRD.md / docs/TOOL-GUIDE.md | 1.74.121 → 1.74.122 / 1.0.6 → 1.0.7 / 1.0.2 → 1.0.3 / 1.0.3 → 1.0.4 / 1.197.76 → 1.197.77 | Add bounded PDF visual optimize/fit and vector-preserving crop backends; add SSRF-resistant public HTTPS preview and single-use import jobs; record the user-facing fidelity warning mock gate and remaining Clop capability gaps. |
| 2026-10-18 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/PRD.md | 1.74.120 → 1.74.121 / 1.0.5 → 1.0.6 / 1.0.1 → 1.0.2 / 1.0.2 → 1.0.3 | Add per-build operation capability discovery, integrate the shared UI and legacy image/PDF entries, and record bounded macOS avconvert/afconvert adapters for video/audio optimize, convert, and fit-size. Keep unimplemented Clop operations and private-beta promotion explicitly outstanding. |
| 2026-10-18 | docs/TOOL-GUIDE.md | 1.197.75 → 1.197.76 | Add the development-only Media Toolkit capability and current operation/platform limits to the tool depth audit. |
| 2026-10-18 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md | 1.74.119 → 1.74.120 / 1.0.4 → 1.0.5 / 1.0.0 → 1.0.1 | Document the implemented native-grant Media Toolkit queue, typed operations, streamed artifacts, current adapter limits, and truthful unavailable states. |
| 2026-10-18 | docs/hld/media-toolkit.md | 1.0.3 → 1.0.4 | Record official Apple/FFmpeg engine capability and redistribution research as a packaging gate; no encoder is selected yet. |
| 2026-10-18 | docs/hld/media-toolkit.md / docs/lld/media-toolkit.md | 1.0.2 → 1.0.3 / unchanged 1.0.0 | Align shared job cap at 30 items and clarify the existing image batch route retains its separate 50-image cap. |
| 2026-10-18 | docs/lld/media-toolkit.md | New 1.0.0 | Map the staged media adapters, API/client/native ownership, bounded jobs, and verification plan after HLD approval. |
| 2026-10-18 | docs/ARCHITECTURE.md / docs/hld/media-toolkit.md / docs/PRD.md / review/clop-media-toolkit/requirements.md | 1.0.0 → 1.0.1 / 1.0.1 → 1.0.2 / 1.0.1 → 1.0.2 / 1.0.1 → 1.0.2 | Record owner “go ahead” selecting the OfficeKit-owned local-adapter architecture, approving the revised mock, and confirming full integrated capability scope. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/PRD.md / docs/hld/media-toolkit.md | 1.0.0 → 1.0.1 / 1.0.0 → 1.0.1 / 1.0.0 → 1.0.1 | Add explicit public HTTPS import, full per-media operation detail, and SSRF/automation boundaries; updated mock approval pending. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/PRD.md / docs/hld/media-toolkit.md | New 1.0.0 | Record complete Clop capability scope, OfficeKit integration map, staged product requirements, and proposed local Media Toolkit architecture. |
| 2026-10-17 | DESIGN_SYSTEM.md | 1.8.17 → 1.9.0 | Senior UI: Apple Pro revamp with Liquid Glass split-pane materials, specular hairlines, Space Black dark mode, floating Siri STT HUD, tactile progress bar, and in-app banner. |
| 2026-10-17 | design/COMPONENT_STRUCTURE.md | 1.2.4 → 1.2.5 | Senior UI: AppBanner, ProgressBarSystem, and SttFloatingHud architecture and ownership. |
| 2026-10-17 | docs/hld/pii-hybrid.md / docs/lld/pii-hybrid.md | 1.0.6 → 1.0.7 / 1.0.5 → 1.0.6 | Record bounded C++ runtime timeouts and end-to-end username/IP-address candidates. |
| 2026-10-17 | DESIGN_SYSTEM.md | 1.8.16 → 1.8.17 | Add approved automatic sidebar collapse when opening a tool, and clarify manual expansion remains available. |
| 2026-10-17 | API-CONTRACT.md | 1.74.118 → 1.74.119 | Document live file-job insights and storage-scan entry/candidate counters for the Activity monitor. |
| 2026-10-17 | DESIGN_SYSTEM.md | 1.8.15 → 1.8.16 | Approved cross-app Activity with operation insights, background continuation, merged result history, and desktop minimum window sizing. |
| 2026-10-17 | docs/hld/pii-hybrid.md | 1.0.5 → 1.0.6 | Record user approval and durable decision for the PII result flow. |
| 2026-10-17 | docs/hld/pii-hybrid.md / docs/lld/pii-hybrid.md | 1.0.4 → 1.0.5 / 1.0.4 → 1.0.5 | Record supported-format messaging, post-output image editing, and extension-safe downloads. |
| 2026-10-17 | docs/hld/pii-hybrid.md / docs/lld/pii-hybrid.md | 1.0.3 → 1.0.4 / 1.0.3 → 1.0.4 | Record shipped English document-cue candidates and optional model behavior. |
| 2026-10-17 | docs/hld/pii-hybrid.md / docs/lld/pii-hybrid.md | 1.0.1 → 1.0.2 / 1.0.1 → 1.0.2 | Record optional offline C++ runtime, bounded long-text inference, and expanded evaluation evidence/disabled-by-default decision. |
| 2026-10-17 | docs/hld/pii-hybrid.md / docs/lld/pii-hybrid.md | 1.0.2 → 1.0.3 / 1.0.2 → 1.0.3 | Specify entity-specific resolver tie-breaks and regression evidence for IP/address and international phone/card overlaps. |
| 2026-10-17 | docs/hld/pii-hybrid.md / docs/lld/pii-hybrid.md / review/pii-hybrid/requirements.md | 1.0.0 → 1.0.1 / 1.0.0 → 1.0.1 / 1.0.0 → 1.0.1 | Record approved context-match review hint, opt-in local model integration, and current disabled-by-default decision. |
| 2026-10-17 | docs/ARCHITECTURE.md | New 1.0.0 | Record owner-selected hybrid local PII detection decision and candidate-size/language constraints. |
| 2026-10-17 | docs/hld/pii-hybrid.md | New 1.0.0 | Define local hybrid detection flow, stable span identity and resource/privacy boundaries. |
| 2026-10-17 | docs/lld/pii-hybrid.md | New 1.0.0 | Map adapter, resolver, corpus, evaluator, tests and packaging checkpoints. |
| 2026-10-17 | review/pii-hybrid/requirements.md | New 1.0.0 | Capture goal, acceptance criteria and current UI/API compatibility constraints. |
| 2026-10-16 | DESIGN_SYSTEM.md / design/COMPONENT_STRUCTURE.md | 1.8.14 → 1.8.15 / 1.2.4 → 1.2.5 | Approved app-wide reserved bottom action area and compact Duplicate Finder with Details. |
| 2026-10-16 | docs/TESTING.md | 1.12.252 → 1.12.253 | Persistent action containment, stationary scrolling, registry routes and complete result-flow checks. |
| 2026-10-16 | DESIGN_SYSTEM.md | 1.8.13 → 1.8.14 | Codex: approved border-only field focus and parent-owned composite search focus. |
| 2026-10-16 | docs/TESTING.md | 1.12.251 → 1.12.252 | Codex: registry-wide focus matrix with advanced controls, themes and keyboard-focus preservation. |
| 2026-10-16 | API-CONTRACT.md | 1.74.117 → 1.74.118 | Codex: recursive default, exact folder matches, authenticated full paths and native scan-bound Finder reveal. |
| 2026-10-16 | DESIGN_SYSTEM.md | 1.8.12 → 1.8.13 | Codex: approved header sorting, Finder rows/path hover and inspection-only folder mode. |
| 2026-10-16 | docs/TESTING.md | 1.12.250 → 1.12.251 | Codex: exact folder matching, scan/root identity and native reveal acceptance. |
| 2026-10-16 | docs/TESTING.md | 1.12.249 → 1.12.250 | Codex: nested duplicate scope, date metadata, grouped pagination/sorting, page sizes and cross-page selection acceptance. |
| 2026-10-16 | API-CONTRACT.md | 1.74.116 → 1.74.117 | Codex: strict direct-folder duplicate scope, optional recursive scan and date metadata for sorting. |
| 2026-10-16 | DESIGN_SYSTEM.md | 1.8.11 → 1.8.12 | Codex: approved grouped pagination, page size, sorting, all-page selection and bounded duplicate list. |
| 2026-10-16 | DESIGN_SYSTEM.md | 1.8.11 | Approved app-wide decorative action icons, quiet text exceptions, and runtime/result-button coverage. |
| 2026-10-16 | API-CONTRACT.md | 1.74.116 | Scan-bound duplicate Trash job with retained originals, strict opaque IDs, write authority and per-file recovery. |
| 2026-10-16 | DESIGN_SYSTEM.md | 1.8.10 | Approved common page-title hierarchy and actions after output; neutral duplicate Trash control with explicit confirmation. |
| 2026-10-16 | design/COMPONENT_STRUCTURE.md | 1.2.4 | Shared title token, appended result actions and library duplicate-selection controls. |
| 2026-10-16 | docs/TESTING.md | 1.12.249 | Duplicate mutation safety and full-flow placement/confirmation checks. |
| 2026-10-15 | DESIGN_SYSTEM.md / design/COMPONENT_STRUCTURE.md / design/officekit-tokens.css | 1.8.8 → 1.8.9 / 1.2.2 → 1.2.3 / tokens v1.8.9 | Define and apply app-wide button/field dimensions, textarea minimum, and Ice Blue primary-action color; add registry-wide rendered consistency checks |
| 2026-10-15 | DESIGN_SYSTEM.md / design/COMPONENT_STRUCTURE.md | 1.8.7 → 1.8.8 / 1.2.1 → 1.2.2 | Record the Tailwind CSS 4.3.3 migration, daisyUI 5.7.50, and CSS-first theme and source configuration |
| 2026-10-15 | DESIGN_SYSTEM.md / design/COMPONENT_STRUCTURE.md | 1.8.6 → 1.8.7 / 1.2.0 → 1.2.1 | Record daisyUI 4.12.24 as the shared UI component library and restrict custom controls to patterns the library does not provide |
| 2026-10-15 | DESIGN_SYSTEM.md / shared token reference | 1.8.5 → 1.8.6 | Record selected Ice Blue palette, intentional light/dark pair and restrained glass material rules from the approved clickable refresh |
| 2026-10-15 | PDF HLD / API-CONTRACT.md / PITFALLS.md | 1.0.1 → 1.0.2 / 1.74.114 → 1.74.115 / new P-164–165 | Define authoritative Undo/Redo restoration, record HYP2003 vendor provenance and proven geometry/alpha/crop-budget review regressions |
| 2026-10-15 | API-CONTRACT.md / TESTING.md / FIRST-MAC-RELEASE.md | 1.74.113 → 1.74.114 / 1.12.247 → 1.12.248 / 1.0.192 → 1.0.193 | Declare implemented development PDF workspace resources and native provider boundary, verification requirements and beta/hardware gates |
| 2026-10-15 | PDF editing/annotation/DSC HLD and LLD | HLD 1.0.0 → 1.0.1; LLD new 1.0.0 | Record owner architecture approval and file/interface/checkpoint implementation plan |
| 2026-10-15 | PDF editing/annotation/DSC HLD and feature API contract | New → 1.0.0 | Record approved expanded UI, screenshot-style toolbar, full editing/OCR scope and proposed local session/signing architecture; architecture agreement pending |
| 2026-10-14 | API-CONTRACT.md | 1.74.112 → 1.74.113 | Document observed-traffic physical interface selection and VPN tunnel exclusion for system network rates |
| 2026-10-14 | docs/TESTING.md | 1.12.246 → 1.12.247 | Add multi-adapter network metrics and desktop/compact UI checks |
| 2026-10-14 | API-CONTRACT.md | 1.74.111 → 1.74.112 | Document bounded Screenshot Editor line, rounded rectangle, stamp, pixelate and rotate operations |
| 2026-10-14 | docs/TESTING.md | 1.12.245 → 1.12.246 | Add Screenshot Editor operation, image-output and pending UI acceptance checks |
| 2026-10-14 | DESIGN_SYSTEM.md | 1.8.4 → 1.8.5 | Record approved consistent bottom action docks for primary and result actions |
| 2026-10-14 | DESIGN_SYSTEM.md | 1.8.3 → 1.8.4 | Record approved compact dictation transcript cards and opt-in 7/30/90-day local history retention |
| 2026-10-14 | DESIGN_SYSTEM.md and shared token reference | 1.8.3 → 1.8.4 | Record approved system-wide storage categories, exact cleanup review, normal-flow footer and permission recovery |
| 2026-10-14 | API-CONTRACT.md | 1.74.110 → 1.74.111 | Finalise largest entries, typed Docker usage, native permission settings and verified package-cache staging |
| 2026-10-14 | docs/PITFALLS.md | New P-163 | Record real cache-tool incompatibility with inherited descriptor paths and disposable runtime regression |
| 2026-10-14 | storage-cleaner HLD/LLD | 1.0.0 → 1.0.1 | Record safe cache staging, real tool fixtures, largest reports, Docker usage and permission recovery |
| 2026-10-14 | API-CONTRACT.md | 1.74.109 → 1.74.110 | Declare native-authorised system-wide scans, cancellation, identity-bound cleanup plans and typed execution outcomes |
| 2026-10-14 | docs/TESTING.md | 1.12.244 → 1.12.245 | Add system-wide storage coverage, category overview, reviewed cleanup and platform evidence checks |
| 2026-10-14 | storage-cleaner HLD/LLD and PRD | New → 1.0.0 | Record approved system-wide discovery, multicolour category overview, OS adapter architecture and reviewed cleanup |
| 2026-10-13 | DESIGN_SYSTEM.md | 1.8.2 → 1.8.3 | Record app-wide System/Light/Dark implementation, semantic cross-screen surfaces, microphone discovery, truthful model progress and safe local model cleanup |
| 2026-10-13 | docs/TESTING.md | 1.12.243 → 1.12.244 | Add complete dark-theme destination sweep, separate no-input microphone state, engine-specific progress, and guarded model removal checks |
| 2026-10-13 | dictation HLD/LLD | 1.0.1 → 1.0.2 | Record hardware input discovery, exact Whisper versus library FluidAudio progress, model inventory/removal guards, and appearance coverage |
| 2026-10-13 | DESIGN_SYSTEM.md | 1.8.1 → 1.8.2 | Record approved screenshot editor state-based source actions, compact top toolbar and selected-tool settings |
| 2026-10-13 | docs/PITFALLS.md | New P-159 | Record launch abort on API port collision and per-instance loopback routing regression |
| 2026-10-13 | docs/APPROVED-DICTATION-MODEL-CATALOG.md | 1.0.0 | Record approved per-model benchmark fields, language/output controls, and shell visibility states |
| 2026-10-13 | docs/TESTING.md | 1.12.242 → 1.12.243 | Add multilingual dictation source checks and separate real-model/installed acceptance gates |
| 2026-10-13 | dictation HLD/LLD | 1.0.0 → 1.0.1 | Record whisper.cpp source implementation, English-only translation scope and pending installed/runtime verification |
| 2026-10-13 | API-CONTRACT.md | 1.74.108 → 1.74.109 | Specify validated direct-file response DTOs and fail-closed no-replace publication for results and extraction |
| 2026-10-13 | docs/TESTING.md | 1.12.241 → 1.12.242 | Add no-replace, held-directory extraction, owned cleanup and response DTO regression requirements |
| 2026-10-13 | workspace-refresh HLD/LLD | 1.0.1 → 1.0.2 | Record direct original processing, typed route results, no-replace publication and descriptor-owned extraction cleanup |
| 2026-10-12 | DESIGN_SYSTEM.md | 1.8.0 → 1.8.1 | Record combined design/architecture approval and implementation verification status |
| 2026-10-12 | API-CONTRACT.md | 1.74.107 → 1.74.108 | Record implemented direct selection/jobs, native Save As/copy/tray, metric snapshot, dual-color/path annotations and honest recoverable dictation delivery |
| 2026-10-12 | docs/TESTING.md | 1.12.240 → 1.12.241 | Add whole-registry consistent-workspace acceptance and reusable installed evidence checklist |
| 2026-10-12 | workspace-refresh HLD/LLD | 1.0.0 → 1.0.1 | Record combined "lgtm" approval and implementation verification status |
| 2026-10-12 | docs/hld/workspace-and-annotation-refresh.md; docs/lld/workspace-and-annotation-refresh.md; feature-local API-CONTRACT.md | 1.0.0 | Add proposed architecture, file-by-file rollout and local selection/job/annotation/metrics contracts for combined design review; no implemented-surface claim |
| 2026-10-12 | design/COMPONENT_STRUCTURE.md | 1.1.0 → 1.2.0 | Align shell, shared result actions, three layout families, direct filesystem selection and editable annotation ownership with the revised design system |
| 2026-10-12 | DESIGN_SYSTEM.md | 1.7.2 → 1.8.0 | Revisit the app-wide system for simple, intuitive, appealing consistency: Home/fixed shell, three shared tool layouts, complete Copy/Download actions, direct original-file processing and editable dual-color annotations; distinguish proposed design from implementation |
| 2026-10-12 | API-CONTRACT.md | 1.74.106 → 1.74.107 | Specify default partial-mask mode, explicit full redaction mode and output filenames |
| 2026-10-12 | docs/TESTING.md | 1.12.239 → 1.12.240 | Add partial/full PII mode integrity and screenshot annotation checks |
| 2026-10-12 | API-CONTRACT.md | 1.74.105 → 1.74.106 | Specify local PII scan and separate masked-copy routes, formats, limits and heuristic detection boundary |
| 2026-10-12 | docs/TESTING.md | 1.12.238 → 1.12.239 | Add file-based PII review, output-integrity and limitation acceptance checks |
| 2026-10-12 | docs/FIRST-MAC-RELEASE.md | 1.0.191 → 1.0.192 | Add the PII review tool to catalogue scope and retain its OCR, fidelity and metadata release gates |
| 2026-10-12 | DESIGN_SYSTEM.md | 1.7.1 → 1.7.2 | Merge Developer Tools into Developer & Data and document the shared gallery category |
| 2026-10-12 | docs/TESTING.md | 1.12.237 → 1.12.238 | Correct physical modifier verification guidance and define native overlay/cancellation and screenshot annotation API/browser acceptance |
| 2026-10-12 | Dictation and screenshot UX | Native overlay / capture shortcut | Add focus-preserving overlay, generation-guarded Escape cancellation, native area capture shortcuts and accessible rectangle/text annotations; record measured hardware failure behavior and pending physical acceptance |
| 2026-10-12 | docs/PITFALLS.md | New P-155 | Reproduce packaged cleanup disconnect caused by TCP half-close and correct the native HTTP transport and test fixture |
| 2026-10-12 | docs/PITFALLS.md | New P-153/P-154 | Record measured Right Shift state-query failure and no-input AVFAudio tap crash; add recorded-event, hardware and Objective-C exception regressions |
| 2026-10-12 | docs/PITFALLS.md | P-151 diagnosis corrected | Inspect installed signature, identify missing Hardened Runtime audio-input entitlement, and add mounted-DMG entitlement enforcement |
| 2026-10-12 | docs/PITFALLS.md | P-151 corrected | Remove the default-audio-device prerequisite from the explicit macOS microphone permission request |
| 2026-10-12 | DESIGN_SYSTEM.md | 1.7.0 → 1.7.1 | Define global operation-error toast with persistent context at the failed control |
| 2026-10-12 | docs/PITFALLS.md | New P-152 | Prevent dictation errors from appearing only in an off-screen setup section |
| 2026-10-12 | docs/PITFALLS.md | P-151 update | Record that requestAccess alone did not present the installed-app prompt; require explicit capture-input probe and stop behavior |
| 2026-10-11 | docs/PITFALLS.md | New P-151 | Record stale dictation permission state after changing macOS TCC settings |
| 2026-10-11 | docs/TOOL-GUIDE.md | 1.197.74 → 1.197.75 | Point engine references at `officekit/engines/` after source reorganization |
| 2026-10-09 | docs/PITFALLS.md | New P-150 | Record beta UI assertions that went stale after tool-scope growth |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.73 → 1.197.74 | Refresh Python test totals and record focused beta WebKit recovery |
| 2026-10-09 | docs/TESTING.md | 1.12.236 → 1.12.237 | Align beta release checks with the 39-tool profile and avoid stale counts |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.188 → 1.0.189 | Record current Mac test installer fingerprint and beta UI regression recovery |
| 2026-10-09 | docs/PITFALLS.md | New P-149 | Record limited XLSX locale/literal number-format rendering and the pending packaged acceptance gate |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.72 → 1.197.73 | Record Indian grouping, locale-tagged currency and literal XLSX format support with sidecar gap |
| 2026-10-09 | docs/TESTING.md | 1.12.235 → 1.12.236 | Expand XLSX display-format verification across localized, literal, fallback and packaging cases |
| 2026-10-09 | API-CONTRACT.md | 1.74.104 → 1.74.105 | Specify the supported localized XLSX numeric-display subset and safe fallback |
| 2026-10-09 | docs/PITFALLS.md | New P-148 | Record and prevent spreadsheet formula injection through configurable delimited null markers |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.71 → 1.197.72 | Record spreadsheet-formula marker rejection for optional CSV/TSV null handling |
| 2026-10-09 | docs/TESTING.md | 1.12.234 → 1.12.235 | Add formula-shaped null-marker rejection to conversion test requirements |
| 2026-10-09 | API-CONTRACT.md | 1.74.103 → 1.74.104 | Require formula-safe values for the optional delimited null marker |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.70 → 1.197.71 | Record the 39-tool beta inventory and explicit CSV/TSV null-marker behavior and browser evidence |
| 2026-10-09 | docs/TESTING.md | 1.12.233 → 1.12.234 | Require escaped null-marker round trips and invalid-marker coverage for CSV/TSV conversion |
| 2026-10-09 | API-CONTRACT.md | 1.74.102 → 1.74.103 | Specify bounded optional CSV/TSV null marker and same-marker escape behavior |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.187 → 1.0.188 | Expand the beta to 39 tools and document enabled image metadata cleanup with packaged EXIF verification |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.186 → 1.0.187 | Promote local image metadata cleanup into the beta profile with EXIF, palette, animation, and packaged-output checks |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.185 → 1.0.186 | Promote bounded single and batch image resizing into the beta shortlist and record the new acceptance gates |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.184 → 1.0.185 | Record the 37-tool Apple Silicon beta installer, packaged image-conversion smoke and current release gates |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.183 → 1.0.184 | Record the verified 36-tool Apple Silicon beta installer and packaged page-management smoke |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.182 → 1.0.183 | Promote PDF page deletion and reordering after preserving forms/navigation, desktop/compact flows and packaged page-order checks |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.181 → 1.0.182 | Promote bounded selectable PDF text extraction into the private-beta scope after browser and packaged-sidecar coverage |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.167 → 1.0.168 | Add PDF text extraction to development scope and next-candidate audit |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.68 → 1.197.69 | Add PDF text extraction depth, evidence and updated counts |
| 2026-10-09 | docs/RELEASE-123-TOOLS.md | 1.89.42 → 1.89.43 | Update catalogue and tool-family totals for PDF text extraction |
| 2026-10-09 | docs/TESTING.md | 1.12.232 → 1.12.233 | Add bounded PDF text extraction verification matrix |
| 2026-10-09 | API-CONTRACT.md | 1.74.101 → 1.74.102 | Specify the selectable PDF text extraction endpoint and limits |
| 2026-10-09 | docs/TESTING.md | 1.12.231 → 1.12.232 | Require every tool registry entry to map and dispatch through its UI destination |
| 2026-10-09 | docs/TESTING.md | 1.12.230 → 1.12.231 | Document the WebKit launch preflight before UI matrices |
| 2026-10-09 | docs/PITFALLS.md | P-144 prevention update | Automate fail-fast WebKit startup checks while retaining the host UI blocker |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.67 → 1.197.68 | Clarify last successful UI matrix versus current preflight failure |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.166 → 1.0.167 | Reconcile current 29-tool scope and WebKit preflight evidence |
| 2026-10-09 | docs/PITFALLS.md | New P-144 | Record the Playwright WebKit startup abort, failed forced reinstall and unexecuted UI matrix |
| 2026-10-09 | docs/PITFALLS.md | P-142 status update | Record bundled RapidOCR as the primary OCR path and keep the failing macOS 27 Vision fallback explicitly open |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.66 → 1.197.67 | Record offline RapidOCR, green source/package OCR checks, current 1,111-test baseline, beta artifact limits and blocked WebKit UI runner |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.165 → 1.0.166 | Record packaged OCR success, full test baseline, unsigned/unnotarized beta artifacts and the WebKit launch failure |
| 2026-10-09 | docs/PITFALLS.md | New P-143; P-022/P-060 status update | Record invalid HDR+ RAW conversion and the verified LibRaw benchmark plus real HEIC fixtures |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.65 → 1.197.66 | Record 42 HEIC-scanner test passes and 95/95 real burst-frame recall with zero cross-scene merges |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.164 → 1.0.165 | Record current real HEIC/HEIF and 15-burst benchmark evidence while retaining outstanding release gaps |
| 2026-10-09 | docs/PITFALLS.md | P-142 status update | Record the legacy and modern Vision runtime failures confirmed on this host |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.64 → 1.197.65 | Replace stale green-suite claims with current 1,102/4/5 test result and selectable-statement acceptance evidence |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.163 → 1.0.164 | Record current supplied-PDF pass and all four Vision OCR integration failures |
| 2026-10-09 | docs/PITFALLS.md | New P-142 | Record the Vision helper deployment-target mismatch and regression checks |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.63 → 1.197.64 | Record current Vision OCR, WebKit and DMG mount blockers plus the source deployment-target fix |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.162 → 1.0.163 | Record current statement OCR failures, helper macOS 14 targeting fix, and blocked package/browser acceptance |
| 2026-10-09 | docs/PITFALLS.md | New P-141 | Record missing native Fn key-code mapping and exhaustive stable-ID regression |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.62 → 1.197.63 | Record Fn key-code mapping coverage and current verification boundary |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.161 → 1.0.162 | Record Fn mapping fix, native tests and rebuilt Apple Silicon test installer |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.61 → 1.197.62 | Record the Export-first result action hierarchy and latest calculator evidence |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.160 → 1.0.161 | Record Export-first result toolbar and build-17 Apple Silicon installer evidence |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.159 → 1.0.160 | Record freelance-rate correction and build-16 Apple Silicon installer evidence |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.60 → 1.197.61 | Record freelance-rate expense input, response reconciliation, saved-input and assumption-disclosure fix |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.59 → 1.197.60 | Record latest complete development WebKit and Rust verification results |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.158 → 1.0.159 | Record the fresh full development UI and native Rust checks plus failed native bridge startup |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.157 → 1.0.158 | Record the pointer-up fallback, full private-beta UI/backend verification and build-15 Mac installer evidence |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.58 → 1.197.59 | Record the expanded 116-check private-beta UI matrix and latest test gate |
| 2026-10-09 | docs/TESTING.md | 1.12.229 → 1.12.230 | Clarify beta PDF navigation coverage and record current matrix evidence |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.156 → 1.0.157 | Record 29-tool beta matrix, supplied statement acceptance and revision 14 installer |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.57 → 1.197.58 | Record PDF merge/grouped split in beta scope and retain installed acceptance gates |
| 2026-10-09 | docs/TESTING.md | 1.12.228 → 1.12.229 | Add beta PDF merge/grouped split route, archive and source-preservation acceptance |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.155 → 1.0.156 | Promote tested PDF merge/grouped split and define the 29-tool beta scope |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.56 → 1.197.57 | Record real supplied-statement UI/API extraction and CSV/XLS/XLSX export verification |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.154 → 1.0.155 | Record supplied-statement real beta flow and export/source-preservation acceptance |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.55 → 1.197.56 | Record the clean full desktop/compact private-beta UI matrix |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.153 → 1.0.154 | Replace incomplete beta-run note with 112-pass matrix evidence |
| 2026-10-09 | docs/TESTING.md | 1.12.227 → 1.12.228 | Align beta verification guidance with held updater, license and support scope |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.54 → 1.197.55 | Record PDF protection beta scope and current packaged verification limits |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.152 → 1.0.153 | Record PDF protection beta promotion, DMG hash and incomplete broad beta UI matrix |
| 2026-10-09 | docs/TESTING.md | 1.12.226 → 1.12.227 | Document PDF protect/unlock end-to-end beta acceptance |
| 2026-10-09 | API-CONTRACT.md | 1.74.100 → 1.74.101 | Correct PDF password bounds to the enforced normalized UTF-8 limit |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.52 → 1.197.53 | Record the full supplied-statement desktop/compact WebKit run and precise remaining gates |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.151 → 1.0.152 | Record the 14/14 statement UI result and the corrected test-locator regression |
| 2026-10-09 | API-CONTRACT.md | 1.74.99 → 1.74.100 | Specify strict optional statement source-column mapping contract |
| 2026-10-09 | docs/TESTING.md | 1.12.225 → 1.12.226 | Add statement mapping validation, recomputation, and desktop/compact UI release checks |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.51 → 1.197.52 | Record manual statement mapping evidence and current test results |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.150 → 1.0.151 | Record mapping regression coverage and revision 12 installer fingerprint |
| 2026-10-09 | API-CONTRACT.md | 1.74.98 → 1.74.99 | Reject stale release manifests, nonstandard HTTPS ports and oversized version components |
| 2026-10-09 | docs/TESTING.md | 1.12.224 → 1.12.225 | Add updater stale-feed, custom-port and oversized-version cases |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.50 → 1.197.51 | Record 1,101-test run and revision 11 Mac beta installer |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.149 → 1.0.150 | Record revision 11 installer, checksum and smoke results |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.147 → 1.0.148 | Record revision 10 private-beta DMG build, mounted smoke and checksum |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.48 → 1.197.49 | Record refreshed update-check installer and remaining live-manifest/installed-app gates |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.146 → 1.0.147 | Record full 184-case desktop/compact WebKit pass after update-check corrections |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.47 → 1.197.48 | Refresh full development WebKit matrix totals and update-check caveats |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.145 → 1.0.146 | Record truthful update-check behavior, packaged-CSP action fix and live-manifest release gate |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.46 → 1.197.47 | Record update manifest validation and title-bar action coverage; keep live feed unverified |
| 2026-10-09 | docs/TESTING.md | 1.12.223 → 1.12.224 | Specify updater version, manifest trust, failure and packaged-CSP interaction cases |
| 2026-10-09 | API-CONTRACT.md | 1.74.97 → 1.74.98 | Define truthful release-manifest status and fail-closed update responses |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.144 → 1.0.145 | Record native dictation shortcut validation, test results and rebuilt revision 9 Mac DMG |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.45 → 1.197.46 | Document custom-shortcut key validation and revision 9 private-beta installer verification |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.143 → 1.0.144 | Record real-statement responsive layout assertions and the focused 12-case rerun |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.44 → 1.197.45 | Document supplied-PDF layout assertions at intermediate and narrow widths |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.142 → 1.0.143 | Record complete development UI matrix with supplied statement PDF enabled |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.43 → 1.197.44 | Update full desktop/compact WebKit verification and statement acceptance status |
| 2026-10-09 | API-CONTRACT.md | 1.74.96 → 1.74.97 | Specify optional reply contact, testimonial publication consent, saved_locally state and legacy normalization |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.141 → 1.0.142 | Record truthful support drafts, direct statement acceptance and refreshed private-beta DMG fingerprint |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.42 → 1.197.43 | Correct support status and document the truthful local-draft feedback flow |
| 2026-10-09 | docs/TESTING.md | 1.12.222 → 1.12.223 | Add local draft, consent, legacy-state and failure-preservation release checks |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.140 → 1.0.141 | Record truthful crash-report copy flow, full desktop/compact browser matrix and refreshed Mac test installer revision 7 |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.41 → 1.197.42 | Record crash-report privacy/error handling and current WebKit/installer verification |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.139 → 1.0.140 | Record passing 172-case full desktop/compact WebKit matrix and refreshed release status |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.40 → 1.197.41 | Record passing full WebKit matrix and correct passphrase-format regression |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.138 → 1.0.139 | Record the revised bookmark privacy wording and refreshed DMG revision 6 fingerprint |
| 2026-10-09 | docs/TESTING.md | 1.12.221 → 1.12.222 | Clarify that saved Markdown may itself contain transcript text while no separate transcript field is stored |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.39 → 1.197.40 | Clarify saved-note transcript privacy semantics and updated Mac candidate evidence |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.38 → 1.197.39 | Record current full-test outcomes, focused meeting-notes rerun and refreshed Mac installer evidence |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.137 → 1.0.138 | Record the rebuilt bookmark-enabled Mac test DMG and current UI-matrix status |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.136 → 1.0.137 | Record local meeting-note bookmarks and the Mac installer rebuild required after this source change |
| 2026-10-09 | docs/TESTING.md | 1.12.220 → 1.12.221 | Require meeting-note bookmark privacy, persistence, duplicate-save, hostile-Markdown and exact-download coverage |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.37 → 1.197.38 | Record meeting-note local save/reopen/download coverage; retain D1 for heuristic semantic accuracy |
| 2026-10-09 | docs/TESTING.md | 1.12.219 → 1.12.220 | Add real-API meeting-notes edit, exact Markdown download and stale-result invalidation checks |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.36 → 1.197.37 | Record editable/downloadable meeting-note output and desktop/compact real-API coverage |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.135 → 1.0.136 | Record meeting-notes workflow regression and rebuilt Apple Silicon test DMG evidence |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.134 → 1.0.135 | Record real supplied-statement acceptance, truthful license screen coverage and refreshed development DMG evidence |
| 2026-10-09 | docs/TESTING.md | 1.12.218 → 1.12.219 | Add compiled native modifier-state regression and installed-Mac press/release acceptance steps |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.35 → 1.197.36 | Record physical modifier-key state tracking, native regression checks and latest suite counts |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.133 → 1.0.134 | Record dictation shortcut release-order fix and refreshed full-profile development DMG fingerprint |
| 2026-10-09 | docs/PITFALLS.md | New P-131 | Record aggregate left/right modifier state bug and native regression prevention |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.34 → 1.197.35 | Refresh the verified desktop/compact WebKit suite count to 164 passing with four profile/opt-in skips |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.33 → 1.197.34 | Record full-suite results, successful desktop/compact statement visuals and mounted beta smoke with the CSV/XLS/XLSX format set |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.132 → 1.0.133 | Record statement and generic-table legacy XLS export coverage, search wording fix and refreshed local Mac beta verification |
| 2026-10-09 | API-CONTRACT.md | 1.74.95 → 1.74.96 | Add the bounded BIFF8 XLS statement and PDF table export routes |
| 2026-10-09 | docs/TESTING.md | 1.12.217 → 1.12.218 | Require real XLS signature, formula-safety and download checks in PDF and statement flows |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.32 → 1.197.33 | Record the legacy XLS workbench export path and its current verification limits |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.131 → 1.0.132 | Update PDF table release evidence for CSV, XLS and XLSX output |
| 2026-10-08 | docs/TESTING.md | 1.12.216 → 1.12.217 | Document the profile-pinned macOS beta DMG smoke command and optional supplied-statement acceptance input |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.31 → 1.197.32 | Record mounted-DMG sidecar acceptance of the supplied statement’s generic PDF-table date-row handling |
| 2026-10-08 | docs/RELEASE-123-TOOLS.md | 1.89.41 → 1.89.42 | Record real supplied-statement API acceptance for transaction extraction, reconciliation, CSV/XLSX export and distinct-date PDF table rows; installed visual acceptance remains open |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.30 → 1.197.31 | Record comma/group-subject Meeting Notes edge coverage, refreshed Python suite count, and latest beta DMG verification |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.29 → 1.197.30 | Refresh Python suite count and record the rebuilt sidecar regression verification |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.28 → 1.197.29 | Record Meeting Notes recovery of an explicit new-subject commitment after a negated clause; engine, HTTP and packaged-sidecar regressions pass |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.27 → 1.197.28 | Record current Node/Python/UI/native/sidecar results and successful cached Parakeet and Qwen3 CoreML runtime acceptance |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.130 → 1.0.131 | Promote known-password PDF unlock to beta with other PDF operations denied |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.26 → 1.197.27 | Record PDF unlock's scoped beta acceptance and remaining installed review |
| 2026-10-08 | docs/TESTING.md | 1.12.215 → 1.12.216 | Require beta PDF unlock success and deny unpromoted PDF operations |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.129 → 1.0.130 | Promote supported bank-statement extraction into the 25-tool beta after supplied-PDF acceptance |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.25 → 1.197.26 | Update beta scope to include the supported statement exporter |
| 2026-10-08 | docs/TESTING.md | 1.12.214 → 1.12.215 | Define real statement extraction, CSV/XLSX export and beta route checks |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.128 → 1.0.129 | Record private statement CSV/XLSX semantic acceptance and its installed-Mac boundary |
| 2026-10-08 | docs/TESTING.md | 1.12.213 → 1.12.214 | Document opt-in private-PDF acceptance for transaction, reconciliation and workbook values |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.127 → 1.0.128 | Promote the tested percentages workbench into the 24-tool beta scope |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.24 → 1.197.25 | Record Everyday Percentages beta coverage and remaining installed acceptance |
| 2026-10-08 | docs/TESTING.md | 1.12.212 → 1.12.213 | Update release-scope counts and require percentage operations in beta verification |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.126 → 1.0.127 | Record fail-closed beta routing and the refreshed Mac test candidate |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.23 → 1.197.24 | Record the release-profile navigation hardening evidence |
| 2026-10-08 | docs/TESTING.md | 1.12.211 → 1.12.212 | Require desktop/compact denial checks when release-scope discovery fails |
| 2026-10-08 | docs/PITFALLS.md | P-130 | Record release-profile loading/failure state conflation |
| 2026-10-08 | API-CONTRACT.md | 1.74.94 → 1.74.95 | Document bounded legacy XLS support and first-sheet behavior |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.125 → 1.0.126 | Record actual statement PDF column/reconciliation acceptance and refreshed private-beta Mac installer |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.22 → 1.197.23 | Record bounded legacy XLS support and its remaining first-sheet limitation |
| 2026-10-08 | docs/TESTING.md | 1.12.210 → 1.12.211 | Add legacy XLS bounds, malformed input and packaged verification requirements |
| 2026-10-08 | docs/PITFALLS.md | P-129 | Record missing legacy XLS reader dependency and required conversion coverage |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.124 → 1.0.125 | Record native screenshot clipboard integration and updated Mac test DMG evidence |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.21 → 1.197.22 | Document the bounded Tauri-native screenshot clipboard bridge and remaining manual acceptance |
| 2026-10-08 | docs/TESTING.md | 1.12.209 → 1.12.210 | Require least-privilege native clipboard tests and resource cleanup for screenshot editing |
| 2026-10-08 | docs/PITFALLS.md | P-128 | Record browser-only clipboard permissions gap in packaged macOS WebView |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.20 → 1.197.21 | Update Meeting Notes benchmark count and document the expanded negative-directive coverage |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.123 → 1.0.124 | Record negative-directive classification regression and updated Meeting Notes evidence |
| 2026-10-08 | docs/PITFALLS.md | P-127 | Record negative “let’s not” action-classification bug and test prevention |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.122 → 1.0.123 | Record full-suite verification and refreshed Mac test DMG after dictation monitor fix |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.121 → 1.0.122 | Record dictation monitor startup guard and remaining physical Mac acceptance |
| 2026-10-08 | docs/PITFALLS.md | P-126 | Record partial native dictation monitor failure and regression prevention |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.114 → 1.0.115 | Record mounted-DMG compression pixel comparison using supplied statement |
| 2026-10-08 | docs/TESTING.md | 1.12.208 → 1.12.209 | Document optional real-PDF compression and extraction acceptance command |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.16 → 1.197.17 | Record packaged three-preset pixel fidelity and retained release gates |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.113 → 1.0.114 | Record PDF compression structure and three-preset rendered fidelity evidence |
| 2026-10-08 | docs/TESTING.md | 1.12.207 → 1.12.208 | Require form/widget, outline and metadata preservation in PDF compression |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.15 → 1.197.16 | Document PDF compression structural fidelity tests and open release gates |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.112 → 1.0.113 | Record desktop/compact unit-converter boundary coverage |
| 2026-10-08 | docs/TESTING.md | 1.12.206 → 1.12.207 | Require all-category bit/byte and temperature-boundary WebKit checks |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.14 → 1.197.15 | Record comprehensive unit-converter UI coverage and retain native acceptance gate |
| 2026-10-08 | docs/PITFALLS.md | P-023–P-025 status update | Close stale unit-converter gaps with API and desktop/compact evidence |
| 2026-10-08 | API-CONTRACT.md | 1.74.93 → 1.74.94 | Specify the cumulative decoded-pixel work limit for image-resize batches |
| 2026-10-08 | docs/TESTING.md | 1.12.205 → 1.12.206 | Require exact and over-limit cumulative image-resize batch work tests |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.13 → 1.197.14 | Record image-resize batch work bounds and correct statement verification status |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.111 → 1.0.112 | Add cumulative image-resize work cap to candidate depth evidence |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.110 → 1.0.111 | Record verified four-row statement reconciliation and current tested Mac candidate |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.12 → 1.197.13 | Document opening-balance-based statement reconciliation and refreshed verification |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.109 → 1.0.110 | Record 22-case meeting-notes contrast benchmark and remaining accuracy/installed-Mac gates |
| 2026-10-08 | docs/TESTING.md | 1.12.204 → 1.12.205 | Add curated meeting-notes benchmark and focused/package verification commands |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.11 → 1.197.12 | Record meeting-notes false-positive coverage and benchmark limits |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.108 → 1.0.109 | Record validated media-brand detection and desktop/compact file-type coverage; retain native picker gate
| 2026-10-08 | docs/TESTING.md | 1.12.203 → 1.12.204 | Specify ISO base-media header, brand, malformed-input and alias test coverage
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.10 → 1.197.11 | Record ISO media-brand detection and expanded file-type UI evidence
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.9 → 1.197.10 | Record row-level narration/value/CSV checks for the supplied statement and its real-API UI acceptance
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.8 → 1.197.9 | Add family 51, correct catalogue totals and record selectable-table plus supplied-statement evidence
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.107 → 1.0.108 | Correct current tool audit counts and record desktop/compact PDF table and statement acceptance evidence
| 2026-10-08 | docs/RELEASE-123-TOOLS.md | 1.89.40 → 1.89.41 | Refresh source counts and supplied-statement status
| 2026-10-08 | docs/TESTING.md | 1.12.202 → 1.12.203 | Add real-API PDF table CSV/XLSX UI and source-preservation gates
| 2026-10-08 | docs/hld/pdf-table-extractor.md | 1.0.0 | Add bounded selectable-table extraction product scope
| 2026-10-08 | docs/lld/pdf-table-extractor.md | 1.0.0 | Add engine, API and UI boundaries for PDF table extraction
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.105 → 1.0.106 | Record direct replay of the supplied statement PDF, current full test results and accurate image-converter depth evidence |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.6 → 1.197.7 | Refresh full test and WebKit totals and reference the direct statement PDF/CSV verification |
| 2026-10-08 | API-CONTRACT.md | 1.74.91 → 1.74.92 | Specify base64url challenge and activation ID lengths required by the license service |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.104 → 1.0.105 | Record native Mac activation integration, licensing blockers and verified Apple Silicon package |
| 2026-10-08 | docs/hld/licensing-service.md | 1.1.0 → 1.2.0 | Record native macOS Keychain activation client and identify deployment/key distribution/paid-operation gates |
| 2026-10-08 | docs/LICENSING-PLAN.md | 1.2.4 → 1.2.5 | Update licensing implementation status and remaining release blockers |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.103 → 1.0.104 | Record desktop/compact network-interface privacy flow coverage and retain installed acceptance gate |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.5 → 1.197.6 | Record real desktop/compact WebKit coverage for network diagnostics and interface address privacy |
| 2026-10-08 | docs/TESTING.md | 1.12.201 → 1.12.202 | Add real-API WebKit checks for on-demand DNS/ping and hidden-then-revealed interface addresses |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.102 → 1.0.103 | Record supplied statement API/browser evidence while keeping native installed acceptance open |
| 2026-10-08 | docs/TESTING.md | 1.12.200 → 1.12.201 | Specify seven-column value-date, wrapped-narration and CSV regression coverage for statement PDFs |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.101 → 1.0.102 | Record current passing Mac package smoke and direct statement API/export evidence; retain installed UI gate |
| 2026-10-08 | docs/TESTING.md | 1.12.199 → 1.12.200 | Keep mounted-sidecar CSV smoke aligned with the typed folder-comparison export schema |
| 2026-10-08 | API-CONTRACT.md | 1.74.90 → 1.74.91 | Add bounded explicit directory import and file-plus-folder comparison/CSV response fields |
| 2026-10-08 | docs/TESTING.md | 1.12.198 → 1.12.199 | Require empty-directory import, structure comparison, changed empty-state, directory-only and CSV coverage |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.4 → 1.197.5 | Record empty-folder-aware comparison and current desktop/compact validation |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.100 → 1.0.101 | Record directory comparison coverage while retaining native Mac picker acceptance gate |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.3 → 1.197.4 | Record folder-compare scope disclosure, desktop/compact regression and rebuilt Mac package |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.99 → 1.0.100 | Record the refreshed Mac DMG with folder-compare scope disclosure |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.2 → 1.197.3 | Record folder-compare file-only scope disclosure and its UI regression |
| 2026-10-08 | docs/TESTING.md | 1.12.197 → 1.12.198 | Require explicit empty-directory and filesystem-metadata limitation coverage |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.1 → 1.197.2 | Record passing full development and private-beta WebKit matrices |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.98 → 1.0.99 | Record current development/private-beta UI matrix results and retain native acceptance gate |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.0 → 1.197.1 | Record desktop/compact real-API delete/reorder PDF page-management coverage |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.97 → 1.0.98 | Update PDF page-management browser evidence and retain installed acceptance gaps |
| 2026-10-08 | docs/TESTING.md | 1.12.196 → 1.12.197 | Require desktop/compact PDF page deletion and reordering workbench verification |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.99 → 1.197.0 | Record custom JPEG/DPI/quality real-API UI coverage for PDF pages-to-images |
| 2026-10-08 | docs/TESTING.md | 1.12.195 → 1.12.196 | Require desktop/compact PDF image settings, decoded dimensions, archive and invalid-input checks |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.96 → 1.0.97 | Record desktop/compact PDF-to-image JPEG settings and ZIP evidence |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.98 → 1.196.99 | Record complete current Node/Python regression results after repairing stale XSS test extraction |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.95 → 1.0.96 | Record full source test results and the repaired renderer test helper |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.97 → 1.196.98 | Record focused statement regression results and the rebuilt arm64 Mac candidate |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.94 → 1.0.95 | Record the rebuilt Mac candidate and mounted-DMG smoke for statement extraction fix |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.96 → 1.196.97 | Record direct local validation of the supplied statement PDF and retain other bank-layout gates |
| 2026-10-08 | docs/TESTING.md | 1.12.194 → 1.12.195 | Require inferred cell-bound coverage and privacy-safe customer PDF verification for vector statements |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.93 → 1.0.94 | Record statement sample row/CSV validation while retaining broader layout and installed acceptance gates |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.92 → 1.0.93 | Record screenshot editor browser/API evidence and retain native clipboard release gate |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.95 → 1.196.96 | Add the screenshot editor real-API desktop/compact test to its evidence record |
| 2026-10-08 | docs/TESTING.md | 1.12.193 → 1.12.194 | Require clipboard paste-event, crop/blur/mask, undo/redo and decoded screenshot-export UI verification |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.94 → 1.196.95 | Record desktop/compact screenshot-editor real-API coverage and retain native clipboard acceptance gate |
| 2026-10-08 | docs/TESTING.md | 1.12.192 → 1.12.193 | Require bounded statement-correction serialization, reconciliation and desktop/compact export checks |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.93 → 1.196.94 | Record statement corrections, linked excluded-row recovery and real-API validation |
| 2026-10-08 | API-CONTRACT.md | 1.74.89 → 1.74.90 | Define strict percent-of, percentage-change and discount local API contracts |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.92 → 1.196.93 | Add the Everyday Percentages operation families and refresh catalogue/depth counts |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.91 → 1.0.92 | Record Everyday Percentages as a development tool outside the 23-tool beta profile |
| 2026-10-08 | docs/RELEASE-123-TOOLS.md | 1.89.39 → 1.89.40 | Refresh tool/family counts and document calculator addition |
| 2026-10-08 | docs/TESTING.md | 1.12.191 → 1.12.192 | Require percentage engine/API boundaries and browser save/reopen/export verification |
| 2026-10-08 | docs/hld/everyday-percentages.md | 1.0.0 | Define local calculator boundaries, assumptions, release profile and quality evidence |
| 2026-10-08 | docs/lld/everyday-percentages.md | 1.0.0 | Specify percentage DTOs, Decimal calculations, UI snapshot identity and tests |
| 2026-10-08 | API-CONTRACT.md | 1.74.83 → 1.74.84 | Record client validation and full schedule display/export for loan EMI |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.82 → 1.196.83 | Record loan schedule UI, client checks and complete saved exports |
| 2026-10-08 | docs/TESTING.md | 1.12.182 → 1.12.183 | Add loan schedule UI, compact pagination, invalid response and full export checks |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.81 → 1.0.82 | Update loan EMI evidence and retain installed-Mac acceptance gate |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.81 → 1.196.82 | Record BMP/JPEG alpha compositing behavior and contextual transparency warning |
| 2026-10-08 | docs/TESTING.md | 1.12.181 → 1.12.182 | Require alpha-mode compositing and target-aware warning coverage |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.80 → 1.0.81 | Record image alpha fix, full suites and rebuilt Apple Silicon DMG evidence; retain installed acceptance gate |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.80 → 1.196.81 | Record pixel-identical vector/text/raster rendering evidence for lossless PDF compression |
| 2026-10-08 | docs/TESTING.md | 1.12.180 → 1.12.181 | Require PDF compression visual-fidelity regression under pinned PDFium |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.79 → 1.0.80 | Record PDF compression visual-fidelity evidence and remaining release gates |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.78 → 1.196.79 | Correct stale statement locale control status and document real-API UI evidence |
| 2026-10-08 | docs/TESTING.md | 1.12.178 → 1.12.179 | Require a real-API visible-selector statement locale/date flow |
| 2026-10-08 | docs/PITFALLS.md | P-066 status | Record visible selectors and real-API ambiguity regression evidence |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.77 → 1.0.78 | Record Quick Search recovery, full test results and rebuilt Apple Silicon DMG |
| 2026-10-08 | API-CONTRACT.md | 1.74.81 → 1.74.82 | Define half-up margin/markup rounding and safe overflow responses |
| 2026-10-08 | docs/TESTING.md | 1.12.177 → 1.12.178 | Require in-place Quick Search retry and path-backed WebKit upload fixtures |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.77 → 1.196.78 | Record title-bar Quick Search retry behavior and recovery states |
| 2026-10-08 | docs/PITFALLS.md | P-065, P-115, P-116 | Record Quick Search recovery, calculator rounding and WebKit fixture findings |
| 2026-10-08 | API-CONTRACT.md | 1.74.80 → 1.74.81 | Add bounded XLSX worksheet discovery and selection contract |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.75 → 1.196.76 | Record selected-sheet conversion support and remaining table-fidelity gaps |
| 2026-10-08 | docs/TESTING.md | 1.12.175 → 1.12.176 | Require XLSX worksheet discovery, safe rendering, selection and recovery coverage |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.74 → 1.0.75 | Record one-click gallery entry, keyboard Quick Search coverage and rebuilt Mac installer evidence |
| 2026-10-08 | docs/TESTING.md | 1.12.174 → 1.12.175 | Require keyboard Quick Search and direct gallery-card entry under packaged CSP |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.73 → 1.0.74 | Record restricted-beta WebKit matrix and rebuilt beta DMG sidecar smoke |
| 2026-10-08 | docs/TESTING.md | 1.12.173 → 1.12.174 | Require VAT zero-rate and maximum-rate browser boundary checks |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.72 → 1.0.73 | Record VAT assumption validation, full test gates and refreshed arm64 DMG evidence |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.74 → 1.196.75 | Record VAT assumption disclosure and strict client response checks |
| 2026-10-08 | docs/TESTING.md | 1.12.172 → 1.12.173 | Require VAT assumption disclosure, malformed-response and hostile-value browser coverage |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.71 → 1.0.72 | Record Quick Search startup recovery, full profile matrices, repeat-tested image fixture integrity and refreshed DMG evidence |
| 2026-10-08 | docs/TESTING.md | 1.12.171 → 1.12.172 | Require Quick Search behavior on profile discovery failure and SHA-256 verification of staged image fixtures |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.70 → 1.0.71 | Record beta banner/startup correction and rerun both release-profile matrices |
| 2026-10-08 | docs/TESTING.md | 1.12.170 → 1.12.171 | Require profile-derived beta banner count and scope consistency |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.69 → 1.0.70 | Record full restricted-profile WebKit run and live CSP scope checks |
| 2026-10-08 | docs/TESTING.md | 1.12.169 → 1.12.170 | Require real release-profile endpoints in both CSP navigation profiles |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.68 → 1.0.69 | Record complete 108-check UI run, stale native process evidence and missing signing identities |
| 2026-10-08 | docs/TESTING.md | 1.12.168 → 1.12.169 | Require full app relaunch after package rebuild before native acceptance |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.67 → 1.0.68 | Add real-API PDF metadata-removal candidate evidence |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.73 → 1.196.74 | Record PDF metadata-removal browser acceptance |
| 2026-10-08 | docs/TESTING.md | 1.12.167 → 1.12.168 | Require PDF metadata-removal download, readability and source-preservation UI checks |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.66 → 1.0.67 | Record live-catalogue Quick Search and file-type empty/mismatch browser coverage |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.72 → 1.196.73 | Record empty-file and misleading-extension file-type UI evidence |
| 2026-10-08 | docs/TESTING.md | 1.12.166 → 1.12.167 | Require file-type empty/mismatch selected-file flows at both WebKit sizes |
| 2026-10-08 | docs/TESTING.md | 1.12.165 → 1.12.166 | Exercise title-bar Quick Search with the authenticated live catalogue under packaged CSP |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.71 → 1.196.72 | Record checksum copy/download and clipboard recovery coverage |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.65 → 1.0.66 | Record CSP build sync, checksum actions, and refreshed Mac installer evidence |
| 2026-10-08 | docs/TESTING.md | 1.12.164 → 1.12.165 | Require build-synchronized Tauri script hashes and checksum copy/export validation |
| 2026-10-08 | docs/PITFALLS.md | New P-111 | Prevent inline UI edits from leaving the packaged CSP hash stale |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.70 → 1.196.71 | Record 95/95 HDR+ frame recall across 15 real camera bursts and remaining validation limits |
| 2026-10-08 | docs/RELEASE-123-TOOLS.md | 1.89.37 → 1.89.38 | Update similar-image burst benchmark evidence from 37 to 95 real frames |
| 2026-10-08 | docs/TESTING.md | 1.12.163 → 1.12.164 | Gate similar-image burst recall on a 95-frame, 15-sequence HDR+ corpus |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.64 → 1.0.65 | Record expanded real-camera burst recall while retaining the tool holdback |
| 2026-10-08 | docs/TESTING.md | 1.12.162 → 1.12.163 | Add reproducible cached Parakeet CoreML inference and cache-artifact checks |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.69 → 1.196.70 | Correct FluidAudio v3 cache filename evidence and record real cached inference |
| 2026-10-08 | docs/PITFALLS.md | New P-110 | Record Parakeet encoder filename mismatch and real-runtime regression |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.63 → 1.0.64 | Record Parakeet cache correction and packaged candidate evidence |
| 2026-10-08 | docs/TESTING.md | 1.12.161 → 1.12.162 | Require a least-privilege Tauri event capability and separate package smoke from installed dictation acceptance |
| 2026-10-08 | docs/PITFALLS.md | New P-109 | Record missing native event-listener permission and the outstanding installed Fn verification |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.62 → 1.0.63 | Record the scoped dictation event capability and rebuilt Mac candidate evidence |
| 2026-10-08 | docs/TESTING.md | 1.12.160 → 1.12.161 | Cover cold-load and retained-query title-bar Quick Search races |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.76 → 1.0.77 | Record current private-beta WebKit/API-scope results, real Parakeet runtime pass, stale in-memory app evidence and outstanding source-PDF access gate |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.75 → 1.0.76 | Record XLSX worksheet-selection flow, current full test results, fresh Apple Silicon DMG hash and mounted sidecar checks |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.76 → 1.196.77 | Record XLSX worksheet selector coverage and retain broader Excel fidelity and installed-UI gaps |
| 2026-10-08 | docs/PITFALLS.md | P-114 status | Record engine/API, UI, packaged-sidecar and mounted-DMG verification; keep installed-Mac acceptance open |
| 2026-10-08 | docs/PITFALLS.md | New P-108 | Record Quick Search catalog-load response race and regression paths |
| 2026-10-08 | API-CONTRACT.md | 1.74.79 → 1.74.80 | Document common tentative future language excluded from confirmed Meeting Notes actions |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.68 → 1.196.69 | Record tentative-commitment edge coverage while retaining Meeting Notes at D1 |
| 2026-10-08 | docs/TESTING.md | 1.12.159 → 1.12.160 | Require tentative-commitment and positive-control checks through the engine, HTTP and sidecar |
| 2026-10-08 | docs/RELEASE-123-TOOLS.md | 1.89.36 → 1.89.37 | Record tentative-future Meeting Notes regressions without changing release status |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.61 → 1.0.62 | Record full backend/native test gates and the current WebKit regression matrix |
| 2026-10-08 | docs/TESTING.md | 1.12.158 → 1.12.159 | Clarify native-bridge coverage for Quick Search and dictation model setup UI |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.60 → 1.0.61 | Record strict-CSP event delegation, title-bar search regression and fresh Mac installer evidence |
| 2026-10-08 | docs/TESTING.md | 1.12.157 → 1.12.158 | Add title-bar Quick Search routing to the strict packaged-CSP browser regression gate |
| 2026-10-08 | docs/TESTING.md | 1.12.156 → 1.12.157 | Require installed Tauri CSP interaction checks because browser-only tests miss blocked inline UI handlers |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.59 → 1.0.60 | Record the CSP-blocked navigation finding, successful matching-CSP regression, and refreshed local app |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.58 → 1.0.59 | Record local app launch evidence and distinguish the invalid bundle signature from distributable signing |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.57 → 1.0.58 | Record CORS metadata fix, refreshed development/beta matrices and mounted Apple Silicon test DMG evidence |
| 2026-10-08 | API-CONTRACT.md | 1.74.78 → 1.74.79 | Document the CORS-exposed OfficeKit metadata headers read by the webview |
| 2026-10-08 | docs/TESTING.md | 1.12.155 → 1.12.156 | Require real-browser visibility checks for custom PDF and image response headers |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.56 → 1.0.57 | Record current full and private-beta WebKit evidence and retain the real-statement and installed-Mac release gates |
| 2026-10-08 | API-CONTRACT.md | 1.74.77 → 1.74.78 | Specify sanitized duplicate-scan error fields and incomplete status semantics |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.55 → 1.0.56 | Record duplicate finder partial-result UI coverage and remaining installed/performance gates |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.67 → 1.196.68 | Record validated partial duplicate-scan presentation |
| 2026-10-08 | docs/TESTING.md | 1.12.154 → 1.12.155 | Require safe partial-scan UI and duplicate response validation |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.54 → 1.0.55 | Record nested storage, partial-scan, safe-error and singular-count browser checks |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.66 → 1.196.67 | Update storage analyzer evidence and retain installed/performance limitations |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.53 → 1.0.54 | Record nested storage totals in desktop/compact browser coverage and retain partial/native gates |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.65 → 1.196.66 | Record real browser coverage for recursive storage totals |
| 2026-10-08 | docs/TESTING.md | 1.12.153 → 1.12.154 | Require desktop/compact nested storage totals and partial-scan UI checks |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.52 → 1.0.53 | Record completed real desktop/compact file split/join workflow and remaining installed-Mac gate |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.51 → 1.0.52 | Record partial reconciliation for skipped rows, fresh test matrices and rebuilt DMG |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.64 → 1.196.65 | Document excluded-row reconciliation semantics and real-API UI coverage |
| 2026-10-08 | docs/TESTING.md | 1.12.152 → 1.12.153 | Require skipped-row partial state and desktop/compact export regression |
| 2026-10-08 | API-CONTRACT.md | 1.74.76 → 1.74.77 | Count excluded ambiguous rows as unverified in reconciliation state |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.50 → 1.0.51 | Record mounted Apple Silicon DMG verification and ad-hoc signature blocker |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.49 → 1.0.50 | Add current native Rust test results and retain direct PDF/installed acceptance gates |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.48 → 1.0.49 | Record fresh full-suite, WebKit and bundled sidecar statement/filesystem verification |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.47 → 1.0.48 | Correct full UI matrix totals to 88/92 development and 64/92 private-beta |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.46 → 1.0.47 | Record real grouped PDF split flow and 92-case WebKit matrices |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.63 → 1.196.64 | Record ZIP download and independent output-PDF checks for grouped split |
| 2026-10-08 | docs/TESTING.md | 1.12.151 → 1.12.152 | Require desktop/compact grouped-split API, overlap and artifact checks |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.45 → 1.0.46 | Record live CSV converter browser flow and 90-case WebKit matrices |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.62 → 1.196.63 | Record real-API data conversion coverage and retain XLSX fidelity gate |
| 2026-10-08 | docs/TESTING.md | 1.12.150 → 1.12.151 | Require CSV selection, JSON output fidelity and malformed-input browser checks |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.45 → 1.0.46 | Record CSV-to-JSON real-API browser evidence and 90-case UI matrices |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.62 → 1.196.63 | Record live data-converter coverage and retain XLSX fidelity gate |
| 2026-10-08 | docs/TESTING.md | 1.12.150 → 1.12.151 | Require desktop/compact CSV conversion, output fidelity and malformed-input browser checks |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.44 → 1.0.45 | Record real statement-to-CSV WebKit flow and refreshed 86-case matrices |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.61 → 1.196.62 | Record real-API statement extraction, reconciliation and CSV browser evidence |
| 2026-10-08 | docs/TESTING.md | 1.12.149 → 1.12.150 | Require synthetic statement UI-to-CSV verification plus retained direct-source gate |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.43 → 1.0.44 | Record live PDF merge flow and updated 84-case desktop/private-beta matrices |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.60 → 1.196.61 | Record real-API PDF merge coverage alongside protect/unlock flows |
| 2026-10-08 | docs/TESTING.md | 1.12.148 → 1.12.149 | Require a downloaded and reopened real-API PDF merge in desktop/compact WebKit |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.42 → 1.0.43 | Record real-API PDF protect/unlock browser acceptance on desktop and compact layouts |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.59 → 1.196.60 | Replace stubbed PDF protect/unlock browser evidence with live local API proof |
| 2026-10-08 | docs/TESTING.md | 1.12.147 → 1.12.148 | Require real API WebKit verification of encrypted/decrypted PDF outputs |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.41 → 1.0.42 | Record rebuilt private-beta DMG and mounted sidecar/package smoke; retain signing blocker |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.40 → 1.0.41 | Record full-suite and 82-case UI matrix evidence for statement-row exclusion |
| 2026-10-08 | API-CONTRACT.md | 1.74.75 → 1.74.76 | Document excluded multi-date statement rows and raw-row indexing |
| 2026-10-08 | docs/TESTING.md | 1.12.146 → 1.12.147 | Require multi-date row exclusion, review disclosure and export regression coverage |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.58 → 1.196.59 | Record fail-closed handling of ambiguous statement date cells |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.39 → 1.0.40 | Record statement row-safety correction and retain direct-source validation gate |
| 2026-10-08 | docs/TESTING.md | 1.12.145 → 1.12.146 | Require deterministic loopback DNS integration for MX/TXT API behavior |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.57 → 1.196.58 | Record loopback MX/TXT engine and HTTP coverage while retaining packaged gap |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.38 → 1.0.39 | Record loopback DNS coverage, current full-suite metrics and remaining package validation |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.37 → 1.0.38 | Record verified full-suite pass/skip counts and current UI matrices |
| 2026-10-08 | docs/TESTING.md | 1.12.144 → 1.12.145 | Require desktop/compact browser proof of EXIF APP1 removal and source preservation |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.56 → 1.196.57 | Record end-to-end EXIF cleanup and read-back evidence |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.36 → 1.0.37 | Record 80-case browser matrices and EXIF cleanup verification |
| 2026-10-08 | docs/TESTING.md | 1.12.143 → 1.12.144 | Require real desktop/compact batch image resize coverage and ZIP cleanup |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.55 → 1.196.56 | Record WebKit batch image resize API and download evidence |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.35 → 1.0.36 | Record 78-case browser matrices and image-resize verification |
| 2026-10-08 | docs/TESTING.md | 1.12.142 → 1.12.143 | Require real local API image-conversion browser checks, including malformed-image recovery |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.54 → 1.196.55 | Record real WebKit image conversion and malformed-input flow coverage |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.34 → 1.0.35 | Record fresh full-suite results and image-conversion browser coverage |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.31 → 1.0.32 | Enable seven selected-file workspace tools in beta and update the readiness split |
| 2026-10-08 | API-CONTRACT.md | 1.74.74 → 1.74.75 | Document the test-only exact UI origin gate for the local API |
| 2026-10-08 | docs/TESTING.md | 1.12.140 → 1.12.141 | Record regression requirements for isolated browser-origin CORS configuration |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.52 → 1.196.53 | Record private-beta workspace browser, API and package evidence |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.32 → 1.0.33 | Record seven workspace tools, current test totals and refreshed local beta DMG |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.53 → 1.196.54 | Record the real local API WebKit flow for similar-image review |
| 2026-10-08 | docs/TESTING.md | 1.12.141 → 1.12.142 | Require real-photo browser-to-sidecar coverage for similar-image workflow |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.33 → 1.0.34 | Refresh development/beta UI totals and held-back similar-image scope evidence |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.51 → 1.196.52 | Record expanded beta test scope without marking workspace tools production-ready |
| 2026-10-08 | docs/TESTING.md | 1.12.139 → 1.12.140 | Require beta UI and API tests for selected-file workspace workflows |
| 2026-10-08 | API-CONTRACT.md | 1.74.73 → 1.74.74 | Document beta workspace scope and single-segment route patterns |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.30 → 1.0.31 | Record statement-results layout and currency-neutral amount corrections; retain the direct-PDF and distribution gates |
| 2026-10-08 | docs/TESTING.md | 1.12.138 → 1.12.139 | Specify long-value preview/disclosure, currency-neutral display, containment and full-export checks |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.50 → 1.196.51 | Record statement-results layout and currency-neutral formatting without changing D2 depth |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.29 → 1.0.30 | Record phrase-only non-final decision regression and final beta artifact checksum |
| 2026-10-08 | docs/TESTING.md | 1.12.137 → 1.12.138 | Include no-final-decision wording that omits a completion verb |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.28 → 1.0.29 | Record Meeting Notes regression, latest private-beta DMG checksum, and fresh full/browser/native test evidence |
| 2026-10-08 | API-CONTRACT.md | 1.74.72 → 1.74.73 | Specify exclusions for explicitly unresolved Meeting Notes decisions |
| 2026-10-08 | docs/TESTING.md | 1.12.136 → 1.12.137 | Require pending/non-final decision engine, API and package regressions |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.49 → 1.196.50 | Record Meeting Notes unresolved-decision guard and evidence scope |
| 2026-10-08 | docs/RELEASE-123-TOOLS.md | 1.89.35 → 1.89.36 | Record pending-decision regression while retaining D1 release status |
| 2026-10-08 | docs/PITFALLS.md | New P-106 | Record the unresolved-decision classification failure and guard |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.27 → 1.0.28 | Record final targeted and full-suite counts while keeping customer-PDF verification explicitly open |
| 2026-10-08 | API-CONTRACT.md | 1.74.71 → 1.74.72 | Tighten weak-vector OCR recovery criteria to repeated dates and missing numeric values |
| 2026-10-08 | docs/TESTING.md | 1.12.135 → 1.12.136 | Add independent repeated-date and missing-financial-value OCR cases |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.48 → 1.196.49 | Refine statement weak-vector quality threshold documentation |
| 2026-10-08 | docs/RELEASE-123-TOOLS.md | 1.89.34 → 1.89.35 | Refine weak-vector statement recovery acceptance description |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.26 → 1.0.27 | Record actual Vision fixture and rebuilt beta DMG checksum |
| 2026-10-08 | docs/PITFALLS.md | Completed P-105 | Record parser, multipart, Vision and packaged sidecar evidence |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.25 → 1.0.26 | Record weak-vector statement OCR recovery and refreshed private-beta DMG smoke/checksum |
| 2026-10-08 | API-CONTRACT.md | 1.74.70 → 1.74.71 | Specify quality-based weak-vector statement OCR recovery and preservation behavior |
| 2026-10-08 | docs/TESTING.md | 1.12.134 → 1.12.135 | Add weak-vector PDF recovery, candidate-order and OCR-failure regressions |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.47 → 1.196.48 | Record weak-vector table OCR recovery and direct-customer verification gap |
| 2026-10-08 | docs/RELEASE-123-TOOLS.md | 1.89.33 → 1.89.34 | Record weak-vector bank-statement fallback implementation and evidence |
| 2026-10-08 | docs/PITFALLS.md | New P-105 | Record statement OCR routing gap for weak non-empty vector tables |
| 2026-10-08 | docs/PITFALLS.md | New P-103 | Record strict YAML file-import regression and prevention |
| 2026-10-08 | API-CONTRACT.md | 1.74.68 → 1.74.69 | Specify YAML file-import strictness and resource limits |
| 2026-10-08 | docs/TESTING.md | 1.12.132 → 1.12.133 | Add strict YAML file-import engine/API/package checks |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.45 → 1.196.46 | Record bounded YAML converter behavior and remaining fidelity gaps |
| 2026-10-08 | docs/RELEASE-123-TOOLS.md | 1.89.31 → 1.89.32 | Record generic YAML converter hardening and evidence |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.21 → 1.0.22 | Record strict JSON converter verification and refreshed development DMG artifact/checks |
| 2026-10-08 | docs/PITFALLS.md | New P-102 | Record strict bounded JSON import regression and prevention |
| 2026-10-08 | API-CONTRACT.md | 1.74.67 → 1.74.68 | Specify strict bounded JSON input for tabular conversion |
| 2026-10-08 | docs/TESTING.md | 1.12.131 → 1.12.132 | Add duplicate/non-finite/deep JSON conversion engine and HTTP gates |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.44 → 1.196.45 | Record strict bounded JSON import behavior and remaining converter gaps |
| 2026-10-08 | docs/RELEASE-123-TOOLS.md | 1.89.30 → 1.89.31 | Record strict JSON conversion regression evidence and unresolved type-fidelity work |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.20 → 1.0.21 | Record real-vector statement parser fix, full tests and rebuilt DMG smoke while retaining source-PDF verification gap |
| 2026-10-08 | docs/PITFALLS.md | Updated P-093 | Preserve vector-PDF narration spilled into amount columns and prevent “Accounts” from matching summary “count” checks |
| 2026-10-08 | docs/TESTING.md | 1.12.130 → 1.12.131 | Add vector statement PDF coverage for wrapped narration spilling into nominal amount columns |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.43 → 1.196.44 | Record narration-complete vector-PDF fallback and preserve direct-customer verification gate |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.19 → 1.0.20 | Record current full/private-beta WebKit, packaged sidecar and DMG smoke evidence |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.42 → 1.196.43 | Correct stale calculator-export claims and align catalogue/persistence coverage with current tested behavior |
| 2026-10-08 | API-CONTRACT.md | 1.74.66 → 1.74.67 | Document compound-growth frequency, bounds, visible assumptions/history and saved export context |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.18 → 1.0.19 | Record compound-growth desktop/compact interaction evidence and remaining installed-Mac gate |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.41 → 1.196.42 | Record compound-growth frequency control, assumptions/history and real API browser coverage |
| 2026-10-08 | docs/TESTING.md | 1.12.129 → 1.12.130 | Add compound-growth browser bounds, history, save and export acceptance checks |
| 2026-10-08 | docs/PITFALLS.md | Completed P-101 | Prevent compound-growth UI from hiding calculation frequency and returned assumptions/history |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.17 → 1.0.18 | Record refreshed development DMG smoke, checksum and remaining signing gate |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.40 → 1.196.41 | Record updated arm64 app size and mounted DMG sidecar verification |
| 2026-10-08 | docs/TESTING.md | 1.12.128 → 1.12.129 | Add statement-copy scope gate for supported layouts and reconciliation claims |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.16 → 1.0.17 | Record WebKit verification after statement scope-copy correction |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.39 → 1.196.40 | Record accurate statement scope copy and customer-PDF verification limitation |
| 2026-10-08 | docs/TESTING.md | 1.12.127 → 1.12.128 | Add Meeting Notes regressions for interrogative and negated need-to statements |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.38 → 1.196.39 | Record Meeting Notes false-positive correction and packaged smoke |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.15 → 1.0.16 | Record latest full suite and sidecar evidence while keeping source-PDF/package gates open |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.9 → 1.0.10 | Record PDF password truncation correction, 127-byte API/UI boundary checks and pending packaged smoke |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.37 → 1.196.38 | Document normalized PDF password bounds and UI/API test coverage |
| 2026-10-08 | docs/PITFALLS.md | Completed P-099 | Prevent PDF password aliasing through excessive/truncated input; verify raw and NFKC byte boundaries |
| 2026-10-08 | docs/PITFALLS.md | Completed P-017 | Close unbounded PDF password input gap with engine/API policy tests |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.8 → 1.0.9 | Record 20-point wrapped bank-statement description regression and retain direct customer-PDF verification gate |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.36 → 1.196.37 | Document bounded statement continuation leading and 20-point generated-PDF coverage |
| 2026-10-08 | docs/PITFALLS.md | Updated P-093 | Add the missed 20-point wrapped-description case and keep real customer sample verification open |
| 2026-10-07 | docs/FIRST-MAC-RELEASE.md | 1.0.7 → 1.0.8 | Record PDF-protection browser states, Unicode policy and independent pikepdf read-back while retaining installed-Mac gate |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.35 → 1.196.36 | Record password confirmation, code-point validation and remaining native acceptance gap |
| 2026-10-07 | docs/PITFALLS.md | Completed P-098 | Require PDF password confirmation and align client limits with Unicode API policy |
| 2026-10-07 | docs/PITFALLS.md | Completed P-097 | Ensure PDF quick access actually navigates to the workbench |
| 2026-10-07 | docs/FIRST-MAC-RELEASE.md | 1.0.7 | Record fresh Apple Silicon beta build, mounted DMG smoke and unsigned distribution gap |
| 2026-10-07 | docs/FIRST-MAC-RELEASE.md | 1.0.6 | Record restricted-beta browser and packaged-sidecar validation with held filesystem scope |
| 2026-10-07 | docs/FIRST-MAC-RELEASE.md | 1.0.5 | Record refreshed full-suite, UI and collision-safe sidecar smoke evidence; retain unverified Mac and statement gates |
| 2026-10-07 | docs/PITFALLS.md | Completed P-096 | Record sidecar smoke port collision and reserve/pass a free loopback port |
| 2026-10-07 | docs/PITFALLS.md | Completed P-095 | Record invalid folder comparison defaults and require end-to-end sibling comparison/CSV coverage |
| 2026-10-07 | docs/PITFALLS.md | Completed P-094 | Record the disabled rename-artifact action and require a full WebKit workspace flow regression |
| 2026-10-05 | DESIGN_SYSTEM.md | 1.0.0 | Initial proposed OfficeKit design system, theme tokens, result/export/privacy and review rules |
| 2026-10-05 | design/COMPONENT_STRUCTURE.md | 1.0.0 | Initial proposed UI ownership, typed boundaries and implementation slices |
| 2026-10-05 | docs/PRODUCT-PLAN.md | 1.0.0 | Consolidated complete OfficeKit product, architecture and implementation roadmap |
| 2026-10-05 | docs/TESTING.md | 1.0.0 | Engine, UX, persistence, exports, privacy and desktop-release testing guidelines |
| 2026-10-05 | DESIGN_SYSTEM.md | 1.1.0 | Define category-grouped tool gallery and equivalent List view |
| 2026-10-05 | docs/PRODUCT-PLAN.md | 1.1.0 | Add Mac-style gallery/list, grouped-by-category baseline |
| 2026-10-05 | docs/TESTING.md | 1.1.0 | Add catalogue view, grouping, filter and destination checks |
| 2026-10-05 | design/COMPONENT_STRUCTURE.md | 1.1.0 | Define shared ToolCatalogue ownership for Gallery/List views |
| 2026-10-05 | docs/LICENSING-PLAN.md | 1.0.0 | Free/Paid build separation, device-bound activation and offline/device-transfer policy |
| 2026-10-05 | docs/PRODUCT-PLAN.md | 1.2.0 | Incorporate proposed editions and licensing architecture |
| 2026-10-05 | docs/TESTING.md | 1.2.0 | Add edition packaging, entitlement authorization and device recovery gates |
| 2026-10-05 | docs/COMMUNICATIONS-PLAN.md | 1.0.0 | User-facing release history, update alerts and dismissible notices |
| 2026-10-05 | docs/PRODUCT-PLAN.md | 1.3.0 | Incorporate updates, What's new and quick communications |
| 2026-10-05 | docs/TESTING.md | 1.3.0 | Add updater/release notes/banner behavior and privacy checks |
| 2026-10-05 | docs/LICENSING-PLAN.md | 1.1.0 | Require per-key single/multi-device policy and activation semantics |
| 2026-10-05 | docs/PRODUCT-PLAN.md | 1.4.0 | Replace fixed device allowance with server-owned per-key limits |
| 2026-10-05 | docs/TESTING.md | 1.4.0 | Add capacity boundaries, concurrent activation and policy-change checks |
| 2026-10-05 | docs/TOOL-GUIDE.md | 1.0.0 | Audit 33 tool families, 24 catalogue entries, API/UI depth and missing work |
| 2026-10-05 | docs/RELEASE-123-TOOLS.md | 1.0.0 | 123-capability depth/test matrix, Markdown/HTML/PPT exports and value workflows |
| 2026-10-06 | API-CONTRACT.md | 1.0.0 | Inventory implemented API routes, DTO limits, runtime gaps and file-workspace boundary |
| 2026-10-06 | API-CONTRACT.md | 1.0.1 | Add the Tauri local API readiness probe contract |
| 2026-10-05 | docs/PRODUCT-PLAN.md | 1.5.0 | Expand release scope and share-ready/AI-chat exports |
| 2026-10-05 | docs/TESTING.md | 1.5.0 | Add capability traceability and Markdown/HTML/PPT/JSON/ZIP output checks |
| 2026-10-05 | DESIGN_SYSTEM.md | 1.2.0 | Define richer local report formats and AI-context preview behavior |
| 2026-10-06 | API-CONTRACT.md | 1.0.2 | Document process-owned file workspaces, ZIP extraction, artifact download and remaining file-tool gaps |
| 2026-10-06 | API-CONTRACT.md | 1.0.3 | Use a resource-noun extraction route for workspace ZIP processing |
| 2026-10-06 | API-CONTRACT.md | 1.0.4 | Document generic client errors and local-only diagnostics |
| 2026-10-06 | API-CONTRACT.md | 1.0.5 | Add workspace-scoped batch rename preview and downloadable artifact routes |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.0.1 | Update rename depth and desktop caveats after adding workspace-scoped rename engine/API |
| 2026-10-06 | docs/TESTING.md | 1.5.1 | Document cross-platform CI, full test command and real sidecar smoke gate |
| 2026-10-06 | API-CONTRACT.md | 1.0.6 | Add workspace-scoped exact duplicate scan with relative paths and bounded entry count |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.0.2 | Record workspace duplicate-report API and revise tool-family wiring counts |
| 2026-10-06 | API-CONTRACT.md | 1.0.7 | Add bounded workspace-only storage summary route with sanitized relative paths |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.0.3 | Record storage-report API and revise workspace tool wiring counts |
| 2026-10-06 | API-CONTRACT.md | 1.0.8 | Require strict workspace request DTOs and reject arbitrary path fields |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.0.1 | Refresh the API wiring audit and link current implementation evidence |
| 2026-10-06 | API-CONTRACT.md | 1.0.9 | Add bounded workspace-scoped perceptual-hash image similarity reports |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.0.4 | Record similar-image scan API, limitations and updated code-level counts |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.0.2 | Refresh family and API wiring counts after similar-image scan addition |
| 2026-10-06 | API-CONTRACT.md | 1.1.0 | Add bounded compound-interest DTOs, typed response and explicit monthly timing assumptions |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.0.5 | Record corrected compound-interest calculation depth and remaining UI/API verification gaps |
| 2026-10-06 | API-CONTRACT.md | 1.2.0 | Add bounded compound-interest and break-even request/response contracts |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.0.6 | Record break-even API depth and refresh backend family counts |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.0.3 | Refresh current API wiring count after break-even route addition |
| 2026-10-06 | API-CONTRACT.md | 1.3.0 | Add bounded loan request and typed complete amortization response contract |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.0.7 | Record full loan schedule engine and pending UI/runtime release gaps |
| 2026-10-06 | API-CONTRACT.md | 1.4.0 | Add bounded, typed VAT request/response with explicit rounding and jurisdiction assumptions |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.0.8 | Record VAT validation/rounding behavior and remaining UI gaps |
| 2026-10-06 | API-CONTRACT.md | 1.5.0 | Add bounded, typed freelance-rate input/output and assumptions |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.0.9 | Record freelance-rate validation and explicit model limitations |
| 2026-10-06 | API-CONTRACT.md | 1.6.0 | Add bounded margin/markup route with explicit undefined-denominator behavior |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.1.0 | Record margin/markup API wiring and revised family counts |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.0.4 | Refresh API wiring count after margin/markup route addition |
| 2026-10-06 | API-CONTRACT.md | 1.7.0 | Document case-folded and Unicode-canonical filename collision checks on workspace imports |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.1.1 | Record Unicode-safe filesystem imports and current verification limits |
| 2026-10-06 | API-CONTRACT.md | 1.8.0 | Bound expression calculator input, AST complexity, exponent size and finite results |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.1.2 | Record expression calculator bounds and remaining UI/runtime gaps |
| 2026-10-06 | API-CONTRACT.md | 1.9.0 | Add typed unit-conversion bounds and validation semantics |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.1.3 | Record unit conversion validation and remaining catalogue gaps |
| 2026-10-06 | API-CONTRACT.md | 1.10.0 | Document identifier validation and scalar-safe SQL export behavior |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.1.4 | Record SQL identifier/value validation and remaining converter gaps |
| 2026-10-06 | API-CONTRACT.md | 1.11.0 | Define bounded 64 MiB inputs for direct document-processing endpoints |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.1.5 | Record upload bounds for statement, converter and PDF tools |
| 2026-10-06 | API-CONTRACT.md | 1.12.0 | Document pre-parser request-body limits and multipart overhead for upload routes |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.1.6 | Refresh verified checks and request-body upload protection status |
| 2026-10-06 | docs/TESTING.md | 1.5.2 | Add request framing, exact-boundary and oversized-upload test requirements |
| 2026-10-06 | API-CONTRACT.md | 1.13.0 | Bound password-generator length and document character-class behavior |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.1.7 | Record password-generation limits and remaining UX gaps |
| 2026-10-06 | docs/TESTING.md | 1.5.3 | Add password-generator boundary, character-class and secret-retention checks |
| 2026-10-06 | API-CONTRACT.md | 1.14.0 | Bound strict hash/HMAC requests and add fixed-width digest response model |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.1.8 | Record bounded hash/HMAC API depth and remaining UI gaps |
| 2026-10-06 | docs/TESTING.md | 1.5.4 | Add hash/HMAC known-vector, UTF-8-boundary and input-safety checks |
| 2026-10-06 | API-CONTRACT.md | 1.15.0 | Bound developer text tools and add strict operations and typed response variants |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.1.9 | Record developer text-tool limits and strict Base64/JWT behavior |
| 2026-10-06 | docs/TESTING.md | 1.5.5 | Add developer text input, Base64/JWT and malformed-JSON checks |
| 2026-10-06 | API-CONTRACT.md | 1.16.0 | Add workspace-scoped streaming SHA-256/SHA-512 report route |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.2.0 | Add file hashing family and refresh API/tool depth counts |
| 2026-10-06 | docs/TESTING.md | 1.5.6 | Add workspace hash selection, stream-limit and path-safety tests |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.0.5 | Refresh family and API wiring audit counts |
| 2026-10-06 | API-CONTRACT.md | 1.17.0 | Bound support ticket requests, document safe local storage and clarify Tauri sidecar status |
| 2026-10-06 | docs/TESTING.md | 1.5.7 | Add local support queue validation, atomic persistence and concurrency checks |
| 2026-10-06 | docs/TESTING.md | 1.5.8 | Add burst-photo similarity, lazy-input bounds and real-image fixture release checks |
| 2026-10-06 | API-CONTRACT.md | 1.18.0 | Add bounded workspace-scoped file type detection with typed results |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.3.0 | Record file type detector and refresh capability wiring counts |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.0.6 | Refresh current tool-family and API wiring audit counts |
| 2026-10-06 | docs/TESTING.md | 1.5.9 | Add signature-detection and workspace file-type route verification cases |
| 2026-10-06 | API-CONTRACT.md | 1.19.0 | Require per-launch bearer authentication for packaged sidecar API requests |
| 2026-10-06 | docs/TESTING.md | 1.6.0 | Add packaged API token authentication and failure-mode verification cases |
| 2026-10-06 | docs/TESTING.md | 1.6.1 | Add hostile-value regression checks for statement, calculator and search rendering |
| 2026-10-06 | API-CONTRACT.md | 1.20.0 | Add bounded typed straight-line depreciation endpoint |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.4.0 | Record cent-balanced depreciation API and refresh capability wiring counts |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.0.7 | Refresh capability API wiring audit count |
| 2026-10-06 | docs/TESTING.md | 1.6.2 | Add depreciation schedule rounding, validation and route test requirements |
| 2026-10-06 | API-CONTRACT.md | 1.21.0 | Add explicit-unit simple-interest calculator endpoint |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.5.0 | Record simple-interest API and refresh tool-family depth counts |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.0.8 | Refresh tool-family and API wiring counts |
| 2026-10-06 | docs/TESTING.md | 1.6.3 | Add simple-interest reference, unit and rounding edge cases |
| 2026-10-06 | API-CONTRACT.md | 1.22.0 | Document bounded relevance-ranked tool search and keyword aliases |
| 2026-10-06 | docs/TESTING.md | 1.6.4 | Add search synonym, ranking, normalization and boundary test cases |
| 2026-10-06 | DESIGN_SYSTEM.md | 1.3.0 | Specify the Toolkit app icon and small-size treatment; document reproducible cross-platform asset generation |
| 2026-10-06 | API-CONTRACT.md | 1.23.0 | Document translation-tolerant perceptual fingerprints for the bounded similar-image report |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.6.0 | Record burst-image alignment matching and separate synthetic recall from open real-photo validation |
| 2026-10-06 | docs/TESTING.md | 1.6.5 | Add crop, two-pixel framing, compression-noise and unrelated-scene similarity checks |
| 2026-10-06 | docs/TESTING.md | 1.6.6 | Define persistence, privacy, immutability, recency-cap and recovery tests for local records |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.7.0 | Record tested local favorites/history storage foundation and its remaining UI/artifact gaps |
| 2026-10-06 | API-CONTRACT.md | 1.24.0 | Add bounded typed workspace folder-comparison endpoint |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.8.0 | Record folder-comparison backend depth and refresh family/API totals |
| 2026-10-06 | docs/TESTING.md | 1.6.7 | Add folder comparison content, path, bounds, no-mutation and HTTP cases |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.0.9 | Record partial F04 engine/API delivery without counting it release-ready |
| 2026-10-06 | DESIGN_SYSTEM.md | 1.4.0 | Ensure native builds regenerate the Toolkit icon and document macOS icon-cache refresh |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.9.0 | Refresh the audit with the folder-comparison and app-icon regression checks |
| 2026-10-06 | docs/TESTING.md | 1.6.8 | Add direct-reference equivalence coverage for the optimized image DCT |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.10.0 | Record the equivalent separable DCT and current local audit results |
| 2026-10-06 | docs/TESTING.md | 1.6.9 | Require isolated support API state, cross-platform protected-path tests and decoded file outputs |
| 2026-10-06 | docs/TESTING.md | 1.7.0 | Require exact version and bounded payload checks in native sidecar readiness |
| 2026-10-06 | API-CONTRACT.md | 1.25.0 | Specify version-matched, size-bounded native API health validation |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.11.0 | Record native readiness bounds while preserving the unverified packaging caveat |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.12.0 | Update local test count and document version-contract checks |
| 2026-10-06 | API-CONTRACT.md | 1.26.0 | Specify sanitized 422 conversion-input errors and generic unexpected 500 responses |
| 2026-10-06 | API-CONTRACT.md | 1.27.0 | Bound image conversion quality at both HTTP and engine boundaries |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.13.0 | Refresh verification count and document conversion error/quality boundary work |
| 2026-10-06 | API-CONTRACT.md | 1.28.0 | Specify sanitized RFC 6266 filenames for uploaded-file downloads |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.14.0 | Record safe attachment naming and refresh local test counts |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.15.0 | Record bounded filename normalization and refresh local test counts |
| 2026-10-06 | API-CONTRACT.md | 1.29.0 | Specify generic PDF processing errors while preserving safe password errors |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.16.0 | Record PDF diagnostic sanitization and current local test count |
| 2026-10-06 | API-CONTRACT.md | 1.30.0 | Specify empty-password rejection and PDF password size limits |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.17.0 | Record PDF password bounds and refresh local test count |
| 2026-10-06 | API-CONTRACT.md | 1.31.0 | Specify typed statement export rows, request/row limits and spreadsheet formula-safe text |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.18.0 | Record hardened statement exports and refresh local test count |
| 2026-10-06 | API-CONTRACT.md | 1.32.0 | Record preservation of zero debit, credit and balance values in spreadsheet exports |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.19.0 | Record dependency-independent CSV output tests and zero-value preservation |
| 2026-10-06 | API-CONTRACT.md | 1.33.0 | Document cross-platform archive path collision and Windows filename validation |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.20.0 | Record safer ZIP extraction paths and refresh local test count |
| 2026-10-06 | DESIGN_SYSTEM.md | 1.5.0 | Make one icon generator refresh shared, macOS and Windows assets and document parity verification |
| 2026-10-06 | API-CONTRACT.md | 1.34.0 | Document crop-aware burst grouping and bounded tolerance for perceptual image fingerprints |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.21.0 | Record crop-aware burst matching and shared cross-platform app-icon parity checks |
| 2026-10-06 | API-CONTRACT.md | 1.35.0 | Add typed area, volume, speed and fixed-duration time conversion categories and absolute-zero validation |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.22.0 | Record added conversion categories, US/Imperial volume semantics and absolute-zero validation |
| 2026-10-06 | API-CONTRACT.md | 1.36.0 | Preserve SI/IEC bit-versus-byte case semantics in the digital-storage converter |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.23.0 | Record correct bit/byte conversion and expanded storage-unit verification |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.24.0 | Record no-follow batch-rename copying, the remaining app-icon design issue and refreshed local test counts |
| 2026-10-06 | DESIGN_SYSTEM.md | 1.6.0 | Adopt the selected geometric OfficeKit monogram across generated platform app icons |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.25.0 | Record the selected OfficeKit monogram and current verification limits |
| 2026-10-06 | API-CONTRACT.md | 1.37.0 | Specify no-follow descriptor and stability checks for ZIP extraction sources |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.26.0 | Record safe ZIP source opening and refresh the test count |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.27.0 | Record the missing Tauri CLI and sidecar dependencies blocking packaged verification |
| 2026-10-06 | API-CONTRACT.md | 1.38.0 | Specify no-overwrite workspace upload commits and precise rollback ownership |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.28.0 | Record atomic workspace upload commits and sidecar build status |
| 2026-10-06 | DESIGN_SYSTEM.md | 1.7.0 | Use the pinned Tauri icon encoder for valid small-size ICNS renditions and document decoded verification |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.29.0 | Record Apple-decoded small-size ICNS parity and refresh the Node test count |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.30.0 | Record strict ordered PDF page-range parsing and refresh the Python test count |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.1.0 | Define ordered page-range output and duplicate/overlap rejection for PDF split/extract |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.31.0 | Record the screenshot-editor mock and refresh the Node verification count |
| 2026-10-06 | API-CONTRACT.md | 1.39.0 | Distinguish unavailable and failed statement image OCR from empty recognition results |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.32.0 | Record actionable OCR errors and refresh the Python test count |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.33.0 | Distinguish missing Tesseract binary and refresh the Python test count |
| 2026-10-06 | API-CONTRACT.md | 1.40.0 | Specify comma CSV and tab TSV parsing with strict UTF-8, BOM and safe malformed-input behavior |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.34.0 | Record delimiter-aware statement imports and refresh the Python test count |
| 2026-10-06 | API-CONTRACT.md | 1.41.0 | Add typed unit-conversion categories and precise case-sensitive engineering units |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.35.0 | Record six unit-converter dimensions and refresh the Python test count |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.36.0 | Record wrong-case SI prefix rejection and refresh the Python test count |
| 2026-10-06 | API-CONTRACT.md | 1.42.0 | Define bounded typed HEX/RGB/HSL/HSV color conversion and formatting rules |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.37.0 | Record color-converter depth and refresh implementation counts |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.38.0 | Record color-converter validation evidence and refreshed Python test count |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.39.0 | Record CI dependency installation fix and refreshed Node test count |
| 2026-10-06 | API-CONTRACT.md | 1.43.0 | Add typed URI-component encode/decode operations to the developer-tools contract |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.40.0 | Record URL-tool API coverage, implementation depth and refreshed Python test count |
| 2026-10-06 | API-CONTRACT.md | 1.44.0 | Add the typed bounded Markdown export endpoint for immutable result snapshots |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.41.0 | Record result Markdown exports and refreshed test evidence |
| 2026-10-06 | API-CONTRACT.md | 1.45.0 | Add the 8 MiB request-body limit to the result Markdown export contract |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.42.0 | Record the Markdown export boundary, missing formats and refreshed test count |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.2.0 | Record current Markdown result-export implementation and remaining shared formats |
| 2026-10-06 | API-CONTRACT.md | 1.46.0 | Consolidate Markdown/HTML/JSON snapshots under one bounded typed result-export route |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.43.0 | Record standalone HTML and versioned JSON result exports with refreshed tests |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.3.0 | Record supported result-export formats and remaining release outputs |
| 2026-10-06 | API-CONTRACT.md | 1.47.0 | Add formula-safe typed CSV result export to the bounded snapshot route |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.44.0 | Record long-form CSV export coverage, spreadsheet-injection handling and remaining integration gaps |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.4.0 | Update shared export acceptance for typed CSV result snapshots and optional metadata attribution |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.45.0 | Record ZIP extraction success-response validation and refresh the Node regression count |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.46.0 | Record atomic private license-state writes and refresh the standard-library test count |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.47.0 | Refresh verification count after adding a failed-flush license persistence test |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.48.0 | Record deterministic burst-image grouping under handheld camera rotation |
| 2026-10-06 | API-CONTRACT.md | 1.48.0 | Add bounded checksum-verified workspace file split/join resources |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.5.0 | Record the implemented F08 split/join API and its remaining UI/release gates |
| 2026-10-06 | docs/TESTING.md | 1.7.1 | Add split/join manifests, binary round trips, archive tampering and race checks |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.49.0 | Record F08 API exposure, implementation depth and refreshed test counts |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.50.0 | Record the split part-limit cleanup regression and current Python test count |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.51.0 | Record canonical artifact path validation, symlink-output regression and refreshed Python test count |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.52.0 | Record zero-principal loan schedule behavior and regression evidence |
| 2026-10-06 | docs/TESTING.md | 1.7.2 | Add image scan symlink and source-mutation edge checks |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.53.0 | Record no-follow image reads and refresh standard-library test count |
| 2026-10-06 | docs/PITFALLS.md | Completed P-034 | Reject protected-path ancestor scopes in storage analysis |
| 2026-10-06 | docs/TESTING.md | 1.7.3 | Add protected storage ancestor-scope boundary |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.54.0 | Record protected-path ancestor rejection and refreshed test count |
| 2026-10-06 | docs/REVIEW-REMEDIATION-PLAN.md | 1.1.0 | Add prompt sidecar startup-failure detection to R01 verification |
| 2026-10-06 | docs/TESTING.md | 1.7.4 | Require prompt failure when the sidecar exits before readiness |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.55.0 | Record sidecar startup exit detection |
| 2026-10-06 | docs/PITFALLS.md | Active P-035 | Prevent rename artifact publication from replacing an existing directory |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.56.0 | Record exclusive rename artifact publication and regression coverage |
| 2026-10-06 | docs/TESTING.md | 1.7.5 | Add batch-rename artifact collision and failed-publish cleanup cases |
| 2026-10-06 | API-CONTRACT.md | 1.49.0 | Cap every workspace JSON POST body before DTO parsing |
| 2026-10-06 | docs/PITFALLS.md | Active P-036 | Record missing body caps on workspace JSON routes and recurrence of P-004 |
| 2026-10-06 | docs/TESTING.md | 1.7.6 | Require exact workspace JSON body-cap route coverage |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.57.0 | Record complete workspace body-limit mapping and regression tests |
| 2026-10-06 | API-CONTRACT.md | 1.50.0 | Apply a default 8 MiB pre-parse cap to all API paths with explicit upload overrides |
| 2026-10-06 | docs/PITFALLS.md | Active P-036 follow-up | Add a fail-closed default body cap for future API routes |
| 2026-10-06 | docs/TESTING.md | 1.7.7 | Verify default API body caps, upload overrides and non-API behavior |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.58.0 | Record the default API body cap and upload-specific overrides |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.59.0 | Refresh the passing standard-library test count after body-cap coverage |
| 2026-10-06 | API-CONTRACT.md | 1.51.0 | Specify strict Content-Length grammar and early rejection of invalid request framing |
| 2026-10-06 | docs/PITFALLS.md | Active P-037 | Reject parseable but malformed Content-Length values |
| 2026-10-06 | docs/TESTING.md | 1.7.8 | Add Content-Length digit-grammar and leading-zero cases |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.60.0 | Record strict request-framing validation and current test evidence |
| 2026-10-06 | API-CONTRACT.md | 1.52.0 | Document formula-safe generic CSV/TSV/XLSX conversion outputs |
| 2026-10-06 | docs/TESTING.md | 1.7.9 | Add formula-injection and numeric-type checks for generic spreadsheet conversions |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.61.0 | Record generic spreadsheet export sanitization, current test count and local dependency limits |
| 2026-10-06 | docs/PITFALLS.md | Active P-038 | Record and prevent formula injection in generic spreadsheet conversions |
| 2026-10-06 | API-CONTRACT.md | 1.53.0 | Document the exact trusted origin for the loopback Python launcher |
| 2026-10-06 | docs/TESTING.md | 1.8.0 | Add local-launcher origin allow/deny coverage |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.62.0 | Record the local Python launcher origin fix and updated test count |
| 2026-10-06 | docs/PITFALLS.md | Active P-039 | Record API origin mismatch blocking the supported local launcher |
| 2026-10-06 | API-CONTRACT.md | 1.54.0 | Add bounded local screenshot crop, blur and opaque-mask resource |
| 2026-10-06 | docs/TESTING.md | 1.8.1 | Add screenshot editor bounds, metadata, redaction and HTTP checks |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.63.0 | Inventory screenshot editor as a requested extra and update family/API/test counts |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.6.0 | Record the screenshot editor as an additional requested tool outside the 123-item inventory |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.64.0 | Record screenshot editor aggregate pixel-work/JSON bounds and updated test count |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.65.0 | Correct screenshot-editor skip count and state that UI mock approval is pending |
| 2026-10-06 | docs/PITFALLS.md | Completed P-040 | Add cumulative image-edit processing bound and regression test |
| 2026-10-06 | API-CONTRACT.md | 1.55.0 | Specify cumulative screenshot edit-work cap and safe malformed-operation behavior |
| 2026-10-06 | docs/TESTING.md | 1.8.2 | Add UTF-8 byte-bound and EXIF-normalization screenshot cases |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.66.0 | Record screenshot editor UTF-8/EXIF tests and current skip count |
| 2026-10-06 | docs/PITFALLS.md | Active P-041 | Record ignored PDF compression presets and concealed output expansion |
| 2026-10-06 | docs/TESTING.md | 1.8.3 | Add PDF preset, size-ratio, fidelity and local-installer evidence guidance |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.67.0 | Record lossless PDF compression policy and correct local installer evidence |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.6.1 | Record user-confirmed installer build and observed installed-app gaps |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.68.0 | Refresh standard-library test count after PDF compression policy coverage |
| 2026-10-06 | docs/TESTING.md | 1.8.4 | Add atomic packaged-UI synchronization build and failure-path checks |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.69.0 | Correct installed-runtime evidence and record packaged-UI synchronization |
| 2026-10-06 | API-CONTRACT.md | 1.56.0 | Add bounded merge, ordered split, compression and metadata PDF routes |
| 2026-10-06 | docs/TESTING.md | 1.8.5 | Add multipart PDF route, fidelity, limits and safe-error cases |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.70.0 | Record four API-wired PDF families and update verified test totals |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.6.2 | Update API-wired family count after advanced PDF route work |
| 2026-10-06 | docs/PITFALLS.md | Active P-042 | Record missing HTTP routes for advertised PDF engines and add route regressions |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.71.0 | Update depth counts and test totals after PDF API contract and mock coverage |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.6.3 | Refresh release audit version after API-family count correction |
| 2026-10-06 | docs/TESTING.md | 1.8.6 | Include encrypted-source PDF error behavior in route verification |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.72.0 | Record Favorites/History screen wiring and expanded UI regression totals |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.73.0 | Refresh verified test count and accurately describe advanced PDF search results |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.74.0 | Record approved filesystem utility UI flow, preserve generated downloads across tool switches, and update regression count |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.6.4 | Refresh UI wiring audit and document workspace file-tool flow |
| 2026-10-06 | API-CONTRACT.md | 1.57.0 | Add bounded PDFium page-to-PNG/JPEG ZIP export route |
| 2026-10-06 | docs/TESTING.md | 1.8.7 | Add PDF rendering dimensions, output budgets, format and handle cleanup cases |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.75.0 | Record PDF page image export and refresh test evidence |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.6.5 | Record bounded PDF-to-image API and pending screen/runtime gates |
| 2026-10-06 | API-CONTRACT.md | 1.59.0 | Document the PDF-to-image search ID, CSV/XLSX aliases and directional query behavior |
| 2026-10-06 | docs/TESTING.md | 1.8.8 | Add PDF workbench API, search, output-ratio, page-count, password and UI-flow test cases |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.76.0 | Record approved PDF workbench routes, update UI/catalog counts and remaining verification gaps |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.6.6 | Refresh catalogue/UI counts and record PDF workbench integration scope |
| 2026-10-06 | API-CONTRACT.md | 1.60.0 | Specify safe generic 422 validation errors that do not echo rejected request values |
| 2026-10-06 | docs/TESTING.md | 1.8.9 | Document root import-path setup and raw non-finite JSON API regression cases |
| 2026-10-06 | docs/TESTING.md | 1.9.0 | Specify macOS one-folder sidecar packaging, lazy tool imports and functional sidecar smoke checks |
| 2026-10-06 | docs/TESTING.md | 1.9.1 | Document smoke-checking the packaged macOS app executable |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.77.0 | Refresh local dependency-backed test counts and packaged macOS sidecar evidence |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.6.7 | Record macOS packaged sidecar smoke verification while retaining the 0/123 release gate |
| 2026-10-06 | docs/TESTING.md | 1.9.2 | Require macOS package smoke coverage for PDF protect/unlock and PDF-to-PNG rendering |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.78.0 | Record packaged macOS PDF protection, unlock and rendering smoke evidence |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.6.8 | Record packaged macOS PDF tool smoke evidence without changing tool completion count |
| 2026-10-06 | API-CONTRACT.md | 1.61.0 | Align similar-image group response cardinality with the 500-file request bound |
| 2026-10-06 | docs/TESTING.md | 1.9.3 | Specify JPEG burst decoder, EXIF, corrupt-input and workspace HTTP integration cases |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.79.0 | Record similar-image API response correction and real-decoder test coverage |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.80.0 | Record all-green API and image test suite after similar-image response fix |
| 2026-10-06 | docs/TESTING.md | 1.9.4 | Require packaged sidecar verification for selected-workspace similar-image flow |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.81.0 | Record packaged image scan verification and full regression counts |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.6.9 | Record macOS bundled similar-image route smoke evidence; tool gate remains open |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.82.0 | Record the rebuilt macOS bundle passing similar-image import, scan and cleanup |
| 2026-10-06 | docs/TESTING.md | 1.9.5 | Include malformed-PNG per-file handling in packaged similar-image smoke coverage |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.83.0 | Record packaged malformed-PNG recovery evidence for similar-image scanning |
| 2026-10-06 | docs/TESTING.md | 1.9.6 | Require packaged filesystem duplicate, storage and rename-download smoke coverage |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.84.0 | Correct PyInstaller availability and record macOS packaged filesystem verification |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.7.0 | Record packaged filesystem API smoke evidence without claiming tool release completion |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.85.0 | Record 86 passing Node tests after packaged filesystem smoke coverage |
| 2026-10-06 | API-CONTRACT.md | 1.62.0 | Add bounded, typed XLSX structured-result attachment format |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.86.0 | Record literal-safe result workbooks and keep API/UI depth separate |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.8.0 | Track XLSX result export as API-only pending UI and broader export formats |
| 2026-10-06 | docs/TESTING.md | 1.9.7 | Add structured-result XLSX fidelity and resource-bound checks |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.87.0 | Record macOS bundled-sidecar XLSX export evidence and refreshed full-suite count |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.9.0 | Record bundled-sidecar typed XLSX result-export smoke coverage |
| 2026-10-06 | docs/TESTING.md | 1.9.8 | Require packaged-sidecar verification for XLSX result attachments |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.88.0 | Record the updated Node suite count after XLSX sidecar smoke coverage |
| 2026-10-06 | API-CONTRACT.md | 1.63.0 | Specify spreadsheet-formula and XML-invalid-text handling for result workbooks |
| 2026-10-06 | docs/TESTING.md | 1.9.9 | Cover invalid XML codepoints in result-workbook text |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.89.0 | Record XML-safe workbook serialization and final suite counts |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.90.0 | Record fresh macOS app bundle and DMG smoke for XLSX results |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.10.0 | Record XLSX smoke from the rebuilt OfficeKit.app executable |
| 2026-10-06 | docs/TESTING.md | 1.10.0 | Record direct verification of the current app bundle executable |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.91.0 | Correct search, favorites/history, export and macOS Tauri evidence against current source and bundle smoke |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.92.0 | Record the Node test count after adding saved-result flow mock verification |
| 2026-10-06 | API-CONTRACT.md | 1.64.0 | Add bounded paginated PowerPoint result-export attachment contract |
| 2026-10-06 | docs/TESTING.md | 1.10.1 | Require independent PPTX fidelity and packaged-sidecar verification |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.93.0 | Record API-only PowerPoint result export and its test boundaries |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.94.0 | Record PPTX result-export tests and updated suite totals |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.95.0 | Record API-only PPTX export packaged smoke and final test counts |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.96.0 | Correct complete-suite Python test total after PPTX edge-case coverage |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.97.0 | Clarify the result UI gap for XLSX and PPTX exports |
| 2026-10-06 | API-CONTRACT.md | 1.65.0 | Add bounded searchable PDF result-export attachments with Unicode shaping/search support |
| 2026-10-06 | docs/TESTING.md | 1.10.2 | Require PDF extraction, pagination, font and packaged-sidecar verification |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.98.0 | Record API-only searchable PDF result exports and current UI gap |
| 2026-10-06 | docs/TESTING.md | 1.10.3 | Record fresh macOS bundled-sidecar PDF and Tamil-font smoke evidence |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.99.0 | Record the macOS app bundle build and packaged PDF attachment smoke |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.11.0 | Record API-only searchable PDF result export and macOS package evidence while retaining the release gate |
| 2026-10-06 | API-CONTRACT.md | 1.66.0 | Define safe PDF statement parse failures, repeated-header handling and scanned-PDF OCR limits |
| 2026-10-06 | docs/TESTING.md | 1.10.4 | Add valid multi-page and malformed statement-PDF extraction acceptance cases |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.100.0 | Correct result-export depth and API-only PDF coverage after packaged smoke verification |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.101.0 | Record statement-PDF malformed-input and repeated-header fixes with OCR limit |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.12.0 | Record statement-PDF HTTP coverage without changing the release-verified tool count |
| 2026-10-06 | docs/TESTING.md | 1.10.5 | Require and record packaged statement-PDF extraction smoke coverage |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.102.0 | Record macOS packaged ruled-statement PDF extraction and reconciliation smoke |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.13.0 | Record packaged statement-PDF extraction evidence while retaining release gates |
| 2026-10-06 | API-CONTRACT.md | 1.67.0 | Specify standalone debit markers for combined statement amounts |
| 2026-10-06 | docs/TESTING.md | 1.10.6 | Add amount-marker and merchant-label sign regressions for statements |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.103.0 | Record precise debit-marker parsing and statement sign regression |
| 2026-10-06 | docs/RELEASE-123-TOOLS.md | 1.14.0 | Record amount-sign regression without changing release verification totals |
| 2026-10-06 | docs/TESTING.md | 1.10.7 | Add image metadata-strip palette, animation and EXIF orientation regressions |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.104.0 | Record image metadata-strip engine fix without changing verified tool totals |
| 2026-10-06 | API-CONTRACT.md | 1.68.0 | Add bounded local image EXIF-removal attachment endpoint |
| 2026-10-06 | docs/TESTING.md | 1.10.8 | Add image metadata engine/API and packaged macOS smoke guidance |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.105.0 | Record API-only image metadata-removal route without changing release totals |
| 2026-10-06 | docs/TESTING.md | 1.10.9 | Require animated-WebP and multipage-TIFF metadata coverage |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.106.0 | Record animated-WebP and multipage-TIFF engine tests without changing release totals |
| 2026-10-06 | API-CONTRACT.md | 1.69.0 | Specify decoded-pixel preservation for animated WebP metadata removal |
| 2026-10-06 | API-CONTRACT.md | 1.70.0 | Bound decoded image work, frame count and metadata-export response bytes |
| 2026-10-06 | docs/TESTING.md | 1.11.0 | Add metadata-removal decompression and output-size limits to release verification |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.107.0 | Record metadata-removal resource bounds without changing release-ready totals |
| 2026-10-06 | API-CONTRACT.md | 1.71.0 | Define frame-preserving image conversion and decoded-work limits |
| 2026-10-06 | docs/TESTING.md | 1.11.1 | Add animated and multipage image-conversion preservation checks |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.108.0 | Record frame-safe image conversion without changing release-ready totals |
| 2026-10-06 | API-CONTRACT.md | 1.72.0 | Specify EXIF orientation normalization and image profile/resolution preservation |
| 2026-10-06 | docs/TESTING.md | 1.11.2 | Add image-conversion orientation, ICC profile and DPI cases |
| 2026-10-06 | docs/TOOL-GUIDE.md | 1.109.0 | Record image-conversion orientation and profile handling without changing release totals |
| 2026-10-07 | API-CONTRACT.md | 1.73.0 | Add bounded formula-safe CSV export for folder comparisons |
| 2026-10-07 | docs/TESTING.md | 1.11.3 | Verify folder-comparison CSV response and injection boundaries |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.110.0 | Record folder-comparison CSV export while retaining the missing UI gate |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.15.0 | Record folder-comparison CSV API capability and open UI gap |
| 2026-10-07 | docs/TESTING.md | 1.11.4 | Select a Python interpreter with pytest for reliable npm test runs |
| 2026-10-07 | docs/hld/licensing-service.md | 1.0.0 | Design the first-party FakeCloud-tested and AWS CDK licensing service |
| 2026-10-07 | API-CONTRACT.md | 1.74.0 | Specify the target device-bound hosted license activation API |
| 2026-10-07 | docs/LICENSING-PLAN.md | 1.2.0 | Replace managed-provider evaluation with the requested first-party AWS design |
| 2026-10-07 | docs/TESTING.md | 1.11.5 | Define FakeCloud, KMS signature and device-slot licensing gates |
| 2026-10-07 | docs/hld/licensing-service.md | 1.0.1 | Require device-key proof and one-use activation challenges |
| 2026-10-07 | API-CONTRACT.md | 1.74.1 | Add tenant-bound activation challenges and proof-of-possession |
| 2026-10-07 | docs/LICENSING-PLAN.md | 1.2.1 | Record challenge-based device proof for activation |
| 2026-10-07 | docs/TESTING.md | 1.11.6 | Require challenge replay, expiry and proof-of-possession cases |
| 2026-10-07 | docs/hld/licensing-service.md | 1.0.2 | Specify opaque high-entropy keys and safe challenge-consuming retries |
| 2026-10-07 | API-CONTRACT.md | 1.74.2 | Define strict OfficeKit license-key credential format |
| 2026-10-07 | docs/hld/licensing-service.md | 1.0.3 | Specify challenge signature and nonce encodings |
| 2026-10-07 | API-CONTRACT.md | 1.74.3 | Define exact challenge nonce and signature wire formats |
| 2026-10-07 | docs/TESTING.md | 1.11.7 | Require 100% branch, line and function coverage for licensing primitives |
| 2026-10-07 | docs/TESTING.md | 1.11.8 | Require full coverage and boundary tests for the activation challenge HTTP handler |
| 2026-10-07 | docs/hld/licensing-service.md | 1.0.4 | Define consistent credential lookup and record the FakeCloud-tested challenge handler and DynamoDB adapter status |
| 2026-10-07 | API-CONTRACT.md | 1.74.4 | Bind the opaque license reference to its tenant partition and document partial hosted implementation status |
| 2026-10-07 | docs/TESTING.md | 1.11.9 | Add isolated FakeCloud DynamoDB integration to macOS CI and full coverage for persistence adapters |
| 2026-10-07 | docs/hld/licensing-service.md | 1.0.5 | Define strict RS256 entitlement claims and record the FakeCloud-verified KMS signer |
| 2026-10-07 | API-CONTRACT.md | 1.74.5 | Specify exact signed entitlement claims, trusted times and message bounds |
| 2026-10-07 | docs/TESTING.md | 1.12.0 | Require full coverage for the KMS signer and verify entitlement signatures against FakeCloud public keys |
| 2026-10-07 | docs/hld/licensing-service.md | 1.0.6 | Record that officekit.app is configured with Cloudflare and defer API DNS until the AWS endpoint is ready |
| 2026-10-07 | API-CONTRACT.md | 1.74.6 | Align hosted licensing DNS status with the configured Cloudflare domain |
| 2026-10-07 | docs/LICENSING-PLAN.md | 1.2.2 | Record configured Cloudflare ownership and the post-deployment API DNS step |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.111.0 | Record half-frame zoom recall coverage and retain the curated real-photo benchmark gap |
| 2026-10-07 | docs/TESTING.md | 1.12.1 | Require half-frame zoom and transparent-image cases for similar-image scanning |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.16.0 | Record half-frame zoom regression without claiming real-world burst precision |
| 2026-10-07 | docs/hld/licensing-service.md | 1.0.7 | Specify the implemented atomic challenge-consumption and seat-reservation primitive and its remaining handler gap |
| 2026-10-07 | API-CONTRACT.md | 1.74.7 | Record FakeCloud-verified transactional activation persistence without claiming a public activation route |
| 2026-10-07 | docs/TESTING.md | 1.12.2 | Require FakeCloud proof of one-device limits, one-use challenges and last-seat concurrency |
| 2026-10-07 | docs/hld/licensing-service.md | 1.0.8 | Record the activation handler, idempotent challenge consumption and FakeCloud end-to-end coverage |
| 2026-10-07 | API-CONTRACT.md | 1.74.8 | Clarify that activation handlers are tested but not deployed through API Gateway |
| 2026-10-07 | docs/TESTING.md | 1.12.3 | Record FakeCloud end-to-end activation and retain deployment/client release gates |
| 2026-10-07 | docs/hld/licensing-service.md | 1.0.9 | Record composed Lambda, synth-tested API Gateway stack, optional Cloudflare domain mapping and remaining release blockers |
| 2026-10-07 | API-CONTRACT.md | 1.74.9 | Document activation routes as CDK-wired and FakeCloud-tested but not deployed |
| 2026-10-07 | docs/TESTING.md | 1.12.4 | Add CDK synth and resource-security assertions to the hosted licensing gate |
| 2026-10-07 | docs/LICENSING-PLAN.md | 1.2.3 | Update implementation status for tested handlers and initial CDK stack |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.112.0 | Record hosted activation and CDK work without marking licensing or tools release-ready |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.17.0 | Record initial FakeCloud-tested hosted activation stack and keep production blockers visible |
| 2026-10-07 | docs/TESTING.md | 1.12.5 | Add direct HTTP and packaged sidecar depth checks for color conversion |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.113.0 | Record HTTP and macOS sidecar evidence for color conversion without marking its UI complete |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.18.0 | Record API and packaged-runtime color conversion checks while preserving the missing UI gate |
| 2026-10-07 | docs/TESTING.md | 1.12.6 | Add HTTP and packaged macOS amortization checks for loan EMI |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.114.0 | Record loan EMI HTTP edge tests and packaged schedule validation without claiming release readiness |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.19.0 | Record loan EMI route and packaged amortization evidence with remaining UI gates |
| 2026-10-07 | API-CONTRACT.md | 1.74.10 | Document the bundled macOS Vision image OCR helper and platform-specific OCR availability |
| 2026-10-07 | docs/TESTING.md | 1.12.7 | Add bounded macOS Vision image-to-statement API coverage and clarify platform limits |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.115.0 | Record macOS Vision OCR parsing evidence and preserve scanned-PDF and cross-platform gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.20.0 | Record end-to-end macOS statement-image OCR fixture without claiming real-world accuracy |
| 2026-10-07 | API-CONTRACT.md | 1.74.11 | Add bounded PNG/JPEG calculator-summary attachments with opt-in image attribution |
| 2026-10-07 | docs/TESTING.md | 1.12.8 | Add decoded-image, metadata-consent, one-page bounds and packaged-sidecar PNG/JPEG smoke checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.116.0 | Record tested PNG/JPEG result-summary endpoints while preserving the pending UI gate |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.21.0 | Track one-page result image exports as API-ready and UI approval pending |
| 2026-10-07 | API-CONTRACT.md | 1.74.12 | Add a bounded native macOS ping route with measured loss/latency and explicit unsupported-platform behavior |
| 2026-10-07 | docs/TESTING.md | 1.12.9 | Add native ping failure-path, input-boundary and packaged-loopback validation |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.117.0 | Add N05 ping to source audit counts without claiming UI or release readiness |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.22.0 | Record macOS N05 ping API and packaged smoke evidence; retain platform and UI gaps |
| 2026-10-07 | docs/TESTING.md | 1.12.10 | Specify independent compound-interest HTTP vectors and packaged macOS schedule verification |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.118.0 | Record independent compound-interest HTTP vectors and packaged schedule evidence |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.23.0 | Record compound-interest reference and packaged macOS evidence without changing release-ready counts |
| 2026-10-07 | API-CONTRACT.md | 1.74.13 | Add bounded DNS lookup route with typed records and failure states |
| 2026-10-07 | docs/TESTING.md | 1.12.11 | Specify deterministic DNS resolver, validation and response-cap coverage |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.119.0 | Add N04 DNS lookup to code/API family totals without claiming release readiness |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.24.0 | Record N04 DNS API and deterministic test evidence; retain UI and package gaps |
| 2026-10-07 | API-CONTRACT.md | 1.74.14 | Record successful packaged macOS system-resolver DNS query and remaining route gaps |
| 2026-10-07 | docs/TESTING.md | 1.12.12 | Add packaged DNS A-record smoke acceptance and network-test boundary |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.120.0 | Record N04 DNS macOS packaged A-query evidence and retain user-facing gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.25.0 | Record packaged N04 A-query smoke without changing release-ready count |
| 2026-10-07 | API-CONTRACT.md | 1.74.15 | Add privacy-controlled local network-interface route and response bounds |
| 2026-10-07 | docs/TESTING.md | 1.12.13 | Specify network-interface privacy defaults, platform fixtures and caps |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.121.0 | Add N03 interface inventory to code/API audit counts without claiming release readiness |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.26.0 | Record N03 API and packaged privacy-default smoke while retaining platform/UI gaps |
| 2026-10-07 | API-CONTRACT.md | 1.74.16 | Add typed CPU utilization, RAM and bounded sample-cache contract |
| 2026-10-07 | docs/TESTING.md | 1.12.14 | Specify measured resource samples, cache expiry and provider-error coverage |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.122.0 | Upgrade N02 resource overview evidence and D2 depth classification |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.27.0 | Record packaged macOS resource-sampling evidence and UI/platform gaps |
| 2026-10-07 | API-CONTRACT.md | 1.74.17 | Add redacted macOS system-information report endpoint |
| 2026-10-07 | docs/TESTING.md | 1.12.15 | Specify redaction and native-provider coverage for system information |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.123.0 | Add N01 system information to code/API counts with explicit platform limits |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.28.0 | Record N01 report API and packaged macOS evidence without claiming release readiness |
| 2026-10-07 | docs/TESTING.md | 1.12.16 | Add off-center zoom-crop recall and unrelated-scene precision cases |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.124.0 | Record four-corner image fingerprints and off-center burst tests |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.29.0 | Record expanded off-center burst matching evidence and retain real-photo benchmark gap |
| 2026-10-07 | docs/PITFALLS.md | — | Extend P-022 prevention and regression coverage for off-center zoom crops |
| 2026-10-07 | API-CONTRACT.md | 1.74.18 | Add bounded same-format image resize API contract |
| 2026-10-07 | docs/TESTING.md | 1.12.17 | Specify resize bounds, frame preservation and packaged smoke coverage |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.125.0 | Reconcile image resize and metadata API exposure with source, tests and counts |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.30.0 | Record image resize API and correct release audit totals without claiming UI readiness |
| 2026-10-07 | docs/PITFALLS.md | — | Record the engine-only image-resize exposure gap and end-to-end prevention gate |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.126.0 | Record successful authenticated resize smoke against the packaged macOS sidecar |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.31.0 | Record packaged macOS resize evidence and retain UI and release verification gaps |
| 2026-10-07 | API-CONTRACT.md | 1.74.19 | Add bounded all-or-nothing ZIP batch image resize contract |
| 2026-10-07 | docs/TESTING.md | 1.12.18 | Add aggregate bounds, safe names and batch failure cases for image resize |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.127.0 | Record bounded batch image resize API and retain missing UI/release gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.32.0 | Record image batch API bounds and verification evidence |
| 2026-10-07 | docs/PITFALLS.md | — | Close the image-resize batch API gap while retaining UI/release status |
| 2026-10-07 | API-CONTRACT.md | 1.74.20 | Define encoding-time output caps for PDF protect and unlock |
| 2026-10-07 | docs/TESTING.md | 1.12.19 | Add protect/unlock output-overflow regression guidance |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.128.0 | Record bounded generated output for PDF protect and unlock |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.33.0 | Record PDF protect/unlock output-overflow fix and remaining audit scope |
| 2026-10-07 | docs/PITFALLS.md | — | Record output-buffer bounds for PDF serializers |
| 2026-10-07 | API-CONTRACT.md | 1.74.21 | Define PDF workbench and image-conversion output limits |
| 2026-10-07 | docs/TESTING.md | 1.12.20 | Require injected output-cap tests across PDF and image conversion APIs |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.129.0 | Record bounded serialization for PDF operations and image conversion |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.34.0 | Record output-cap coverage across PDF workbench and image conversion |
| 2026-10-07 | docs/PITFALLS.md | — | Extend bounded-output review to all PDF workbench operations and image conversions |
| 2026-10-07 | API-CONTRACT.md | 1.74.22 | Clarify the PDF compression output check and image-output cap wording |
| 2026-10-07 | docs/TESTING.md | 1.12.21 | Require bounded output checks across document and image endpoints |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.130.0 | Correct the PDF output-bound evidence and fidelity gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.35.0 | Refresh PDF and image output safety audit |
| 2026-10-07 | API-CONTRACT.md | 1.74.23 | Specify bounded page-level scanned-statement OCR fallback |
| 2026-10-07 | docs/TESTING.md | 1.12.22 | Add real Vision, mixed-page, alignment and OCR resource-bound cases |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.131.0 | Record scanned-PDF OCR, header alignment and remaining accuracy gaps |
| 2026-10-07 | API-CONTRACT.md | 1.74.24 | Remove stale claim that scanned-PDF OCR is unavailable |
| 2026-10-07 | docs/TESTING.md | 1.12.23 | Align OCR guidance with page-level scanned-PDF fallback |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.132.0 | Record packaged OCR status and correct stale scan limitation |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.36.0 | Record bounded Mac-first scanned statement OCR verification |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.37.0 | Correct statement OCR support and test evidence |
| 2026-10-07 | API-CONTRACT.md | 1.74.25 | Specify bounded OCR orientation retries for rotated scans |
| 2026-10-07 | docs/TESTING.md | 1.12.24 | Add quarter-turned statement OCR and shared retry-budget cases |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.133.0 | Record rotated scan OCR behavior and test evidence |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.38.0 | Add rotated statement OCR depth and verification evidence |
| 2026-10-07 | API-CONTRACT.md | 1.74.26 | Specify OCR orientation scoring for reversed statement headers |
| 2026-10-07 | docs/TESTING.md | 1.12.25 | Cover reversed-header orientation selection and OCR retry bounds |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.134.0 | Record OCR row/header scoring and Mac integration evidence |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.39.0 | Add reversed-header scan depth and test evidence |
| 2026-10-07 | API-CONTRACT.md | 1.74.27 | Document cumulative similar-image scan-work limits |
| 2026-10-07 | docs/TESTING.md | 1.12.26 | Verify cumulative similar-image scan budget and continuation |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.135.0 | Record aggregate similar-image pixel-work cap and regression |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.40.0 | Add bounded similar-image scan-work evidence |
| 2026-10-07 | docs/PITFALLS.md | — | Record page-level scanned PDF OCR and blank-column alignment prevention |
| 2026-10-07 | API-CONTRACT.md | 1.74.28 | Specify capped screenshot PNG encoding and HTTP 413 overflow behavior |
| 2026-10-07 | docs/TESTING.md | 1.12.27 | Add encoder-buffer and HTTP 413 screenshot output-bound regression |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.136.0 | Record bounded screenshot PNG encoding behavior and test evidence |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.41.0 | Record screenshot output memory cap and 413 behavior |
| 2026-10-07 | docs/PITFALLS.md | — | Record post-encoding screenshot output cap and regression prevention |
| 2026-10-07 | docs/TESTING.md | 1.12.28 | Add authenticated screenshot editor smoke for bundled macOS app |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.137.0 | Record passing screenshot engine, HTTP and packaged macOS smoke evidence |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.42.0 | Add screenshot editor packaged macOS smoke evidence |
| 2026-10-07 | API-CONTRACT.md | 1.74.29 | Disable legacy local license activation and ignore editable entitlement JSON |
| 2026-10-07 | docs/LICENSING-PLAN.md | 1.2.4 | Record fail-closed local license status and hosted activation blockers |
| 2026-10-07 | docs/hld/licensing-service.md | 1.1.0 | Update service context after removing the desktop HMAC issuer |
| 2026-10-07 | docs/TESTING.md | 1.12.29 | Require fail-closed regressions until signed desktop entitlements ship |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.138.0 | Update license trust and activation gap assessment |
| 2026-10-07 | docs/PITFALLS.md | — | Record client-side license issuer and editable-status regression prevention |
| 2026-10-07 | docs/TESTING.md | 1.12.30 | Add packaged macOS license fail-closed smoke requirement |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.139.0 | Correct desktop license behavior after removing local issuance |
| 2026-10-07 | docs/TESTING.md | 1.12.31 | Specify packaged split/join binary round trip and license status smoke |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.140.0 | Record packaged macOS binary split/join round-trip evidence |
| 2026-10-07 | API-CONTRACT.md | 1.74.30 | Specify ZIP overhead preflight for file split artifacts |
| 2026-10-07 | docs/TESTING.md | 1.12.32 | Add split archive overhead boundary and cleanup tests |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.141.0 | Record preflight validation for split ZIP output size |
| 2026-10-07 | docs/TESTING.md | 1.12.33 | Require bundled offline web assets and restrictive Tauri CSP verification |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.142.0 | Record local UI asset/CSP checks and the two-phase duplicate scanner |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.43.0 | Record local UI hardening and exact-duplicate prefilter evidence |
| 2026-10-07 | docs/TESTING.md | 1.12.34 | Add duplicate-prefilter collision and between-pass mutation regressions |
| 2026-10-07 | docs/TESTING.md | 1.12.35 | Add headless macOS DMG build and mounted-installer smoke requirements |
| 2026-10-07 | docs/PITFALLS.md | — | Record Finder automation hang prevention and macOS DMG smoke evidence |
| 2026-10-07 | API-CONTRACT.md | 1.74.31 | Specify bounded native macOS HEIC/HEIF decoding for similar-image scans |
| 2026-10-07 | docs/TESTING.md | 1.12.36 | Add HEIC/HEIF burst grouping, resource-limit and packaged-sidecar checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.143.0 | Record Mac-native HEIC/HEIF similar-image support and verification gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.44.0 | Record generated HEIC burst unit and packaged-sidecar evidence |
| 2026-10-07 | docs/PITFALLS.md | — | Record HEIC burst-photo skip prevention and native decoder bounds |
| 2026-10-07 | API-CONTRACT.md | 1.74.32 | Define tri-state statement reconciliation and preserved export row statuses |
| 2026-10-07 | docs/TESTING.md | 1.12.37 | Require no-false-pass, missing-amount and partial-reconciliation cases |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.144.0 | Record honest statement reconciliation states and the pending screen update |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.45.0 | Track verified, partial, discrepancy and unverified statement outcomes |
| 2026-10-07 | docs/PITFALLS.md | — | Record statement reconciliation false-positive prevention and regression paths |
| 2026-10-07 | docs/TESTING.md | 1.12.38 | Require fresh packaged macOS sidecar coverage for unverified statements |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.145.0 | Record packaged macOS rejection of statement false-pass state |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.46.0 | Record the packaged statement unverified-state smoke while preserving the UI gate |
| 2026-10-07 | docs/PITFALLS.md | — | Record full-suite and packaged-sidecar verification for P-061 |
| 2026-10-07 | docs/TESTING.md | 1.12.39 | Require a missing-balance gap to break reconciliation continuity |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.146.0 | Record stale-balance prevention in statement reconciliation |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.47.0 | Add missing-intermediate-balance acceptance coverage for P01 |
| 2026-10-07 | docs/PITFALLS.md | — | Add stale-balance continuity regression to P-061 |
| 2026-10-07 | docs/TESTING.md | 1.12.40 | Add four-state statement-result UI and accessible status regression checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.147.0 | Record approved reconciliation-state UI and remaining package verification |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.48.0 | Record four-state reconciliation result screen implementation |
| 2026-10-07 | docs/TESTING.md | 1.12.41 | Require authenticated packaged PDF split output and page-count smoke |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.148.0 | Record packaged macOS PDF page-split output verification |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.49.0 | Track packaged P03 split smoke and remaining release gaps |
| 2026-10-07 | API-CONTRACT.md | 1.74.33 | Specify supported statement decimal marks and validated Western/Indian grouping |
| 2026-10-07 | docs/TESTING.md | 1.12.42 | Add locale-aware statement amount and reconciliation test requirements |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.149.0 | Record EU/Indian statement amount normalization and remaining locale gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.50.0 | Track statement locale parsing evidence and remaining P01 gaps |
| 2026-10-07 | docs/PITFALLS.md | — | Record decimal-comma and Indian grouping amount corruption regressions for P-062 |
| 2026-10-07 | API-CONTRACT.md | 1.74.34 | Add strict explicit statement number locales to the extraction route |
| 2026-10-07 | docs/TESTING.md | 1.12.43 | Require locale-specific statement amount and HTTP reconciliation vectors |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.150.0 | Record API locale selection and the missing user-facing selector |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.51.0 | Track explicit statement locales and the UI release gate |
| 2026-10-07 | docs/PITFALLS.md | — | Extend P-062 with explicit locale acceptance and packaged smoke evidence |
| 2026-10-07 | API-CONTRACT.md | 1.74.35 | Add explicit statement date-order parsing and safe auto-mode preservation |
| 2026-10-07 | docs/TESTING.md | 1.12.44 | Require explicit date-order normalization and ambiguous-date preservation |
| 2026-10-07 | docs/TESTING.md | 1.12.45 | Define refusal and compatibility gates for QuickBooks Web Connect output |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.152.0 | Remove the false generic-OFX-as-QBO readiness claim |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.53.0 | Gate QBO release claims on supported-institution import tests |
| 2026-10-07 | docs/PITFALLS.md | — | Record the false QBO alias and fail-closed regression |
| 2026-10-07 | docs/TESTING.md | 1.12.46 | Require strict PDF attachment media, signature and client size validation |
| 2026-10-07 | docs/PITFALLS.md | — | Record PDF UI attachment false-success prevention and regression tests |
| 2026-10-07 | docs/TESTING.md | 1.12.47 | Add global-search catalog failure, retry and broad related-query checks |
| 2026-10-07 | docs/PITFALLS.md | — | Record search catalog failure and retry-state regression |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.151.0 | Record statement date-order API support and missing screen controls |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.52.0 | Track explicit statement date-order support and remaining UI gap |
| 2026-10-07 | docs/PITFALLS.md | — | Record strict date-order handling and preserve ambiguous source dates |
| 2026-10-07 | API-CONTRACT.md | 1.74.36 | Refuse ambiguous comma-only financial amounts in automatic mode |
| 2026-10-07 | docs/TESTING.md | 1.12.48 | Require ambiguous automatic amounts to remain unparsed and unverified |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.153.0 | Record fail-safe handling of ambiguous comma-only statement amounts |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.54.0 | Track fail-safe automatic statement amount parsing |
| 2026-10-07 | docs/PITFALLS.md | — | Record ambiguous automatic statement amount regression and packaged check |
| 2026-10-07 | docs/TESTING.md | 1.12.49 | Require packaged macOS PDF merge page-count and order verification |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.154.0 | Record mounted-DMG PDF merge sequence smoke and remaining fidelity gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.55.0 | Add packaged PDF merge evidence without claiming release readiness |
| 2026-10-07 | docs/PITFALLS.md | — | Record missing packaged PDF merge coverage and regression test |
| 2026-10-07 | docs/TESTING.md | 1.12.50 | Require packaged PDF compression preset ratio and render checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.155.0 | Record packaged compression preset smoke and remaining fidelity scope |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.56.0 | Add packaged compression evidence without expanding the feature claim |
| 2026-10-07 | docs/PITFALLS.md | — | Record missing packaged PDF compression and fidelity regressions |
| 2026-10-07 | docs/TESTING.md | 1.12.51 | Require packaged PDF metadata sentinel removal and fidelity checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.156.0 | Record packaged standard-metadata removal evidence and limits |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.57.0 | Add packaged PDF metadata-removal evidence without implying redaction |
| 2026-10-07 | docs/PITFALLS.md | — | Record absent packaged metadata verification and regression coverage |
| 2026-10-07 | docs/TESTING.md | 1.12.52 | Require PDF merge source-bookmark title and destination checks; clarify outline/form limits |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.157.0 | Record source-boundary bookmarks and remaining merge-structure gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.58.0 | Add source-name bookmarks to PDF merge acceptance and test scope |
| 2026-10-07 | docs/PITFALLS.md | — | Record missing PDF merge navigation and regression coverage |
| 2026-10-07 | docs/TESTING.md | 1.12.53 | Require merge outline and AcroForm fidelity tests with explicit unsupported-structure limits |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.158.0 | Record form-aware PDF merge and nested internal outline coverage |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.59.0 | Expand PDF merge acceptance with supported forms and nested outlines |
| 2026-10-07 | docs/PITFALLS.md | — | Record form loss from page-only PDF copying and regression coverage |
| 2026-10-07 | docs/TESTING.md | 1.12.54 | Add internal-link retargeting and packaged PDF outline/form read-back checks |
| 2026-10-07 | docs/TESTING.md | 1.12.55 | Specify exact packaged source-bookmark, nested-destination, form-value and page-order assertions |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.159.0 | Record internal link preservation and rebuilt macOS merge-structure smoke |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.60.0 | Record packaged read-back evidence and remaining PDF structure limits |
| 2026-10-07 | docs/TESTING.md | 1.12.56 | Require malformed-outline rejection without partial output and current packaged read-back checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.160.0 | Record strict outline parsing and current PDF integration/package evidence |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.61.0 | Add malformed-outline safe failure evidence to PDF merge acceptance |
| 2026-10-07 | API-CONTRACT.md | 1.74.37 | Add bounded ordered PDF page-count preflight for merge review |
| 2026-10-07 | docs/TESTING.md | 1.12.57 | Require PDF page-count preflight bounds, ordering and per-file safe failures |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.161.0 | Record PDF page-count preflight API and pending UI approval |
| 2026-10-07 | docs/TESTING.md | 1.12.58 | Require packaged PDF page-count order, total and path-free response checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.162.0 | Record mounted-DMG PDF page-count preflight evidence |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.62.0 | Add packaged PDF page-count preflight evidence and retain pending UI approval |
| 2026-10-07 | docs/TESTING.md | 1.12.59 | Require packaged OfficeKit monogram ICNS identity and parity verification |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.163.0 | Record mounted-DMG verification of the packaged monogram icon |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.63.0 | Track packaged icon verification and remaining installed-cache check |
| 2026-10-07 | docs/TESTING.md | 1.12.60 | Compare decoded ICNS images instead of container bytes |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.164.0 | Correct icon audit using decoded installed and packaged artwork |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.64.0 | Record visually identical installed icon and likely cache issue |
| 2026-10-07 | .github/workflows/build-installers.yml | — | Require macOS Developer ID signing and notarization; publish only verified drafts |
| 2026-10-07 | tests/tauri-dmg-build.test.mjs | — | Cover release credentials, notarization checks and verified-draft publication |
| 2026-10-07 | docs/TESTING.md | 1.12.62 | Require cleanup of temporary certificate and notarization keys |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.165.0 | Track configured but unverified macOS signing and notarization pipeline |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.65.0 | Record fail-closed signed-release workflow and missing credentials |
| 2026-10-07 | docs/PITFALLS.md | — | Add P-070 for unsigned macOS release prevention |
| 2026-10-07 | tests/sidecar-smoke.test.mjs | — | Require all PDF-to output destinations and accurate format scope in packaged search |
| 2026-10-07 | tests/ui-search-routing.test.mjs | — | Require every catalogue match to render as a selectable PDF result |
| 2026-10-07 | scripts/smoke-backend-sidecar.mjs | — | Verify PDF-to search results against the authenticated packaged sidecar |
| 2026-10-07 | docs/TESTING.md | 1.12.63 | Add packaged PDF-to search coverage requirements |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.166.0 | Record PDF search destination smoke and pending UI mock approval |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.66.0 | Record packaged search evidence and pending presentation approval |
| 2026-10-07 | tests/test_module5_data_converter.py | — | Preserve CSV/TSV identifiers, date-like values and numeric precision; enforce malformed/input-boundary cases |
| 2026-10-07 | tests/test_e2e_api.py | — | Verify multipart CSV/TSV fidelity and safe 422 response on tabular resource limits |
| 2026-10-07 | engine_file_converter.py | — | Add conservative delimited inference and pre-allocation row/column/cell bounds |
| 2026-10-07 | API-CONTRACT.md | 1.74.38 | Document delimited type-preservation and table-dimension limits |
| 2026-10-07 | docs/TESTING.md | 1.12.64 | Require CSV/TSV identifier, precision and resource-bound regressions |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.167.0 | Record fixed CSV/TSV data-loss issue and remaining Excel fidelity gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.67.0 | Record tabular converter preservation evidence and open scope |
| 2026-10-07 | tests/sidecar-smoke.test.mjs | — | Validate packaged CSV/TSV data fidelity for identifiers, exact values and dates |
| 2026-10-07 | scripts/smoke-backend-sidecar.mjs | — | Exercise delimited-data fidelity through the authenticated bundled macOS API |
| 2026-10-07 | docs/TESTING.md | 1.12.65 | Require packaged macOS CSV/TSV fidelity verification |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.68.0 | Record verified data fidelity in the rebuilt macOS sidecar |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.168.0 | Record macOS sidecar verification of CSV/TSV identifier and precision preservation |
| 2026-10-07 | docs/PITFALLS.md | — | Add P-071 for destructive CSV numeric inference |
| 2026-10-07 | tests/test_devtools_validation_unittest.py | — | Cover YAML-to-JSON scalar fidelity, hostile inputs, aliases, duplicate keys and parser bounds |
| 2026-10-07 | tests/test_e2e_modular_api.py | — | Verify YAML-to-JSON typed HTTP success and safe rejection paths |
| 2026-10-07 | tests/test_api_contract_unittest.py | — | Require the YAML-to-JSON operation in the typed developer-tool contract |
| 2026-10-07 | engine_devtools.py | — | Add bounded SafeLoader YAML-to-JSON conversion with YAML 1.2 scalar resolution |
| 2026-10-07 | app.py | — | Expose YAML-to-JSON through the strict developer-tools API operation |
| 2026-10-07 | scripts/smoke-backend-sidecar.mjs | — | Verify packaged YAML conversion and alias rejection through authenticated API |
| 2026-10-07 | tests/sidecar-smoke.test.mjs | — | Validate the packaged YAML-to-JSON smoke response contract |
| 2026-10-07 | API-CONTRACT.md | 1.74.39 | Specify bounded safe YAML-to-JSON conversion and YAML 1.2 scalar policy |
| 2026-10-07 | docs/TESTING.md | 1.12.66 | Require YAML type-fidelity, hostile-input, bounds and packaged checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.169.0 | Record JSON↔YAML API depth and remaining formatter UI gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.69.0 | Record YAML conversion depth, scalar policy and packaged macOS evidence |
| 2026-10-07 | docs/PITFALLS.md | — | Add P-072 for source-tree macOS sidecar smoke path resolution |
| 2026-10-07 | tests/test_devtools_validation_unittest.py | — | Cover strict JSON duplicate/non-finite rejection, exact decimal round trips, Unicode and resource bounds |
| 2026-10-07 | tests/test_e2e_modular_api.py | — | Verify strict JSON HTTP rejection and JSON↔YAML numeric fidelity |
| 2026-10-07 | tests/test_api_contract_unittest.py | — | Require bounded strict JSON parsing in the developer-tools contract |
| 2026-10-07 | engine_devtools.py | — | Preserve exact JSON decimal values; reject duplicates, non-finite numbers and invalid Unicode |
| 2026-10-07 | API-CONTRACT.md | 1.74.40 | Specify strict bounded JSON parsing and decimal fidelity |
| 2026-10-07 | docs/TESTING.md | 1.12.67 | Require duplicate-key, numeric-precision, Unicode and JSON limit cases |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.170.0 | Record JSON formatter strictness, resource bounds and numeric fidelity |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.70.0 | Extend JSON formatter release tests for precision and malformed values |
| 2026-10-07 | docs/PITFALLS.md | — | Add P-073 for permissive JSON parsing and silent value changes |
| 2026-10-07 | scripts/smoke-backend-sidecar.mjs | — | Verify exact JSON decimal fidelity and duplicate-key rejection in packaged macOS sidecar |
| 2026-10-07 | tests/sidecar-smoke.test.mjs | — | Pin JSON decimal fidelity response validation for packaged smoke |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.171.0 | Record exact JSON↔YAML precision and authenticated arm64 sidecar evidence |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.71.0 | Record strict JSON packaged-sidecar verification |
| 2026-10-07 | tests/test_similar_images_unittest.py | — | Add a seeded 12-scene / 36-frame JPEG burst recall and cross-scene separation corpus |
| 2026-10-07 | tests/screenshot-editor-mock.test.mjs | — | Validate the responsive screenshot-editor before/after review mock and controls |
| 2026-10-07 | design/mocks/screenshot-editor-review.html | — | Prepare responsive before/after screenshot editor mock with local clipboard and edit limits |
| 2026-10-07 | review/officekit-design/requirements.md | — | Record screenshot-editor mock approval request and proposed privacy limits |
| 2026-10-07 | review/officekit-design/requirements.md | — | Record approval of PDF page management workbench flow |
| 2026-10-07 | review/officekit-design/requirements.md | — | Record approval of file split/join workbench flow |
| 2026-10-07 | docs/TESTING.md | 1.12.68 | Require multi-scene burst recall and separation checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.172.0 | Record synthetic multi-scene burst benchmark without claiming real-camera accuracy |
| 2026-10-07 | engine_pdf_ranges.py | — | Bound PDF page-range expansion before building large page lists |
| 2026-10-07 | engine_pdf_advanced.py | — | Add bounded named page-group PDF splitting into ZIP archives |
| 2026-10-07 | app.py | — | Expose strict multipart grouped PDF split API with safe validation and size limits |
| 2026-10-07 | tests/test_pdf_endpoints.py | — | Verify ordered grouped PDF outputs, hostile manifests and ZIP overflow |
| 2026-10-07 | tests/test_pdf_page_ranges_unittest.py | — | Verify selected-page expansion bounds at and over the limit |
| 2026-10-07 | tests/test_api_contract_unittest.py | — | Require request-body caps for the grouped PDF split upload route |
| 2026-10-07 | scripts/smoke-backend-sidecar.mjs | — | Verify grouped PDF outputs and rendered page order in the authenticated macOS sidecar |
| 2026-10-07 | tests/sidecar-smoke.test.mjs | — | Validate exact named grouped-PDF ZIP contents |
| 2026-10-07 | API-CONTRACT.md | 1.74.41 | Document the grouped PDF split route and limits |
| 2026-10-07 | API-CONTRACT.md | 1.74.42 | Document the single-split selected-page cap alongside grouped output limits |
| 2026-10-07 | docs/TESTING.md | 1.12.69 | Require grouped-split ZIP and packaged page-order verification |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.173.0 | Record grouped split API depth and remaining UI gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.72.0 | Record P03 grouped PDF split API and packaged acceptance evidence |
| 2026-10-07 | docs/TESTING.md | 1.12.70 | Add grouped PDF split UI, client-validation and ZIP-download acceptance checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.174.0 | Record approved grouped PDF split UI and remaining mounted-DMG verification |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.73.0 | Record named grouped-split workbench integration and remaining release gaps |
| 2026-10-07 | design/mocks/pdf-group-split-review.html | — | Fix grouped-output add/remove IDs and enforce the 2–50 group mock state |
| 2026-10-07 | tests/pdf-group-split-mock.test.mjs | — | Verify responsive mock copy and add/remove group limits and unique IDs |
| 2026-10-07 | index.html | — | Connect named page groups to the bounded grouped-split ZIP endpoint |
| 2026-10-07 | tests/pdf-workbench-ui.test.mjs | — | Verify grouped split DTOs, endpoint, safe names and bounded ZIP validation |
| 2026-10-07 | dist-ui/index.html | — | Regenerate the Tauri UI from the authoritative grouped-split screen |
| 2026-10-07 | engine_math.py | — | Add bounded scientific expression evaluation with constants, an allowlisted function set and radians/degrees modes |
| 2026-10-07 | engine_units.py | — | Re-export MathEvaluator from its focused engine module for compatibility |
| 2026-10-07 | app.py | — | Expose strict angle-mode input/output on the typed math evaluation API |
| 2026-10-07 | tests/test_math_evaluator_unittest.py | — | Cover constants, functions, angle modes, sandbox limits, precedence and numeric edge cases |
| 2026-10-07 | tests/test_e2e_api.py | — | Verify scientific math and angle-mode validation over HTTP |
| 2026-10-07 | scripts/smoke-backend-sidecar.mjs | — | Exercise a degree-mode reference expression through the authenticated macOS sidecar |
| 2026-10-07 | tests/sidecar-smoke.test.mjs | — | Validate packaged scientific-math response values and angle-mode metadata |
| 2026-10-07 | tests/tool-guide-counts.test.mjs | — | Update the observed D1/D2 family totals after C01 engine expansion |
| 2026-10-07 | API-CONTRACT.md | 1.74.43 | Document scientific functions and explicit radians/degrees math evaluation |
| 2026-10-07 | docs/TESTING.md | 1.12.71 | Add scientific expression and packaged angle-mode acceptance coverage |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.175.0 | Reclassify the expression evaluator at D2 and record its tests and remaining screen gap |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.74.0 | Record C01 scientific expression API progress and remaining product/release gaps |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.176.0 | Record the successful arm64 macOS scientific-math sidecar smoke and keep GUI gaps explicit |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.75.0 | Record C01 packaged runtime evidence without claiming product-complete depth |
| 2026-10-07 | API-CONTRACT.md | 1.74.45 | Document strict DTO fields, bounded input and safe heuristic Markdown output |
| 2026-10-07 | docs/TESTING.md | 1.12.73 | Add meeting-notes classification, Markdown safety and exact input-boundary checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.178.0 | Record strict bounded heuristic meeting-notes behavior and remaining quality limits |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.77.0 | Record meeting-notes hardening and retain its non-release-verified status |
| 2026-10-07 | API-CONTRACT.md | 1.74.46 | Add bounded theoretical search-space bits to the typed password generator response |
| 2026-10-07 | docs/TESTING.md | 1.12.74 | Add independent password output-space and API response checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.179.0 | Record password generator entropy evidence and remaining UI/passphrase gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.78.0 | Record password generator API depth and keep UI work open |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.180.0 | Correct the grouped PDF split audit to match the implemented named ZIP flow |
| 2026-10-07 | API-CONTRACT.md | 1.74.47 | Document strict bounded JWT segment and claim parsing |
| 2026-10-07 | docs/TESTING.md | 1.12.75 | Add hostile JWT encoding and claims regression requirements |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.181.0 | Record strict JWT claim parsing and unverified-only behavior |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.79.0 | Record strict JWT parsing safeguards and limits |
| 2026-10-07 | docs/TESTING.md | 1.12.76 | Require contrastive-clause and pending-decision meeting-notes regressions |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.182.0 | Record independent mixed-clause classification and pending-decision handling |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.80.0 | Add contrastive and pending-decision acceptance cases for meeting notes |
| 2026-10-07 | docs/TESTING.md | 1.12.77 | Add CC0 photo-texture recall and cross-scene false-positive benchmark |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.183.0 | Record real-photo texture benchmark while retaining true-burst verification gap |
| 2026-10-07 | docs/TESTING.md | 1.12.78 | Raise real-photo benchmark zoom, translation, rotation and JPEG degradation coverage |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.184.0 | Record stronger CC0 photo variants and unchanged camera-burst gap |
| 2026-10-07 | API-CONTRACT.md | 1.74.48 | Return only positive contrastive clauses as Meeting Notes actions and decisions |
| 2026-10-07 | docs/TESTING.md | 1.12.79 | Require Meeting Notes results to omit adjacent negated clauses |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.185.0 | Record positive-clause-only Meeting Notes output |
| 2026-10-07 | API-CONTRACT.md | 1.74.49 | Add bounded, typed recursive folder summaries to workspace storage reports |
| 2026-10-07 | docs/TESTING.md | 1.12.80 | Specify recursive storage-report totals, ordering, limits and failure handling |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.186.0 | Record selected-copy folder totals and remaining storage-screen gaps |
| 2026-10-07 | API-CONTRACT.md | 1.74.50 | Add bounded local dictation cleanup request/response contract |
| 2026-10-07 | docs/TESTING.md | 1.12.81 | Specify deterministic dictation cleanup and strict local API regressions |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.187.0 | Record tested cleanup API and refresh API exposure counts; native dictation remains open |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.81.0 | Record cleanup API progress and refreshed API exposure count without closing local push-to-talk |
| 2026-10-07 | docs/TESTING.md | 1.12.82 | Specify explicit Parakeet setup, cache integrity and the limits of packaging-only evidence |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.188.0 | Record explicit macOS Parakeet model setup and remaining dictation gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.82.0 | Record model setup progress without claiming transcription or push-to-talk readiness |
| 2026-10-07 | API-CONTRACT.md | 1.74.51 | Declare native Parakeet status/setup IPC commands and identify dictation operations still missing |
| 2026-10-07 | API-CONTRACT.md | 1.74.52 | Declare explicit macOS microphone permission status/request IPC operations |
| 2026-10-07 | docs/TESTING.md | 1.12.83 | Require read-only permission checks and explicit, recoverable microphone prompts |
| 2026-10-07 | API-CONTRACT.md | 1.74.53 | Declare bounded native Mac audio capture and local Parakeet transcription IPC |
| 2026-10-07 | docs/TESTING.md | 1.12.84 | Define audio duration, resampling, buffer-clearing and capture-error verification |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.189.0 | Record bounded native capture/transcription commands and unverified runtime status |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.83.0 | Record local capture IPC implementation without claiming a real-audio release test |
| 2026-10-07 | API-CONTRACT.md | 1.74.54 | Declare macOS Accessibility and Fn monitor commands and runtime limitations |
| 2026-10-07 | docs/TESTING.md | 1.12.85 | Add Fn enable/hold/release/disable and app-exit lifecycle verification |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.190.0 | Record native Fn state-machine build evidence without claiming runtime readiness |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.84.0 | Track Fn backend progress while leaving dictation release gaps open |
| 2026-10-07 | API-CONTRACT.md | 1.74.55 | Declare bounded native focused-app paste-back and clipboard restoration behavior |
| 2026-10-07 | docs/TESTING.md | 1.12.86 | Add clipboard safety and paste-back runtime verification cases |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.191.0 | Record bounded paste-back IPC while keeping end-to-end dictation unverified |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.85.0 | Track paste-back IPC without claiming integrated dictation readiness |
| 2026-10-07 | API-CONTRACT.md | 1.74.56 | Avoid restoring clipboard over content copied during paste-back |
| 2026-10-07 | docs/TESTING.md | 1.12.87 | Cover concurrent clipboard changes during transcript insertion |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.192.0 | Record guarded clipboard restoration and remaining dictation gaps |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.86.0 | Track clipboard race protection without claiming runtime verification |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.193.0 | Update dictation depth evidence while retaining D1 and unverified status |
| 2026-10-07 | API-CONTRACT.md | 1.74.57 | Add authenticated loopback cleanup-and-paste IPC contract |
| 2026-10-07 | docs/TESTING.md | 1.12.88 | Specify local cleanup client, dictionary validation and no-paste-on-error cases |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.194.0 | Record cleanup-to-paste backend and keep dictation at D1 |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.87.0 | Record local cleanup pipeline while retaining runtime and UI gaps |
| 2026-10-07 | API-CONTRACT.md | 1.74.58 | Record approved local dictation UI wiring and retain real-runtime verification gap |
| 2026-10-07 | docs/TESTING.md | 1.12.89 | Add dictation UI, local dictionary and responsive-rendering checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.195.0 | Record approved dictation UI wiring while retaining D1/runtime status |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.88.0 | Record dictation UI and local dictionary tests without claiming runtime readiness |
| 2026-10-07 | API-CONTRACT.md | 1.74.59 | Add bounded local passphrase generation route and wordlist resource contract |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.195.1 | Record bundled passphrase API and keep its screen/release verification open |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.88.1 | Track passphrase API implementation while retaining user-flow release gap |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.195.2 | Add opt-in real-camera HDR+ burst recall and false-merge benchmark evidence |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.88.2 | Record measured HDR+ burst grouping while retaining broader dataset release gates |
| 2026-10-07 | API-CONTRACT.md | 1.74.60 | Document bounded PDF page deletion and reordering routes, limits and fidelity caveats |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.195.3 | Record tested PDF page-management APIs and outstanding UI/release gates |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.88.3 | Track P04/P05 API progress without claiming user-facing or release readiness |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.195.4 | Record authenticated arm64 rendered-output smoke for PDF page management |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.88.4 | Add packaged delete/reorder page-order evidence and preserve UI/platform release gates |
| 2026-10-07 | API-CONTRACT.md | 1.74.61 | Document bounded ordered PDF page-thumbnail previews |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.195.5 | Record approved PDF page-management workbench and remaining package gate |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.88.5 | Track approved PDF delete/reorder UI while retaining packaged release gates |
| 2026-10-07 | docs/TESTING.md | 1.12.90 | Add PDF thumbnail, delete and reorder workbench acceptance checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.195.6 | Reconcile PDF page-management UI and current packaged Mac evidence |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.88.6 | Record approved P04/P05 UI and current Mac package verification |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.195.7 | Add PDF page-management families and reconcile exposure/depth totals |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.88.7 | Refresh tool family and catalogue counts after P04/P05 UI wiring |
| 2026-10-07 | docs/TESTING.md | 1.12.91 | Add searchable split/join UI and client acceptance checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.195.8 | Record searchable file split/join workbench and current verification limits |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.88.8 | Record F08 screen availability and refresh exposure totals |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.195.9 | Record rebuilt app/DMG and authenticated split/join round-trip smoke evidence; note unavailable visual UI bridge |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.88.9 | Record packaged F08 split/join smoke evidence and installer inclusion without claiming mounted visual verification |
| 2026-10-07 | docs/TESTING.md | 1.12.92 | Align test guide version after rebuilt split/join package verification |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.0 | Connect four calculator screens to immutable saved results and nine existing export formats; note remaining visual/package evidence |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.0 | Record calculator snapshot and export UI wiring while retaining installed visual review gate |
| 2026-10-07 | docs/TESTING.md | 1.12.93 | Add calculator save/reopen/export fidelity, bounds and failure acceptance cases |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.1 | Reconcile outdated saved-result and screenshot-editor status after calculator snapshot UI wiring |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.1 | Reconcile older saved-result and screenshot-editor release-gate wording after calculator snapshot UI wiring |
| 2026-10-07 | API-CONTRACT.md | 1.74.62 | Document optional PNG/JPEG screenshot-edit output and bounded metadata-free attachments |
| 2026-10-07 | docs/TESTING.md | 1.12.94 | Add screenshot editor clipboard, ordered edit, export-boundary and cleanup acceptance coverage |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.2 | Record screenshot editor screen/API wiring and refresh catalogue/UI family totals |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.2 | Record screenshot editor UI, clipboard and PNG/JPEG export implementation with Mac verification gaps |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.3 | Add folder-comparison searchable UI, validated report/export evidence and refreshed exposure totals |
| 2026-10-07 | docs/TESTING.md | 1.12.95 | Specify folder-comparison UI states, selection invalidation, DTO checks and packaged Mac coverage |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.3 | Record F04 folder-comparison UI and update catalogue/UI exposure totals |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.4 | Correct UI-wired screen-count copy after adding folder comparison |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.5 | Add password/passphrase screen evidence and refresh catalogue, UI and depth totals |
| 2026-10-07 | docs/TESTING.md | 1.12.96 | Add ephemeral-secret UI, strict response, copy-permission and clearing checks |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.4 | Record searchable password/passphrase UI and update catalogue/UI audit totals |
| 2026-10-07 | API-CONTRACT.md | 1.74.63 | Update UI status for the existing password/passphrase APIs |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.6 | Connect similar-image burst finder to searchable workspace and refresh exposure totals |
| 2026-10-07 | docs/TESTING.md | 1.12.97 | Add similar-image format, threshold, hostile-name and burst-recall checks |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.5 | Record similar-image workbench wiring and update catalogue/UI counts |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.7 | Record searchable color converter UI and refresh catalogue exposure totals |
| 2026-10-07 | docs/TESTING.md | 1.12.98 | Add color converter screen and privacy regression checks |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.6 | Record color converter workbench wiring and update catalogue/UI counts |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.8 | Record source-specific conversion targets and remove unsupported fallback claims |
| 2026-10-07 | docs/TESTING.md | 1.12.99 | Add file-converter format-matrix and HTTP attachment checks |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.7 | Record tabular conversion targets, unsupported-input handling and current UI status |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.9 | Replace stale API-only split/join status with verified workbench coverage and current visual limitation |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.8 | Record focused split/join and PDF page-management verification results |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.10 | Add searchable EXIF cleanup screen and update UI wiring count |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.9 | Record EXIF cleanup UI verification and revised exposure counts |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.11 | Add single/batch image resize workbench and update UI exposure totals |
| 2026-10-07 | docs/TESTING.md | 1.12.100 | Document image resize workbench validation and backend fidelity coverage |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.10 | Record image resize UI wiring and revised capability audit |

| 2026-10-07 | API-CONTRACT.md | 1.74.64 | Document the typed local unit catalog endpoint |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.12 | Record scientific calculator and unit converter screens and revised UI exposure totals |
| 2026-10-07 | docs/TESTING.md | 1.12.101 | Add calculator screen, search and unit catalog verification guidance |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.11 | Record scientific and unit calculator UI wiring and current evidence |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.13 | Add searchable URL codec screen and update catalogue/UI exposure counts |
| 2026-10-07 | docs/TESTING.md | 1.12.102 | Add URL encoder/decoder UI, search and edge-case checks |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.12 | Record URL codec screen and revised capability audit |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.14 | Record four searchable financial calculator screens and revised exposure totals |
| 2026-10-07 | docs/TESTING.md | 1.12.103 | Add business calculator edge, UI, history and packaged smoke checks |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.13 | Record margin, break-even, simple-interest and depreciation UI wiring |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.15 | Add three searchable network workbench families; update exposure counts and evidence |
| 2026-10-07 | docs/TESTING.md | 1.12.104 | Add network DNS, ping, interface privacy, UI and package verification cases |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.14 | Record searchable DNS, ping and network-interface screen and remaining release checks |
| 2026-10-07 | API-CONTRACT.md | 1.74.65 | Update network diagnostics UI disclosure and user-triggered behavior notes |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.16 | Add searchable macOS system summary and resource overview; update exposure counts |
| 2026-10-07 | docs/TESTING.md | 1.12.105 | Add system report redaction, metrics reconciliation, manual refresh and package test guidance |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.15 | Record system information and CPU/RAM screens, strict clients and current visual verification gap |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.17 | Add searchable developer utilities workbench; update API/UI exposure totals |
| 2026-10-07 | docs/TESTING.md | 1.12.106 | Add local developer utilities validation and privacy checks |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.16 | Record developer workbench and revised UI coverage count |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.18 | Add selected-copy checksum and file-type screens; update family exposure counts |
| 2026-10-07 | docs/TESTING.md | 1.12.107 | Add selected-copy file hash and type report test guidance |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.17 | Record file inspector UI and revised catalogue exposure totals |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.19 | Add searchable file hash and file type detection screens; close API-only family gap |
| 2026-10-07 | docs/TESTING.md | 1.12.108 | Add file inspector packaged smoke and UI validation cases |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.18 | Record all families UI-routed and remaining release verification |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.20 | Record explicit statement number/date selectors and safety behavior |
| 2026-10-07 | docs/TESTING.md | 1.12.109 | Add statement locale and date interpretation checks |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.19 | Record statement extraction controls and remaining fixture gaps |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.21 | Show recursive storage folders; update depth and correct stale catalogue math |
| 2026-10-07 | docs/TESTING.md | 1.12.110 | Add storage folder totals, safe rendering and partial-scan validation |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.20 | Record storage screen depth improvement and release limitations |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.22 | Record conservative meeting-note action classification and regression coverage |
| 2026-10-07 | docs/TESTING.md | 1.12.111 | Add false-positive checks for questions, recommendations and passive future statements |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.21 | Track meeting-note heuristic reliability improvement and remaining D1 gaps |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.23 | Record packaged meeting-note false-positive smoke cases |
| 2026-10-07 | docs/TESTING.md | 1.12.112 | Require packaged meeting-note suggestion and commitment checks |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.22 | Track meeting-note packaged regression evidence |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.24 | Distinguish passive future states from progressive commitments |
| 2026-10-07 | docs/TESTING.md | 1.12.113 | Add active-progressive commitment and passive-status cases |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.23 | Record progressive commitment coverage for Meeting Notes |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.25 | Record fail-closed clipboard snapshot bounds for dictation paste-back |
| 2026-10-07 | docs/TESTING.md | 1.12.114 | Require complete bounded clipboard snapshots before mutation |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.24 | Track native clipboard snapshot edge case and remaining runtime test |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.26 | Record native Dictation clipboard and final-buffer safeguards |
| 2026-10-07 | docs/TESTING.md | 1.12.115 | Require final audio callback sample-state verification |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.25 | Track final-buffer race fix and installed microphone runtime gap |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.27 | Record Parakeet vocabulary repair and native verification boundary |
| 2026-10-07 | docs/TESTING.md | 1.12.116 | Require fresh and partial model-cache vocabulary checks |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.26 | Track Parakeet repair and remaining runtime verification |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.28 | Record Swift vocabulary-repair tests and native package evidence |
| 2026-10-07 | docs/TESTING.md | 1.12.117 | Add focused vocabulary repair regression test command |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.27 | Track three Swift setup tests and remaining clean-cache runtime check |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.29 | Record real Parakeet inference and corrupt-cache repair coverage |
| 2026-10-07 | docs/TESTING.md | 1.12.118 | Require cache-repair edge cases and document opt-in native inference |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.28 | Close fresh-model and offline-inference evidence gaps; retain installed microphone/Fn/paste gates |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.30 | Record real calculator/history/export WebKit verification and corrected reuse wiring |
| 2026-10-07 | docs/TESTING.md | 1.12.119 | Add isolated authenticated WebKit flow suite and Mac CI evidence requirements |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.29 | Track browser interaction progress without increasing release-ready counts |

| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.31 | Record readable snapshots, correct units and first-subset readiness boundary |
| 2026-10-07 | docs/TESTING.md | 1.12.120 | Add snapshot/list regressions and six deterministic first-release browser flows |
| 2026-10-07 | docs/RELEASE-123-TOOLS.md | 1.89.30 | Sequence verified subset before the full roadmap; hold reported statement failure |
| 2026-10-07 | docs/FIRST-MAC-RELEASE.md | 1.0.0 | Audit 45 entries into 16 priority, 23 next and 6 hold candidates |
| 2026-10-07 | API-CONTRACT.md | 1.74.65 → 1.74.66 | Declare startup-owned release scope, exact API allowlist and blocked operation behavior |
| 2026-10-07 | docs/FIRST-MAC-RELEASE.md | 1.0.0 → 1.0.1 | Confirm private beta, document 16-tool build and separate installed/distribution gates |
| 2026-10-07 | docs/TESTING.md | 1.12.120 → 1.12.121 | Add beta scope, startup-failure and packaged-subset verification commands |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.31 → 1.196.32 | Distinguish restricted beta candidates from full source and production certification |
| 2026-10-07 | docs/FIRST-MAC-RELEASE.md | 1.0.1 → 1.0.2 | Record 50 beta browser checks, final regression totals, package evidence and 4/5 milestone ledger |
| 2026-10-07 | docs/FIRST-MAC-RELEASE.md | 1.0.2 → 1.0.3 | Record final DMG/checksum and safe bounded eject retries with current test totals |
| 2026-10-07 | docs/TESTING.md | 1.12.121 → 1.12.122 | Add coordinate-based unruled statement PDF extraction cases |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.32 → 1.196.33 | Record unruled bank-statement PDF recovery and its source-file verification limit |
| 2026-10-07 | docs/TESTING.md | 1.12.122 → 1.12.123 | Verify undated statement summary rows are not exported as transactions |
| 2026-10-07 | docs/TESTING.md | 1.12.123 → 1.12.124 | Require packaged-sidecar unruled statement extraction smoke |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.33 → 1.196.34 | Record staged macOS sidecar statement-layout smoke evidence |
| 2026-10-07 | docs/TESTING.md | 1.12.124 → 1.12.125 | Require successful PDF protect/unlock attachment read-back checks |
| 2026-10-07 | docs/TOOL-GUIDE.md | 1.196.34 → 1.196.35 | Record PDF protect/unlock HTTP round-trip fidelity coverage |
| 2026-10-07 | docs/FIRST-MAC-RELEASE.md | 1.0.3 → 1.0.4 | Record current full regression and isolated development-profile DMG smoke boundary |

| 2026-10-08 | docs/TESTING.md | 1.12.125 → 1.12.126 | Require exact 127-byte normalized PDF password boundary through the packaged sidecar |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.10 → 1.0.11 | Record full regression, browser and Unicode password sidecar evidence; retain source-PDF access gap |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.11 → 1.0.12 | Record refreshed private-beta DMG smoke, checksum and ad-hoc-signing distribution blocker |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.12 → 1.0.13 | Record private-beta browser run and exact eight scope skips |
| 2026-10-08 | docs/TESTING.md | 1.12.126 → 1.12.127 | Add screenshot-shaped multi-date unruled statement PDF coverage |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.13 → 1.0.14 | Record the new synthetic statement-layout regression without claiming source-PDF verification |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.14 → 1.0.15 | Record updated full-suite, native Rust, FakeCloud and CDK synthesis results |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.22 → 1.0.23 | Record strict YAML file-import regression, full-suite result and refreshed macOS development DMG checksum |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.23 → 1.0.24 | Record fresh development/private-beta UI matrices and rebuilt restricted-profile DMG/sidecar smoke |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.24 → 1.0.25 | Record bounded XLSX import, spreadsheet display-value preservation and refreshed beta DMG verification |
| 2026-10-08 | API-CONTRACT.md | 1.74.69 → 1.74.70 | Specify bounded XLSX package and worksheet-shape validation |
| 2026-10-08 | docs/TESTING.md | 1.12.133 → 1.12.134 | Require hostile XLSX dimensions/archive and multipart 422 regression coverage |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.46 → 1.196.47 | Record bounded XLSX input preflight while retaining precision and sheet-selection gaps |
| 2026-10-08 | docs/RELEASE-123-TOOLS.md | 1.89.32 → 1.89.33 | Record XLSX archive and worksheet resource-bound checks |
| 2026-10-08 | docs/PITFALLS.md | New P-104 | Record unbounded XLSX package/dimension risk and prevention |

| 2026-10-08 | API-CONTRACT.md | 1.74.82 → 1.74.83 | Specify selectable local Parakeet model variants and state semantics |
| 2026-10-08 | docs/TESTING.md | 1.12.179 → 1.12.180 | Add model selection, persistence, cache and switch-safety regression requirements |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.79 → 1.196.80 | Record local model selection and remaining native inference verification |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.78 → 1.0.79 | Record v2/v3 inference, rebuilt Mac installer smoke and remaining distribution gates |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.82 → 1.0.83 | Record Qwen3-ASR local model selection, cached-model checks, native integration tests and remaining inference validation |

| 2026-10-08 | docs/RELEASE-123-TOOLS.md | 1.89.38 → 1.89.39 | Record v2/v3 local dictation selection and native inference verification |
| 2026-10-08 | API-CONTRACT.md | 1.74.84 → 1.74.85 | Add Qwen3-ASR to local model selection, setup, cache and transcription contracts |
| 2026-10-08 | docs/TESTING.md | 1.12.183 → 1.12.184 | Define Qwen3 gating, cache, switch-safety and real inference verification requirements |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.83 → 1.196.84 | Record Qwen3-ASR model choice, native route and remaining inference gate |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.83 → 1.0.84 | Record successful cached Qwen3 inference, CPU/Neural Engine stability and long-audio chunking |
| 2026-10-08 | API-CONTRACT.md | 1.74.85 → 1.74.86 | Specify bounded overlapping Qwen3 chunks for long dictation captures |
| 2026-10-08 | docs/TESTING.md | 1.12.184 → 1.12.185 | Record passing Qwen3 long-audio runtime verification |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.84 → 1.196.85 | Record verified Qwen3 runtime and chunked inference; retain installed-flow gaps |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.84 → 1.0.85 | Record dictation event-listener rollback/retry behavior and updated UI evidence |
| 2026-10-08 | docs/TESTING.md | 1.12.185 → 1.12.186 | Require CSP UI coverage for dictation listener failure recovery |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.85 → 1.196.86 | Record dictation event setup retry coverage without overstating native acceptance |

| 2026-10-08 | API-CONTRACT.md | 1.74.86 → 1.74.87 | Define conservative automatic parsing for ambiguous single-separator amounts |
| 2026-10-08 | docs/TESTING.md | 1.12.186 → 1.12.187 | Require comma and period ambiguity vectors with explicit locale resolution |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.86 → 1.196.87 | Record statement amount ambiguity fix and focused verification |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.85 → 1.0.86 | Record conservative amount parsing and direct-PDF verification gap |

| 2026-10-08 | API-CONTRACT.md | 1.74.87 → 1.74.88 | Specify nested JSON/YAML serialization across flat data-conversion formats |
| 2026-10-08 | docs/TESTING.md | 1.12.187 → 1.12.188 | Add nested-value, exact-decimal and null-format conversion cases |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.87 → 1.196.88 | Record nested tabular conversion behavior and remaining display-format gap |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.86 → 1.0.87 | Record nested JSON/YAML conversion fix and verification boundary |
| 2026-10-08 | API-CONTRACT.md | 1.74.88 → 1.74.89 | Specify conservative common XLSX numeric display preservation and fallback |
| 2026-10-08 | docs/TESTING.md | 1.12.188 → 1.12.189 | Require formatted XLSX numeric API cases, rounding and unsupported-format fallback |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.88 → 1.196.89 | Record common Excel display-format support and remaining complex-format gaps |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.87 → 1.0.88 | Record formatted XLSX coverage and current rebuilt Mac artifact |
| 2026-10-08 | docs/PITFALLS.md | New P-117 | Record standalone CSV dash escaping regression and prevention |
| 2026-10-08 | docs/TESTING.md | 1.12.189 → 1.12.190 | Add packaged-sidecar verification for common XLSX display formats |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.89 → 1.196.90 | Record authenticated-sidecar XLSX display-format coverage |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.88 → 1.0.89 | Record formatted XLSX sidecar smoke and current candidate evidence |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.89 → 1.0.90 | Record latest focused model, image, statement and mounted-installer verification boundaries |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.90 → 1.196.91 | Record latest focused verification and outstanding installed-Mac evidence |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.90 → 1.0.91 | Record configurable dictation push-to-talk keys and native acceptance boundary |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.196.91 → 1.196.92 | Record modifier-key dictation configuration coverage and remaining native acceptance |
| 2026-10-08 | docs/TESTING.md | 1.12.190 → 1.12.191 | Require push-to-talk key mapping, persistence and installed event-delivery coverage |
| 2026-10-08 | docs/PITFALLS.md | New P-115 | Record Fn-only dictation shortcut limitation and regression checks |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.115 → 1.0.116 | Record real supplied-statement desktop/compact CSV verification and rebuilt mounted DMG smoke, including signing and native-interaction limits |
| 2026-10-08 | docs/PITFALLS.md | New P-123 | Record release-profile mismatch in private-beta calculator smoke and the route-set regression |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.116 → 1.0.117 | Record private-beta WebKit and mounted-DMG smoke results and the profile-aware smoke correction |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.17 → 1.197.18 | Record file-checksum comparison, discovery aliases and real desktop/compact coverage |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.117 → 1.0.118 | Record full development-profile test installer and checksum-comparison smoke results |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.118 → 1.0.119 | Record full UI/backend/Rust suites, actual Parakeet and Qwen local inference, and exact test-installer verification limits |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.119 → 1.0.120 | Verify Parakeet v2 inference in addition to v3 and Qwen3 for every selectable Mac dictation model |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.18 → 1.197.19 | Record passing generated-speech Core ML inference for all three selectable Mac dictation models |
| 2026-10-08 | docs/PITFALLS.md | New P-125 | Record false-positive meeting action classification for static obligations and its engine/API/sidecar regression |
| 2026-10-08 | docs/FIRST-MAC-RELEASE.md | 1.0.120 → 1.0.121 | Record meeting-notes classification fix, full test results and rebuilt mounted DMG fingerprint |
| 2026-10-08 | docs/TOOL-GUIDE.md | 1.197.19 → 1.197.20 | Record static-state action exclusion, expanded notes benchmark and packaged-sidecar proof |
| 2026-10-09 | docs/PITFALLS.md | New P-146 | Record unrelated HEIC fixture false-positive smoke expectation and corrected regression coverage |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.168 → 1.0.169 | Correct HEIC fixture claims and record positive duplicate matching, cross-scene separation and passing packaged smoke |
| 2026-10-09 | docs/PITFALLS.md | New P-147 | Record CORS-hidden PDF text metadata and the browser regression that prevents recurrence |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.169 → 1.0.170 | Record supplied-statement desktop/compact UI proof, green full UI matrix and refreshed private-beta DMG verification |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.170 → 1.0.171 | Add passing private-beta UI evidence and the verified latest installer SHA-256 |
| 2026-10-09 | docs/TOOL-GUIDE.md | 1.197.69 → 1.197.70 | Refresh current Mac release evidence and remove superseded WebKit/DMG failure claims |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.171 → 1.0.172 | Record passing PDF text desktop/compact browser flow and current beta gate evidence |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.172 → 1.0.173 | Record promotion of tested lossless PDF compression into 30-tool private beta |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.173 → 1.0.174 | Record rebuilt, mounted-smoke-tested 30-tool Apple Silicon beta installer and fingerprint |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.174 → 1.0.175 | Add PDF page-to-image export to private-beta scope and define desktop/compact acceptance |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.175 → 1.0.176 | Record PDF page-to-image promotion into the 31-tool private beta and acceptance coverage |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.176 → 1.0.177 | Record verified 31-tool Apple Silicon installer and SHA-256 fingerprint |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.177 → 1.0.178 | Add tested PDF metadata removal to the 32-tool private beta and update gates |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.178 → 1.0.179 | Record current 32-tool Mac beta installer, full gate, supplied-statement mounted smoke and fingerprint |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.179 → 1.0.180 | Promote tested selectable PDF table export to the private beta and update the remaining candidate count |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.180 → 1.0.181 | Record the 33-tool DMG and packaged CSV/XLS/XLSX acceptance against the supplied statement |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.190 → 1.0.191 | Record the verified 42-tool Mac beta DMG, sidebar categories, System tools and Dictation/Meeting Notes acceptance |
| 2026-10-09 | docs/FIRST-MAC-RELEASE.md | 1.0.189 → 1.0.190 | Record 42-tool source scope with Dictation and System tools; note that the refreshed test installer is pending |
| 2026-10-12 | docs/PITFALLS.md | P-151 updated | Record microphone TCC mismatch, switch to AVFoundation capture authorization, and document ad-hoc code-signing identity limits across rebuilt installers |
| 2026-10-12 | docs/PITFALLS.md | P-151 corrected | Record regression to AVAudioApplication, restore AVFoundation authorization, and guard it with native and UI regression tests |
| 2026-10-12 | docs/PITFALLS.md | P-151 extended | Require main-queue microphone authorization and visible pending feedback; add click-path regression coverage |
| 2026-10-18 | docs/lld/archive-manager.md | 1.0.5 → 1.0.6 | Record approved unsupported-format and browse-only selection warnings |
| 2026-10-18 | docs/lld/archive-manager.md | 1.0.6 → 1.0.7 | Record archive engine and API regression coverage with platform verification limits |
| 2026-10-18 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/PRD.md / docs/TOOL-GUIDE.md | 1.74.122 → 1.74.123 / 1.0.7 → 1.0.8 / 1.0.3 → 1.0.4 / 1.0.4 → 1.0.5 / 1.197.77 → 1.197.78 | Wire approved PDF fidelity and crop disclosures; enable packaged PDF visual/crop operations; add approved public URL preview UI that consumes its one-use grant only when starting a job; update current capability and limitation records. |

| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md | 1.0.5 → 1.0.6 / 1.1.4 → 1.1.5 / 1.0.10 → 1.0.11 / 1.12.256 → 1.12.257 / 1.197.83 → 1.197.84 | Add a typed source-checkout CLI adapter over the existing media operation DTO and engine; enforce bounded input, batch limits, and exclusive no-overwrite output; record standalone packaging as outstanding. |
| 2026-10-18 | docs/FIRST-MAC-RELEASE.md / docs/TOOL-GUIDE.md / docs/RELEASE-123-TOOLS.md | 1.0.193 → 1.0.194 / 1.197.84 → 1.197.85 / 1.89.43 → 1.89.44 | Add Media Toolkit to catalogue/release counts as development-only and held outside private beta; correct source-family totals. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md | 1.0.15 → 1.0.16 / 1.1.7 → 1.1.8 / 1.0.23 → 1.0.24 | Add bounded macOS AVFoundation video-to-GIF conversion with truthful capability reporting and DMG acceptance for decoded GIF output and unchanged source files. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md | 1.0.16 → 1.0.17 / 1.1.8 → 1.1.9 / 1.0.24 → 1.0.25 | Add bounded macOS AVFoundation video cropping with crop-bound validation, exact output-dimension smoke checks, and unchanged source-file verification. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md | 1.0.17 → 1.0.18 / 1.1.9 → 1.1.10 / 1.0.25 → 1.0.26 | Add off-by-default macOS clipboard image preparation using pasteboard revision changes, explicit bypass, shared staged media jobs, and opt-out-safe clipboard delivery. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md | 1.0.18 → 1.0.19 / 1.1.10 → 1.1.11 / 1.0.26 → 1.0.27 | Bundle the typed Media Toolkit CLI in the macOS app and add mounted-installer smoke coverage for real output and no-overwrite behavior. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md | 1.0.19 → 1.0.20 / 1.1.11 → 1.1.12 / 1.0.27 → 1.0.28 | Bundle a local stdio MCP server over the shared media operation contract and record its discovery, conversion, validation and collision coverage. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md | 1.0.20 → 1.0.21 / 1.1.12 → 1.1.13 / 1.0.28 → 1.0.29 | Add a shared result format control for typed image, video and audio output formats, including pipeline recipes. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md | 1.0.21 → 1.0.22 / 1.1.13 → 1.1.14 / 1.0.29 → 1.0.30 | Add searchable local operation defaults that store only validated option values, with a bounded storage size and clear-all control. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md | 1.0.14 → 1.0.15 / 1.1.6 → 1.1.7 / 1.0.22 → 1.0.23 | Add bounded, packaged macOS AVFoundation transforms for video speed and mute; report truthful runtime availability and verify real output duration, tracks, and source preservation in DMG acceptance. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md | 1.0.22 → 1.0.23 / 1.1.14 → 1.1.15 / 1.0.30 → 1.0.31 / 1.12.257 → 1.12.258 | Add bounded macOS AVFoundation and ImageIO resizing of embedded audio artwork into a separate M4A copy; report runtime availability and document package acceptance. |
| 2026-10-18 | API-CONTRACT.md / docs/PRD.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md / review/clop-media-toolkit/requirements.md | 1.74.132 → 1.74.133 / 1.0.12 → 1.0.13 / 1.1.19 → 1.1.20 / 1.0.35 → 1.0.36 / 1.12.262 → 1.12.263 / 1.197.88 → 1.197.89 / 1.0.28 → 1.0.29 | Add approved preset-zone management controls that bind local zones to saved pipelines, reset enabled state after relaunch, and load selected presets into the manual prepare flow. |
| 2026-10-18 | API-CONTRACT.md / docs/PRD.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md / review/clop-media-toolkit/requirements.md | 1.74.133 → 1.74.134 / 1.0.13 → 1.0.14 / 1.1.20 → 1.1.21 / 1.0.36 → 1.0.37 / 1.12.263 → 1.12.264 / 1.197.89 → 1.197.90 / 1.0.29 → 1.0.30 | Register native bounded target rectangles for enabled preset zones and run their saved allowlisted pipeline via read-only grants and the normal local job route. |
| 2026-10-18 | API-CONTRACT.md / docs/PRD.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.134 → 1.74.135 / 1.0.14 → 1.0.15 / 1.1.21 → 1.1.22 / 1.0.37 → 1.0.38 / 1.12.264 → 1.12.265 / 1.0.30 → 1.0.31 | Add opt-in Control+Shift+C image preparation with local job routing, explicit clipboard writeback, and no implicit clipboard monitoring. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md | 1.0.31 → 1.0.32 | Clarify that clipboard image processing is implemented while downscale/crop shortcut variants and Finder Quick Action remain open. |
| 2026-10-18 | review/clop-media-toolkit/requirements.md | 1.0.32 → 1.0.33 | Add local MCP listing and creation of strict saved media pipelines; record remaining update/delete and automation-settings gaps. |
| 2026-10-18 | docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md | 1.1.22 → 1.1.23 / 1.0.39 → 1.0.40 / 1.12.265 → 1.12.266 | Document MCP saved-pipeline list/create, package tool discovery, and the updated native shortcut and preset-drop status. |
| 2026-10-18 | docs/TOOL-GUIDE.md | 1.197.90 → 1.197.91 | Update Media Toolkit status for the explicit clipboard shortcut and packaged MCP pipeline list/create tools. |
| 2026-10-18 | docs/lld/media-toolkit.md | 1.0.38 → 1.0.39 | Record approved preset-zone UI coverage and retain the physical native drag gesture as an installed-app verification gap. |
| 2026-10-18 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.142 → 1.74.143 / 1.1.31 → 1.1.32 / 1.0.49 → 1.0.50 / 1.12.274 → 1.12.275 / 1.0.41 → 1.0.42 | Add safe saved-pipeline rebinding for preset zones and omit session-only enablement from subprocess MCP mutation results. |
| 2026-10-19 | API-CONTRACT.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / review/clop-media-toolkit/requirements.md | 1.74.149 → 1.74.150 / 1.1.39 → 1.1.40 / 1.0.66 → 1.0.67 / 1.0.59 → 1.0.60 | Document private clipboard and drop-zone pipeline trigger bindings across API, design, implementation, and feature scope. |
| 2026-10-19 | API-CONTRACT.md | 1.74.150 → 1.74.151 | Correct the media capability response contract and documented inventory to 25 operations. |
| 2026-10-19 | docs/TESTING.md | 1.12.289 → 1.12.290 | Update packaged MCP smoke inventory to include pipeline-trigger tools. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md | 1.0.69 → 1.0.70 | Recheck parity against installed Clop 3.6.0, record the complete CLI command surface, and list concrete operation and automation gaps. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md | 1.0.70 → 1.0.71 | Compare Clop's installed pipeline DSL prompt and record missing typed filters, fork/file actions, pipeline integrations, and secure send. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md | 1.0.71 → 1.0.72 / 1.0.77 → 1.0.78 / 1.12.313 → 1.12.314 / 1.197.108 → 1.197.109 | Add factor-based image downscaling to the typed CLI and MCP presets through the shared bounded image-resize operation; factor one preserves bytes, output publication remains copy-only, and source hashes are verified. |
| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md | 1.0.78 → 1.0.79 / 1.12.314 → 1.12.315 | Record successful packaged DMG smoke coverage for downscale dimensions, byte-identical factor-one copies, packaged MCP discovery and execution, and unchanged sources. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / API-CONTRACT.md / docs/TOOL-GUIDE.md / docs/PRD.md | 1.0.72 → 1.0.73 / 1.1.49 → 1.1.50 / 1.0.79 → 1.0.80 / 1.12.315 → 1.12.316 / 1.74.161 → 1.74.162 / 1.197.109 → 1.197.110 / 1.0.27 → 1.0.28 | Add typed `pdf-uncrop` and CLI/MCP `uncrop-pdf` preset; restore CropBox to MediaBox in a new searchable copy, preserve sources, and add engine, interface, and packaged smoke evidence. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md / docs/hld/media-toolkit.md / docs/lld/media-toolkit.md / docs/TESTING.md / docs/TOOL-GUIDE.md / docs/PRD.md | 1.0.73 → 1.0.74 / 1.1.50 → 1.1.51 / 1.0.80 → 1.0.81 / 1.12.316 → 1.12.317 / 1.197.110 → 1.197.111 / 1.0.28 → 1.0.29 | Add CLI schema/list/get/set/clear for typed operation defaults through the same private store used by the desktop Automation view and MCP; support clearing one operation without affecting others. |
| 2026-10-19 | docs/TESTING.md | 1.12.317 → 1.12.318 | Record latest full Node/Python/macOS suites and fresh packaged DMG acceptance for PDF uncrop and isolated typed CLI settings. |
| 2026-10-19 | API-CONTRACT.md / review/clop-media-toolkit/requirements.md / docs/TESTING.md | 1.74.162 → 1.74.163 / 1.0.74 → 1.0.75 / 1.12.318 → 1.12.319 | Correct the Media Toolkit inventory to 26 operation IDs and record the passing 32-case desktop/compact browser run plus the interrupted full UI suite and its unrelated overflow failure. |
| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.104 → 1.0.105 / 1.12.346 → 1.12.347 / 1.0.98 → 1.0.99 | Add final-only typed PDF page image export to the bounded pipeline DSL; verify ordered ZIP outputs, cancellation, invalid step rejection, and source preservation. |
| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.105 → 1.0.106 / 1.12.347 → 1.12.348 / 1.0.99 → 1.0.100 | Add bounded audio `changeSpeed` as a typed local M4A pipeline operation and verify packaged duration/source preservation. |
| 2026-10-19 | review/clop-media-toolkit/requirements.md | 1.0.100 → 1.0.101 | Reconcile the parity summary with PDF page export and audio speed pipeline support. |
| 2026-10-19 | API-CONTRACT.md / docs/lld/media-toolkit.md / review/clop-media-toolkit/requirements.md | 1.74.163 → 1.74.164 / 1.0.106 → 1.0.107 / 1.0.101 → 1.0.102 | Add a private staged-logo, local AVFoundation video watermark pipeline step; retain audio, preserve the source, and keep workbench controls behind the approved-mock gate. |
| 2026-10-19 | docs/TESTING.md | 1.12.348 → 1.12.349 | Record full-suite, desktop/compact UI, and fresh mounted-DMG verification for video watermarking, including decoded-frame visibility, source preservation, and audio retention. |
| 2026-10-19 | API-CONTRACT.md / docs/PRD.md | 1.74.164 → 1.74.165 / 1.0.31 → 1.0.32 | Reconcile the 27-operation desktop capability surface with the 30-operation typed model and document PDF page export, audio speed, and video watermarking as pipeline-only additions. |
| 2026-10-19 | API-CONTRACT.md / docs/PRD.md / docs/lld/media-toolkit.md / docs/TOOL-GUIDE.md | 1.74.165 → 1.74.166 / 1.0.32 → 1.0.33 / 1.0.107 → 1.0.108 / 1.197.116 → 1.197.117 | Add runtime-probed local FFmpeg video targets for H.264 MP4, VP9 WebM, and software x265/HEVC MP4 through typed jobs, CLI, and MCP; keep the desktop selector behind mock approval. |
| 2026-10-19 | docs/TESTING.md | 1.12.349 → 1.12.350 | Record bounded runtime-probed H.264, VP9, and x265 acceptance, including packaged codec, audio, decode, and source-preservation checks. |
| 2026-10-19 | API-CONTRACT.md / docs/lld/media-toolkit.md / docs/TESTING.md | 1.74.166 → 1.74.167 / 1.0.108 → 1.0.109 / 1.12.350 → 1.12.351 | Add a typed 5–100 H.264 MP4 compression factor, safe pipeline DSL syntax, encoder mapping, and packaged decode/source-preservation acceptance. |
| 2026-10-19 | API-CONTRACT.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.168 → 1.74.169 / 1.0.110 → 1.0.111 / 1.12.352 → 1.12.353 / 1.0.104 → 1.0.105 | Separate adaptive image quality from image-format adaptation, and map Clop's 5–100 compression factor across image, video, and audio operations. |
| 2026-10-19 | API-CONTRACT.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.169 → 1.74.170 / 1.0.111 → 1.0.112 / 1.12.353 → 1.12.354 / 1.0.105 → 1.0.106 | Add bounded crop sizing and source-aware lowerBitrate pipeline steps, composing existing local crop, resize, and audio optimize operations. |
| 2026-10-19 | API-CONTRACT.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.170 → 1.74.171 / 1.0.112 → 1.0.113 / 1.12.354 → 1.12.355 / 1.0.106 → 1.0.107 | Add explicit inline PDF encoder/DPI choices, preserving the default lossless path. |
| 2026-10-19 | API-CONTRACT.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.171 → 1.74.172 / 1.0.113 → 1.0.114 / 1.12.355 → 1.12.356 / 1.0.107 → 1.0.108 | Add typed lossless WebP/JPEG XL conversion and safe inline DSL control; reject unsupported target formats and preserve default recipe compatibility. |
| 2026-10-19 | API-CONTRACT.md / docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.74.172 → 1.74.173 / 1.0.114 → 1.0.115 / 1.12.356 → 1.12.357 / 1.0.108 → 1.0.109 | Add bounded Clop-style first-step regex, type, file-size, and image-dimension filters to the pipeline DSL. |
| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.115 → 1.0.116 / 1.12.357 → 1.12.358 / 1.0.109 → 1.0.110 | Add inline `fork()` snapshots that publish collision-safe intermediate copies while continuing the main pipeline; reject fork side effects in saved pipelines. |
| 2026-10-19 | docs/lld/media-toolkit.md / docs/TESTING.md / review/clop-media-toolkit/requirements.md | 1.0.116 → 1.0.117 / 1.12.358 → 1.12.359 / 1.0.110 → 1.0.111 | Add bounded local image DPI filters to inline pipelines; missing metadata fails closed, with PDF DPI filters retained as an explicit gap. |
| 2026-10-20 | API-CONTRACT.md | 1.74.177 → 1.75.0 | Global desktop settings endpoint (POST), window manager settings |
| 2026-10-20 | docs/TESTING.md | 1.12.373 → 1.12.374 | Add global desktop tools automated and installed-app evidence section |
| 2026-10-20 | docs/FIRST-MAC-RELEASE.md | 1.0.195 → 1.0.196 | Add global desktop tools manual acceptance checklist |
| 2026-10-20 | docs/hld/global-desktop-tools.md | 1.0.0 → 1.0.1 | Add launcher (⌃⌥Space) section; file drop deferred |
| 2026-10-20 | docs/TESTING.md | 1.12.374 → 1.12.375 | Add launcher installed-app check |
| 2026-10-20 | API-CONTRACT.md | 1.75.0 → 1.75.1 | Merge global desktop settings with dictation quality command results |
| 2026-10-21 | docs/ARCHITECTURE.md | 1.0.5 → 1.0.6 | Add paid activation ADR: email + key, gates, gated delivery; encryption dropped |
| 2026-10-21 | API-CONTRACT.md | 1.75.1 → 1.76.0 | Design hosted licensing contract: email + key, downloads, Dodo webhook, local entitlement gate |
| 2026-10-21 | docs/hld/paid-activation.md | — → 1.0.0 | New HLD for paid activation S1–S7 |
| 2026-10-21 | docs/hld/licensing-service.md | 1.2.0 → 1.3.0 | Mark superseded in part by the paid-activation HLD |
| 2026-10-21 | docs/LICENSING-PLAN.md | 1.2.5 → 1.3.0 | Single installer, no Free edition, email + key; encryption not used |
| 2026-10-21 | docs/hld/paid-activation.md | 1.0.0 → 1.1.0 | DBA pass: items, ledger IAM boundary, revoke/deactivate/reactivate, repository interfaces, email retry fix |
| 2026-10-21 | API-CONTRACT.md | 1.76.0 → 1.76.1 | Webhook returns 503 on email failure; pending key rotates on retry |
| 2026-10-21 | docs/hld/paid-activation.md | 1.1.0 → 1.2.0 | Owner agreed the HLD; record quantity, revocation and download-page decisions |
| 2026-10-21 | docs/hld/paid-activation.md | 1.2.0 → 1.2.1 | Client checks email_sha256 shape instead of recomputing it |
| 2026-10-21 | API-CONTRACT.md | 1.76.1 → 1.76.2 | Client checks email_sha256 shape instead of recomputing it |
| 2026-10-21 | docs/lld/paid-activation.md | — → 1.0.0 | New LLD for paid activation S1–S3 |
| 2026-10-21 | API-CONTRACT.md | 1.76.2 → 1.76.3 | List route 422 and header-failure behavior documented as built |
| 2026-10-21 | docs/hld/paid-activation.md | 1.2.1 → 1.2.2 | Point at the restored contract heading |
| 2026-10-21 | API-CONTRACT.md | 1.76.3 → 1.76.4 | Restore the "Target hosted licensing API — not implemented" heading pinned by tests/test_api_contract_unittest.py |
| 2026-10-21 | docs/lld/paid-activation.md | 1.0.0 → 1.0.1 | As-built note for S1 server (email, list, deactivate, re-activation) |
| 2026-10-21 | API-CONTRACT.md | 1.76.4 → 1.76.5 | Per-resource implementation status and the server email grammar (review round 1 ARCH-1, ARCH-2) |
| 2026-10-21 | docs/lld/paid-activation.md | 1.0.1 → 1.0.2 | Review round 1 decisions (LeadingKeys is an S2 gate, findById trigger, helper-copy plan, display-only seat count, reserved TTL name); remove stale list-422 sentence |
| 2026-10-21 | review/paid-activation/requirements.md | 0.2 → 0.3 | AC1 amended by the owner ("Amend AC1 (Recommended)") after review round 1 |
| 2026-10-21 | docs/lld/paid-activation.md | 1.0.2 → 1.0.3 | Round 2 nits: fix the header-endpoints 422 sentence, note response-DTO schemas due before S2 (CR-7, ARCH-7, ARCH-3) |
| 2026-10-21 | docs/lld/paid-activation.md | 1.0.3 → 1.1.0 | Verified Dodo webhook contract (events, payload fields, Standard Webhooks scheme) and "As built (S2 server)" |
| 2026-10-21 | API-CONTRACT.md | 1.76.5 → 1.76.6 | S2 server built: verified webhook payload fields, implementation status for downloads and webhook, `no_build` for updates window or tier, `entitlement_grant.revoked` fails closed |
| 2026-10-21 | docs/lld/paid-activation.md | 1.1.0 → 1.2.0 | "As built (S2 infra)": two-Lambda split, LeadingKeys boundary, installer bucket, webhook route throttle, NoEcho secret decision, alarms and cost |
| 2026-10-21 | docs/hld/paid-activation.md | 1.2.2 → 1.2.3 | S2 review round 1: issuance lease for PENDING rotation, refund-before-payment tombstone, transaction items authorized as PutItem/UpdateItem (QA-1, CR-2, DBA-3) |
| 2026-10-21 | docs/lld/paid-activation.md | 1.2.0 → 1.3.0 | S2 review round 1: issuer role PutItem fix and derived-action test, lease, tombstone, cancellation reasons, SES FromAddress/region guards, 4xx alarm, secret pattern, cost and concurrency notes (CR-1..9, ARCH-1..4, DBA-1..5, QA-1..4, DEVOPS-1..7) |
| 2026-10-21 | API-CONTRACT.md | 1.76.6 → 1.76.7 | S2 review round 1: webhook status list (401 header failures, 400 timestamp only, 429, unfamiliar event types 200), delivery lease, refund-before-payment tombstone, download 201 note (ARCH-2, ARCH-3, ARCH-4, CR-7, QA-1, CR-2) |
| 2026-10-21 | docs/hld/paid-activation.md | 1.2.3 → 1.2.4 | S2 review round 2: early-refund tombstone shape qualified (no tenant_id/license_id) in the data model and cross-tenant paragraph (ARCH-5); owner decisions PM-1, PM-2, PM-4, PM-5 recorded |
| 2026-10-21 | docs/lld/paid-activation.md | 1.3.0 → 1.4.0 | S2 review round 2: owner decisions PM-1/PM-2/PM-4/PM-5, `unsupported_payment_payload` alarm (nine alarms), lease fails closed on bad updated_at (CR-10), tombstone no-TTL note (ARCH-6), lease vs Lambda timeout test (QA-5) |
| 2026-10-21 | review/paid-activation/requirements.md | 0.3 → 0.4 | Record owner decisions PM-1 (owner-pending sample), PM-2, PM-4, PM-5 with their exact answers and date |
| 2026-10-22 | API-CONTRACT.md / docs/TOOL-GUIDE.md / docs/TESTING.md | 1.77.0 → 1.77.1 / 1.197.120 → 1.197.121 / 1.12.383 → 1.12.384 | Add the plain dictionary word list (`words`), per-stage `steps` and capture numbers for the dictation history steps view, with engine, Rust, unit and browser evidence. |
| 2026-10-22 | API-CONTRACT.md / docs/TOOL-GUIDE.md / docs/TESTING.md | 1.78.0 → 1.78.1 / 1.197.122 → 1.197.123 / 1.12.384 → 1.12.385 | Record every dictation attempt in history: `dictation-attempt-failed` event, `model` and `pieces` on the transcript event, word-loss flags and failure views, with Rust, unit and browser evidence. |
| 2026-10-22 | API-CONTRACT.md / docs/TOOL-GUIDE.md / docs/TESTING.md | 1.78.1 → 1.78.2 / 1.197.123 → 1.197.124 / 1.12.385 → 1.12.386 | Add the reminder bubble Close button (Pause all becomes a link) and three guided eye-rest steps, with browser evidence. |
| 2026-10-22 | API-CONTRACT.md / docs/TOOL-GUIDE.md / docs/TESTING.md | 1.78.2 → 1.78.3 / 1.197.124 → 1.197.125 / 1.12.386 → 1.12.387 | Add the `open` action to `ergonomics_calendar_action` (opens the macOS Calendar app), the calendar list count, loading state and per-calendar Open in Calendar row action, with browser evidence. |
| 2026-10-22 | docs/TOOL-GUIDE.md / docs/TESTING.md | 1.197.127 → 1.197.128 / 1.12.387 → 1.12.388 | Launcher tool rows use the catalog icon (SF Symbol) in a softened category colour; Swift logic and Rust icon-string tests. |

| 2026-10-22 | API-CONTRACT.md / docs/TOOL-GUIDE.md / docs/TESTING.md | 1.79.1 → 1.79.2 / 1.197.128 → 1.197.129 / 1.12.388 → 1.12.389 | Detailed menu-bar drawers: memory, pressure, swap, CPU split, load, uptime and disk throughput on /api/system/metrics; Quit limited to the signed-in user own non-root processes outside OfficeKit process tree; Swift, Python, Node and Playwright evidence. |

| 2026-10-22 | API-CONTRACT.md / docs/TOOL-GUIDE.md / docs/TESTING.md | 1.79.2 → 1.80.0 / 1.197.129 → 1.198.128 / 1.12.389 → 1.12.390 | Split global tools settings: Global Launcher tool with its own launcher switch, shortcut, result kinds and quick-result switches; snippets panel switch; clipboard capture pause (15 min, 1 hour, until resume) with banner, Resume and menu-bar row; Panel opens on filter. New fields default on and load from older files; Rust, Python, Swift, Node and browser evidence. |
| 2026-10-22 | docs/TESTING.md | 1.12.390 → 1.12.391 | Mascot sprite animation (water, eyes, break ready) loops instead of holding the last frame; browser frame-sequence evidence. |
| 2026-10-22 | API-CONTRACT.md / docs/TOOL-GUIDE.md / docs/TESTING.md | 1.85.1 → 1.85.2 / 1.198.131 → 1.198.132 / 1.12.390 → 1.12.391 | Reminder bubble and mascot fade in as a teaser (meeting 30 → 5 minutes, wellness reminders last 2 minutes) with overlap rules, mascot animation loops; Rust and browser evidence. |
| 2026-10-23 | docs/TESTING.md | 1.12.391 → 1.12.392 | Speech Coach panel layout: Swift checks for the measuring line, level bars and which controls show per mode (coach-only, dictation, both). |
| 2026-10-23 | docs/TESTING.md | 1.12.392 → 1.12.393 | Speech Coach Live Workspace: Rust tests for the memory-only transcript and fixes, window-command access rule and structured suggestion parsing; WebKit Playwright spec for the panel states. |
| 2026-10-23 | docs/TESTING.md | 1.12.393 → 1.12.394 | Speech Coach and Listen In separated (Listen In is a runtime-only solo session; the coach joins a dictation only while it records); Rust and Swift tests for attach, release and restore; mascot-click reopen guard test. |
| 2026-10-23 | docs/TESTING.md | 1.12.394 → 1.12.395 | Speech Coach panel close button and livelier level bars: Swift checks for button visibility, bar placement and heights; Rust test that closing ends Listen In and keeps Speech Coach on. |
| 2026-10-23 | docs/TESTING.md | 1.12.395 → 1.12.396 | Menu bar stats switches in Quick controls (CPU, RAM, Storage, Network): Rust tests for independent switches, one-time carry-over of the old single switch, saved file and main-window-only commands; Playwright specs for the four switches and for drawers filtered by what is on; reminder bubble no longer stretches to the window height. |
| 2026-10-23 | docs/TESTING.md | 1.12.396 → 1.12.397 | Quick controls grouped into Speech, Desktop and Menu bar stats: Playwright check of group headings and which switches sit in each, and the taller window height limit. |
| 2026-10-23 | docs/TESTING.md | 1.12.397 → 1.12.398 | Launcher lists window layouts and Quick controls (Rust row, entry and item-limit tests; Swift chip-filter checks); Clipboard history switch (Rust mapping test, Playwright spec) and the taller Quick controls window. |
| 2026-10-23 | docs/TESTING.md | 1.12.398 → 1.12.399 | Mascot sprite: each cell skips its top edge so the feet of the pose above no longer show under the reminder bubble; Playwright test plays all 16 preview frames and checks the top rows stay empty (seen to fail without the fix). |
| 2026-10-23 | docs/TESTING.md | 1.12.399 → 1.12.400 | Mascot close no longer opens the main window: a reopen while the mascot is on screen is ignored (replaces the pointer-position check, which did not catch the owner's click); Rust test for the visible check. Hiding and showing the real window is covered by the installed check only. |
| 2026-10-23 | docs/TESTING.md | 1.12.400 → 1.12.401 | First-run setup: WebKit Playwright specs for the model picker and download, the access list with the features each permission serves, tools staying off when their access was skipped, setup running before the tour, feature-page access banners, and the Quick controls "Needs access" switch text. |
| 2026-10-23 | docs/FIRST-MAC-RELEASE.md | 1.0.209 → 1.0.210 | Ergonomics (five reminder tools) ships in every build including private beta, by owner decision; the profile now exposes 49 tools. Installed-Mac acceptance still required. |
| 2026-10-23 | docs/TOOL-GUIDE.md | 1.198.143 → 1.198.144 | Ergonomics reminders ship in every build (owner decision); five IDs added to release-profile.json. |
| 2026-10-23 | docs/TESTING.md | 1.12.401 → 1.12.402 | Ergonomics in every build: Rust access and start-gate tests, release-profile test (49 tools), private-beta banner counts. |
| 2026-10-23 | docs/TESTING.md | 1.12.402 → 1.12.403 | General settings card and the saved setup file: Rust settings-file tests, WebKit spec for the card, permission actions and first-time detection. |
| 2026-10-23 | docs/TESTING.md | 1.12.403 → 1.12.404 | General settings fixes: camelCase desktop settings with a strict mock, Configure links, Calendar real status, background model download, contrast in both themes. |
| 2026-10-23 | docs/TESTING.md | 1.12.404 → 1.12.405 | Speech Coach card and model-change fixes: WebKit specs for the card, search and no Report bug on non-errors, General model download specs, release profile counts 50 tools. |
| 2026-10-23 | docs/FIRST-MAC-RELEASE.md | 1.0.210 → 1.0.211 | Speech Coach catalogue card (speech_coach); profile now exposes 50 tools. |
| 2026-10-23 | docs/TOOL-GUIDE.md | 1.198.144 → 1.198.145 | Speech Coach catalogue card in Audio & Dictation. |
| 2026-10-23 | docs/TESTING.md | 1.12.405 → 1.12.406 | Setup, General and the tool pages read one source for switches and shortcut keys; setup keeps scroll and focus while polling. |
| 2026-10-23 | docs/TESTING.md | 1.12.406 → 1.12.407 | Setup dialog keeps its buttons in view in a short window and no longer clips the selected model. |
| 2026-10-23 | docs/TESTING.md | 1.12.407 → 1.12.408 | Agent skill for Codex and Claude Code (Rust and WebKit tests); overlay failure wording test. |
| 2026-10-23 | docs/TESTING.md | 1.12.408 → 1.12.409 | Setup order (access, tools, model download last) and its WebKit tests; Quick controls fits short screens (Rust test); hotkey changes notify every window. |
| 2026-10-24 | docs/TESTING.md | 1.12.409 → 1.12.410 | Meeting Notes layout and button-budget WebKit tests; launcher meeting-recording row (Rust); Include subfolders checkbox test; setup bar and MCP tab alignment. |
| 2026-10-24 | docs/TESTING.md | 1.12.410 → 1.12.411 | Live calculators and System page live CPU/memory (WebKit `live-results` spec, source tests); network rates use B/KB/MB/GB so large values stay short. |
| 2026-10-26 | docs/PITFALLS.md | New version 1.0.0 | Establish a version header and record the cue-specific animation assertion gap with its mutation-verified regression test (P-254). |

| 2026-10-27 | API-CONTRACT.md | 1.93.0 → 1.93.1 | Document the optional `fixGrammar` argument of `dictation_cleanup_and_paste` and the `grammar_text` / `grammar_fixes` fields of `steps`. |
| 2026-10-28 | docs/verification/speech-model-memory.md | 1.0.0 → 1.0.1 | Record final first-use Whisper memory measurements, full test gates, mutation evidence and the outstanding reviewer sign-off limitation. |
| 2026-10-28 | docs/TEST-PLAN.md | 1.0.23 → 1.0.24 | Map deferred speech-model registration, cached integrity, first-decode reuse, initialization failure handling and memory-profile scope to their tests. |
| 2026-10-28 | docs/hld/pending-tools-image.md | 1.0.2 → 1.0.3 | Answer open question 1: the gallery renders the twelve image tools as ordinary cards from the shared tool-card component; the one-card "Image tools" family with links is removed (owner: component driven, all tools reuse the same component). |
| 2026-10-29 | API-CONTRACT.md | 1.94.2 → 1.94.3 | DNS lookup also returns CNAME and NS records. |
| 2026-11-03 | docs/PITFALLS.md | 1.0.14 → 1.0.15 | Record P-278: an unparseable inline script disabled every button, and the date-picker assets were never published to dist-ui. |
| 2026-11-04 | docs/TOOL-GUIDE.md | 1.199.147 → 1.199.148 | Document the opt-in Restart after a crash switch in Settings → General (LaunchAgent watcher; crash report required, so Quit and Force Quit do not restart). |
| 2026-11-04 | design/officekit-tokens.css | 1.8.11 → 1.8.12 | Define --ok-canvas (light and dark) for the Screenshot Editor preview surface; the dark theme used the light fallback. |
| 2026-11-05 | docs/TOOL-GUIDE.md | 1.199.148 → 1.199.149 | Clipboard history panel: pushpin at the left of text and link rows to pin or unpin in place; images cannot be pinned; "★" prefix removed. |
| 2026-11-05 | docs/TOOL-GUIDE.md | 1.199.149 → 1.199.150 | Document the fixed 64px shared bottom bar, success toast, error popup and Storage report actions moved to the Explorer header. |
| 2026-11-05 | DESIGN_SYSTEM.md | 1.9.16 → 1.9.17 | Record the fixed-slot bottom action bar with toast and popup outcomes. |
| 2026-11-05 | API-CONTRACT.md | 1.94.3 → 1.94.4 | Storage cleanup progress (GET) and stop (DELETE) on the plan execution resource. |
| 2026-11-05 | docs/TOOL-GUIDE.md | 1.199.150 → 1.199.151 | Storage analyser: scan row, clickable tiles, capped groups, summary review dialog, cleanup progress and stop, 3-button bar. |
| 2026-11-06 | API-CONTRACT.md | 1.94.4 → 1.94.5 | Image summary on a file selection (per-folder image counts and the 10,000 limit) for Find similar images. |
| 2026-11-06 | docs/TOOL-GUIDE.md | 1.199.151 → 1.199.152 | Find similar images: folder-only chooser, selection list with counts, 10,000 image limit, candidate-based grouping, progress and cancel. |
| 2026-11-19 | docs/PITFALLS.md | 1.0.15 → 1.0.16 | Record the clipboard skip-list regression that kept Apple Passwords copies in history (P-279). |
| 2026-11-19 | docs/APPROVED-DICTIONARY-IMPORT-EXPORT.md | 1.0.0 | Record the approved dictionary variants, import and export behavior. |
| 2026-11-19 | docs/APPROVED-DICTATION-PER-APP.md | 1.0.0 | Record the approved per-app Smart cleanup and Fix grammar settings. |
| 2026-11-19 | API-CONTRACT.md | 1.94.5 → 1.94.6 | Clipboard clip "use" resource: a pasted clip moves to the top of the history. |
| 2026-11-19 | docs/MACOS-SIGNING.md | 1.0.0 | New runbook: build and sign, submit to Apple and finish are separate manual workflows; nothing waits on Apple. |
| 2026-11-22 | infra/licensing/README.md | unversioned | Automated licensing backend deploys: a CodePipeline (test, cdk diff, manual approval, cdk deploy) fed by the GitHub connection. |
| 2026-11-24 | API-CONTRACT.md | 1.96.0 → 1.97.0 | Hosted support reports (S5): tickets, status by token, release notices; two Exempt native commands. |
| 2026-11-25 | infra/licensing/README.md | unversioned | The CodePipeline also tests, diffs, deploys and probes `OfficeKit-support-prod`; the HTTP API id is a sixth required pipeline input. |
| 2026-11-25 | API-CONTRACT.md | 1.97.1 → 1.97.2 | Support tickets get a `support` label in Linear (untrusted user text, never agent-ready); `linear_label_id` is optional in the settings. |
| 2026-11-25 | API-CONTRACT.md | 1.97.0 → 1.97.1 | Support ticket ids are opaque random references; the Linear issue key stays server-side. |
| 2026-11-24 | DESIGN_SYSTEM.md | 1.9.20 → 1.9.21 | Help & feedback is send-only: Send report, Try again, "See exactly what is sent", fixed-in toast on launch. |
| 2026-11-24 | docs/TESTING.md | unversioned | Support send, failure and release-notice checks replace the local-draft checks. |
| 2026-11-26 | DESIGN_SYSTEM.md | 1.9.22 → 1.9.23 | Coach me on call/meeting reminders; meeting recordings coached from the microphone only; coach surfaces ask macOS to hide them from screen sharing, every reminder included, not yet confirmed on an installed build (approved mock `meeting-coach-prompt`). Live Workspace fixes and saved notes show the grammar rule with an example (mock `speech-coach-grammar-rules`, option A). Review round 1: Coach me ends with the call only once a call was seen, its state belongs to the session, a failed save never leaks into the next note. |
| 2026-11-26 | DESIGN_SYSTEM.md | 1.9.21 → 1.9.22 | "OfficeKit closed unexpectedly" notice after a run that ended without a normal quit (approved mock `crash-notice-on-launch`): Not now and Send report, no automatic send, no crash report file read. |
| 2026-11-27 | docs/OPEN-SOURCE-PLAN.md | new 1.0.0 | Plan to publish the desktop app under GPL-3.0-only from a fresh public repo, with the licensing backend and release pipeline kept private. Draft for approval. |
| 2026-11-27 | docs/OPEN-SOURCE-PLAN.md | 1.0.0 → 1.1.0 | Approved; Phase 1 result recorded (tree made publishable, backend removed, fresh-clone proof). |
| 2026-11-27 | docs/OPEN-SOURCE-PLAN.md | 1.1.0 → 1.2.0 | Phase 2 result: hosted-runner CI green, release workflows kept private, version-bump stays public. |
| 2026-11-27 | DESIGN_SYSTEM.md | 1.9.23 → 1.9.24 | Parakeet CC BY 4.0 credit line names the creator, the Core ML conversion and the licence link (approved mock `model-attribution`). |
| 2026-11-27 | docs/OPEN-SOURCE-PLAN.md | 1.2.0 → 1.3.0 | Phase 3 result: public documents added, Parakeet credit line approved and shipped, open items listed. |
| 2026-11-27 | docs/OPEN-SOURCE-PLAN.md | 1.3.0 → 1.4.0 | Phase 4 result: scan and squashed export clean, real statement data replaced, owner checklist for the public push. |
| 2026-11-27 | API-CONTRACT.md | 1.97.2 → 1.98.0 | Hosted licensing design and AWS topology moved to the private repository. |
| 2026-11-27 | docs/TESTING.md | 1.12.417 → 1.12.418 | Hosted licensing test notes moved to the private repository. |
| 2026-11-27 | docs/MACOS-SIGNING.md | 1.0.0 → 2.0.0 | Rewritten as a short public page; the signing pipeline is private. |
| 2026-11-27 | BUILDING.md, CONTRIBUTING.md, README.md | — | Document OFFICEKIT_DEV_UNLOCK, OFFICEKIT_DEV_NOAUTH and the loopback Host check for source builds. |
