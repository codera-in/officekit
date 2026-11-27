"""Shared source handling for the PDF tool slice engines (P06, P08, P10, P12-P17)."""

import io
import math

import pikepdf

from officekit.engines.engine_pdf_advanced import AdvancedPdfEngine
from officekit.engines.engine_pdf_ranges import parse_page_ranges
from officekit.engines.engine_pdf_security import BoundedPdfBuffer

MAX_TOOL_PAGES = AdvancedPdfEngine.MAX_PAGE_MANAGEMENT_PAGES


class PdfOptionError(ValueError):
    """A bad option or page selection (the caller's request), not a bad PDF. Gets the options copy (422)."""


MM_TO_PT = 72.0 / 25.4
PAGE_PRESETS_PT = {
    "a4": (595.2756, 841.8898), "a5": (419.5276, 595.2756), "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0), "tabloid": (792.0, 1224.0),
}
_UNIT_TO_POINTS = {"pt": 1.0, "mm": MM_TO_PT, "in": 72.0}


_MALFORMED_PAGE_MESSAGE = "The PDF page structure is invalid."


def _check_page_structure(page) -> None:
    """Reject geometry, rotation and annotation shapes the engines cannot process (CR-2).

    Each failure is a ValueError, so the route returns the fixed PDF copy (422) rather than the 500 boundary.
    """
    for box in (page.obj.get("/MediaBox"), page.obj.get("/CropBox")):
        if box is None:
            continue
        try:
            coordinates = [float(value) for value in box]
        except (TypeError, ValueError) as error:
            raise ValueError(_MALFORMED_PAGE_MESSAGE) from error
        if len(coordinates) != 4 or not all(math.isfinite(value) for value in coordinates):
            raise ValueError(_MALFORMED_PAGE_MESSAGE)
        if coordinates[2] <= coordinates[0] or coordinates[3] <= coordinates[1]:
            raise ValueError(_MALFORMED_PAGE_MESSAGE)
    page_rotation(page.obj)
    annotations = page.obj.get("/Annots")
    if annotations is None:
        return
    if not isinstance(annotations, pikepdf.Array):
        raise ValueError(_MALFORMED_PAGE_MESSAGE)
    for annotation in annotations:
        if not isinstance(annotation, pikepdf.Dictionary):
            raise ValueError(_MALFORMED_PAGE_MESSAGE)
        appearance = annotation.get("/AP")
        if appearance is not None and not isinstance(appearance, pikepdf.Dictionary):
            raise ValueError(_MALFORMED_PAGE_MESSAGE)


def open_source_pdf(content: bytes) -> pikepdf.Pdf:
    """Open an upload read-only. Caller closes the returned document."""
    if not isinstance(content, bytes) or not content:
        raise ValueError("PDF input must be non-empty bytes")
    pdf = pikepdf.open(io.BytesIO(content))
    try:
        page_count = len(pdf.pages)
        if not 1 <= page_count <= MAX_TOOL_PAGES:
            raise ValueError("The PDF must contain between 1 and 2,000 pages.")
        for page in pdf.pages:
            _check_page_structure(page)
    except Exception:
        pdf.close()
        raise
    return pdf


def count_pages(content: bytes) -> int:
    with open_source_pdf(content) as pdf:
        return len(pdf.pages)


def selected_indexes(page_ranges: str, page_count: int) -> list[int]:
    """Empty selection means every page; any other value uses the strict range grammar."""
    if not isinstance(page_ranges, str):
        raise PdfOptionError("Page ranges must be text.")
    if not page_ranges.strip():
        return list(range(page_count))
    try:
        return parse_page_ranges(page_ranges, page_count, MAX_TOOL_PAGES)
    except ValueError as error:
        raise PdfOptionError(str(error)) from error


def inherited_value(node, key: str):
    """First non-null value of ``key`` on ``node`` or its /Parent chain (bounded depth)."""
    current = node
    depth = 0
    while current is not None and depth < 64:
        value = current.get(key)
        if value is not None:
            return value
        current = current.get("/Parent")
        depth += 1
    return None


def page_xobjects(page) -> pikepdf.Dictionary:
    """The page's /XObject dictionary, creating /Resources (copied from inherited ones) when absent."""
    resources = page.obj.get("/Resources")
    if resources is None:
        resources = pikepdf.Dictionary()
        inherited = inherited_value(page.obj, "/Resources")
        if inherited is not None:
            for key in inherited.keys():
                resources[key] = inherited[key]
        page.obj["/Resources"] = resources
    xobjects = resources.get("/XObject")
    if xobjects is None:
        xobjects = pikepdf.Dictionary()
        resources["/XObject"] = xobjects
    return xobjects


def wrap_page_content(pdf: pikepdf.Pdf, page, body: bytes) -> None:
    """Bracket the page's existing content in q/Q, then append ``body`` (which must be self-balanced)."""
    page.contents_add(pdf.make_stream(b"q\n"), prepend=True)
    page.contents_add(pdf.make_stream(b"Q\n" + body))


def page_rotation(node) -> int:
    """Effective /Rotate, resolved through /Parent because the value is inheritable."""
    current = node
    while current is not None:
        value = current.get("/Rotate")
        if value is not None:
            try:
                rotation = int(value) % 360
            except (TypeError, ValueError) as error:
                raise ValueError("Unsupported page rotation.") from error
            if rotation % 90:
                raise ValueError("Unsupported page rotation.")
            return rotation
        current = current.get("/Parent")
    return 0


def save_bounded(pdf: pikepdf.Pdf, max_bytes: int, **options) -> bytes:
    """Serialise through the bounded writer so the output cap stops work before it is exceeded."""
    output = BoundedPdfBuffer(max_bytes)
    pdf.save(output, **options)
    return output.getvalue()


def to_points(value, unit: str) -> float:
    if unit not in _UNIT_TO_POINTS:
        raise PdfOptionError("Units must be mm, in or pt.")
    if isinstance(value, bool) or value is None:
        raise PdfOptionError("Page size values must be numbers.")
    return float(value) * _UNIT_TO_POINTS[unit]
