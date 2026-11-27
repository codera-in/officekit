"""Files slice catalogue entries (F02, F05, F09, F10, S05, F11 symlink inspector; F06 create mode; F07 and F12 search IDs).

``zip_extract`` (F07) and ``archive_inspector`` (F12) are search IDs only: each opens the
core Archive tools (``archive_manager``) in browse-and-extract mode, so they add no new
engine. Development-only: none of these IDs appear in ``release-profile.json``.
"""

TOOLS = [
    {"id": "zip_create", "name": "Create ZIP", "category": "File Utilities", "tab": "workspace", "desc": "Pack selected files and folders into a new ZIP. Originals stay unchanged", "icon": "fa-file-zipper"},
    {"id": "zip_extract", "name": "Extract ZIP", "category": "File Utilities", "tab": "workspace", "desc": "Extract selected entries from a ZIP or supported archive into a new folder. The archive is not changed", "icon": "fa-file-zipper"},
    {"id": "archive_inspector", "name": "Archive inspector", "category": "File Utilities", "tab": "workspace", "desc": "Browse the contents and sizes of a supported archive without extracting it", "icon": "fa-file-zipper"},
    {"id": "file_info", "name": "File info", "category": "File Utilities", "tab": "workspace", "desc": "See size, dates, permissions and hard-link counts for selected files. Links are shown, not followed", "icon": "fa-circle-info"},
    {"id": "file_compare", "name": "Compare two files", "category": "File Utilities", "tab": "workspace", "desc": "Check whether two files are identical and see where they first differ, with a bounded text view", "icon": "fa-code-compare"},
    {"id": "file_age_finder", "name": "File age finder", "category": "File Utilities", "tab": "workspace", "desc": "Find files whose modified or created date falls inside a range, using this Mac's time zone", "icon": "fa-calendar-days"},
    {"id": "empty_file_finder", "name": "Empty file finder", "category": "File Utilities", "tab": "workspace", "desc": "List zero-byte files for review. Nothing is removed", "icon": "fa-file"},
    {"id": "empty_folder_finder", "name": "Empty folder finder", "category": "Storage & Cleanup", "tab": "workspace", "desc": "Find empty folders from the deepest level up. Review only; nothing is removed", "icon": "fa-folder-open"},
    {"id": "symlink_inspector", "name": "Symlink inspector", "category": "File Utilities", "tab": "workspace", "desc": "Find links in a folder and see where each one points, without following them", "icon": "fa-link"},
    {"id": "trash_restore", "name": "Restore from Trash", "category": "Storage & Cleanup", "tab": "workspace", "desc": "Put back files and folders that OfficeKit moved to Trash", "icon": "fa-trash-arrow-up"},
]

KEYWORDS = {
    "zip_create": ["new zip", "pack zip", "zip selected files"],
    "zip_extract": ["unpack zip", "zip extraction", "extract files from zip"],
    "archive_inspector": ["inspect archive", "archive contents", "list archive contents"],
    "file_info": ["file information", "file properties", "file size", "file details", "file attributes", "hard links", "permissions"],
    "file_compare": ["compare files", "file diff", "binary compare", "byte compare", "identical files", "file difference", "diff two files"],
    "file_age_finder": ["old files", "files by date", "modified date", "created date", "date range files", "files older than", "recent files"],
    "empty_file_finder": ["zero byte", "zero byte files", "empty files", "find empty files", "0 byte files"],
    "empty_folder_finder": ["empty folders", "find empty folders", "empty directories", "blank folders", "empty dirs"],
    "symlink_inspector": ["symlinks", "symbolic links", "find links", "broken links", "dangling links", "link checker", "where links point"],
    "trash_restore": ["restore", "put back", "undelete", "recover from trash", "restore from trash", "undo trash", "trash restore"],
}
