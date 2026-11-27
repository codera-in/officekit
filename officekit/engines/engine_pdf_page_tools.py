"""Page rotation (P06) and page-size changes (P15) that edit page geometry, not object transforms."""

from decimal import Decimal, InvalidOperation

import pikepdf

from officekit.engines.engine_pdf_advanced import AdvancedPdfEngine
from officekit.engines.engine_pdf_tool_common import (
    PAGE_PRESETS_PT,
    PdfOptionError,
    open_source_pdf,
    page_rotation,
    save_bounded,
    selected_indexes,
    to_points,
)

_ANCHOR_FACTORS = {
    "bottom-left": (0.0, 0.0), "bottom-center": (0.5, 0.0), "bottom-right": (1.0, 0.0),
    "center-left": (0.0, 0.5), "center": (0.5, 0.5), "center-right": (1.0, 0.5),
    "top-left": (0.0, 1.0), "top-center": (0.5, 1.0), "top-right": (1.0, 1.0),
}


def _raw_anchor(factors, rotation):
    """Map a displayed anchor (fraction across, fraction up) onto the page's unrotated axes.

    /Rotate turns the displayed page clockwise, so the displayed corner the anchor names is a different raw corner.
    """
    fx, fy = factors
    if rotation == 90:
        return 1.0 - fy, fx
    if rotation == 180:
        return 1.0 - fx, 1.0 - fy
    if rotation == 270:
        return fy, 1.0 - fx
    return fx, fy


def _page_content_bytes(page) -> bytes:
    """The decoded bytes of every /Contents stream, joined in order (empty when the page has none)."""
    contents = page.obj.get("/Contents")
    if contents is None:
        return b""
    streams = list(contents) if isinstance(contents, pikepdf.Array) else [contents]
    return b"\n".join(stream.read_bytes() for stream in streams)


class PageToolsEngine:
    MAX_OUTPUT_BYTES = AdvancedPdfEngine.MAX_OUTPUT_BYTES
    ROTATE_ANGLES = (90, 180, 270)
    MIN_SIDE_PT = 72.0
    MAX_SIDE_PT = 14_400.0
    ORIENTATIONS = ("keep", "portrait", "landscape")
    MODES = ("scale", "canvas")
    _PAGE_BOX_KEYS = ("/TrimBox", "/BleedBox", "/ArtBox")

    @classmethod
    def target_size(cls, preset, width=None, height=None, unit=None) -> tuple[float, float]:
        """Displayed target size in points for a preset, or for custom width/height with a unit."""
        if preset in PAGE_PRESETS_PT:
            return PAGE_PRESETS_PT[preset]
        if preset != "custom":
            raise PdfOptionError("Unknown page size preset.")
        if width is None or height is None:
            raise PdfOptionError("Custom page sizes need both width and height.")
        try:
            width_pt = to_points(Decimal(str(width)), unit)
            height_pt = to_points(Decimal(str(height)), unit)
        except (InvalidOperation, TypeError) as error:
            raise PdfOptionError("Page size values must be numbers.") from error
        for side in (width_pt, height_pt):
            if not cls.MIN_SIDE_PT <= side <= cls.MAX_SIDE_PT:
                raise PdfOptionError("Page sides must be between 72 and 14,400 points.")
        return width_pt, height_pt

    @classmethod
    def rotate_pages(cls, content: bytes, angle, page_ranges: str) -> tuple[bytes, int]:
        if isinstance(angle, bool) or angle not in cls.ROTATE_ANGLES:
            raise PdfOptionError("Rotation must be 90, 180 or 270 degrees.")
        with open_source_pdf(content) as pdf:
            indexes = selected_indexes(page_ranges, len(pdf.pages))
            for index in indexes:
                page = pdf.pages[index]
                if "/Rotate" not in page.obj:
                    # Pin the inherited value first so the relative turn starts from what the viewer shows.
                    page.obj["/Rotate"] = page_rotation(page.obj)
                page.rotate(angle, relative=True)
            return save_bounded(pdf, cls.MAX_OUTPUT_BYTES), len(indexes)

    @classmethod
    def resize_pages(cls, content: bytes, *, target: tuple[float, float], orientation: str,
                     mode: str, anchor: str, page_ranges: str) -> tuple[bytes, float]:
        if orientation not in cls.ORIENTATIONS:
            raise PdfOptionError("Orientation must be keep, portrait or landscape.")
        if mode not in cls.MODES:
            raise PdfOptionError("Mode must be scale or canvas.")
        if anchor not in _ANCHOR_FACTORS:
            raise PdfOptionError("Anchor must be one of the nine positions.")
        target_width, target_height = target
        if not (cls.MIN_SIDE_PT <= target_width <= cls.MAX_SIDE_PT
                and cls.MIN_SIDE_PT <= target_height <= cls.MAX_SIDE_PT):
            raise PdfOptionError("Page sides must be between 72 and 14,400 points.")

        with open_source_pdf(content) as pdf:
            indexes = selected_indexes(page_ranges, len(pdf.pages))
            scales = []
            for index in indexes:
                scales.append(cls._resize_page(pdf, pdf.pages[index], target_width, target_height,
                                               orientation, mode, anchor))
            if not scales:
                raise PdfOptionError("Select at least one page or page range.")
            output = save_bounded(pdf, cls.MAX_OUTPUT_BYTES)
        return output, min(scales)

    @classmethod
    def _resize_page(cls, pdf, page, target_width, target_height, orientation, mode, anchor) -> float:
        rotation = page_rotation(page.obj)
        crop_x0, crop_y0, crop_x1, crop_y1 = (float(value) for value in page.cropbox)
        crop_w, crop_h = crop_x1 - crop_x0, crop_y1 - crop_y0
        displayed_w, displayed_h = (crop_h, crop_w) if rotation in (90, 270) else (crop_w, crop_h)

        width, height = target_width, target_height
        source_landscape = displayed_w > displayed_h
        if orientation == "portrait":
            width, height = min(width, height), max(width, height)
        elif orientation == "landscape":
            width, height = max(width, height), min(width, height)
        elif (width > height) != source_landscape and width != height:
            width, height = height, width
        # Unrotated MediaBox is the displayed target turned back into the page's own axes.
        box_w, box_h = (height, width) if rotation in (90, 270) else (width, height)

        if mode == "scale":
            scale = min(box_w / crop_w, box_h / crop_h)
            anchor_x, anchor_y = 0.5, 0.5
        else:
            scale = 1.0
            anchor_x, anchor_y = _raw_anchor(_ANCHOR_FACTORS[anchor], rotation)
        offset_x = (box_w - scale * crop_w) * anchor_x
        offset_y = (box_h - scale * crop_h) * anchor_y
        translate_x = offset_x - scale * crop_x0
        translate_y = offset_y - scale * crop_y0

        # Capture the original bytes before /Contents is replaced; the form must not read the new wrapper.
        original_content = _page_content_bytes(page)
        # Raw page axes: the placement math below works in the unrotated box, and /Rotate is kept on the page.
        form = page.as_form_xobject(handle_transformations=False)
        form.write(original_content)
        xobjects = pikepdf.Dictionary()
        xobjects["/OfficeKitSource"] = form
        page.obj["/Resources"] = pikepdf.Dictionary(XObject=xobjects)
        page.obj["/Contents"] = pdf.make_stream(
            f"q {scale:.6f} 0 0 {scale:.6f} {translate_x:.6f} {translate_y:.6f} cm /OfficeKitSource Do Q".encode("ascii")
        )
        box = pikepdf.Array([0, 0, box_w, box_h])
        page.obj["/MediaBox"] = box
        page.obj["/CropBox"] = pikepdf.Array([0, 0, box_w, box_h])
        for key in cls._PAGE_BOX_KEYS:
            if key in page.obj:
                del page.obj[key]

        for annotation in page.obj.get("/Annots", []):
            cls._transform_annotation(annotation, scale, translate_x, translate_y)
        return scale

    @staticmethod
    def _transform_annotation(annotation, scale, translate_x, translate_y) -> None:
        def transform(values):
            pairs = [float(v) for v in values]
            moved = []
            for index in range(0, len(pairs) - 1, 2):
                moved.append(scale * pairs[index] + translate_x)
                moved.append(scale * pairs[index + 1] + translate_y)
            return moved

        rect = annotation.get("/Rect")
        if rect is not None and len(rect) == 4:
            moved = transform(rect)
            xs, ys = moved[0::2], moved[1::2]
            annotation["/Rect"] = pikepdf.Array([min(xs), min(ys), max(xs), max(ys)])
        quad = annotation.get("/QuadPoints")
        if quad is not None and len(quad) % 8 == 0 and len(quad) > 0:
            annotation["/QuadPoints"] = pikepdf.Array(transform(quad))
