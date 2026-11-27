# Format JSON current-source flow — 2026-11-03

## Build and fixture

Verified the current worktree UI (`1.0.76`) in a new Superset Browser tab against an isolated authenticated local API. Used `{"name":"Ada","active":true,"items":[1,2]}` and the correctable malformed input `{"name":`.

## Observed flow

- Empty state shows the Format JSON operation, editable input and result area. The dock contains only Run locally.
- Malformed input remains editable and is marked invalid with “This JSON is not valid. Check commas, brackets and quoted property names, then format again.” Report bug is absent; Copy and Download are hidden. After editing a successful result to malformed JSON, the old result is cleared.
- Correcting and running again returns the complete formatted result:

  ```json
  {
    "active": true,
    "items": [
      1,
      2
    ],
    "name": "Ada"
  }
  ```

- Copy action passed the full result text to the clipboard adapter (68 UTF-8 bytes); the adapter was intercepted in the browser to avoid changing the user's system clipboard. The UI showed its copy confirmation.
- Download action produced a 68-byte Blob with matching full content, filename `officekit-result.json`, MIME `text/plain;charset=utf-8`. The browser anchor click was intercepted to inspect the payload, so no file was written.
- Valid result state shows Run locally, Copy result and Download result (3 actions); invalid state shows only Run locally (1 action).

## Screenshots

- Home before opening the tool: `docs/verification/tool-unification/after/devtools-format-json-live-source-initial-20261103.png`
- Empty Format JSON screen: `docs/verification/tool-unification/before/devtools-format-json-current-source-empty-20261103.png`
- Invalid input: `docs/verification/tool-unification/after/devtools-format-json-invalid-live-source-20261103.png`
- Invalid input after editing a successful result: `docs/verification/tool-unification/after/devtools-format-json-edited-invalid-live-source-20261103.png`
- Recovered result and three-action dock: `docs/verification/tool-unification/after/devtools-format-json-recovered-after-edit-live-source-20261103.png`

## Test and remaining scope

- `node --test tests/developer-utilities-ui.test.mjs tests/developer-slice-ui.test.mjs`: 89/89 passed.
- `pytest -q tests/developer_routes_unittest.py tests/engine_developer_unittest.py tests/test_devtools_validation_unittest.py`: 179 passed, 63 subtests passed.
- This is current-source browser evidence, not installed-app verification. Installed OfficeKit 1.0.77, keyboard/focus, compact layout, and native clipboard/file-save behavior remain open. The installed build previously showed generic correctable-input feedback plus Report bug; the current worktree source now handles that state locally.
