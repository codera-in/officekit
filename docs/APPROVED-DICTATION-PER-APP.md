# Approved per-app dictation settings

**Date:** 2026-11-19
**Approval:** The owner reviewed the inspected Superset Browser mock `dictation-per-app` (before and after, 0 added buttons) and replied **"approved"**. The mock file was removed from the tree after approval, per AGENTS.md; this document is the durable record.

## Approved behavior

- **Per app section:** the Smart dictation card ends with a "Per app" table. Each app dictated into appears once, newest first, with its name and bundle id and two dropdowns: Smart cleanup and Fix grammar. Each is Default, On or Off. Default follows the card's global switches.
- **Empty state:** "No apps yet. Dictate into an app and it will appear here. Needs “Use the app you are typing in” to be on."
- **Consent:** the app is only known, remembered and used while "Use the app you are typing in" is on. No new capture was added.
- **Stored on this Mac:** only the app name, bundle id and the two choices, at most 64 apps; the oldest fall off. Nothing is sent anywhere.
- **Native cleanup:** the page sends only apps with an explicit On or Off choice. The focused app's choice replaces the global value for that dictation; bundle ids match without regard to case.
- **Buttons:** dropdowns only; the card adds 0 buttons.

## Tests

`tests/dictation-ui.test.mjs`: the store (newest first, bounds, sanitizing, corrupt storage), native modes only when explicit, the card markup (no buttons, empty state), and the cleanup call carrying `appModes` and remembering the focused app. Rust: `dictation_quality` tests for resolution, case-insensitive ids, bounds and the app label.
