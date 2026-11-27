"""Action registry mapping grouped MCP tools onto the shipped OfficeKit API routes.

Every action calls an existing route in-process, so the release profile, request
validation and size limits stay the single source of truth.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    method: str
    path: str
    kind: str  # "json" | "query" | "none" | "form"
    files: str | None = None  # "file" | "files" for multipart uploads
    hint: str = ""  # form fields / limits, shown by officekit_help
    mask_matches: bool = False  # replace each match's raw `value` with a partial hint


def _calc(name):
    return Action("POST", f"/api/calculator/{name}", "json")


# Data that may hold secrets the user never handed to an agent: never exposed over MCP.
SENSITIVE_PATH_MARKERS = ("clipboard", "snippet", "history", "transcript", "dictate", "dictation", "recents")


def assert_no_sensitive_actions(groups=None):
    for group_name, group in (GROUPS if groups is None else groups).items():
        for name, action in group["actions"].items():
            if any(marker in action.path.lower() for marker in SENSITIVE_PATH_MARKERS):
                raise ValueError(f"MCP must not expose sensitive data: {group_name}/{name}")


GROUPS = {
    "calc": {
        "description": "Exact calculators, math, unit and colour conversion.",
        "actions": {
            "loan-emi": _calc("loan-emi"),
            "compound-interest": _calc("compound-interest"),
            "simple-interest": _calc("simple-interest"),
            "vat-sales-tax": _calc("vat-sales-tax"),
            "freelance-rate": _calc("freelance-rate"),
            "margin-markup": _calc("margin-markup"),
            "break-even": _calc("break-even"),
            "depreciation": _calc("depreciation"),
            "percent-of": _calc("percent-of"),
            "percentage-change": _calc("percentage-change"),
            "discount": _calc("discount"),
            "math-eval": Action("POST", "/api/math/eval", "json"),
            "units-convert": Action("POST", "/api/units/convert", "json"),
            "units-catalog": Action("GET", "/api/units/catalog", "none"),
            "colors-convert": Action("POST", "/api/colors/convert", "json"),
        },
    },
    "dev": {
        "description": "JSON/YAML/Base64/URL/JWT tools and hashes.",
        "actions": {
            "devtools": Action("POST", "/api/devtools/process", "json"),
            "hashes": Action("POST", "/api/crypto/hashes", "json"),
            # No password/passphrase generators: a generated secret would land in the chat transcript.
        },
    },
    "pdf": {
        "description": "Read, edit and secure PDFs; outputs are written to the output folder.",
        "actions": {
            "text": Action("POST", "/api/pdf/text", "form", "file",
                           "params: page_ranges (e.g. 1-3,5), format txt|md"),
            "tables": Action("POST", "/api/pdf/tables", "form", "file", "no params; lists tables per page"),
            "tables-export": Action("POST", "/api/pdf/tables/export", "form", "file",
                                    "params: page_number 1-50, table_number 1-40, format csv|xls|xlsx"),
            "page-counts": Action("POST", "/api/pdf/page-counts", "form", "files", "files: 1-20 PDFs"),
            "merge": Action("POST", "/api/pdf/merge", "form", "files", "files: 2-20 PDFs in order"),
            "split-groups": Action("POST", "/api/pdf/split/groups", "form", "file",
                                   "params: groups (JSON string of page-range groups)"),
            "delete-pages": Action("POST", "/api/pdf/pages/delete", "form", "file", "params: page_ranges"),
            "reorder-pages": Action("POST", "/api/pdf/pages/reorder", "form", "file", "params: page_order"),
            "compress": Action("POST", "/api/pdf/compress", "form", "file", "params: preset (default balanced)"),
            "strip-metadata": Action("POST", "/api/pdf/metadata", "form", "file", "no params"),
            "protect": Action("POST", "/api/pdf/protect", "form", "file", "params: password (required)"),
            "unlock": Action("POST", "/api/pdf/unlock", "form", "file", "params: password"),
            "to-images": Action("POST", "/api/pdf/images", "form", "file",
                                "params: target_format png|jpg, dpi, quality 1-100"),
            "extract-statement": Action("POST", "/api/extract/statement", "form", "file",
                                        "bank statement PDF/image; params: number_locale, date_order, column_mapping"),
        },
    },
    "image": {
        "description": "Convert, resize and strip metadata from images.",
        "actions": {
            "convert": Action("POST", "/api/convert/image", "form", "file",
                              "params: target_format (required), quality 1-100"),
            "resize": Action("POST", "/api/image/resize", "form", "file",
                             "params: max_width, max_height (required, 1-10000)"),
            "strip-metadata": Action("POST", "/api/image/metadata", "form", "file", "no params"),
        },
    },
    "privacy": {
        "description": "Find and redact personal information in documents, locally.",
        "actions": {
            "pii-scan": Action("POST", "/api/privacy/pii/scan", "form", "file",
                               "no params; returns findings (type, location, masked hint) with ids",
                               mask_matches=True),
            "pii-redact": Action("POST", "/api/privacy/pii/redact", "form", "file",
                                 "params: selected_ids (JSON list string from pii-scan), mode mask|redact"),
        },
    },
    "system": {
        "description": "Read-only machine information.",
        "actions": {
            "info": Action("GET", "/api/system/info", "none"),
            "resources": Action("GET", "/api/system/resources", "none"),
            "metrics": Action("GET", "/api/system/metrics", "none"),
        },
    },
}
