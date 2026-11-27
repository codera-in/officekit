# PDF Password Remover: recover from a wrong password

## Decision

A rejected password is an expected, user-correctable outcome. Keep the selected PDF and password field, show the error beside the password, and let the user retry. Do not show Report bug for this response. Clear any previous result when starting the attempt; only a successful unlock restores Copy summary and Download.

The shared dock keeps the active title **PDF Password Remover** and exposes the retry action while the password is wrong. A recovered result returns the normal three actions: Copy summary, Download, Unlock PDF.

## Evidence

- The before/after mock was opened and visually inspected in a fresh Superset Browser tab at a narrow viewport. The error state uses 1/3 actions; the installed 1.0.77 before state is labeled 4 (over), matching the observed Report bug CTA plus stale result actions. Both mock states passed the 3-button checker before its temporary HTML was removed.
- Live installed 1.0.77 flow used a repository-generated one-page PDF: Protect PDF created `/tmp/pdf-protect-source_protected.pdf` (1,360 bytes; recognized as PDF 1.7, one page). A wrong password displayed the generic error/Report bug and kept prior Protect PDF actions; this installed behavior predates the current source changes.
- Current-source change marks only the known `Incorrect password.` unlock response as non-reportable. Other processing failures remain reportable.

## Remaining verification

The real UI regression is in `ui-tests/pdf-protect.spec.mjs`. Re-run the Playwright flow against the current source build and inspect valid, wrong-password and recovered states. The installed application is 1.0.77 and is not current-source evidence.

## Implementation milestone

The shared PDF workbench now treats only the exact `Incorrect password.` response from Unlock as correction guidance, preserves bug reporting for other failures, clears previous result actions at the start of a retry, and labels both the task and result dock “PDF Password Remover.” The Playwright flow now asserts the 1/3 wrong-password state and captures the error and recovered states when the browser is available.

`node --test tests/pdf-workbench-ui.test.mjs` passes 28/28; `pytest -q tests/test_pdf_endpoints.py -k unlock` passes 3/3; `node --check ui-tests/pdf-protect.spec.mjs` passes. The rendered current-source Playwright flow remains unverified because both configured browser engines abort before page setup on this machine.

2026-11-02 bundle parity follow-up: the source handler was already correct, but the committed `dist-ui/index.html` still used the generic error handler and could report an incorrect unlock password as an app bug. The Tauri bundle now uses the same unlock-only classifier. `node --test tests/pdf-unlock-bundle.test.mjs tests/pdf-workbench-ui.test.mjs` passes 30/30; `pytest -q tests/test_pdf_endpoints.py -k unlock` passes 3/3. The targeted Playwright run was attempted; WebKit aborted during browser launch (exit 134) before the test body, so it produced no post-fix screenshots. CUA sees OfficeKit running but cannot attach its window (`cgWindowNotFound`). The initial current-source screen is saved at `after/pdf_unlock-current-source-desktop-superset.png`; fresh wrong-password/recovered screenshots, compact, keyboard and installed matching-build checks remain open.
