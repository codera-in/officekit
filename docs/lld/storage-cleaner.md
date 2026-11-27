# Storage cleaner implementation plan

Version: 1.0.1

| File | Responsibility |
| --- | --- |
| officekit/engines/engine_storage_cleaner.py | Strict scan/report/plan/outcome DTOs, platform discovery, bounded asynchronous scan, cache/project detectors, identity-bound plans and safe cleanup |
| app.py | Authenticated typed scan/cancellation/plan/execution resources, bounded request bodies and sanitised errors |
| src-tauri/src/workspace_native.rs | Hidden native credential bridge for scan initiation and reviewed cleanup execution |
| src-tauri/src/lib.rs | Register storage commands on platform handler lists |
| assets/officekit-storage.js | Dedicated system-wide report, volume category bar/legend, coverage, candidate selection and review/results |
| index.html and shared styles/registry | Reuse the existing storage destination and load the new module |
| tests/test_storage_cleaner_unittest.py | Detector, mutation, bounds, identity and contract tests |
| tests/storage-cleaner-ui.test.mjs | Strict client validation and selection/review/progress behaviours |
| tests/test_storage_tool_runtime_unittest.py | Actual npm/pip3/uv cleanup against disposable fixtures, including staging restoration |
| ui-tests/storage-cleaner.spec.mjs | Complete rendered shell flow with mocked native authority and Docker/permission coverage |
| scripts/smoke-storage-sidecar.mjs | Packaged resource boundaries and final typed schemas without scanning or cleaning user data |

All operations reference the resource surface in docs/hld/storage-cleaner.md. Scan jobs expose queued/running/ready/cancelled/failed and partial coverage. Plans expire, cannot be reused and never accept client-supplied file paths. Error handling follows the existing local API safe detail envelope; client retains operation-local recovery status. No schema/migration changes.

Verification proceeds from focused engine/client tests to native formatting/tests, whole npm test and browser synthetic-data acceptance. Packaging/installed acceptance is reported separately; source checks do not establish native permission or Trash integration on every OS.
