# Image ↔ Data URI implementation

## Behavior

The file-to-URI flow clears any prior encoded URI before starting, keeps the shared action dock visible while encoding, and presents an accessible dock error with no stale Copy or Save actions if encoding fails. The URI-to-image flow keeps malformed or undecodable text editable, marks it invalid, reports the failure in the shared dock, and enables Save again only after the URI is corrected.

The approved file-to-URI error treatment was reviewed in Superset Browser; see `2026-11-02-image-data-uri-encoding-error-review.md` and `docs/verification/tool-unification/mock/image-data-uri-encode-error-review-20261102.png`. Historical current-source captures for decode failure and recovery are `docs/verification/tool-unification/after/image_data_uri-corrupt-current-source-20261031.png` and `image_data_uri-recovered-current-source-20261031.png`. They document decode behavior and are not claimed as fresh captures of this implementation.

## Verification

- `node --test tests/image-tools-ui.test.mjs`: 47/47 passed, including encoding-state and editable decode-recovery contracts.
- `pytest -q tests/image_routes_unittest.py -k 'data_uri or bad_base64'`: 1 passed, 2 subtests passed.
- The focused source browser flow was attempted in WebKit and Chrome. Both browsers aborted during launch before page setup (WebKit `Abort trap: 6`; Chrome Crashpad handshake `SIGABRT`), so no fresh rendered source screenshot is claimed for this commit.
- Installed-app, compact rendered, native clipboard/save and keyboard/focus checks remain open.
