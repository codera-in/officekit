# Recursive duplicate scan, Finder and identical folders

Approved 2026-10-16. User: “subfolder are must.. and give me option to open it in finder. hover should give full path to avoid confusions.. can it do duplicate folders as well?” Refinement: “sort could be on the coloumn headers”. Final approval: “lgtm”.

The before/after mock `design/mocks/duplicate-finder-navigation-review.html` was opened in new Superset Browser tabs and visually inspected, including files/folders modes and header sort toggling. Remove its temporary HTML/preview server after approval.

- All desktop duplicate searches include subfolders. This supersedes the direct-folder default approved earlier today.
- Find offers Identical files or Identical folders. Folder matches require identical relative names, structure (including empty directories), and file contents; top-level folder names may differ. Links/special entries prevent exact matches for containing folders; reads stay inside native-authorized roots.
- Folder matches are inspection-only, with Finder and complete report Copy/Download actions. No folder-selection or Trash controls.
- Names and locations expose the complete absolute path on hover; each row provides Show in Finder. Finder receives scan/item IDs and resolves them using native authority; webview-supplied paths are never accepted for reveal.
- Name, Date modified and Size headers are keyboard-accessible sort buttons. The active header shows an ascending/descending arrow and aria-sort. Repeated clicks reverse order. Sort and paginate whole groups without changing keepers or selection.
- Retain 10/25/50/100 groups per page and all-page file duplicate selection, bounded scrolling and explicit file Trash confirmation.

Local full paths now appear in authenticated direct-file reports to support the requested hover. They are not sent over the network or written to application logs. Imported workspace reports retain their existing relative-path contract.
