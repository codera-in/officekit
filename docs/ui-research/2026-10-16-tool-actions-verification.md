# Tool actions and focus verification · 2026-10-16

Source: working changes based on a563c1c; macOS, WebKit, authenticated development registry. UI assets rebuilt from this source. The installed application was not replaced or verified in this pass.

Desktop rebuild completed after the browser checks: `src-tauri/target/release/bundle/macos/OfficeKit.app` and `src-tauri/target/release/bundle/dmg/OfficeKit_1.0.0_aarch64.dmg` (arm64). The app bundle's strict deep signature check passed. `hdiutil verify` reported the DMG checksum valid; SHA-256: `43b0b97414d9f310e03ffcf7f53785a6a6a2a7076eeabcd893c4a31d5287f78c`. The app is Apple Development signed; notarization was skipped because Apple notarization credentials are not configured. The built app has not been installed over `/Applications/OfficeKit.app` or launched for native interaction checks.

50 allowed tools were checked individually. Action containment covers both themes at 1440, 900 and 390px; 390px is repeated in both viewport projects. Field-focus measurements cover both themes at desktop/compact widths, including expanded advanced controls. Every tool action source and its buttons/selects must fit in the reserved bar; the main scrolling area must end above it. Browsing routes omit the bar. Tools excluded by this registry/profile: none.

This is a layout/focus matrix. The fixture for each row is its real initial route with available fields expanded. Counts are individual focused-field measurements across both projects/themes; zero means no visible enabled text fields. Full valid/invalid operation, export and native acceptance are separate evidence, not inferred from a route pass.

| Tool | Destination | Focused-field checks | Bar/layout |
| --- | --- | ---: | --- |
| bank_statement | statement | 8 | Passed |
| pdf_unlock | pdf | 4 | Passed |
| pdf_protect | pdf | 8 | Passed |
| pdf_merge | pdf | 0 | Passed |
| pdf_split | pdf | 16 | Passed |
| pdf_compress | pdf | 4 | Passed |
| pdf_metadata_strip | pdf | 0 | Passed |
| pdf_to_images | pdf | 8 | Passed |
| pdf_delete_pages | pdf | 0 | Passed |
| pdf_reorder_pages | pdf | 0 | Passed |
| pdf_editor | pdf-editor | 0 | Passed |
| pdf_table_extractor | pdf | 0 | Passed |
| pdf_text_extract | pdf | 8 | Passed |
| image_converter | converter | 0 | Passed |
| image_resize | converter | 8 | Passed |
| image_exif_strip | converter | 0 | Passed |
| pii_redaction | pii | 0 | Passed |
| screenshot_editor | screenshot | 4 | Passed |
| data_converter | converter | 0 | Passed |
| dictate_stt | dictate | 24 | Passed |
| loan_emi | calculators | 12 | Passed |
| compound_interest | calculators | 20 | Passed |
| vat_salestax | calculators | 8 | Passed |
| freelance_rate | calculators | 20 | Passed |
| margin_markup | calculators | 8 | Passed |
| break_even | calculators | 12 | Passed |
| simple_interest | calculators | 16 | Passed |
| depreciation | calculators | 12 | Passed |
| everyday_percentages | calculators | 12 | Passed |
| math_eval | calculators | 8 | Passed |
| units_convert | calculators | 13 | Passed |
| batch_rename | workspace | 20 | Passed |
| dup_finder | workspace | 4 | Passed |
| storage_analyzer | workspace | 8 | Passed |
| file_split_join | workspace | 8 | Passed |
| folder_compare | workspace | 0 | Passed |
| file_hash | workspace | 4 | Passed |
| file_type | workspace | 0 | Passed |
| devtools_format | converter | 12 | Passed |
| url_codec | converter | 8 | Passed |
| jwt_inspector | converter | 12 | Passed |
| crypto_hashes | converter | 16 | Passed |
| password_generator | password | 4 | Passed |
| similar_images | workspace | 4 | Passed |
| color_converter | color | 12 | Passed |
| network_dns | network | 28 | Passed |
| network_ping | network | 28 | Passed |
| network_interfaces | network | 28 | Passed |
| system_info | system | 0 | Passed |
| system_resources | system | 0 | Passed |

Complete-flow coverage uses existing calculator, converter, file, statement, developer, network/system, storage, PDF and screenshot fixtures. The long duplicate-folder fixture verifies stationary export buttons while the workspace scrolls, footer clearance, Partial scan/Details and light/dark screenshots. File mutations use disposable originals and retain explicit confirmation. Copy/Download snapshots and native bridge mocks retain their existing assertions.

Validation:

- `npm test`: 592 Node passes, one skip; 1550 Python passes, four skips, 1653 subtests passed; configured coverage gates passed.
- Final screenshot/CSP Node checks: 21 passed.
- Full UI run: 278 passed, 20 skipped, two failed because the PDF test still required normal-flow placement below its whole document.
- Updated PDF containment assertions retain real opening, editing, native-adapter export and unchanged-original checks. Final rebuild and focused recheck of PDF plus every registry route's action/focus checks: 12 passed across desktop/compact projects. No outstanding failures from this change.
- Inspected generated light/dark Duplicate Finder screenshots. Temporary approved mocks and preview server removed.

Raw layout JSON and screenshots are under .test-artifacts/ui/ in each test's output directory. Browser/native adapter mocks do not establish Finder, system clipboard, save dialogs, microphone or installed webview behavior.

Source identities:

- index.html: `85e56100fc306d407b0f899cacd77f8eadd8c04f7f94dbf8160394ff7fd6562d`
- assets/officekit.input.css: `67b6ef778d615e103288ac995c6924045b317ec9f38832f206c9951cf506b809`
- assets/officekit-tool-actions.js: `da52cb8ca30c615758eeea6a3fc0532081452ed744afb6a441e70b74614e21be`
- assets/officekit-files.js: `a7ff3460418f0128ccbb84c6d0b353f9820bc137ac5eea4414d9b53fc769d96f`
