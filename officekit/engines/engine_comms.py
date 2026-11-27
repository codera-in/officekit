"""
OfficeKit - Support Tickets, Auto-Update Checker, Announcements & Global Tool Registry
Handles:
- In-memory & JSON persisted bug reports / support tickets with lifecycle notifications
- Auto-update version check against remote/local release manifests
- In-app communications announcements and status banners
- Global search index across all 57+ tools
"""

import os
import json
import time
import uuid
import re
import sys
import tempfile
import threading
import unicodedata
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import Dict, Any, List, Optional

from officekit.tool_catalog import slice_keywords, slice_tools


def _ticket_storage_path() -> str:
    if sys.platform == "darwin":
        data_root = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    elif os.name == "nt":
        data_root = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    else:
        data_root = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(data_root, "OfficeKit", "support-tickets.json")


TICKETS_FILE = _ticket_storage_path()
APP_CURRENT_VERSION = "1.0.0"
UPDATE_MANIFEST_MAX_BYTES = 64 * 1024
UPDATE_REQUEST_TIMEOUT_SECONDS = 3
UPDATE_MANIFEST_URL = "OFFICEKIT_RELEASE_MANIFEST_URL"
OFFICEKIT_DOWNLOAD_URL = "https://officekit.app/download"
UPDATE_UNAVAILABLE_MESSAGE = "Update information is not available. OfficeKit will keep working offline."
RELEASE_VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def _release_version_key(value: Any) -> Optional[tuple[int, int, int]]:
    if not isinstance(value, str) or len(value) > 32:
        return None
    match = RELEASE_VERSION_PATTERN.fullmatch(value)
    if not match:
        return None
    if any(len(part) > 9 for part in match.groups()):
        return None
    return tuple(int(part) for part in match.groups())


def _is_officekit_https_url(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "officekit.app"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
        )
    except ValueError:
        return False


def _unavailable_update_status(current_version: str = APP_CURRENT_VERSION) -> Dict[str, Any]:
    return {
        "status": "unavailable",
        "current_version": current_version,
        "latest_version": None,
        "update_available": False,
        "release_notes": UPDATE_UNAVAILABLE_MESSAGE,
        "download_url": None,
    }

TOOL_REGISTRY = [
    {"id": "bank_statement", "name": "Bank Statement Extractor", "category": "Finance & Documents", "tab": "statement", "desc": "Convert supported bank PDF & image statements into CSV or Excel spreadsheets (XLS/XLSX) with balance checks", "icon": "fa-file-invoice-dollar"},
    {"id": "pdf_unlock", "name": "PDF Password Remover", "category": "PDF & Documents", "tab": "unlocker", "desc": "Remove passwords and decrypt locked bank statements", "icon": "fa-lock-open"},
    {"id": "pdf_protect", "name": "PDF AES-256 Protector", "category": "PDF & Documents", "tab": "unlocker", "desc": "Encrypt confidential documents with offline AES-256 password", "icon": "fa-shield-halved"},
    {"id": "pdf_merge", "name": "Merge PDFs", "category": "PDF & Documents", "tab": "statement", "desc": "Combine 2–20 selected PDFs in input order into a new PDF", "icon": "fa-object-group"},
    {"id": "pdf_split", "name": "Extract PDF Pages", "category": "PDF & Documents", "tab": "statement", "desc": "Extract selected pages and ranges in requested order into one PDF", "icon": "fa-scissors"},
    {"id": "pdf_compress", "name": "Compress PDF", "category": "PDF & Documents", "tab": "statement", "desc": "Lossless stream recompression; output may be larger, so compare actual sizes", "icon": "fa-file-zipper"},
    {"id": "pdf_metadata_strip", "name": "Remove PDF Metadata", "category": "Privacy & Security", "tab": "statement", "desc": "Remove document-info and root XMP metadata; embedded identifiers may remain", "icon": "fa-user-secret"},
    {"id": "pdf_to_images", "name": "PDF Pages to PNG / JPEG", "category": "PDF & Documents", "tab": "statement", "desc": "Render every PDF page to ordered PNG or JPEG images in a DPI-controlled ZIP", "icon": "fa-images"},
    {"id": "pdf_delete_pages", "name": "Delete PDF Pages", "category": "PDF & Documents", "tab": "pdf", "desc": "Select page thumbnails to remove from a new PDF; preview first and keep at least one page", "icon": "fa-trash-can"},
    {"id": "pdf_reorder_pages", "name": "Reorder PDF Pages", "category": "PDF & Documents", "tab": "pdf", "desc": "Reorder mixed-size PDF pages with thumbnails, drag and drop, keyboard and preview", "icon": "fa-arrow-up-wide-short"},
    {"id": "pdf_editor", "name": "Edit, Annotate & Sign PDF", "category": "PDF & Documents", "tab": "pdf-editor", "desc": "Edit supported text and images, review scanned text with local OCR, annotate and sign with a certificate file or compatible USB DSC token", "icon": "fa-file-signature"},
    {"id": "pdf_table_extractor", "name": "Extract PDF Tables", "category": "PDF & Documents", "tab": "pdf", "desc": "Preview selectable text tables in a PDF and export one table to CSV or Excel (legacy XLS/XLSX) without guessing cell types", "icon": "fa-table"},
    {"id": "pdf_text_extract", "name": "Extract PDF Text", "category": "PDF & Documents", "tab": "pdf", "desc": "Extract selectable PDF page text as plain text or Markdown; scanned image pages are reported without OCR", "icon": "fa-file-lines"},
    {"id": "image_converter", "name": "Universal Image Converter", "category": "Images", "tab": "converter", "desc": "Convert SVG, PNG/JPG, WebP, BMP, GIF, TIFF and ICO images to PNG/JPEG, WebP, BMP, TIFF, ICO or PDF", "icon": "fa-image"},
    {"id": "media_toolkit", "name": "Media Toolkit", "category": "Images", "tab": "converter", "desc": "Prepare local image, video, PDF and audio files with a shared batch workflow; see which Clop-inspired operations are available in this build", "icon": "fa-photo-film"},
    {"id": "image_resize", "name": "Resize Images", "category": "Images", "tab": "converter", "desc": "Resize one image or a batch to fit maximum pixel dimensions while preserving proportions and never upscaling", "icon": "fa-expand"},
    {"id": "image_exif_strip", "name": "Strip EXIF & GPS Metadata", "category": "Privacy & Security", "tab": "converter", "desc": "Wipe camera, GPS coordinates, and device data from photos", "icon": "fa-location-dot"},
    {"id": "pii_redaction", "name": "Find & Mask Personal Information", "category": "Privacy & Security", "tab": "pii", "desc": "Review likely names, email addresses, phone numbers, IDs and other sensitive values in one local file, then create a separate masked copy", "icon": "fa-file-shield"},
    {"id": "screenshot_editor", "name": "Screenshot Editor", "category": "Images", "tab": "screenshot", "desc": "Paste or choose a screenshot, crop it, blur sensitive details, add opaque masks, undo edits and export a metadata-free image", "icon": "fa-crop-simple"},
    {"id": "data_converter", "name": "Spreadsheet & Data Converter", "category": "Developer & Data", "tab": "converter", "desc": "Convert CSV/TXT, TSV, Excel, JSON and YAML; export CSV, TSV, XLSX, JSON, YAML, HTML or SQL", "icon": "fa-table"},
    {"id": "voice_transcription", "name": "Voice Transcription", "category": "Audio & Dictation", "tab": "dictate", "desc": "Transcribe live speech or local audio files on this Mac, with optional English translation", "icon": "fa-microphone-lines"},
    {"id": "meeting_notes", "name": "Meeting Notes", "category": "Audio & Dictation", "tab": "dictate", "desc": "Record or transcribe local audio, then review formatted meeting notes", "icon": "fa-clipboard-list"},
    {"id": "speech_coach", "name": "Speech Coach", "category": "Audio & Dictation", "tab": "dictate", "desc": "Live pace and filler-word cues while you speak, with progress from sessions kept on this Mac", "icon": "fa-gauge-high"},
    {"id": "loan_emi", "name": "Loan & Mortgage EMI Calculator", "category": "Calculators", "tab": "calculators", "desc": "Monthly payment, total interest, and full amortization schedule", "icon": "fa-landmark"},
    {"id": "compound_interest", "name": "Compound Interest Simulator", "category": "Calculators", "tab": "calculators", "desc": "Future balance projections with monthly contributions", "icon": "fa-chart-line"},
    {"id": "vat_salestax", "name": "VAT & Sales Tax Calculator", "category": "Calculators", "tab": "calculators", "desc": "Forward and reverse inclusive tax rate breakdowns", "icon": "fa-percent"},
    {"id": "freelance_rate", "name": "Freelance Hourly Rate Planner", "category": "Calculators", "tab": "calculators", "desc": "Target income calculator with tax and sick leave overhead", "icon": "fa-user-tie"},
    {"id": "margin_markup", "name": "Margin & Markup Calculator", "category": "Calculators", "tab": "calculators", "desc": "Calculate profit, gross margin over revenue and markup over cost; zero denominators are shown as undefined", "icon": "fa-chart-pie"},
    {"id": "break_even", "name": "Break-even Calculator", "category": "Calculators", "tab": "calculators", "desc": "Calculate required whole units and revenue from fixed costs, unit price and variable cost", "icon": "fa-scale-balanced"},
    {"id": "simple_interest", "name": "Simple Interest Calculator", "category": "Calculators", "tab": "calculators", "desc": "Calculate simple interest and total amount for an explicit duration in years or months", "icon": "fa-coins"},
    {"id": "depreciation", "name": "Straight-line Depreciation Calculator", "category": "Calculators", "tab": "calculators", "desc": "Build a cent-balanced annual depreciation schedule from asset cost, salvage value and useful life", "icon": "fa-arrow-trend-down"},
    {"id": "everyday_percentages", "name": "Everyday Percentages", "category": "Calculators", "tab": "calculators", "desc": "Calculate a percentage of a value, percentage change, or discount savings and final price", "icon": "fa-percent"},
    {"id": "math_eval", "name": "Scientific Calculator", "category": "Calculators", "tab": "calculators", "desc": "Evaluate bounded mathematical expressions with approved functions, constants, and radians or degrees", "icon": "fa-calculator"},
    {"id": "units_convert", "name": "Unit Converter", "category": "Unit Converters", "tab": "calculators", "desc": "Convert values across 15 categories using canonical unit choices for measurement, data, engineering, temperature, and typography", "icon": "fa-arrows-left-right"},
    {"id": "batch_rename", "name": "Batch File Renamer", "category": "File Utilities", "tab": "converter", "desc": "Sequence numbering, casing, prefix/suffix, regex replace", "icon": "fa-pen-to-square"},
    {"id": "dup_finder", "name": "Fast Duplicate Finder", "category": "File Utilities", "tab": "converter", "desc": "Two-phase 4KB chunk hash + SHA-256 duplicate scanner", "icon": "fa-clone"},
    {"id": "storage_analyzer", "name": "Storage analyser & cleaner", "category": "Storage & Cleanup", "tab": "converter", "desc": "Analyse local disks, caches and old downloads; review individual cleanup items", "icon": "fa-hard-drive"},
    {"id": "file_split_join", "name": "Split & Join Files", "category": "File Utilities", "tab": "workspace", "desc": "Split large files into numbered parts with SHA-256 checksums, then verify and join OfficeKit split archives", "icon": "fa-scissors"},
    {"id": "folder_compare", "name": "Compare Folders", "category": "File Utilities", "tab": "workspace", "desc": "Compare selected folder copies by relative path and SHA-256; review identical, changed and one-sided files, then export a CSV report", "icon": "fa-code-compare"},
    {"id": "file_hash", "name": "File Checksum Generator", "category": "File Utilities", "tab": "workspace", "desc": "Calculate SHA-256 or SHA-512 checksums for selected local file copies", "icon": "fa-fingerprint"},
    {"id": "file_type", "name": "File Type Detector", "category": "File Utilities", "tab": "workspace", "desc": "Detect actual file types from content signatures and compare them with filename extensions", "icon": "fa-file-circle-question"},
    {"id": "archive_manager", "name": "Compress & Extract ZIP", "category": "File Utilities", "tab": "workspace", "desc": "Pack selected files or folders into a ZIP, or browse and extract an archive, without changing the originals", "icon": "fa-file-zipper"},
    {"id": "image_compress", "name": "Compress Images", "category": "Images", "tab": "converter", "desc": "Reduce photo and image file size with an adjustable quality setting; originals stay unchanged", "icon": "fa-compress"},
    {"id": "devtools_format", "name": "JSON & YAML Formatter", "category": "Developer & Data", "tab": "converter", "desc": "Format and validate JSON, convert JSON/YAML, and encode/decode Base64", "icon": "fa-code"},
    {"id": "url_codec", "name": "URL Encoder & Decoder", "category": "Developer & Data", "tab": "converter", "desc": "Encode or decode URI-component text locally; malformed escapes and invalid UTF-8 are rejected", "icon": "fa-link"},
    {"id": "jwt_inspector", "name": "Offline JWT Inspector", "category": "Developer & Data", "tab": "converter", "desc": "Inspect token headers and payloads safely without server roundtrips", "icon": "fa-key"},
    {"id": "crypto_hashes", "name": "Cryptographic Hash Generator", "category": "Privacy & Security", "tab": "converter", "desc": "Compute MD5, SHA-1, SHA-256, SHA-512, CRC32, HMAC", "icon": "fa-fingerprint"},
    {"id": "password_generator", "name": "Password & Passphrase Generator", "category": "Privacy & Security", "tab": "password", "desc": "Generate cryptographically random passwords and memorable passphrases; copy explicitly and keep secrets out of saved history", "icon": "fa-key"},
    {"id": "similar_images", "name": "Find Similar Images", "category": "Images", "tab": "workspace", "desc": "Compare selected local photos for visual matches and likely camera bursts; review groups without deleting originals", "icon": "fa-clone"},
    {"id": "color_converter", "name": "Color Converter", "category": "Unit Converters", "tab": "color", "desc": "Convert HEX, RGB, HSL and HSV colors locally, preserving supported alpha transparency", "icon": "fa-palette"},
    {"id": "network_dns", "name": "DNS Lookup", "category": "Network", "tab": "network", "desc": "Query A, AAAA, CNAME, NS (name servers), MX, TXT, SPF or DKIM records, with plain-language explanations of SPF and DKIM, individually or all supported types with the system resolver or an optional DNS server", "icon": "fa-magnifying-glass-location"},
    {"id": "network_ping", "name": "Ping Diagnostics", "category": "Network", "tab": "network", "desc": "Measure ICMP replies, packet loss and latency to a hostname or IP address on macOS", "icon": "fa-satellite-dish"},
    {"id": "network_interfaces", "name": "Network Interfaces", "category": "Network", "tab": "network", "desc": "Inspect local interface names and link status; reveal private IP addresses only by choice", "icon": "fa-ethernet"},
    {"id": "system_info", "name": "System Information", "category": "System", "tab": "system", "desc": "View a redacted Mac summary of OS version, architecture, CPU counts and memory capacity", "icon": "fa-circle-info"},
    {"id": "system_resources", "name": "CPU & Memory Overview", "category": "System", "tab": "system", "desc": "Refresh a local snapshot of CPU use, RAM and a rough concurrent-job estimate", "icon": "fa-gauge-high"},
    {"id": "clipboard_manager", "name": "Clipboard & Snippets Studio", "category": "Developer & Data", "tab": "clipboard", "desc": "Clipboard history with search, instant 1–9 paste, dynamic Espanso-style snippet expansion, and CopyQ transformations", "icon": "fa-clipboard-check"},
    {"id": "global_launcher", "name": "Global Launcher", "category": "Developer & Data", "tab": "global-launcher", "desc": "Find apps, OfficeKit tools and snippets from any app with one shortcut; choose what it lists and which quick results it computes", "icon": "fa-magnifying-glass"},
    {"id": "ergonomics_break", "name": "Break & Stretch Reminders", "category": "Ergonomics", "tab": "ergonomics", "desc": "Configurable movement breaks with a playful animated desktop companion, snooze and quiet hours", "icon": "fa-person-walking"},
    {"id": "ergonomics_eyes", "name": "Eye Rest Reminders", "category": "Ergonomics", "tab": "ergonomics", "desc": "Configurable look-away intervals and eye-rest durations with an animated desktop companion", "icon": "fa-eye"},
    {"id": "ergonomics_water", "name": "Water Reminders", "category": "Ergonomics", "tab": "ergonomics", "desc": "Choose your water reminder interval and snooze with a funny bottle-opening companion", "icon": "fa-glass-water"},
    {"id": "ergonomics_posture", "name": "AirPods Head-Angle Nudges", "category": "Ergonomics", "tab": "ergonomics", "desc": "Optional calibrated AirPods Pro head-tilt reminders on supported Macs; adjustable dwell and cooldown", "icon": "fa-headphones"},
    {"id": "meeting_countdown", "name": "Meeting Countdown", "category": "Ergonomics", "tab": "ergonomics", "desc": "Local macOS calendars with a 30-minute countdown and animated watch-checking companion", "icon": "fa-calendar"}
]

TOOL_SEARCH_KEYWORDS = {
    "ergonomics_break": ["ergonomics", "break reminder", "stretch reminder", "movement break", "take a break", "stand up reminder"],
    "ergonomics_eyes": ["ergonomics", "eye rest", "eye strain", "eye exercise", "look away", "screen break", "20 20 20"],
    "ergonomics_water": ["ergonomics", "water reminder", "drink water", "hydration", "water break", "sip reminder"],
    "meeting_countdown": ["meeting", "calendar", "meeting countdown", "meeting reminder", "upcoming meeting", "mascot timer"],
    "ergonomics_posture": ["ergonomics", "airpods", "airpods pro", "head angle", "head tilt", "posture reminder", "posture"],
    "clipboard_manager": ["clipboard", "clipboard manager", "clipboard history", "snippets", "text expansion", "paste", "copy paste", "copyq", "maccy", "clipy", "pastebar", "espanso", "templates"],
    "global_launcher": ["launcher", "spotlight", "quick launch", "find apps", "open app", "global search", "run tool", "alfred", "raycast"],
    "voice_transcription": ["transcribe audio", "voice typing", "speech to text", "dictation", "audio transcription", "translate audio"],
    "meeting_notes": ["meeting notes", "meeting minutes", "record meeting", "action items from meeting"],
    "speech_coach": ["speech coach", "speaking coach", "speaking pace", "filler words", "um uh", "words per minute", "public speaking", "presentation practice"],
    "loan_emi": ["loan payment", "mortgage calculator", "emi", "amortization schedule", "compute loan payment", "calculate mortgage payment"],
    "compound_interest": ["compound interest", "future savings balance", "investment contributions"],
    "vat_salestax": ["sales tax", "vat calculator", "inclusive tax", "reverse tax"],
    "freelance_rate": ["freelance rate", "hourly rate", "target income", "billable hours"],
    "batch_rename": ["rename files", "batch rename", "file naming", "prefix suffix filenames"],
    "dup_finder": ["duplicate files", "find exact duplicates", "identical file scanner"],
    "storage_analyzer": ["storage analyzer", "storage analyser", "disk cleaner", "mac cleaner", "disk space", "largest files", "folder sizes", "docker cache", "node cache", "python cache", "old downloads"],
    "pii_redaction": ["personal information", "pii redaction", "mask sensitive data", "redact private values"],
    "everyday_percentages": ["percentage of", "percent of", "what is percent", "percentage change", "percent increase", "percent decrease", "discount", "discount calculator", "sale price", "savings", "percent off"],
    "margin_markup": ["gross margin", "markup", "margin calculator", "markup calculator", "profit margin", "selling price margin"],
    "break_even": ["break even", "break-even", "break even point", "breakeven units", "contribution margin break even"],
    "simple_interest": ["simple interest", "interest calculator", "interest without compounding", "principal rate time"],
    "depreciation": ["depreciation", "straight line depreciation", "asset depreciation", "salvage value schedule"],
    "network_dns": ["dns", "dns lookup", "dns record", "a record", "aaaa record", "mx record", "txt record", "nameserver", "name server", "domain records"],
    "network_ping": ["ping", "ping test", "ping host", "packet loss", "latency", "icmp", "network reachability"],
    "network_interfaces": ["network interface", "network interfaces", "ip address", "local ip", "wifi address", "ethernet status", "network adapter"],
    "system_info": ["system information", "mac system report", "mac information", "system summary", "hardware overview", "computer specs"],
    "system_resources": ["cpu usage", "cpu monitor", "memory usage", "ram usage", "resource overview", "system resources", "available memory", "monitor cpu usage", "track ram usage", "calculate cpu usage"],
    "url_codec": ["url encode", "url decode", "percent encode", "percent decode", "uri component", "encode url parameter", "decode url parameter"],
    "bank_statement": ["pdf to csv", "pdf to excel", "statement to spreadsheet", "transactions"],
    "pdf_table_extractor": ["pdf to csv", "pdf to xls", "pdf to xlsx", "pdf to excel", "extract pdf table", "pdf table extractor", "pdf table to spreadsheet", "pdf table to csv", "pdf table to excel"],
    "pdf_text_extract": ["pdf to text", "pdf to txt", "pdf to markdown", "pdf to md", "extract text from pdf", "copy pdf text", "pdf text extractor"],
    "pdf_unlock": ["decrypt", "decrypt pdf", "remove pdf password", "remove password from pdf", "password removal pdf", "reset pdf password", "reset password pdf", "unlock document", "unlock pdf", "unprotect pdf", "pdf password remover", "known password pdf"],
    "pdf_protect": ["encrypt", "add pdf password", "add password to pdf", "secure document", "protect pdf", "protect document", "lock pdf", "locked pdf", "pdf protector", "password protect pdf", "password protect document", "set pdf password"],
    "pdf_merge": ["merge pdf", "combine pdf", "join documents"],
    "pdf_split": ["split pdf", "split pdf pages", "extract pdf pages", "separate pages"],
    "pdf_compress": ["shrink pdf", "reduce pdf size"],
    "pdf_metadata_strip": ["remove pdf metadata", "anonymize document"],
    "pdf_to_images": ["pdf to png", "pdf to jpg", "pdf to jpeg", "pdf to image", "pdf pages to images", "render pdf pages"],
    "pdf_delete_pages": ["delete pages from pdf", "remove pdf pages", "delete pdf page", "remove pages from document"],
    "pdf_reorder_pages": ["reorder pdf pages", "rearrange pdf pages", "move pdf pages", "change pdf page order"],
    "pdf_editor": ["edit pdf", "pdf editor", "annotate pdf", "pdf annotation", "sign pdf", "digital signature", "dsc", "usb dsc token", "p12", "pfx", "edit scanned pdf", "ocr pdf"],
    "file_split_join": ["split large file", "split file into parts", "join split files", "restore split archive", "checksum parts", "checksummed parts", "sha256 file parts"],
    "folder_compare": ["compare folders", "folder diff", "directory compare", "compare directory contents", "find changed files between folders"],
    "file_hash": ["file hash", "checksum file", "sha256 file", "sha-256 file", "sha512 file", "sha-512 file", "file digest", "verify file checksum", "compare checksum", "verify checksum against digest"],
    "archive_manager": ["zip", "zip files", "zip folder", "create zip", "make zip", "compress files", "compress folder", "pack files", "archive files", "unzip", "extract zip", "extract archive", "open zip", "browse archive", "7z", "unarchive"],
    "image_compress": ["compress image", "compress images", "compress photo", "compress photos", "reduce image size", "shrink image", "shrink photo", "smaller image", "optimize image", "reduce photo size", "image file size"],
    "file_type": ["file type", "detect file type", "identify file format", "file signature", "mime type", "extension mismatch", "check actual file format"],
    "image_converter": ["jpeg", "jpg", "photo", "picture", "png", "webp", "gif", "tiff", "bmp", "ico", "pdf", "image conversion", "image to pdf", "compress image", "compress photo", "shrink image", "reduce image size"],
    "media_toolkit": ["clop", "media optimizer", "media conversion", "compress video", "compress audio", "compress image", "optimize image", "optimize media", "batch media", "media preparation"],
    "image_resize": ["resize photo", "resize image", "resize images", "batch image resize", "image dimensions", "scale image", "reduce image dimensions", "fit image", "image size pixels", "compress image", "compress photo", "shrink image", "reduce image size"],
    "math_eval": ["scientific calculator", "math evaluator", "evaluate expression", "calculator expression", "sin cos tan", "square root calculator", "radians degrees calculator"],
    "units_convert": ["unit converter", "convert units", "km to miles", "kilometers to miles", "celsius fahrenheit", "bytes to megabytes", "unit conversion"],
    "image_exif_strip": ["photo metadata", "remove gps", "geolocation"],
    "screenshot_editor": ["paste screenshot", "clipboard screenshot", "crop screenshot", "blur screenshot", "redact screenshot", "mask screenshot", "hide screenshot information", "annotate screenshot"],
    "password_generator": ["password", "password generator", "random password", "secure password", "strong password", "passphrase", "diceware", "memorable password", "generate password", "password creator"],
    "similar_images": ["similar image", "similar images", "find similar photos", "burst photos", "camera burst", "photo burst", "near duplicate photos", "visually similar", "almost identical images", "group burst shots"],
    "color_converter": ["color conversion", "color converter", "convert color", "hex to rgb", "hex to rgba", "hex to hsl", "hex to hsv", "rgb to hex", "rgba to hex", "hsl to hex", "hsv to rgb", "css color", "color code", "transparent color", "alpha color"],
    "data_converter": ["spreadsheet", "excel", "xlsx", "xls", "csv", "tsv", "txt", "tab", "json", "yaml", "sql", "html", "data format", "csv to sql", "csv to html", "json to yaml", "excel to html", "table to yaml"],
    "devtools_format": ["json formatter", "format json", "pretty print json", "validate json", "json to yaml", "yaml to json", "yaml converter", "structured text", "base64", "base64 encode", "base64 decode"],
    "jwt_inspector": ["jwt", "jwt decoder", "decode jwt", "inspect token", "token claims", "json web token", "jwt payload"],
    "crypto_hashes": ["hash", "hash generator", "sha256", "sha-256", "sha512", "sha-512", "md5", "sha1", "sha-1", "crc32", "hmac", "text digest"],
}

# Pending-tool slices register through their own catalogue modules so parallel
# branches never edit the literals above.
TOOL_REGISTRY.extend(slice_tools())
TOOL_SEARCH_KEYWORDS.update(slice_keywords())

# Direction-specific operations require their source format in the query; their
# output-format names alone should not crowd out general-purpose converters.
TOOL_SEARCH_CONTEXT_TERMS = {
    "pdf_to_images": frozenset({"pdf"}),
    "pdf_table_extractor": frozenset({"pdf"}),
    "pdf_text_extract": frozenset({"pdf"}),
}

TOOL_SEARCH_SYNONYMS = (
    frozenset({"jpeg", "jpg"}),
    frozenset({"excel", "xls", "xlsx"}),
    frozenset({"csv", "spreadsheet", "table"}),
    frozenset({"convert", "converter", "conversion"}),
    frozenset({"combine", "merge", "join"}),
    frozenset({"split", "extract", "separate"}),
    frozenset({"protect", "secure", "encrypt"}),
    frozenset({"remove", "delete", "erase", "strip", "wipe", "unlock", "decrypt", "reset", "unprotect"}),
    frozenset({"image", "photo", "picture"}),
    frozenset({"shrink", "compress", "reduce"}),
    frozenset({"metadata", "exif", "gps", "geolocation"}),
    frozenset({"compare", "comparison", "diff"}),
    frozenset({"folder", "directory"}),
    frozenset({"rename", "renamer", "renaming"}),
    # Common user wording shared across tools. These are single-token intent
    # equivalents; the remaining query terms still constrain results to the
    # correct tool and prevent a generic thesaurus match from routing alone.
    frozenset({"find", "search", "locate", "look"}),
    frozenset({"detect", "identify", "recognize"}),
    frozenset({"inspect", "examine", "review"}),
    frozenset({"calculate", "compute", "workout", "solve"}),
    frozenset({"generate", "create", "make", "build"}),
    frozenset({"resize", "scale", "dimension"}),
    frozenset({"transcribe", "dictate", "transcription", "dictation"}),
    frozenset({"screenshot", "capture", "screen", "snap"}),
    frozenset({"format", "pretty", "beautify"}),
    frozenset({"validate", "verify", "check"}),
    frozenset({"statistics", "stats", "usage", "utilization"}),
    frozenset({"monitor", "track", "measure", "watch"}),
)

# Explicit inflections avoid broad stemming (for example, “gas” must not become
# “ga”). Normalize both queries and indexed records, preserving action direction.
TOOL_SEARCH_INFLECTIONS = {
    "pdfs": "pdf", "images": "image", "photos": "photo", "pictures": "picture",
    "duplicates": "duplicate",
    "files": "file", "folders": "folder", "directories": "directory",
    "pages": "page", "tables": "table", "colors": "color", "colours": "color",
    "colour": "color", "units": "unit", "checksums": "checksum",
    "passwords": "password", "passphrases": "passphrase", "statements": "statement",
    "archives": "archive", "interfaces": "interface", "records": "record",
    "addresses": "address", "percentages": "percentage", "converters": "converter",
    "unlocked": "unlock", "unlocking": "unlock", "decrypting": "decrypt",
    "unprotected": "unprotect", "unprotecting": "unprotect", "removal": "remove",
    "locked": "lock", "locking": "lock", "encrypted": "encrypt", "encrypting": "encrypt", "merging": "merge",
    "splitting": "split", "compressing": "compress", "resizing": "resize",
    "transcription": "transcribe", "transcribing": "transcribe",
    "searching": "search", "locating": "locate", "finding": "find",
    "detecting": "detect", "identifying": "identify", "inspecting": "inspect",
    "examining": "examine", "reviewing": "review", "calculating": "calculate",
    "computing": "compute", "solving": "solve", "generating": "generate",
    "creating": "create", "building": "build", "deleting": "delete",
    "erasing": "erase", "stripping": "strip", "wiping": "wipe",
    "scaling": "scale", "capturing": "capture", "formatting": "format",
    "validating": "validate", "verifying": "verify", "checking": "check",
    "statistics": "statistic", "stats": "statistic", "utilization": "usage",
}

TOOL_SEARCH_STOPWORDS = frozenset({"a", "an", "and", "for", "from", "into", "of", "the", "to", "with"})
MAX_TOOL_SEARCH_QUERY_LENGTH = 256


def _search_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    plain_text = "".join(character for character in normalized if not unicodedata.combining(character))
    return {TOOL_SEARCH_INFLECTIONS.get(token, token) for token in re.findall(r"[a-z0-9]+", plain_text)}


def _search_phrase(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    plain_text = "".join(character for character in normalized if not unicodedata.combining(character))
    return " ".join(
        TOOL_SEARCH_INFLECTIONS.get(token, token) for token in re.findall(r"[a-z0-9]+", plain_text)
        if token not in TOOL_SEARCH_STOPWORDS
    )


def _expanded_search_token(token: str) -> frozenset[str]:
    for group in TOOL_SEARCH_SYNONYMS:
        if token in group:
            return group
    return frozenset({token})


def _search_term_matches(token: str, group: frozenset[str], indexed_terms: set[str]) -> bool:
    if group & indexed_terms:
        return True
    return len(token) >= 2 and any(term.startswith(token) for term in indexed_terms)


def _search_term_prefix_matches(token: str, terms: set[str]) -> bool:
    return len(token) >= 2 and any(term.startswith(token) for term in terms)


def _tool_search_record(tool: Dict[str, Any]) -> Dict[str, Any]:
    return {**tool, "keywords": TOOL_SEARCH_KEYWORDS.get(tool["id"], [])}


class SupportStoreError(RuntimeError):
    """The local support ticket store cannot be read or safely updated."""


class SupportEngine:

    SUPPORTED_TICKET_TYPES = {"bug", "support", "feature", "testimonial"}
    MAX_EMAIL_LENGTH = 254
    MAX_TITLE_LENGTH = 160
    MAX_DESCRIPTION_LENGTH = 20_000
    MAX_SYSTEM_INFO_FIELDS = 4
    MAX_SYSTEM_INFO_VALUE_LENGTH = 512
    MAX_TICKET_STORE_BYTES = 32 * 1024 * 1024
    _storage_lock = threading.RLock()

    @staticmethod
    def _ticket_response(ticket: Dict[str, Any]) -> Dict[str, Any]:
        response = dict(ticket)
        if response.get("status") == "received":
            response["status"] = "saved_locally"
            response["timeline"] = [
                {
                    **entry,
                    "status": "saved_locally",
                    "message": "Draft saved on this Mac. Nothing was sent or published.",
                }
                if isinstance(entry, dict) and entry.get("status") == "received"
                else dict(entry) if isinstance(entry, dict) else entry
                for entry in response.get("timeline", [])
            ]
        response.setdefault("display_name", None)
        response.setdefault("publication_consent", False)
        return response

    @classmethod
    def _validate_ticket(
        cls,
        user_email: Optional[str],
        ticket_type: str,
        title: str,
        description: str,
        system_info: Optional[Dict[str, Any]],
        display_name: Optional[str],
        publication_consent: bool,
    ) -> dict:
        if user_email is not None and (
            not isinstance(user_email, str) or len(user_email) > cls.MAX_EMAIL_LENGTH or not re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+", user_email
            )
        ):
            raise ValueError("A valid email address is required")
        if not isinstance(ticket_type, str) or ticket_type not in cls.SUPPORTED_TICKET_TYPES:
            raise ValueError("Ticket type must be bug, support, feature or testimonial")
        if display_name is not None and (not isinstance(display_name, str) or len(display_name) > 80):
            raise ValueError("Display name must be 80 characters or fewer")
        if type(publication_consent) is not bool:
            raise ValueError("Publication consent must be a boolean")
        if publication_consent and ticket_type != "testimonial":
            raise ValueError("Publication consent is only available for testimonials")
        if publication_consent and (display_name is None or not display_name.strip()):
            raise ValueError("A display name is required when publication is allowed")
        if not isinstance(title, str) or not title.strip() or len(title) > cls.MAX_TITLE_LENGTH:
            raise ValueError(f"Ticket title must contain 1–{cls.MAX_TITLE_LENGTH} characters")
        if not isinstance(description, str) or not description.strip() or len(description) > cls.MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Ticket description must contain 1–{cls.MAX_DESCRIPTION_LENGTH} characters")
        if system_info is None:
            system_info = {}
        allowed_system_info = {"os", "app_version", "platform", "userAgent"}
        if not isinstance(system_info, dict) or len(system_info) > cls.MAX_SYSTEM_INFO_FIELDS:
            raise ValueError("System information must be a small object")
        if any(
            not isinstance(key, str)
            or key not in allowed_system_info
            or not isinstance(value, str)
            or len(value) > cls.MAX_SYSTEM_INFO_VALUE_LENGTH
            for key, value in system_info.items()
        ):
            raise ValueError("System information contains unsupported or oversized values")
        return dict(system_info)

    @classmethod
    def _load_tickets(cls) -> Dict[str, Any]:
        try:
            size = os.path.getsize(TICKETS_FILE)
        except FileNotFoundError:
            return {}
        except OSError as error:
            raise SupportStoreError("The local ticket store is unavailable") from error
        if size > cls.MAX_TICKET_STORE_BYTES:
            raise SupportStoreError("The local ticket store exceeds its supported size")
        try:
            with open(TICKETS_FILE, "rb") as file:
                raw = file.read(cls.MAX_TICKET_STORE_BYTES + 1)
            if len(raw) > cls.MAX_TICKET_STORE_BYTES:
                raise SupportStoreError("The local ticket store exceeds its supported size")
            tickets = json.loads(raw.decode("utf-8"))
        except SupportStoreError:
            raise
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise SupportStoreError("The local ticket store is unreadable; existing data was preserved") from error
        if not isinstance(tickets, dict) or any(
            not isinstance(ticket_id, str) or not isinstance(ticket, dict)
            for ticket_id, ticket in tickets.items()
        ):
            raise SupportStoreError("The local ticket store has an invalid structure; existing data was preserved")
        return tickets

    @classmethod
    def _save_tickets(cls, data: Dict[str, Any]):
        serialized = json.dumps(data, indent=2, ensure_ascii=False)
        encoded = serialized.encode("utf-8")
        if len(encoded) > cls.MAX_TICKET_STORE_BYTES:
            raise SupportStoreError("The local ticket store exceeds its supported size")

        directory = os.path.dirname(os.path.abspath(TICKETS_FILE))
        temporary_path = None
        try:
            os.makedirs(directory, mode=0o700, exist_ok=True)
            if os.name == "posix":
                os.chmod(directory, 0o700)
            descriptor, temporary_path = tempfile.mkstemp(prefix=".officekit-tickets-", dir=directory)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(serialized)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, TICKETS_FILE)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

    @classmethod
    def create_ticket(
        cls,
        user_email: Optional[str],
        ticket_type: str,
        title: str,
        description: str,
        system_info: Optional[Dict[str, Any]] = None,
        display_name: Optional[str] = None,
        publication_consent: bool = False,
    ) -> Dict[str, Any]:
        system_info = cls._validate_ticket(
            user_email, ticket_type, title, description, system_info, display_name, publication_consent
        )
        with cls._storage_lock:
            tickets = cls._load_tickets()
            t_id = f"OK-{int(time.time())}-{uuid.uuid4().hex.upper()}"
            created_at = time.time()
            ticket = {
                "ticket_id": t_id,
                "user_email": user_email,
                "ticket_type": ticket_type,
                "title": title,
                "description": description,
                "system_info": system_info,
                "display_name": display_name,
                "publication_consent": publication_consent,
                "status": "saved_locally",
                "created_at": created_at,
                "timeline": [{
                    "status": "saved_locally",
                    "message": "Draft saved on this Mac. Nothing was sent or published.",
                    "timestamp": created_at,
                }],
            }
            tickets[t_id] = ticket
            cls._save_tickets(tickets)
            return ticket

    @classmethod
    def get_ticket(cls, ticket_id: str) -> Optional[Dict[str, Any]]:
        with cls._storage_lock:
            tickets = cls._load_tickets()
            ticket = tickets.get(ticket_id)
            return cls._ticket_response(ticket) if ticket else None

    @classmethod
    def list_user_tickets(cls, user_email: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Ticket list limit must be between 1 and 100")
        if type(offset) is not int or not 0 <= offset <= 10_000:
            raise ValueError("Ticket list offset must be between 0 and 10000")
        with cls._storage_lock:
            tickets = cls._load_tickets()
            items = list(tickets.values())
            if user_email:
                items = [t for t in items if t.get("user_email") == user_email]
            items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
            return [cls._ticket_response(ticket) for ticket in items[offset:offset + limit]]


class CommsEngine:

    @staticmethod
    def check_for_updates() -> Dict[str, Any]:
        """Check a bounded HTTPS release manifest without sending usage or file data."""
        current_version = os.environ.get("OFFICEKIT_APP_VERSION", APP_CURRENT_VERSION)
        current_key = _release_version_key(current_version)
        manifest_url = os.environ.get(UPDATE_MANIFEST_URL, "").strip()
        if current_key is None or not _is_officekit_https_url(manifest_url):
            return _unavailable_update_status(
                current_version if current_key is not None else APP_CURRENT_VERSION
            )

        try:
            request = Request(
                manifest_url,
                headers={"Accept": "application/json", "User-Agent": "OfficeKit-Update-Check"},
            )
            with urlopen(request, timeout=UPDATE_REQUEST_TIMEOUT_SECONDS) as response:
                final_url = getattr(response, "geturl", lambda: manifest_url)()
                if not _is_officekit_https_url(final_url):
                    return _unavailable_update_status(current_version)
                content = response.read(UPDATE_MANIFEST_MAX_BYTES + 1)
            if len(content) > UPDATE_MANIFEST_MAX_BYTES:
                return _unavailable_update_status(current_version)
            manifest = json.loads(content.decode("utf-8"))
            if not isinstance(manifest, dict):
                return _unavailable_update_status(current_version)

            latest_version = manifest.get("version")
            latest_key = _release_version_key(latest_version)
            release_notes = manifest.get("release_notes")
            download_url = manifest.get("download_url")
            if (
                latest_key is None
                or not isinstance(release_notes, str)
                or not release_notes.strip()
                or len(release_notes) > 4000
                or not _is_officekit_https_url(download_url)
            ):
                return _unavailable_update_status(current_version)

            # A stale cached feed is not proof that this build is current.
            if latest_key < current_key:
                return _unavailable_update_status(current_version)

            update_available = latest_key > current_key
            return {
                "status": "update_available" if update_available else "up_to_date",
                "current_version": current_version,
                "latest_version": latest_version,
                "update_available": update_available,
                "release_notes": release_notes.strip(),
                "download_url": download_url,
            }
        except (OSError, UnicodeError, ValueError, TypeError):
            return _unavailable_update_status(current_version)

    @staticmethod
    def get_announcement_banner() -> Dict[str, Any]:
        """Provides dynamic alerts or in-app updates to all users."""
        return {
            "active": True,
            "banner_type": "info", # 'info', 'warning', 'success'
            "message": "🚀 OfficeKit v1.0 is active with 100% offline privacy mode. No document data or audio ever leaves this device.",
            "action_text": "View Release Highlights",
            "action_link": "#"
        }

    @staticmethod
    def search_tools(query: str = "") -> List[Dict[str, Any]]:
        """Search stable tool records by all meaningful query terms and known aliases."""
        if not isinstance(query, str):
            raise ValueError("Search query must be text")
        if len(query) > MAX_TOOL_SEARCH_QUERY_LENGTH:
            raise ValueError(f"Search query must be no longer than {MAX_TOOL_SEARCH_QUERY_LENGTH} characters")

        query = query.strip()
        if not query:
            return [_tool_search_record(tool) for tool in TOOL_REGISTRY]

        tokens = _search_phrase(query).split()
        if not tokens:
            return []
        raw_query = unicodedata.normalize("NFKD", query.casefold())
        raw_query_words = [TOOL_SEARCH_INFLECTIONS.get(token, token) for token in re.findall(r"[a-z0-9]+", raw_query)]
        to_index = raw_query_words.index("to") if "to" in raw_query_words else -1
        source_format_terms = set(raw_query_words[:to_index]) if to_index >= 0 else set()
        required_groups = [_expanded_search_token(token) for token in tokens]

        ranked = []
        for registry_index, tool in enumerate(TOOL_REGISTRY):
            context_terms = TOOL_SEARCH_CONTEXT_TERMS.get(tool["id"], frozenset())
            if context_terms and not any(any(c.startswith(token) for c in context_terms) for token in tokens) and not context_terms.issubset(set(tokens)):
                continue
            if tool["id"] in {"pdf_delete_pages", "pdf_reorder_pages"} and not (
                (len(tokens) == 1 and any("pdf".startswith(t) for t in tokens))
                or {"page", "pages"}.intersection(tokens)
            ):
                continue
            if tool["id"] == "bank_statement" and set(tokens) == {"image", "converter"}:
                continue
            if tool["id"] == "image_converter" and "pdf" in source_format_terms and "image" not in source_format_terms:
                continue
            record = _tool_search_record(tool)
            name_tokens = _search_tokens(tool["name"])
            category_tokens = _search_tokens(tool["category"])
            # Negative capability copy must not advertise the unsupported action.
            description = re.sub(r"\b(?:without|no)\s+OCR\b", "", tool["desc"], flags=re.IGNORECASE)
            description_tokens = _search_tokens(description)
            keyword_tokens = _search_tokens(" ".join(record["keywords"]))
            all_tokens = name_tokens | category_tokens | description_tokens | keyword_tokens | _search_tokens(tool["id"])

            if not all(_search_term_matches(token, group, all_tokens) for token, group in zip(tokens, required_groups)):
                continue

            score = 0
            for token, group in zip(tokens, required_groups):
                if token in name_tokens:
                    score += 20
                elif token in category_tokens:
                    score += 16
                elif token in description_tokens:
                    score += 13
                elif token in keyword_tokens:
                    score += 11
                elif group & name_tokens:
                    score += 6
                elif group & category_tokens:
                    score += 4
                elif group & description_tokens:
                    score += 3
                elif group & keyword_tokens:
                    score += 2
                elif _search_term_prefix_matches(token, name_tokens):
                    score += 10
                elif _search_term_prefix_matches(token, category_tokens):
                    score += 8
                elif _search_term_prefix_matches(token, description_tokens):
                    score += 6
                elif _search_term_prefix_matches(token, keyword_tokens):
                    score += 5
                else:
                    score += 1
            normalized_query = _search_phrase(query)
            if normalized_query and normalized_query in _search_phrase(tool["name"]):
                score += 20
            ranked.append((-score, registry_index, record))

        ranked.sort(key=lambda result: (result[0], result[1]))
        return [record for _, _, record in ranked]
