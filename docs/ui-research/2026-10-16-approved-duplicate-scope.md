# Duplicate folder scope, sorting and pagination

Superseded in part by `2026-10-16-approved-duplicate-finder-navigation.md`: desktop scans now always include subfolders and sorting uses column headers. This file retains the earlier approval history.

Approved 2026-10-16. User approval: “approved”. Requested additions: “add paguination / sorting my name/ date / size” and “and page size too”.

The before/after mock was `design/mocks/duplicate-scope-review.html`. It was opened in new Superset Browser tabs and visually inspected. Interactive checks verified paging, sort direction, page-size changes and selection preservation. Temporary mock and preview-server files are removed after approval.

- Default to files directly in the selected folder. Offer an explicit Include subfolders option; changing it invalidates the old result.
- Prefix folder-relative result locations with the selected folder name. Never imply that a relative subfolder is a separate selected root.
- Paginate whole duplicate groups, with 10, 25, 50 or 100 groups per page. Default to 10. Keep group members together and retain the scan's verified keeper regardless of display order.
- Sort groups by keeper filename, latest group modification date, or group file size, ascending or descending. Display each file's date modified. Sort changes return to page 1 and preserve selections.
- Select all duplicates covers every page, keeping one file per group. Clear selection clears every page. Preserve the existing 10,000-copy request limit and disclose it for large scans.
- Place selection controls before a bounded scrollable table and pagination plus Copy/Download/Trash after it. Controls never overlap file rows; large reports cannot displace them by thousands of rows.
- Keep explicit Trash confirmation, native authority and identity checks. No developer files are moved during verification.
