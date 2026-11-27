# Approved: pending tools slices 2–6 UI

Version: 1.14.1 · 2026-10-23 · Record the owner's answer “New wording (Recommended)” to the Restore result note (PM-3, UX-12). Earlier: 1.14.0 · 2026-10-23 · Record the owner's approval “approved” (2026-10-23) of the S06 Restore from Trash mock and its disclosure, with the defaults and button counts. Earlier: 1.13.0 · 2026-10-23 · Record the owner answers “Keep it (Recommended)” (the `denied` state) and “Folder name (Recommended)” (the selection line) for the F11 symlink inspector. Earlier: 1.12.0 · 2026-10-23 · Record the owner's approval of the F11 symlink inspector mock, “Approve (Recommended)” (2026-10-23), with its button counts and open copy questions. Earlier: 1.11.0 · 2026-10-23 · Owner chose the files v3 mock copy for the archive screen (“Files v3 mock”), over the tool-template wording of navigation decision 11. Earlier: 1.10.0 · 2026-10-22 · Round 4 owner answer “Refuse (Recommended)” for archive output inside the selected folder (PM-10). Earlier: 1.9.0 · Round 3 owner answers on the Files screens: UX-12 “Keep, same pattern (Recommended)”, UX-13 “Primary (Recommended)”, UX-7 “Accept as built (Recommended)”, UX-14 “Empty header (Recommended)”; PM-9 and PM-8 coordinator checks recorded. Earlier: 1.8.0 · Owner decisions on the Files re-mock v3 (“Approve (Recommended)”) and the single SHA-256 row (“Accept all as built (Recommended)”). Earlier: 1.7.0 · 2026-10-22 · Round 4 PDF review: owner answered 2026-10-22 “Match the mock (Recommended)” for the dock status (PM-9, UX-21), recorded in the PDF section. Earlier: 1.6.0 · Round 3 PDF review: the drop-zone wording and the dock status are recorded as built (PM-8, UX-20). Earlier: 1.5.0 · Round 2 PDF review: the owner answered “Make it a link” for the PDF drop zone, and “Accept all as built” for the PDF navigation, metadata copy and status, and pages-error copy. Earlier: 1.4.4 · 2026-10-22 · Round 5 review record: the stat tiles show under every comparable mode, and the Save difference dock placement is written down (PM-10). Earlier: 1.4.3 · 2026-10-22 · Owner answer on PM-7: the Rotate overlap with the Screenshot Editor is “Accept overlap (Recommended)”, keep both, and the attribution now quotes that answer instead of “Approve all five”. Earlier: 1.4.2 · 2026-10-22 · Owner answer on PM-6: the I14 border batch stays API-only for now (“API-only for now (Recommended)”); the batch UI or MCP agent is slice 7 work. Earlier: 1.4.1 · 2026-10-22 · Round 2 review record: the Rotate overlap with the Screenshot Editor and the I12 preview-scale judgment are written down as accepted (PM-5). Earlier: 1.4.0 · 2026-10-22 · Round-3 owner answer on the developer stat and badge sizes: “Keep 18px / 12px (Recommended)”. Earlier: 1.3.0 · Round-2 review: the developer timestamp zones are chips, the approved v2 shape, and no longer a deviation. Earlier: 1.2.0 · Owner decisions during review: the files open questions, the calculators time-field focus, and the developer and PDF deviations from the v2 mocks. Earlier: 1.1.0 · Owner re-approved the 3-button re-mocks (“Approve all four”) and decided Tamil, the ZIP search IDs and the as-built scope calls. Earlier: owner approved all five slice mocks (“Approve all five”).

The temporary mock HTML has been removed from the worktree as `AGENTS.md` requires. Each slice HLD (`docs/hld/pending-tools-<slice>.md`) carries the full component tree. The approved decisions are:

- **Calculators:** the 11 selector pills are replaced by one grouped “Calculator” select with 24 entries in four groups: Money & business, Everyday math, Dates & time, Science & geometry. Existing forms, IDs and `switchCalc` stay. The hero becomes the standard left-aligned 28px “Calculators” title, and the selected calculator's name becomes the card heading. **Every** calculator's bottom bar is capped at three buttons:
  - before a result: Calculate (primary);
  - after a result: Download… (primary), Save result (secondary), Calculate again (quiet);
  - Copy result becomes an inline link in the result header;
  - when inputs change after a result, the result shows “Inputs changed — calculate to update”.
- **Developer:**
  - D10 timestamp and D16 text metrics/case become new Time and Text groups in the existing developer select.
  - D04 JSON diff and D17 text diff share one new Compare panel, with side-by-side and unified views.
  - D11 UUID (bulk list, copy/export) and D15 QR (payload, size, error correction, PNG/SVG download) get their own panels.
- **Files:**
  - F06/F07/F12 become searchable as `zip_create`, `zip_extract` and `archive_inspector`. Each opens Archive tools in the matching mode, and the converter's Extract ZIP panel stays.
  - The new read-only scans (file info, compare files, file age, empty files, empty folders) run through the existing selection → job → results flow, with explicit partial and denied states.
  - Track B is a separate PR. Its restore flow is dry-run → confirm → result → restore.
- **Image:** one dedicated Image tools workbench holds all 12 tools; it is not built as Media Toolkit operations.
  - It links to Resize, Remove metadata, Media Toolkit and Screenshot Editor. Its Rotate & flip operation overlaps the Screenshot Editor rotate, and the owner accepted that overlap (see scope calls).
  - Adjustments shows a live preview that matches the export, with a Reset button.
  - EXIF view hides GPS by default.
  - Visual compare offers side-by-side, overlay and difference views, and never claims two images are “identical” automatically.
- **PDF:** the 12 existing operations keep their labels and IDs, and the nav groups all 19 operations plus Bank statement into five sections: Combine & split, Pages, Edit & optimize, Convert & extract, Security & info. On desktop each section is a collapsible disclosure with only the active one open; at compact width the sections become one 44px grouped menu.
  - Watermark and page numbering show a preview.
  - Images → PDF takes an ordered batch.
  - Metadata view is read-only and shows absent fields as absent.
  - Flatten carries a reversibility and signature warning.

## Re-approval for the 3-button limit (2026-10-22)

The `AGENTS.md` “Button Limit” rule arrived after the first approval: at most 3 buttons per screen, with each mock showing its count. During review the owner chose “Re-mock first”. Every screen over the limit was re-mocked with a before/after count on each frame. The owner answered **“Approve all four”** for the developer, calculators, files and PDF re-mocks. Image had no screen over the limit. These rules override the matching parts of the first approval:

- **Shared rules:**
  - Counted: buttons in the screen body and the bottom dock, including disabled ones and segmented toggles.
  - Not counted: tabs, in-text links, row actions and chip remove (×).
  - Each screen keeps one primary action.
  - At most one Copy and one Download per screen. Several export formats become one Download with a Format select.
- **Calculators:**
  - The result bar is Calculate again, Save result, Download… (primary on the right).
  - Copy result is an in-text link on the result label row.
  - The unit converter's Swap is an in-text link.
  - After an input change, the bar is Calculate, Save result, Download…
- **Developer:**
  - Clear, Use now and Add zone become in-text links.
  - Compare shows Compare, Copy, and Download with a format select. Swap becomes a link.
  - UUID shows Generate, Copy all, and Download with a .txt/.csv select.
  - QR shows Create QR code, Copy image, and Download with a PNG/SVG select.
  - Change case shows Run locally, Copy result, Download result.
- **Files:**
  - Choose files…, Choose folder… and Reset selection become in-text links beside the selection summary.
  - Run is the one primary action before a result. After a result the screen shows Copy report and Download. During a run, Cancel joins the busy primary.
  - The search hits `zip_extract` and `archive_inspector` stay, as in the first approval. The owner answered “Add the two search IDs”: each opens Archive tools in Extract or Inspect mode.
- **PDF:**
  - Rotate pages uses a Turn select, not segments.
  - After a successful result, Download replaces Run as the single primary, and no Copy summary is shown.
  - The watermark Image-stamp file chooser is an in-text “Choose image…” link.
  - Watermark and page-number text support **Latin, Greek and Cyrillic only**. The owner answered “Latin/Greek/Cyrillic only”. The default watermark is “CONFIDENTIAL”, and complex scripts such as Tamil get a fixed 422 message.
  - “Count unnumbered pages” defaults to unchecked, and its example matches.
  - Select PDFs is a button styled as an in-text link in the drop zone. The owner answered “Make it a link”. It stays keyboard-operable.
  - Slice tasks hide the generic Output preview. Their preview sits in the options, and the output name appears in the dock status after a result.
  - Owner answer, 2026-10-22, for PM-9 and UX-21: “Match the mock (Recommended)”. After a result the dock status is exactly “Done” for Images to PDF, Grayscale and Flatten, because the file row already shows the name and page count. Page numbers shows “Done · N of M pages numbered”. N is the number of selected pages (blank selects every page), and M is the page count. Start and count unnumbered pages change the printed numbers, not how many pages are numbered, so they do not change N. Rotate, watermark and resize keep their approved forms: “Done · 3 pages turned”, “Done · <name> · <count> pages” and “Done · resized copy”. The trailing “Download it when you are ready.” is dropped.

**Scope calls accepted as built.** The owner answered “Accept all as built”:
- C25 geometry has no diagrams.
- C17 date difference is date-only, with no time zone.
- The Business days “Import from a .txt or .csv file” link is deferred.
- I16 data URIs are capped at 8 MiB.
- Collage keeps its canvas bounds as built.
- The icon pack exports `.iconset`, not `.icns`.
- Collage and contact-sheet drag reordering is deferred. Alt+↑/↓ and the move buttons remain.
- Rotate & flip (I06) overlaps the Screenshot Editor rotate. Owner answer, 2026-10-22: “Accept overlap (Recommended)”. Both stay: Rotate is the batch and file tool, and the Screenshot Editor keeps its in-editor rotate.
- The I14 border batch stays API-only for now. Owner answer, “API-only for now (Recommended)”. The batch UI or MCP agent is slice 7 work.
- The I12 preview is judged at preview scale. Its agreement with the export is at preview scale, not pixel for pixel (owner: “Accept all as built”).
- Compare stat tiles show under every comparable mode, in Side by side, Overlay and Difference alike. The approved mock places `.stats` as a sibling of the three mode panels (mock line 463), so the tiles belong to the result and not to one mode. The Save difference image dock sits under the result in every comparable mode, enabled. In the size-mismatch state it shows the approved dock “Waiting for a choice.” with Save disabled (mock lines 478–481).
- PDF navigation stays hand-written in `index.html`, as in HLD §5 option (b), and is not generated from the catalogue.
- PDF metadata view: the secondary Copy report button, the status line and the reorder hint are not in the mock. They are as built.
- PDF pages-error copy “Enter pages such as 1-3, 5. Ranges must be ascending and not overlap.”, the singular signed-field warning and the count-example note are as built.

## Owner decisions during review (2026-10-22)

The slice reviews raised choices the approved mocks did not settle. The owner answered each one:

- **Calculators, nonexistent time:** “Focus, red on leave”. Focus moves to the invalid time field, which shows the focus border. The error border shows once the user leaves the field. The mock drew the red border straight away; this one state differs from it.
- **Developer, deviations from the v2 mock:** “Accept as built”. The accepted differences are:
  - The source zone is a text field with suggestions.
  - An empty Text metrics shows a message.
  - Copy image is disabled, not hidden, for SVG.
  - UI behaviour is covered by Node tests, with no Playwright spec.
- Timestamp target zones stay as chips with Add zone, as the v2 mock shows. A round-2 review proposed a comma-separated field instead; the review coordinator kept the chips, so the build matches the approved mock.
- **Developer, stat and badge font sizes (2026-10-22):** “Keep 18px / 12px (Recommended)”. The Text metrics stat value uses `--ok-text-lg` (18px) and the developer badge uses `--ok-text-xs` (12px), in place of the mock's 22px and 11px. The owner approved this as an accepted deviation; the design-system scale has no 22px or 11px step.
- **PDF, Images → PDF and watermark:** “Accept, defer rest”.
  - Image-row thumbnails and Alt+↑/↓ reordering ship.
  - PDF page thumbnails, the per-row EXIF and transparency notes and drag reordering move to slice 7.
  - The watermark image limit stays 8 MiB, and the UI says “up to 8 MiB”.
- **Files, open questions:**
  - Beta reveal route, answered “Fix in files slice”: the files PR adds `POST /api/file-jobs/*/reveals` to the private-beta profile, so Duplicate Finder's “Show in Finder” works in beta.
  - Host paths, answered “Show paths”: F11 and the restore ledger show full link targets and original folder paths. These views are local-only, and paths are never logged.
  - Track B, answered “F11 then S06 PR”: F11 lands after track A merges, and S06 restore follows as its own PR.
  - Build choices, answered “Accept as built”: 403 for a kind-level refusal under private beta; the limits of 10,000 skipped rows, 20,000 diff lines and a 2 MiB text view; and “Show” as the row action that reveals an item.

## Files Duplicates and archive re-mock v3, and the single hash row (2026-10-22)

Owner answers, recorded 2026-10-22:

- **UX-11, Duplicates re-mock and the shared Files result pattern:** “Approve (Recommended)”. The re-mock (v3, four frames) is the approved design. Counts are per screen, with the same rule as the Button Limit: in-text links, row actions and tabs are not counted; disabled buttons are.
  - **Frame 1, Duplicate finder after a result:** 12 → 3. Find duplicates (Run) hides after a result. Scan details, the three column sorts, Select all duplicates, Clear selection, Previous and Next are in-text links. The dock is Copy report, Download and Move selected to Trash, with Trash the one primary when enabled. Row actions stay “Show in Finder”, and the list keeps its Open column with an empty header (UX-14).
  - **Frame 2, move-to-Trash confirmation:** 2 before and after, unchanged. The dialog has Cancel and Move to Trash, and the page behind it is inert.
  - **Frame 3, archive inspector beyond 100 entries:** 3 → 1. Previous 100 and Next 100 are in-text links, and Extract selected or all is the one primary.
  - **Frame 4, File checksum generator after a result:** 3 → 2. File checksum joins the read-only results, so Run hides after a result, as the other inspect tools already do. The outline Download styling shown in v3 frame 4 is superseded by UX-13 below.
  - **Other existing Files tools, UX-12:** owner answer “Keep, same pattern (Recommended)”, recorded 2026-10-22. Folder compare and Similar images hide Run after a result (3 → 2). Batch rename (Apply rename), Split and join (Split and join files) and Archive create (Create ZIP) keep Run after a result, and each stays at 3.
  - The mock HTML is not kept in the repository, as `AGENTS.md` requires. Its decisions live in this record and in the test suite `tests/files-tools-ui.test.mjs`, which asserts each frame’s count.
- **UX-9, one SHA-256 row:** “Accept all as built (Recommended)”. The compare table shows one SHA-256 row reading Match or Differ, instead of two hash prefixes. This is the approved behaviour.

## Files round 3 owner answers and open checks (2026-10-22)

Owner answers, recorded 2026-10-22, quoted as given:

- **UX-12, Run after a result:** “Keep, same pattern (Recommended)”. Folder compare and Similar images hide Run after a result. Batch rename, Split and join and Archive create keep Run (3).
- **UX-13, Download on read-only results:** “Primary (Recommended)”. Download stays the primary button on read-only Files results (the v2 style). Duplicate finder keeps Move selected to Trash as the primary and Download as an outline button. The outline styling from v3 frame 4 is superseded.
- **UX-7, compare headline:** “Accept as built (Recommended)”. The compare headline reads “Files differ · first difference at byte N” and the status line is the single Duplicate line. The line-endings banner and the `@@` hunk header are removed from the build. The compare screen shows no created-dates note.
- **UX-14, Duplicate finder header:** “Empty header (Recommended)”. The Open column stays, and its header is empty. The row action remains “Show in Finder”.

Coordinator checks, recorded 2026-10-22 (not owner answers):

- **PM-9, mock review:** the v3 mock was opened and inspected in the Superset Browser on 2026-10-22 before approval.
- **PM-8, storage analyser:** the storage analyser button count was not measured. It is open for a separate check and is not claimed as within the limit.

## Files round 4 owner answer (2026-10-22)

Owner answer, recorded 2026-10-22, quoted as given:

- **PM-10, archive output inside the selected folder:** “Refuse (Recommended)”. Archive create refuses an output file inside a selected folder before any byte is read, with the message “The output file is inside the selected folder. Choose another place to save it.” No ZIP is written and the sources are unchanged. The refusal has no approved mock; the decision is recorded here and in `docs/hld/pending-tools-files.md` section 9.

## Archive screen copy after the rebase onto the tool template (2026-10-23)

The files slice and navigation decision 11 (`docs/ui-research/2026-10-22-approved-navigation-and-tool-screens.md`) gave the archive screen different copy. Owner answer, 2026-10-23, quoted as given: “Files v3 mock”. The archive screen ships as the approved v3 and v2 frames draw it:

- Screen title “Archive tools”.
- An “Operation” picker with “Browse / extract archive” and “Create archive”, and the Format field shown.
- Run reads “Extract selected or all”, or “Create ZIP” when creating.
- “Reset selection” stays as an in-text link in the selection line (not a counted button).

The renamer half of decision 11 (“How to rename”, only the fields the rule uses) is unchanged.

## Symlink inspector (F11) mock approval (2026-10-23)

- Owner approval of the F11 mock, dated 2026-10-23: “Approve (Recommended)”. The mock is titled “Symlink inspector”, with the description “Find links in a folder and see where each one points, without following them.”, folder-only selection with “Include subfolders”, and the Run label “Inspect links”. Its result columns are Link, Points to (as written), Type and State. The Type column is hidden below 900px through `ok-phone-hide`.
- Button rule: one counted button before a result (Inspect links), and two after (Copy report, and Download as the primary). Run hides after a result. The mock's “Buttons: 2/3” counts are kept in the UI tests.
- Earlier owner answers this mock depends on, quoted as recorded in section 9 of the HLD: “Approve as designed” (2026-10-22, F11 B1), “Show paths” (host paths shown in this local-only view) and “F11 then S06 PR” (track B order). The owner's “Keep, same pattern” and “Primary” answers from the mock's note are kept.
- Build, as shipped in this PR: the state copy “Resolves inside folder”, “Broken”, “Circular (N hops)”, “Too many hops”, “Outside selected folder · not checked” and “Not supported on this system” is the approved copy. The `denied` state, “Not checked · permission denied”, is not in the mock; the owner kept it on 2026-10-23 (answer below).
- Owner answer 2026-10-23, quoted as given: “Folder name (Recommended)”. The selection line shows the folder name, not the full path that the mock header shows, as other Files tools do. Showing the full path would need native metadata, which B1 does not change.
- Owner answer 2026-10-23, quoted as given: “Keep it (Recommended)” for the `denied` state, “Not checked · permission denied”. It marks an unreadable target inside the selected folder and is counted in the partial banner.
- The temporary mock HTML is not in the worktree. It is removed after approval, as AGENTS.md requires. This record keeps the approved decision.

## Restore from Trash (S06) mock and disclosure approval (2026-10-23)

- Owner approval of the S06 mock and its disclosure, dated 2026-10-23, quoted as given: “approved”. The mock is titled “Restore from Trash (S06) and the ledger disclosure”. It is an HTML mock of desktop frames, and the narrow-window layout (below 900px, `ok-phone-hide`) is shown as a note on the same frames.
- The disclosure, byte-identical in the storage review dialog, the duplicate finder result and the Restore screen: “OfficeKit keeps a private list of what it moves to Trash, so you can put items back for 30 days. The list stays on this Mac.” with the in-text link “What is kept”, which expands in place to: “To let you put items back, OfficeKit keeps a private list of what it moves to Trash: each item’s name, original folder, size and when it was moved. The list stays on this Mac, is readable only by your account, and is never logged, exported or sent anywhere. Entries are removed after 30 days, or sooner when you choose Forget.”
- Placement, as approved: before each move, in the Storage cleanup “Review selected cleanup” dialog (a bordered block titled “You can put these back for 30 days”, with the line “Open Restore from Trash to put items back or forget them.”) and as a line above the Duplicate finder result dock. The Restore screen shows it too. The HLD had placed it in “the confirm dialog”; the approved mock sets the placement above, and HLD section 4 is amended to match.
- Defaults approved with the mock: the ledger is on by default for every OfficeKit move to Trash; entries last 30 days; at most 10,000 entries, the oldest dropped first; each item can be forgotten on its own; emptying Trash does not erase entries early, and they show “Not in Trash”.
- Button counts, as the mock states them, and kept in the UI tests: Storage cleanup review 2/3 (Back to results, Confirm cleanup; unchanged); Duplicate finder result 3/3 (Copy report, Download, Move selected to Trash; unchanged); Restore from Trash list 1/3 (Restore selected, disabled when nothing is selectable or selected); Restore from Trash result 1/3 (Done); empty Restore from Trash 1/3, disabled. Row links “Restore to…” and “Forget”, and in-text links, are not counted.
- Native confirmations, outside the page: “Restore N items?” with “They go back to their original folders. Nothing is replaced: if a name is taken, that item is skipped.” and Cancel / Restore; “Forget “name”?” with “OfficeKit removes it from this list. The item stays in Trash, and you can still drag it out yourself in Finder.” and Cancel / Forget.
- Earlier owner answers this mock relies on, quoted as recorded in the HLD: “Approve as designed” (2026-10-22), “Show paths” (full host paths shown in the local-only Restore view) and “F11 then S06 PR” (F11 merged first, S06 as its own PR).
- Build choices outside the mock, for the owner to confirm (LLD section 11.7): freed space is not measured with `statvfs` (the result reports restored bytes only); Show in Finder for a restored item uses `trash_restore_reveal`, which takes a path and refuses links.
- Owner answer 2026-10-23 to the Restore result note, quoted as given: “New wording (Recommended)”. The Restore result note reads “Skipped items stay in the list, where you can use Restore to…” and is shown only when at least one item was skipped. A clean result shows no note. This replaces the note copy and the always-on placement that the approved mock showed on the Done result (mock section G), and the change is recorded here so the approval record matches the built screen (PM-3, UX-9, UX-11, UX-12).
- The temporary mock HTML is not in the worktree and is removed as AGENTS.md requires. This record keeps the approved decision.
