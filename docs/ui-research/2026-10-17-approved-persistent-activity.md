# Approved persistent Activity monitor

Date: 2026-10-17
Approval: “Approve the complete mock”
Approved scope: cross-app Activity monitor, operation insights, Continue in background, cancel/return controls and recent results. The user also requested merging Activity and History, removing Quick access because global search already exists, and increasing the minimum app window dimensions after reviewing the cramped sidebar/action layout.

## Behavior

- Activity is the shared destination for running jobs, recent operation results, saved calculator/meeting results and recent tools. The History route forwards to Activity for compatibility.
- Long-running duplicate-file scans report checked/total/remaining files, duplicate groups, extra copies and potential recovery size. Folder duplicate matches remain inspection-only.
- Storage analysis reports entries scanned, cleanup candidates and estimated logical size. The estimate is not presented as reclaimed disk space.
- Moving duplicates to Trash reports copies and bytes moved; disk space is only reclaimed after Trash is emptied.
- PDF workspace jobs expose their current backend phase, cancellation action and route back to the editor.
- Continue in background keeps work running while the user navigates within the open OfficeKit app. Activity remains available for monitoring and cancellation. Jobs live in the app process and are not resumed after the app closes.
- Desktop window minimum size is 1100×760 logical pixels. Quick access is removed because global search and categories already provide the same routes.
- Entering a tool screen automatically collapses the sidebar to give the task more room. The user can expand it manually while working.

## Verification

The approved mock was reviewed in the Superset Browser. Implementation verification includes the duplicate/file-job and storage API tests, the Activity monitor browser test, calculator saved-result navigation and the full `npm test` suite. Native window resizing and packaged-app behavior still require a desktop build review.
