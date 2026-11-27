# OfficeKit design handoff

## Approved UI changes — 2026-10-27 (Network Stats in Mac menu bar)

The owner clarified “Don't want it in the app title bar. I want it in the Mac title bar where we already have it.” The approved placement is the existing macOS Network menu-bar popover. Keep its current rates, history, interface, local address, totals and Network Settings; add the on-demand router-versus-internet result, Run network check action, and Cloudflare Speed Test link there. Remove the duplicate network chip and popover from the app header. The owner also asked to reduce the empty space in the popover; the approved revision distributes the rate gauges across the width and draws traffic history as a line across the chart. Owner approved the revised mock with “Approve revised layout” (2026-10-27). The mock was inspected in a new Superset Browser tab and passes the three-button check. Temporary mock and preview are removed after implementation.

## Earlier approved direction — superseded placement

The initial mock put the rate chip in the OfficeKit app header. That placement was superseded by the owner's clarification above. The diagnostics and Cloudflare shortcut remain user-triggered; wired Ethernet is supported, and an isolated LAN can report gateway timing without claiming an ISP result. The Cloudflare link opens `https://speed.cloudflare.com/`.

## Approved UI changes — 2026-10-21 (Meeting countdown)

The owner requested “I WANT full animation” and approved the inspected Superset Browser mock with “approved”. Reuse the original companion with watch-check/tap, countdown-pointing and starting-wave poses, calendar selection and permission recovery. Existing placement, quiet hours and reduced motion apply. Preview follows the existing inline-link pattern so the workbench stays within three buttons (calendar permission/recovery, contextual motion control, Save). The temporary mock was removed after approval. Durable details: `docs/ui-research/2026-10-21-approved-meeting-countdown.md`; reviewed sample screenshot: `docs/ui-research/meeting-countdown-companion.png`.

## Approved UI changes — 2026-10-20 (Global launcher)

The user reviewed the before/after mock in the Superset Browser and chose "Approve as is". ⌃⌥Space opens the floating panel over any app: type to find OfficeKit tools, clipboard clips and snippets (grouped, with a footer of key hints), an empty state with recent tools and pinned snippets, a Launcher shortcut row in the Global clipboard and snippets settings card, and a phone-width layout. Built so far: tool and snippet search and open. Not built yet: dropping files on the launcher (needs native filesystem grants) and recent/pinned empty-state sections. The temporary mock HTML was removed after implementation.

## Approved UI changes — 2026-10-20 (Storage analyser redesign)

The user reviewed the before/after mock in the Superset Browser and chose "Approve as is". Results show four summary tiles (free after cleanup, safe to remove, needs review, not scanned), a category explorer with a Category/Cleanup toggle (hatched tiles hold removable items, dashed tiles need review), and a recommendations list split into Safe to remove and Review first, with a sticky footer holding "Select safe" and "Review cleanup". There is no "Copy script": cleanup always goes through the review dialog and native Trash. "Select safe" never selects anything under Review first. The temporary mock HTML was removed after implementation.

## Approved UI changes — 2026-10-19 (Global clipboard, snippets and window manager)

The user reviewed before/after mocks in the Superset Browser and approved both "as is". Clipboard history (⌘⌥V) and snippets (⌘⌥S) open as floating, non-activating, searchable panels over any app: type filters (All, Text, Images, Links, Pinned), source app and age per row, Enter pastes into the previous app, Esc closes, with an empty state. Snippet keywords expand while typing in any app, with a short "Expanded ;sig → Email signature" notice (no undo promise, since undo belongs to each app). The Clipboard tab gains one settings card at the top: Accessibility banner, background capture, the two shortcuts, keyword expansion, skipped apps, retention (500 clips / 30 days) and open at login (off by default). The window manager moves the focused window of any app with global Rectangle-style Ctrl+Option shortcuts (halves, quarters, thirds, two thirds, maximize, center, restore, next/previous display) and snaps any window dragged to a screen edge with a preview first; its settings card has a global-shortcuts toggle, drag-to-edge toggle, gap (0–20 px), skipped apps and a shortcut editor. Saved named layouts are a follow-up. The temporary HTML mocks and preview files were removed after approval.

## Approved UI changes — 2026-10-17 (Apple Pro UI Revamp)

The user approved the Apple Pro UI Revamp aligning OfficeKit with macOS Sequoia / Sonoma Human Interface Guidelines. The revamp replaces outdated boxy 1px slate borders with optical specular hairlines (`--hairline`), integrates Liquid Glass split-pane materials (`backdrop-filter: blur(28px) saturate(180%)`), adopts a calibrated Space Black dark mode (`#090E17`) with Electric Azure vibrancy shift, introduces a floating Siri-style STT HUD overlay (`⌥ Space`), a tactile multi-stage progress bar system with shimmering gradient track, and a frosted glass in-app system banner with embedded mini progress feedback. TDD verification confirmed 100% pass rate across 50 tool execution scenarios, 0 document overflow, and preservation of standard 40px/44px control heights. Interactive reference mock: `design/mocks/apple-ui-revamp.html`.

## Approved UI changes — 2026-10-14

The user reviewed the before/after prototype and approved three visible changes: keep Screenshot Editor annotation controls reachable when the workspace scrolls; make Storage Cleaner report columns readable with contained horizontal scrolling and place report actions after the rows; and replace native platform select popups with themed OfficeKit menus. Dropdown menus support keyboard navigation and follow the active light/dark theme. Native select values and change events remain connected to existing tool logic. The temporary HTML preview was removed after implementation.

Status: ready for design review; application implementation is not included.

Start with [the complete flow prototype](mocks/officekit-final-flow.html). Open it directly in a browser with `officekit-tokens.css` left in its parent directory. No server, dependencies, external fonts or internet access required. This is the preferred next mock; earlier files remain as review history and alternate brand exploration.

The requested screenshot editing flow has a separate [workbench mock](mocks/screenshot-editor-workbench.html). It is a design proposal only: clipboard access, image editing, undo and export are not connected to production code.

## Review the flow

1. Browse the category-grouped Gallery, switch to List, filter a category, then search “loan” or “EMI” and press Enter.
2. Calculate the prefilled USD 25,000 / 7.5% / five-year loan.
3. Change an input and inspect the stale-result notice; calculate again if desired.
4. Open Export. Compare PDF, CSV, JPEG and PNG; remove the attribution footer.
5. Close Export, choose Save result, and open History → Saved.
6. Reopen the original snapshot, rename it, and choose Use these inputs.
7. Repeat in Light and Dark from the navigation theme selector.
8. Try a negative amount, zero interest, a term shorter than one month, an empty search, and a search with no matches.

Numbers are actually calculated in the prototype. History, favorites and bookmarks exist only for the browser session and reset on reload. Export presents a designed preview, not a file generator. Copy attempts the browser clipboard and reports failure if unavailable. PDF merge and image conversion are labelled navigation placeholders, not functioning tools. Consent controls never store/send data. These deliberate mock limitations must not be mistaken for production acceptance.

## Canonical specifications

- [Whole product plan](../docs/PRODUCT-PLAN.md): consolidated UX, architecture, features, privacy, safety and phased roadmap.
- [123-capability release matrix](../docs/RELEASE-123-TOOLS.md): expected tool depth, acceptance cases, AI-friendly/share-ready exports and value workflows.
- [Tool guide and depth audit](../docs/TOOL-GUIDE.md): current catalogue, engine/API/UI coverage and missing capabilities.
- [Testing guidelines](../docs/TESTING.md): required checks and evidence for engines, UI, exports, consent and three-OS releases.
- [Communications plan](../docs/COMMUNICATIONS-PLAN.md): What's new, update alerts and quick banners.
- [Design system](../DESIGN_SYSTEM.md): design intent, exact tokens, themes, accessibility, tool/results/history/export/privacy rules, and review gate.
- [Token reference](officekit-tokens.css): semantic CSS variables in light/dark modes.
- [Component structure](COMPONENT_STRUCTURE.md): proposed source layout, ownership, typed boundaries and state.
- [Branding/privacy plan](officekit-branding-and-privacy-plan.md): logo alternatives, attribution, telemetry payloads, heartbeat, retention and backend release checks.
- [Brand chooser](mocks/officekit-branding.html): three palettes and three vector marks for selection.
- [Earlier UX reconstruction](mocks/officekit-ux-review.html): source-based existing pattern versus first-pass proposed screens.
- [URL codec workbench](mocks/url-codec-workbench.html): before/after proposal for local URI-component encoding and decoding; now wired to the bounded local developer-tools API.
- [Financial utility calculator mock](mocks/financial-utilities-workbench.html): margin/markup, break-even, simple interest and straight-line depreciation flows; implementation is searchable and uses the shared calculator result lifecycle.

The main proposal uses Utility blue + Toolkit as a working assumption, not a recorded brand choice. One chosen identity should ship; the alternate palettes are concept comparisons rather than permanent app themes.

## Verified and outstanding

Executed JavaScript in an isolated DOM stub and checked: normal/zero-rate calculations; whole-month schedule length; schedule principal totals; invalid-input handling; save → history → reopen → reuse; preservation of prior snapshots; stale-input notice; four export previews; unbranded preview; clean CSV preview; escaped result names; both themes; absence of network/durable-storage APIs. Static token checks passed normal-text 4.5:1 and necessary control/focus 3:1 for the tested pairs in both themes.

Browser-rendered layout, dialog focus behavior, real clipboard, zoom, actual screen-reader behavior and OS webview differences remain unverified. The available browser preview surface was unavailable. Render at 1240×840, 900×600 and 390px width, at 100%/200% zoom, in both themes; scroll top to bottom and exercise all actions before implementing. Contrast calculations are not a complete accessibility audit.

The user has explicitly authorized continuing the recommended OfficeKit implementation without waiting for additional screen approvals. Keep mocks as the design record, implement within the approved product direction, and report installed visual behavior separately from source-level evidence. Brand alternatives remain concepts until one is explicitly selected.

## Global panel: OfficeKit label and number shortcuts (approved 2026-10-20)

The clipboard, snippets and launcher panel shows the OfficeKit mark and name before its title, and the first nine visible rows carry a Command-1 to Command-9 badge that pastes (or opens) that row. Badges follow the filtered list; the footer gains "Command-1 to 9 paste row". The owner approved this mock ("all the mocks approved"); the mock was removed after approval. Verified in the installed app: the header, badges and footer render, and Command-2 pasted the second row into TextEdit.

## Spotlight-style launcher (approved 2026-10-20)

The launcher is a wide Spotlight-style panel (720pt) with a large search field, All / Apps / Tools / Snippets filter chips, recents first, installed apps beside tools and snippets, and ranked search (title prefix, then title contains, then other fields). Each filter has a user-chosen shortcut key (default Control-1 to Control-4) set in Settings under Global desktop tools. Owner feedback after the installed check: the panel hangs from 70% of the screen height and the search field has square corners. The mock was removed after approval. Verified in the installed app: the panel opened and listed apps and tools; the owner confirmed it works.

## Menu-bar drawers (approved 2026-10-20)

With persistent stats on, CPU, RAM, SSD and network each get their own menu-bar item; clicking one opens a drawer under it with the headline figure. CPU and Memory also list the busiest processes with a Quit button (the shell confirms, system processes are never offered); the network drawer shows upload and download rates and has no Quit buttons. RAM follows macOS monitors (everything except free and file-backed pages) and SSD reads the user-data volume. A Mic drawer lists the five latest dictated transcripts (first 40 characters and time) from the Dictation history already kept on this Mac, so it follows that history's clear and retention settings and adds no new store; the owner approved building it on 2026-10-20. The Window drawer from the mock is not built yet. The mock was removed after approval. Verified in the installed app: the drawers open, and the owner reported and we fixed a column misalignment.

## Menu-bar process controls and CPU/RAM details (approved 2026-10-27)

The approved mock keeps the Top applications list at the bottom of the CPU and RAM drawers, with the existing rows, order, values and per-row Quit actions. Advanced history, cores and details start collapsed behind one disclosure control in each drawer and reset to collapsed when closed. Choosing Quit shows confirmation inside the same drawer; confirming closes only the selected process, leaves the drawer open and does not foreground the OfficeKit window. The owner said the mock looked good and confirmed the bottom application list should remain untouched. The mock was inspected in a new Superset Browser tab and passed the three-button check; the temporary HTML is removed after implementation.

## Global panel look (2026-10-20)

The clipboard and snippets panels share the launcher position (top edge at 70% of the screen height) and its large square search field. The clipboard Text filter includes links. The launcher may be set to Command-Space once Spotlight's own shortcut is off.

## Launcher quick results (approved 2026-10-20)

In the All filter the launcher shows a result row above the normal matches for a typed sum (+ - x / ^ % and brackets, "15% of 800"), "uuid" or "guid" (dashed and plain), and "password" or "pw" with an optional length from 8 to 128. Enter pastes into the app the launcher opened over (the previous clipboard comes back); Shift+Enter copies, marked transient so clipboard managers skip it. Computed locally with the system secure random generator; nothing is stored. The four-word passphrase row from the mock is not built (a weak embedded word list would not be strong). The mock was removed after approval.

## Skip-app picker (approved 2026-10-20)

Settings, Global desktop tools, clipboard history card, Edit: the apps whose copies are never saved are chosen from the installed apps (search box and checkbox list, ticked apps first) instead of typing bundle ids. The bundle-id box stays under "Add an app by bundle id". Only app names and bundle ids are read. The mock was removed after approval.

## Launcher finance results (owner request 2026-10-20)

Same row style as the quick results: `emi 500000 8.5% 20y` (also `loan`; months as `240m`) shows the monthly payment and, below it, the total repaid; `compound 10000 7% 10y [500]` (also `invest`) shows the balance after monthly compounding with an optional monthly deposit. They use the Loan EMI and Compound interest calculators' bounds and cent rounding, and give no row for missing, out-of-range or part-month values.

## Media tool image preview (approved 2026-10-20: "LOOK GOOD TO ME")

In the Media Toolkit file list each image gets a 48 px thumbnail and its pixel size beside the file size; the file whose Settings are open (the first image by default) also gets a larger preview with its name, pixel size and "Preview only; the original is not changed". HEIC is decoded locally through macOS; files this build cannot draw (for example JXL or AVIF) show a "No preview" tile and "preview unavailable", and can still be prepared. Audio, video and PDF rows are unchanged. Previews come from `GET /api/media-previews/{selection}/{file}?size=32-640`: read-only, at most 64 MiB and 100 megapixels, one request at a time, kept in memory only. Mock `media-image-preview.html` removed after approval. The action bar keeps Prepare copies, Cancel job and Clear selection in the bottom dock.

## Media tool previews for every file type and expanded viewer (approved 2026-10-21)

Videos, audio and PDFs now get the same 48 px row thumbnail and larger preview as images, and any other file gets a labelled type tile (icon and extension) instead of "No preview". Video shows a still frame with its duration; audio shows its cover art or a waveform with its duration; a PDF shows page 1 with its page count and a previous/next page control in the larger preview; password-protected PDFs show a lock tile ("password protected"). An Expand button (or a double-click on a thumbnail or the larger preview) opens a viewer over the app: zoom out/in, Fit, 100%, drag to pan, scroll or pinch to zoom, previous/next file, PDF pages (PgUp/PgDn), a frame-position slider for video, full screen (the browser's full-screen mode where the webview allows it, otherwise the viewer fills the window) and keyboard shortcuts (arrows, + - 0, F, Esc). Video and audio are still previews only, with no playback. Image and PDF previews work on every platform; video and audio use the macOS media helper and fall back to the type tile elsewhere. `GET /api/media-previews/{selection}/{file}?size=32-2048&page=&position=` is read-only, limited to 64 MiB, fetched one at a time per lane and kept in memory only (the last six viewer-size pictures). A password-protected PDF answers 200 with `locked: true`. Mock `media-preview-all-types.html` removed after approval.

## Media Toolkit clear next step (approved 2026-10-21: "mock approved")

Owner feedback: "ui is intunutive as not sure where to take next action". The Prepare view gets a three-step strip (Choose files, Choose operation, Prepare copies; finished steps show a check) and one highlighted Next panel under the settings that says what to do now and holds the main button: "Next: choose files" (button disabled) with nothing selected, "Ready: N files → operation" when ready, "Preparing copies…" with Cancel job while a job runs, and a green "N copies ready" with Show results afterwards. Choose files is the primary button until a file is selected. Link import, Recent results (opens by itself when results arrive) and Operation coverage are collapsed sections; nothing was removed. The bottom action bar stays as the scroll-proof shortcut. Mock `media-toolkit-next-step.html` removed after approval.

## Tool catalog header: one category control (approved 2026-10-21: "header redeign approved")

Owner feedback: the "All categories" dropdown arrow overlapped its label and the category pills repeated the dropdown (the last pill wrapped alone onto a second row). The pill bar is removed. The dropdown stays, is wider, and each option shows its tool count ("All categories (124)", "Documents (20)"). The Gallery/List switch, search and the rest of the page are unchanged. Starring a tool now flips the star at once and reverts it, with the existing "Could not save this preference" notice, if the save fails. Mock `tool-catalog-header.html` removed after approval. The dropdown keeps 2.75 rem clear on the right (set in the stylesheet, not inline) so its arrow never covers the last character of the label.

## System overview: fewer buttons, loads on open (approved 2026-10-21: "mock is approved")

Owner feedback: "it should load automatically" and "too many buttons" (six in the bottom bar plus Check this Mac). Opening System overview now loads the recommendations, CPU and memory snapshot and redacted summary by itself. The bar shows three buttons: Refresh (reloads all three), Copy report and Download report (the redacted summary). Check this Mac, Refresh metrics, Load summary and the metrics Copy/Download pair are gone from view (the first three stay in the page, hidden, as the Refresh button's targets). Other screens with long button rows (Network diagnostics shows seven after a lookup and a ping) have not been changed yet.

## Media Toolkit: numbered cards, named action, three buttons at most (approved 2026-10-21: "approved")

Owner feedback: "it is still confusion, i was searching where is the operation" and "prepare copies is confusing, what copy?". The page is two numbered cards that match the step strip (1 Files, 2 Operation, 3 Run). The main button names what happens to what ("Optimize 1 image", "Convert 3 files"; other labels read "<operation> · N files"); the word "copy" is gone from buttons and the result is called a result. The bar shows at most three buttons: Choose files and the named action when ready; Cancel (replacing the action, Choose files disabled) while running; Start over, Save (Save all for several) and "<action> again" when done. Removed from view: the Next panel's button, Show results (results open on their own), per-file Settings and Expand buttons (click the file row; it is a keyboard-reachable role=button), and Save as local default (now inside Advanced). Mock `media-toolkit-three-buttons.html` removed after approval.

## Network diagnostics: sections, three buttons at most (approved 2026-10-21: "mock approved for network interfaces")

DNS lookup, Ping and Interfaces are now three sections chosen with a switch under the intro text (like tabs, not counted as buttons); only the chosen section and its result are shown. The bottom bar shows that section's action plus one Copy and one Download: Look up records, Run ping, or Refresh, which replaces "Refresh interfaces". Choosing Interfaces reads this Mac's interfaces at once (it sends nothing anywhere); DNS and Ping still run only when asked. Opening a tool from search lands on its own section. Seven buttons became three. This follows the "no more than 3 buttons per page" rule in `AGENTS.md`. Mock `network-diagnostics-actions.html` removed after approval.

## Tools page: no second search bar (owner request 2026-10-21)

"we dont need it as we have search bar at the top": the "All capabilities" search field on the Tools page is hidden from view. The input stays in the page, visually hidden, because the top search and Home search pass their query through it. The "All capabilities" heading and the "Showing N of M" count stay.

## Switches: explicit on state (approved 2026-10-21: "approved")

Owner feedback: an on switch was an outlined pill with the knob on the right, easy to mistake for off. Every switch in the app now shows on as a filled accent pill with a dark knob; off stays an empty grey outline with the knob on the left. Labels, size, layout and the focus ring are unchanged. Mock `toggle-on-state.html` removed after approval.

## Six-row sidebar with starter favorites (owner choice 2026-10-21: "6 rows, seed favorites"; build requested with "start these pending items")

Owner feedback: the Workspace / Pro Studios / Categories groups were confusing, the studios were an arbitrary subset of the tools, and Categories duplicated the All Tools category dropdown. The sidebar is now Home, All Tools (count), Favorites (count), Recent tools, Activity and, pinned at the bottom, Settings, with no headings or per-row badges and no scrolling. The seven former studios (Loan & Mortgage EMI as the finance entry, Edit/Annotate/Sign PDF, Screenshot Editor, Voice Transcription, Storage analyser, CPU & Memory Overview, Clipboard & Snippets) are added to Favorites once (`officekit.favorites.seeded.v1`); an owner's existing favorites stay first and a removed favorite is never re-added. The System stats page (formerly "Progress & Tasks") has no catalogue entry and stays reachable from the menu bar. Tour steps for Speech-to-Text, Clipboard and Storage now point at the page heading. Mock `sidebar-clean.html` removed.

## Break: follow-me stretch routine (approved 2026-10-21: "approved")

Owner feedback: the character froze after 4 seconds of a break; it should show real stretches and say "Follow me". While a break is active the companion loops four 20-second steps built from the poses already in the stretch sheet (reach up, lean left, lean right, shoulder roll): the title reads "Follow me!", with the step name, a hint, four progress dots and "step n of 4" beside the countdown. Buttons are unchanged (End early, Snooze, Pause all). Reduced motion shows one still pose per step. Before Start, and on eye and water reminders, nothing changes. New poses (neck, wrist, standing back-bend, hips, dance) need new character art and are not included. Mock `guided-stretch.html` removed.

## Searchable ZIP and image compression entries (owner request 2026-10-21)

"Where is the file compression utils? ... image compression." The archive manager (PR #19) had no catalogue entry, so search never found it. Added `archive_manager` ("Compress & Extract ZIP", opens Archive tools) and `image_compress` ("Compress Images", opens Media Toolkit with image optimisation chosen) as ordinary catalogue cards; no new screen or engine.

## Ergonomics settings and the bottom bar on every page (approved 2026-10-21: "yes approved")

Owner feedback: "ui inconsistencies" and "some pages have footer / some don't". Ergonomics fields now share one style (40 px, label above in muted 13 px, same border), switches sit on the right of a row with the text on the left, Preview and Pause all are text links, and head-angle sensing has one contextual button (Enable & calibrate, then Recalibrate) plus a Turn off sensing link, so the page shows two buttons. A reminder preview gains a Close preview button (Start, Replay, Close; Pause all is hidden in a preview). The bottom bar (68 px) is now on every page: Home, Tools, Favorites, Recent, Activity, Settings and Clipboard show the page name and no buttons. Mocks `ergonomics-consistency.html` and `bottom-bar-everywhere.html` removed after approval.

## Transcript steps view and dictionary word list (approved 2026-10-22: "approved")

Owner feedback: speech-to-text seemed to miss words and there was no way to see why; a first mock with a debug switch in settings was rejected ("Since we have this history, ... open a debugging view ... for every history of transcription, we can go in and see the full processing history"). A push-to-talk row in Recent transcripts now has a "Steps ›" chip (clicking the text does the same). It replaces the list with: Microphone (recorded seconds, speech found, silence trimmed, loudest level), Heard (raw text before any cleanup), Smart cleanup (the raw text with removed words struck through), Dictionary and tidy (the text after dictionary fixes, punctuation and capitals, plus one line per dictionary fix), On-device polish (used or not), Final text with its delivery result, and the settings in force. The page shows two buttons, Copy raw and Copy final; "Back to transcripts" is a link and Escape also goes back. Steps are saved inside the history entry, so they follow its retention, Remove and Clear history; entries saved earlier and meeting or audio-file transcripts show "No steps recorded" or no chip. Differences from the mock: steps follow the real order (smart cleanup runs before the dictionary), there is no engine/language label, and a recording with no speech is not saved to history (it fails with an error that now names the recorded seconds and loudest level).

The Personal dictionary takes plain words: "Word or phrase" first, "Often misheard as (optional)" second, one Add button, commas split several words, and each row is tagged Word or Replace. A plain word is sent to the speech model as a hint and, after transcription, a cautious sound-alike fix turns "easy D P" into `easydp` (at least four sound letters, same first sound, text under 20,000 characters); an explicit replacement always wins. Each fix is listed in the steps view. Mocks `dictation-debug-steps.html` and `dictionary-word-list.html` removed after approval.

## All processing levels in the transcript history (approved 2026-10-22: "lgtm")

Owner feedback: the steps view only showed the translation layer, some transcripts were lost or garbled, and there was no way to tell which level caused it. Every push-to-talk attempt is now saved, including failures (tags No speech heard, Speech model error, Capture error, Cleanup failed, Cancelled), and a "Words lost" tag appears when a level keeps 70% or fewer of at least five words. The steps view numbers the levels in the order they ran (Microphone, Speech model with its name and, when Faster results was on, the pieces it was decoded in, English translation, Smart cleanup, Dictionary and tidy, On-device polish, Final text, Settings) with word-count badges such as `19 → 11`, amber when a level lost 30% or more. A failed attempt stops at the level that broke with a plain diagnosis and marks later levels Skipped. Failed rows offer only Remove; the detail page keeps at most two buttons (Copy raw, disabled with no text, and Copy final, hidden for failures). No audio is stored, only numbers and text, on this Mac. Differences from the mock: the translation level sits right after the speech model because translation runs before cleanup, a translated dictation saves one entry (the English text with the original heard text in its steps), a failed cleanup keeps the raw text in history but does not paste it, and cancelled attempts are recorded. Mock `dictation-all-levels.html` removed after approval.

## Reminder Close button and guided eye rest (approved 2026-10-22: "approved")

Owner feedback: the reminder bubble could not just be closed, and the eye rest only counted down. A round ✕ in the top-right corner (also Escape) dismisses the reminder without snoozing: the next one comes at its normal interval; a meeting reminder is hidden, a preview closes. The bubble already showed three buttons, so Pause all became a text link (links are not counted) and the Close preview button was replaced by the ✕; every state shows at most three buttons. During an active eye rest the bubble names three steps (Look far away, Blink slowly, Look side to side) with progress dots, a step announcement for screen readers and the remaining time; the steps share the configured rest length at 5 to 10 seconds each. The mascot keeps its current animation: eye-exercise poses will be supplied separately, and a step can gain mascot frames later. A drawn in-bubble animation shown in an earlier mock was rejected. Mock `reminder-close-button.html` removed after approval.

## Meeting reminders calendar list (approved 2026-10-22: "calendar mock approved")

Owner feedback: after Calendar access was allowed the calendar list was misaligned and showed nothing while loading, and there was no way to open a calendar. The list is now two tidy columns (one below 480 px) with each checkbox directly beside its name (long names are cut with an ellipsis), a "Calendars · N of M selected" heading, and a small ↗ "Open in Calendar" row action per calendar (not counted as a button). macOS cannot deep-link to one calendar, so it opens the Calendar app and the tooltip names the calendar; the native `open` action of `ergonomics_calendar_action` does this. While calendars load (refreshing, or allowed with no list yet) a spinner, "Loading your calendars…" and four placeholder rows show; reduced motion freezes them. The empty state text and the footer are unchanged (the footer already uses the shared action dock), and the page still counts 2 buttons (Save settings, Pause all link). Mock `calendar-list-alignment.html` removed after approval.

## Launcher tool icons (approved 2026-10-22: "all three approved, build them", with "keep the color little less intensive")

Owner feedback: every OfficeKit tool in the launcher showed the same indigo wrench. Tool rows now show the tool's own catalog icon, mapped to the closest macOS symbol, on a rounded square coloured by category (PDF red, Images orange, Finance green, Calculators and Unit Converters blue, Developer purple, Audio pink, File Utilities and Storage yellow, Network teal, System grey, anything else indigo). On the owner's request the colours are less intense than the mock: saturation is reduced to about 60% and brightness slightly lowered. A tool with no icon, or a symbol this macOS lacks, keeps the wrench in its category colour. Applications keep their own icons; quick results, commands and snippets are unchanged; no buttons added. Mock `launcher-tool-icons.html` removed after approval.

## Detailed menu-bar drawers (approved 2026-10-22: "all three approved, build them")

Owner feedback on the Stats-style drawers: Memory, CPU and Disk keep their headline figure and process list, and gain a usage history graph, a details breakdown and an Open Activity Monitor action in every drawer. Network gains a traffic history graph with rates only. The approved mock was design/mocks/menu-bar-detailed-drawers.html; it is not committed, and this section keeps the decision.

Decisions: the history is kept in memory only (the last 90 samples, about three minutes at the two-second drawer rate) and is never written to disk. Quit stays on each process row behind a confirm and is offered only for the signed-in user own non-root processes outside OfficeKit own process tree. The Disk drawer bottom buttons stack full width so they stay inside the card, which fixes the overflow in the mock. Each drawer shows at most three buttons: the Activity Monitor header link, the bottom Activity Monitor button and, on Disk only, Open Storage analyser. Labels: Disk history is "Activity history" and Network history is "Traffic history", as the mock shows.

Left out on purpose, because macOS gives no reliable unprivileged source: CPU frequency, temperature, the per-core Efficiency and Performance split, and per-process disk read and write. Nothing is shown for them rather than invented numbers.

## Global tools: separate switches, Global Launcher and capture pause (approved 2026-10-22: "all three approved, build them")

Owner feedback: one "Global clipboard and snippets" card held six things, so the launcher could not be switched off on its own. Built as the approved mock shows: the Global Launcher is its own catalogue tool with a launcher switch that releases its shortcut, a "Show in results" choice (Apps, Tools, Snippets), Calculator, UUID and Password quick-result switches, and filter keys (pick a filter, Change key, Reset). The clipboard history card gained Pause capture (Off, 15 min, 1 hour, Until I resume) with an amber banner ("Capture paused until 5:40 PM" or "until you resume") and a Resume button, a menu-bar row "● Clipboard paused" while paused, and Panel opens on (All, Text, Images, Links, Pinned; default Text, which includes links). The snippets card has a snippets panel switch that releases its shortcut, next to keyword expansion and the shortcut. A pause never deletes history. Decisions: the master "Use OfficeKit from any app" switch stays where it was, at the top of the clipboard card, not at the top of Settings; every new switch defaults to on, so the Password generator is on by default although the mock drew it off; the clipboard history shortcut stays registered while the master switch is on, because its panel still shows saved clips while capture is paused; the Global Launcher page carries a "new" pill in its header, since the catalogue has no badge field. Button budget on the new screens: the clipboard block shows at most three (Resume while paused, clipboard shortcut, snippets shortcut), the accessibility action is a text link, skipped apps is a disclosure that saves as it changes, and the launcher page shows three (shortcut, Change key, Reset) with one selector for the filter. The clipboard panel's own header buttons predate this change and remain above the limit. The mock `global-tools-settings.html` is kept in the main checkout's design/mocks and is not part of this branch.

## Reminder fade-in teaser (approved 2026-10-22: "approved and push it in the same pr")

Owner request: a reminder should be a teaser before it is a demand. The bubble and the same mascot (no separate graphic) fade in: a meeting reminder rises steadily from 0% at 30 minutes out to 100% at 5 minutes, then stays at 100% until it starts; water, stretch and eye-rest reminders fade in over the 2 minutes before they are due (the due time itself does not change). Below about 5% nothing is shown, so a faint bubble never blocks a click. A teaser has nothing to press (no buttons, Escape ignored); the real reminder takes over at full strength when it is due. A stretch or eye rest in progress always stays at 100%. A preview fades in over about 8 seconds (instantly with reduced motion). When two reminders overlap, one bubble is shown at a time: a meeting inside its last 5 minutes wins as before; before that, a wellness reminder already on screen is not pushed aside and the meeting waits; a wellness teaser yields to a visible meeting; two wellness reminders due together show one after the other. No buttons or settings were added. The mascot animation also now loops until the reminder closes instead of holding its last frame. Mock `reminder-fade-in.html` removed after approval.

## Speech Coach panel: no overlap, live level bars (approved 2026-10-23: "mock approved, build it")

Owner report: in coach-only mode the dictation controls (Esc hint, microphone icon, level meter) were drawn over the coach rows, and nothing moved for the first 10 seconds of speech. Coach-only mode now hides those controls, shows five level bars next to the title (the "Esc to stop" label was removed on 2026-10-23: Esc stops transcription only, and the coach is stopped from Quick Controls) that follow the voice at once, and shows "Measuring your pace · N of 10 s of speech" until the first pace reading. The zone track is dimmed until a reading exists. The panel has no buttons in this mode. Dictation, and dictation with coaching, keep their existing controls; their overlap is a separate pass. The 10 second rule for the first pace reading is unchanged.

## Speech Coach Live Workspace (approved 2026-10-23: "The live-workspace mock ... is approved")

Owner request: while listening (Listen In), capture speech into a temporary workspace and flag words that need correcting (for example "was" where "were" belongs) with the correct form, so every place to improve is visible at once. A second floating panel, the Live Workspace, opens from Listen In; the HUD is unchanged and the workspace is never shown automatically. It shows a level-bar header, a state line ("Listening · speak naturally", "Checking the last sentence…", or "Listening · pace and pitch only" when grammar checks are unavailable), a pace line, the live transcript with flagged words underlined and the fix as a superscript, and an Improvements list of before → after rows with a category pill (Grammar or Word choice), a one-line reason and a "Not a mistake" row link. "Not a mistake" removes the item and feeds the existing dismissed-pattern list. Bottom bar: "Copy corrected text" (primary; "Copy text" when nothing was checked) and "Done", so 2 buttons (limit 3). Grammar checks unavailable shows a warning and "Not checked", never "0 mistakes". Privacy: transcript and fixes live in memory only while the workspace is open, are cleared on Done or close, and are never written, logged or sent; session notes keep only counts and categories. Limits: last 2,000 words, one grammar check in flight, a slow check never blocks audio. Checks reuse the on-device grammar and word-choice suggestion run on each completed sentence; a fix whose quoted words cannot be found exactly in the sentence is dropped.

## Transcribe and Speech Coach as separate overlays (approved 2026-10-23: "mock appoved. build it after live workspace")

Owner request: keep transcription and the coach as two separate overlays instead of one shared panel. The transcription overlay returns to what it was before the coach existed (Transcribing, live preview, level meter, "Esc to stop") and never shows coach rows. The coach overlay shows pace, pitch, level bars and the live cue, with no Esc hint, mic icon or meter, while the coach is coaching a dictation or Listen In is running. Esc stops transcription only and never stops the coach, which is stopped from Quick Controls (or Done in the Live Workspace). Both panels follow the existing corner setting; when both are visible the coach stacks 8 px away from the transcription panel on the side away from the screen edge, never overlapping; each hides independently and the other is not moved. No buttons on either panel (limit 3).

## Speech Coach panel close button (approved 2026-10-23: "mock approved, build it")

Owner request: add a close ✕ to the Speech Coach panel. A small round ✕ (24 px) sits at the top-right of the coach-only panel (Listen In) and the level bars move left to make room: 1 button (limit 3). ✕ ends the Listen In session: the microphone is released, the panel and the Live Workspace close and Listen In shows off in Quick Controls; Speech Coach itself stays on and still coaches the next dictation. It shows only while the Listen In panel is on screen; when the coach only rides along on a dictation the panel leaves by itself when dictation stops. Labelled "Stop Speech Coach" with tooltip "Stop Listen In"; Esc is not used (it stops transcription only).

## Quick controls: menu bar stats (approved 2026-10-23: "mock approved")

Owner request: add CPU, RAM, Storage and Network controls to Quick controls. A "Menu bar stats" group of four compact switches (2x2) sits under the six tool rows; each shows or hides its own item in the macOS menu bar. Buttons stay at 1 (Disable all, which also switches the four off). The old single "Show compact stats in menu bar" switch in the main window is removed; anyone who had it on starts with all four on. The tiles read "In menu bar" or "Off" (live values are not shown because the Quick controls window has no access to the numbers). Quick controls window height 590 → 740 px.

## Quick controls grouped (approved 2026-10-23: "approved")

Owner request: group the Quick controls. Three outlined groups with small headings: Speech (Speech Coach, Listen In, Speech to text, Meeting Recorder), Desktop (Window Manager, Ergonomics) and Menu bar stats (CPU, RAM, Storage, Network). Same switches and behaviour, 1 button (Disable all). Headings add height, so the window grows from 740 to 800 px.

## Launcher: Quick controls entry, window layouts and Clipboard history switch (approved 2026-10-23: "looks good")

Owner request: bring window movement and clipboard into the control center and add it to the launcher. The launcher lists "OfficeKit Quick controls" (opens the panel) and 12 window layouts as Commands (left, right, top, bottom halves, four corners, center, maximize, next and previous screen). Layouts and Quick controls sit under the All and Tools chips; Finder commands stay under Apps. Return runs a layout on the window you were using; with Window Manager off a notice says to turn it on. Quick controls gets a Clipboard history switch in the Desktop group (pauses or resumes saving what you copy; saved items stay). The Window menu and its settings are unchanged. Launcher: 0 buttons; Quick controls: 1 button. Not built from the mock: the shortcut hint on the right of each layout row. Quick controls window height 800 → 860 px.

## First-run setup (approved 2026-10-23: "Approved")

Owner request: a new Mac did nothing (launcher, clipboard, window layouts off; no speech model; no permission prompts). A three-step dialog opens once on first launch and from Settings → "Run setup again": (1) Speech model, where the owner picks the model from the same eight as the Speech model card (Parakeet v3, 460 MB, preselected) with a progress bar; (2) Access, listing Microphone, Accessibility, Screen Recording (and Calendar where meeting reminders ship), each with the features that need it and an Allow row action; (3) Tools, five switches (Launcher, Clipboard history and snippets, Window layouts, Open at login on; Speech to text shortcut off), where a tool whose access was skipped stays off and says what is missing. Every step can be skipped. Setup runs first and the app tour starts after it closes. Afterwards the Speech to text, Window layouts, Launcher and Screenshot pages show one banner naming the missing access and the feature it affects (Allow, or Open System Settings after a refusal), and a Quick controls switch says "Needs Accessibility · tap to allow". The speech model Download button stays in its card instead of the bottom action bar. Page buttons: setup 2/2/1, banners add one row action.

## General settings (approved 2026-10-23: "Approved")

Owner request: settings that persist, plus the system permission status with an Allow option when not allowed. A General card sits above Agent skill and MCP in Settings. It shows setup state (done and when, or "This Mac is not set up yet" with a Run setup link), the speech model with a chooser and Downloaded or Not downloaded, the background tool switches, and System permissions (Microphone, Accessibility, Screen Recording, Calendar where meeting reminders ship) with a status chip and Allow when macOS can still ask or Open System Settings after a refusal. Changes save at once; the card adds no counted buttons (the Allow buttons are row actions). Setup and Settings share a small saved file (setup done, version, date, model); the switches and permissions stay with the code that owns them. Built differently from the mock: the launcher and clipboard switches are one row because they are one setting; Calendar and the non-microphone permissions cannot tell "denied" from "not asked yet", so they read "Not allowed" or "Not checked". Today the Settings page already shows four counted buttons (Install skill, Copy, Change…, Show in Finder), not two as drawn; bringing it under the limit is a separate change.

## Approved UI change — 2026-10-23 (Speech Coach tool card)

Audio & Dictation gets a third catalogue card, Speech Coach, beside Voice Transcription and Meeting Notes. Owner approved the inspected Superset Browser mock ("approved"). Open Tool goes to Voice Transcription scrolled to its Speech Coach section with the Coach switch focused; search finds it by speech coach, speaking pace and filler words. No new buttons (Buttons: 0). Also this round: General settings tools got a Configure text link (not a button); the model row shows Download and progress in place; "Report bug" is attached only to failures, never to a ready or preparing message or a red Delete button.

## Approved UI change — 2026-10-23 (Agent skill for Codex as well as Claude Code)

The Agent skill card lists one row per agent (Claude Code, Codex) with a checkbox, the install path and its state; one Install skill button installs for every ticked agent. Owner approved the inspected Superset Browser mock ("mock is approved for codex"). An agent that is not on this Mac is skipped and a skill with another author is never overwritten. Built differently from the mock: Codex reads user skills from `~/.agents/skills/officekit/SKILL.md` (OpenAI docs), not `~/.codex/skills`; the Codex MCP tab already existed (TOML for `~/.codex/config.toml`), so no new tab was added. Also: when the speech shortcut cannot start recording (for example no microphone), the dictation overlay itself says so ("No microphone detected · connect one or choose an input in Sound settings") for four seconds instead of an error in the app.

## Setup step order changed — 2026-10-23 (owner request)

Setup now runs Access, then Background tools, then the speech model download last, because earlier steps may need an app restart that would stop a background download. This replaces the order in the approved setup mock at the owner's request. The model step offers Skip for now / Download, and Finish once a download runs. Quick controls is sized to the screen it opens on and scrolls inside when the screen is shorter than 860 px.

## Approved UI change — 2026-10-24 (Meeting Notes revamp)

Owner approved the inspected Superset Browser mock ("meeting notes page approved"). Meeting Notes uses the full width: the recorder strip on top, the transcript beside the notes (stacked on narrow windows). The hidden section list no longer keeps a 13rem column. Buttons: Start meeting recording, Generate meeting notes and Choose audio file; Clear transcript and notes, Copy/Download/Save notes, Optimize audio copy and Clear all history are text links. Built differently from the mock: the audio source stays a menu (not a segmented control) and Transcribe an audio file keeps its card with a button, so the page stays within three buttons without changing the shared Voice Transcription flow. The launcher also lists "Start or stop meeting recording" (owner request 2026-10-24).

## Approved UI change — 2026-10-24 (live results)

Owner approved the inspected Superset Browser mock ("mock approved"). Calculators recalculate 300 ms after the last key once every required field has a value; Calculate and Calculate again are gone, and an incomplete form says "Fill in every field to see the result." The System page refreshes CPU and memory every 2 s while it is visible and the window is focused; its Refresh button is hidden. Network rates are shown in the shortest unit (B, KB, MB, GB per second). Buttons: Save result and Download… (2) on a calculator; 0 on System.

## Approved UI change — 2026-10-25 (System Stats panels like the Stats app)

Owner approved the inspected Superset Browser mock ("mock approved"). The CPU, Memory, Disk, GPU, Network, Battery, Sensors and Bluetooth panels (menu bar and System Stats page) show titled rings, a history that is already filled when a panel opens (sampled in the background from launch, 30 min in memory, never saved), per-core bars, frequency, thermal state, power, fans, volumes, since-start-up totals and connected Bluetooth batteries. The System page shows live CPU and Memory cards. Rows the Mac does not expose are hidden, never zero. Built differently from the mock: the public address, per-process network traffic, memory bandwidth, the CPU "Speed limit" and CPU power (not readable on this macOS) are not built; the System page keeps only the CPU and Memory cards; Sensors and Bluetooth panels reuse the Activity Monitor button. Buttons: unchanged (at most 3 per panel). Windows and Linux: in-app pages use psutil readings; Apple-only readings are hidden; untested on Windows.

## Approved UI change — 2026-10-25 (System page sections on demand)

Owner approved the inspected Superset Browser mock ("mock appreoved"). On the System page, System recommendations and Redacted system summary are collapsed rows with a Show/Hide link and load only when opened; the CPU and Memory cards and the Suggested concurrent jobs line stay live. Buttons: 0 collapsed, 2 with the summary open (Copy report, Download report).

## Approved UI change — 2026-10-25 (dictation transcripts in Clipboard history)

Owner approved the inspected Superset Browser mock ("mock approved, build it and install"). The menu-bar Mic item and its recent-dictation list are removed. The Clipboard & Snippets page gets a Dictation tab beside History and Snippets that lists saved transcripts (time, source), searches them, and offers Copy and Paste on the selected one. Transcripts are read-only there (no transformations, Save as Snippet or Delete; history is managed on the Dictation page) and are never copied into the clipboard database or sent anywhere. Buttons: Copy and Paste are the page's existing inspector buttons; the tab is a segmented toggle.

## Approved UI change — 2026-10-25 (menu bar stat switches)

Owner approved the inspected Superset Browser mock ("both mocks approved, build and install"). Quick controls → Menu bar stats gets one switch each for GPU, Temperature, Battery and Bluetooth beside CPU, RAM, Storage and Network; the new four default off, and a drawer appears in the menu bar only when its own switch is on. The Bluetooth, Network and Battery panels have an "Open … settings" row that opens the matching System Settings pane. Buttons: 1 (Disable all); switches are not counted.

## Approved UI change — 2026-10-25 (Finder: Open in OfficeKit)

Owner approved the inspected Superset Browser mock ("both mocks approved, build and install"). Quick controls → Desktop gets one switch, "Finder: Open in OfficeKit", off by default. On installs a Finder Quick Action "Open in OfficeKit" in ~/Library/Services (shown under Quick Actions and Services in the right-click menu); off removes it, and only a workflow carrying OfficeKit's marker is ever replaced or removed. It sends up to 30 selected regular files (no symlinks) to the "Choose a tool for your file" page. No new buttons.

## Approved UI change — 2026-10-25 (file intake tool tiles)

Owner chose the tile view for "Choose a tool for your file" ("i prefer a tile viw as it can fit in more tools", "mock approved for file open", then "revert it to old one.. that was good" after a single-line variant). Tools show as a grid of tiles (about four across, two when narrow): icon, name, two-line description, selection circle at the top right. The "1 file" line shows only when a tool cannot take the selection. Same filter and single Continue button (1 button).

## Approved UI change — 2026-10-25 (Finder switch moves to Settings)

Owner approved the inspected Superset Browser mock ("Finder switch → Settings … approved", after "this is part of setting not on title bar"). "Finder: Open in OfficeKit" is a switch in Settings → General → Tools running in the background (off by default; on installs the Finder Quick Action, off removes it) and is removed from the Quick controls window. No new buttons.

## Approved UI change — 2026-10-25 (Quick controls stat tiles)

Owner approved the inspected Superset Browser mock ("approved", after asking for a tile view with single lines like Control Center). In Quick controls, Disable all moves to the top under the title and the eight menu-bar stats become rounded two-across tiles (icon circle and name on one line; a bright tile means on). Clicking a tile toggles it; there is no separate switch. The tile keeps a hidden checkbox and a screen-reader state line. Buttons: 1.

## Approved UI change — 2026-10-25 (checksum result, file intake header)

Owner approved both inspected Superset Browser mocks ("both mocks approved"). File checksum result: one card titled "SHA-256 · N files · size" with File / Size / Checksum columns, no internal id column, no "Result ready." or "Operation complete." lines, a copy-to-clipboard icon beside each digest (a row action, not a counted button), and the pre-run button reads "Calculate checksum". Choose a tool for your file: the selected file is one slim line (name left, type and size right) and "Filter tools" plus its small box become one full-width search bar, focused when the file opens. Tool tiles and the Continue button are unchanged. Buttons stay at 1 before and 2 after.

## Approved UI change — 2026-10-25 (replace the open file?)

Owner approved the inspected Superset Browser mock ("approved", after asking for a popup and fixing alignment). When a second file is opened while "Choose a tool for your file" is showing, a centered dialog "Replace this file?" names the new file (and how many more are waiting) and the file on screen. Replace switches to the new file and discards the old selection; Keep current (or Esc) closes the dialog, leaves the screen untouched and the new file waits. Two buttons in the dialog, Continue behind it is inactive.

## Approved UI change — 2026-10-25 (click a tool to open it)

Owner approved the inspected Superset Browser mock ("ok"), after asking that choosing a tool opens it instead of scrolling down to Continue and that Esc, Backspace and undo return to the tool choice. In "Choose a tool for your file" a click (or Enter/Space) on a tool tile opens the tool; arrow keys only move the choice. The Continue button is removed. On the opened tool a "Back to tool choice  Esc" link sits at the top, and Esc, Backspace or Cmd+Z return to the choice for the same file (a chosen subset is kept). The keys do nothing while typing in a field or while a dialog is open. The opened file selection is held until the user moves to another page, then released.

## Approved UI change — 2026-10-26 (file tool input screen)



Owner approved the inspected Superset Browser mock ("make this chanegs as well"). The shared Files input card shows, while nothing is chosen, a dashed centred area with "No files selected.", a one-line hint and the Choose files… / Choose folder… links; "Reset selection" appears only once something is chosen. File checksum generator: a one-line purpose sentence under the title and SHA-256 / SHA-512 as a two-way toggle (not counted as buttons) with a hint. Built differently from the mock: the area does not say "Drop files here" because a drop anywhere in the window opens the tool choice rather than filling this tool, and the per-file ✕ / Add more… / Clear all list and the "Choose a file to start" bottom-bar text are not built. Buttons stay at 1 before and after.

## Speech Coach Live Workspace is private, movable and opens with Speech Coach (approved 2026-10-26: "yes", after the inspected mock)

Owner clarified that the Live Workspace belongs to the Speech Coach, not only Listen In (Listen In is free-form practice and uses the same panel). With Speech Coach on, the panel opens beside the coach HUD once you start speaking in a dictation, shows the running text with flagged words, improvements and pace, and closes with Done (it stays closed for the rest of that dictation, and opens again at the next one). It is hidden from screen sharing and screen recordings (macOS content protection), shows a "Private · hidden from screen sharing" badge, and the whole header is a drag handle (grip dots) so it can move anywhere, including another display; it reopens where it was left when that spot is still on a connected display. "Not a mistake" is a small grey link, underlined only on hover. Quick controls wording: Speech Coach "live corrections, improvements and pace while you dictate", Listen In "free-form speaking practice". Not built yet: Speech Coach during meeting recording (approved earlier, separate audio path). Buttons: 2 (Copy corrected text, Done).

## Approved UI fix — 2026-10-27 (Not a mistake dismissal blink)

Owner reported that "Not a mistake blinks once its clicked" and approved the inspected before/after mock with "approve it". Dismissing a fix removes that row while keeping the other fix rows and links steady through the workspace's periodic refresh. The temporary mock was removed after approval; regression coverage preserves the surviving link node in `ui-tests/coach-workspace.spec.mjs`.

## Live Workspace keeps your words, has Clear, and explains Apple Intelligence (approved 2026-10-27: "yes" after the inspected continuity and grammar-setup mocks)

Each dictation is added to the end of the Live Workspace pad instead of replacing it; the pad has a fixed height with its own scroll bar and follows the newest words unless the person scrolled up. A Clear button (shown only when there is text) empties the pad and fixes and keeps the panel open; Done still closes and clears. Grammar checks no longer depend on Apple Intelligence: Harper (Apache-2.0, offline, in-process) always checks each finished sentence, and Apple on-device model adds word choice when available. The panel says why word choice is off (turned off with a Turn on Apple Intelligence link to System Settings, still preparing, or not supported on this Mac) and that basic grammar checks are on. A downloadable grammar model for word choice on Macs without Apple Intelligence is not built; no model has been chosen.

## Live Workspace correction de-duplication (approved 2026-10-27: “approved”)

The transcript is the clean, readable record of what the person said. Each rewrite is shown once, in Improvements, alongside its reason and “Not a mistake” action; the transcript does not underline the same phrase or append the proposed replacement. Copy continues to produce the existing corrected text. The inspected temporary before/after mock was removed after implementation. Buttons: 3/3.

## Transcript history revamp (approved 2026-10-27: "rest everything looks good", delete icon changed)

The row shows the transcript text first; clicking the text opens it in the editor (an attempt with no text opens its steps instead), so the loud Open button is gone. Copy, download and remove are quiet icon buttons; remove is a drawn outline trash can that turns red on hover. Steps became the plain link "How it was made". Dates read Today/Yesterday for recent entries. The expiry still reads "Auto-clears in N days". Page buttons: 0/3, row icons and links not counted.

## Meeting reminder opens Calendar, and calls can be recorded (approved 2026-10-27: "apprved" after the inspected meeting mock)

The meeting reminder's main button is now Open Calendar (opens the Calendar app, never OfficeKit); Hide this meeting is a quiet link and the close button only hides the mascot. With the new setting Offer to record calls (Reminders > Meetings, off by default) a meeting that has started, or a call app holding the microphone (Zoom, Slack, Teams, FaceTime, Webex, Discord, Skype; a browser shows Call in progress), shows Record this meeting/call, which starts the local Meeting Recorder when pressed. Nothing records without that press, and Not now or the close button is remembered until that call ends. Detection reads only which apps are capturing the microphone (CoreAudio process list, macOS 14.4+); it never opens or hears audio and OfficeKit's own capture is ignored. A started meeting keeps its Record offer for 2 minutes (8 seconds when the setting is off). Mascot buttons: 2/3.

## Transcript steps highlight what each step changed (approved 2026-10-27: "approved" after the inspected mock)

Each step in "How it was made" is compared word by word with the step above it: added or changed words are highlighted green, removed words stay visible struck through in red, the step header carries a chip such as "3 changed" or "1 removed", and a step that changed nothing says "No changes from the step above." instead of repeating the text. Final text is always shown in full with the last step's changes highlighted. Case and punctuation count as changes. Highlights are display only; copied text is plain. Buttons: 2/3.

## Fix grammar step for dictated text (approved 2026-10-27: "approved", then "ok" after the On-device polish switch was removed from the mock)

Speech-to-Text gains a Fix grammar switch under Smart cleanup (off by default). When on, Harper's single clear replacements are applied after Dictionary and tidy and before any polish: at most 5 per dictation, never numbers, quoted text or anything in the personal dictionary or word list, spelling left alone. "How it was made" gains a Fix grammar step with the change highlights and a line per fix (or "Not used"). No On-device polish switch was added: the Apple polish code exists but has no setting that turns it on. Buttons: 2/3.

## Reminder mascot has no End early (approved 2026-10-27: "approved")

While a break or eye rest counts down the primary button is gone; the close button already ends the reminder. Snooze and Pause all stay. Start break, Done, meeting and call buttons are unchanged. Mock `mascot-no-end-early.html` removed.

## Reminder mascot close button is always visible (approved 2026-10-27: "close buttton should be visible alwasy")

The close button is shown from the first moment a reminder fades in, at full strength (it sits outside the fading bubble). Pressing it or Esc dismisses the reminder without snoozing; the next one comes at its normal interval. Mock `mascot-teaser-close.html` removed.

## Live Workspace auto-clears after inactivity (approved 2026-10-27: "Approve updated mock")

An Auto-clear selector sits at the left of the Live Workspace bar with Off, 5 min and 10 min choices; Clear, Copy and Done stay on the right. The selected duration is remembered locally. After the last recognized speech, its timer clears the transcript and fixes through the existing memory-only Clear action; new recognized words restart the timer. The workspace remains open and listening. Its privacy note reflects the selected timer. Mock `live-workspace-auto-clear.html` removed after approval.

## CPU and Memory drawer tabs (approved 2026-10-27: "approevd", replacing the earlier disclosure row chosen with "opntion c looks good to me")

The CPU and Memory drawers have two tabs under the gauges: Applications (the top applications with Quit, shown when the drawer opens) and History and details (usage graph, cores or memory details). Switching eases the drawer to its new height over 0.2 s and fades the content in; Reduce Motion changes it at once. The Show/Hide toggle and the disclosure row are gone. Mocks `drawer-details-toggle.html` and `drawer-tabs.html` removed.

## Network drawer checks when opened (approved 2026-10-27: "network drawer mock approevd")

Opening the Network drawer starts the router and internet check unless one finished in the last minute; the button reads "Run network check" before a result and "Run again" after. The mock also showed an off switch in settings; the Quick controls panel is a tile grid, so that switch needs its own mock and is not built yet. Mock `network-check-on-open.html` removed.

## Icon-only menu bar tiles and Network footer (approved 2026-10-27: "Mock approved and option A for footer")

Quick controls "Menu bar stats" are a 4 x 2 grid of icon-only tiles (names stay as tooltips and for VoiceOver; on = light tile, green icon, small green dot). Icons: GPU cube, Network linked computers, Bluetooth mark (inline SVG); the others unchanged. The Network drawer footer is two equal buttons, "Run again" and "Network settings", with "Cloudflare Speed Test" as a plain link underneath. Mock `icon-tiles-network-footer.html` removed.

## Drawer footer: one Activity Monitor entry point

Owner 2026-10-27 (mock approved): every drawer already has an "Activity Monitor ↗" link in its header, so the bottom "Open Activity Monitor" button was a duplicate and is removed from CPU, Memory, GPU, Disk, Sensors and Battery. Network keeps "Run again" and "Network settings", and Bluetooth keeps "Bluetooth settings", because those do different jobs. The drawer ends one row shorter. The mock was design/mocks/drawer-no-duplicate-activity-monitor.html; it is not committed.

## Global clipboard panel: a Dictation tab

Owner 2026-10-28 (mock approved): the global clipboard panel (⌘⌥V) gets a Dictation tab after Pinned, completing the 2026-10-25 decision that had only reached the in-app Clipboard page. It lists saved transcripts newest first, searches them ("Search dictation"), and Return or ⌘1–9 pastes one into the app you were using. Rows are read-only (no pin or delete; the key hints drop them), and they do not appear under All. The main window hands recent transcripts (50 at most) to the panel in memory; they are never copied into the clipboard database, written to disk or logged. No buttons on the panel (0/3).

## Network drawer: the check result is a banner

Owner 2026-10-28 (mock approved, variant B): the "Connection looks healthy" result was centred, so it floated between rows that sit on the left and right edges. It is now one tinted, rounded banner across the full row width: dot and headline on the left, the time it was checked on the right (hours and minutes), and the explanation under them. The separate centred "Checked" line is gone. Variants A (plain left-aligned line) and C (status folded into the Connection header) were not chosen. Buttons unchanged: Run again and Network settings (2/3).
