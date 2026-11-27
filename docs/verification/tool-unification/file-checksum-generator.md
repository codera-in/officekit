# File Checksum Generator verification

## Installed run — 2026-11-02

Selected a disposable 25-byte `known.txt` containing `OfficeKit checksum audit\n` in OfficeKit 1.0.77. Ran SHA-256 and SHA-512 separately. Both outputs matched independent Node `crypto` digests:

- SHA-256: `68569cfe0b229ed9e83a8aa41098783790484223618c643bcd42731fcf3be727`
- SHA-512: `8722bf0091feb210f0a54513a8eed881bbae3df5b3b3b7ac358bf28df3b310903bd5614f211debe2a6bf5235fbbadf8a834f74549dd09cb91833b483eccb7741`

Changing the algorithm invalidated the prior result and exposed “Calculate checksum”; running again replaced the result with the selected digest. Each completed result exposed Copy report and Download, plus a per-row digest copy action. The selected file was a temporary fixture; no original user file was changed.

The installed app’s shared action footer remained stale from the prior tool and read “Empty file finder” with a disabled “Find files” action. This is an installed 1.0.77 routing defect; current source already scopes the checksum dock correctly.

## Current-source checks and screenshots

- `node --test tests/files-tools-ui.test.mjs`: 60/60 passed, including checksum result visibility, SHA-256/SHA-512 selection, scoped actions and the three-button cap.
- `pytest -q tests/test_file_jobs_unittest.py tests/test_hash_generator_unittest.py`: 53 passed, 5 subtests passed.
- Existing source screenshots: `before/file_hash-initial-current-source-20261031.png` and `after/file_hash-result-scoped-dock-current-source-20261031.png`. They document the shared layout and dock but use a separate fixture; the installed screen was inspected live and its digests were recorded above. The available native capture interface did not persist the installed screenshot.

Keyboard navigation, native picker behavior, compact layout, exact clipboard bytes and installed/current-source parity remain open.
