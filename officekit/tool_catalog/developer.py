"""Developer slice catalogue entries (D04, D10–D11, D15–D17).

All seven tools are development-only: none is listed in release-profile.json.
"""

TOOLS = [
    {"id": "json_compare", "name": "JSON Compare", "category": "Developer & Data", "tab": "developer", "desc": "Compare two JSON documents by structure with RFC 6901 paths; object key order is ignored", "icon": "fa-code-compare"},
    {"id": "text_diff", "name": "Text Diff", "category": "Developer & Data", "tab": "developer", "desc": "Compare two texts line by line, side by side or unified, with export as .patch or Markdown", "icon": "fa-file-lines"},
    {"id": "timestamp_converter", "name": "Timestamp Converter", "category": "Developer & Data", "tab": "converter", "desc": "Convert Unix seconds, milliseconds or microseconds, ISO 8601 and local times across up to eight time zones", "icon": "fa-clock"},
    {"id": "uuid_generator", "name": "UUID Generator", "category": "Developer & Data", "tab": "developer", "desc": "Generate v4, v7 or v5 UUIDs locally in batches of up to 1,000, with copy and export", "icon": "fa-hashtag"},
    {"id": "qr_generator", "name": "QR Code Generator", "category": "Developer & Data", "tab": "developer", "desc": "Create QR codes from text or links as PNG or SVG; generated locally, nothing is uploaded", "icon": "fa-qrcode"},
    {"id": "text_metrics", "name": "Text Metrics", "category": "Developer & Data", "tab": "converter", "desc": "Count graphemes, code points, UTF-8 bytes, words, lines and blank lines", "icon": "fa-ruler-combined"},
    {"id": "text_case", "name": "Change Case", "category": "Developer & Data", "tab": "converter", "desc": "Convert text to nine case styles, with Turkish and Azeri dotted-i rules", "icon": "fa-font"},
]

KEYWORDS = {
    "json_compare": ["json diff", "compare json", "json compare", "json difference", "diff json", "structural diff", "json changes"],
    "text_diff": ["text diff", "diff text", "compare text", "patch", "unified diff", "side by side diff", "line diff", "markdown diff"],
    "timestamp_converter": ["timestamp", "unix time", "epoch converter", "epoch to date", "unix timestamp", "time zone converter", "convert timestamp", "iso 8601"],
    "uuid_generator": ["uuid", "guid", "uuid generator", "uuid v4", "uuid v7", "uuid v5", "random id", "bulk uuid"],
    "qr_generator": ["qr code", "qr generator", "make qr", "qr png", "qr svg", "barcode", "two dimensional code"],
    "text_metrics": ["word count", "character count", "grapheme count", "line count", "text statistics", "count characters", "utf-8 bytes"],
    "text_case": ["change case", "uppercase", "lowercase", "title case", "camel case", "snake case", "kebab case", "sentence case", "constant case", "turkish case"],
}
