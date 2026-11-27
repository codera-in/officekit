# Approved navigation, names and tool-screen direction

Version: 1.0.11 · 2026-10-24 · Decision 20: calculator card names the calculator, no docked bar on calculator screens, card fills the work area (approved 2026-10-24). Earlier: 1.0.10 · 2026-10-23 · Decision 1 records one accepted exception: the Archive screen title “Archive tools” against the catalogue name “Compress & Extract ZIP” (owner, “Accept the exception (Recommended)”). Earlier: 1.0.9 · 2026-10-23 · Decision 11: the archive half is superseded by the owner's “Files v3 mock” answer. Approved 2026-10-22 · Implementation in progress (see decisions 12–19). Screenshot editor action bar built 2026-10-23 (decision 12). Media toolkit type-from-files built 2026-10-23 (decision 17). PDF sign-panel cap 2026-10-23 (decision 18). Mixed batches grouped by type 2026-10-23 (decision 19).

## Approval

The owner reviewed four proposals in a new Superset Browser tab and replied **"approved"**. The approval covers the direction in the four mocks below. It does not approve any single screen's final copy, which is set when each screen is built.

## Problem recorded

A whole-app review (13 sidebar destinations, 57 tools, captured at 1440px and 390px) found that the app is hard to use because of structure:

- One screen holds several unrelated tools: Calculators (10), PDF (12), Converter and Workspace (about 8 each).
- The same tool has up to six names across the sidebar, screen title and catalogue.
- The sidebar groups ("Pro Studios", "Categories") disagree with the gallery categories.
- Batch renamer and Archive tools show every option at once, with no order or default.
- Archive tools puts a 42-row reference table in the main form.
- Several screens show more than the three buttons allowed by AGENTS.md.

## Decisions

1. **One name per tool.** The sidebar item, screen title and catalogue name are the same string. One exception, accepted by the owner on 2026-10-23 (“Accept the exception (Recommended)”): the Archive screen is titled “Archive tools”, while its catalogue entry stays “Compress & Extract ZIP”.
2. **No tool groups in the sidebar.** Superseded 2026-10-22 by the owner: the six-row sidebar from commit `dd01407` stays (Home, All Tools, Favorites, Recent tools, Activity, Settings). Tools are found by search and on the All Tools page, which groups them by category. The seven-group plan is dropped.
3. **One screen per tool.** Shared screens are split. A group hub is a plain list of its tools, not a mode switch. Calculators is the first split.
4. **Standard tool screen:** Input, then Rule or options (only what the tool needs, defaults set, "More options" for the rest), then Result, then one primary action in the bottom bar.
5. **Reference material behind a disclosure.** Format lists and similar tables are not on the main screen.
6. **Header:** Search, Help (holding Tour) and Activate. Theme moves to Settings. Refresh moves to the screen it applies to.
7. **Trust banner** shown once or in Settings, not on every screen.
8. **Copy states the task,** not the system or implementation detail.
12. **Over-limit screens approved as mocked (owner, 2026-10-22: "approve all four mocks").** Each screen keeps three buttons or fewer. Voice transcription: the one setup step still needed, then the task; model, shortcut, terms and clear-history move into Details. Media toolkit: one picker, then the one task; the other options move into Details as text links. Screenshot editor: "Choose image" covers file and paste; Copy, Download and Optimize move into Save and More. Ergonomics: Preview and Pause become text links; Save settings is the one primary action. Mock HTML was removed after approval. Build not yet started; it is tracked as step 4b.
11. **Batch renamer and archive follow the tool template.** Rename asks "How to rename" and shows only the fields its rule uses. The archive screen asks "What to do", offers "Make a ZIP" and hides the single-format picker. The screen is titled "Compress & Extract ZIP", as in the catalogue. Reset is removed, because choosing files replaces the selection. Both screens stay at three buttons or fewer. Superseded 2026-10-23 for the archive screen by the owner: “Files v3 mock”. The archive screen is titled “Archive tools”, keeps the “Operation” picker and Format field, runs “Extract selected or all” or “Create ZIP”, and keeps “Reset selection” as an in-text link (see `2026-10-22-approved-pending-tools.md`, 1.11.0). The renamer half of this decision stands.
10. **Calculators: one screen each.** The eleven-pill selector is removed. Each calculator's heading and subtitle come from the catalogue name. The only way back is "All tools". The approved hub list is not built, because the six-row sidebar (commit `dd01407`) has no Calculators entry to open it from; the hub is still open if the sidebar decision goes back to groups.
9. **No empty bottom bar.** The bar appears only when a screen has a task action or result. Browsing screens and tool screens with nothing to do show no bar. Owner request 2026-10-22: "fix it across all the pages". This replaces the earlier rule that kept a name-only bar on every page.
13. **Universal success and failure feedback.** Owner approval 2026-10-22 ("mock is approved for universal success"). Every action shows its outcome in one slot beside the button: green tick and words for success, red icon, reason and next step for failure (`role="alert"`), and progress while working. The same helper and wording on every tool; the app-wide toast is used only for a background failure the user cannot see from the action. Per-tool status text is retired for action results. Mock 11, removed after approval.
14. **Section list for long screens.** Owner approval 2026-10-22 ("approved"; mock 12). A screen with several sections (Voice transcription has six) shows a section list on the left that jumps to each section. Links, not buttons, so they do not count toward the button limit. The current section is marked; sections that do not apply to the user's setup are hidden; the list becomes a row across the top on a phone. Mock 12, removed after approval.
15. **Voice: Speech Coach as a section, no tabs.** Owner approval 2026-10-22 ("approve the mock"; mock `voice-speech-coach-sections`). The Voice screen is one scrolling screen with the section list. Speech Coach (from the Speech Coach PR) is a section beside Dictation and Smart dictation. The Dictate, Speech Coach and Setup tab bar is removed, and Setup & history sections stay in place rather than moving into tab panels. The list has five links, as in the mock; the Personal dictionary section stays on the screen without its own link.
16. **Home has one search: the header bar.** Owner request 2026-10-22 ("remove home search"). The "Find a tool or task" field on Home is removed; the header search (⌘K) covers every screen.
17. **Media toolkit: type from the files, one task.** Owner approval 2026-10-23 ("APPROVED", mock `media-by-type`, removed after approval). The type is detected from the chosen files: an image batch lists the 8 image operations, video the 9 video, PDF the 5 and audio the 5. A JPEG-only batch does not offer JPEG as a convert target. A mixed batch is grouped by type instead (decision 19). "Select files" is a text link. The operation select is labelled "What do you want to do?". Run is the one primary button; Start over and Save appear only after a run. Unavailable operations stay in the list, disabled and marked "unavailable", as before (the mock hid them; the owner's approval did not address this, so it is open).
19. **Media toolkit: mixed batches grouped by type.** Owner approval 2026-10-23 ("approved", mock `mixed-grouped`, removed after approval). A batch with more than one type lists its operations under one labelled group per type, for example "Images (2 files)", "Video (1 file)". Choosing an operation applies it to that type's files only; each type keeps its own settings. "Settings for <file>" selects that file's type. Still one Run button.
18. **PDF editor (annotate): bottom bar and sign panel.** Owner approval 2026-10-23 (mock `media-and-pdf`, removed after approval; answer B: the tool tray is not counted). The bottom bar keeps three buttons (Download PDF, Verify signatures, Sign PDF). The inspector column is capped to its grid track so the sign panel cannot run past the window edge. The overflow the owner saw did not reproduce at 800, 1000 or 1280 px in the test harness; the cap is defensive and the exact pane width is still needed to confirm it.

20. **Calculator work area: name in the card, no bottom bar.** Owner approval 2026-10-24 ("Approve the after version", mock `workarea`, removed after approval). The card heading is the calculator's name. Calculate, Save result and Download all sit in the card (option A of mock `result-actions`, owner choice 2026-10-25: "Option A"), and calculator screens show no bottom bar. The card fills the work area down to the version footer, so no empty band sits between them. Settings icon unchanged. The approved bottom row (status left, one Calculate button right, inside the card) is built on all 27 calculator forms; the status text is the approved placeholder "Result appears here after you convert." and does not change after a run. "All tools" is a text link, so the screen stays within three buttons.

## Order of work

1. Rename and regroup the sidebar and tool names (lowest risk).
2. Split shared screens, starting with Calculators.
3. Apply the tool-screen template to Batch renamer and Archive tools, then to the rest.
4. Remove or move extra buttons and the always-on banner.

Each step needs its own review against the approved direction before code lands.

## Evidence

- Screenshots and metrics from the whole-app capture are in the local review folder (not committed).
- Audit report: `review/ui-ux-audit-5ca6b928/app-audit/ux.md` (local, gitignored).
- The temporary mock HTML was removed from the worktree after approval, per AGENTS.md.
