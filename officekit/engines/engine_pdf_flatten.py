"""Flatten forms and annotations (P17): draw each appearance into the page and remove the interactive layer.

Structure is verified after writing (P-070/P-071): the output is reopened and must have no AcroForm
and no widgets in scope forms/all, and no non-widget annotations in scope annotations/all. A render
check alone would pass a file that still has editable fields.
"""

import io

import pikepdf

from officekit.engines.engine_pdf_advanced import AdvancedPdfEngine
from officekit.engines.engine_pdf_tool_common import (
    inherited_value,
    open_source_pdf,
    page_xobjects,
    save_bounded,
    wrap_page_content,
)

_FLAG_HIDDEN = 2
_FLAG_NOVIEW = 32
_FIELD_TYPE_SIGNATURE = pikepdf.Name.Sig


class FlattenRefusedError(ValueError):
    """A typed refusal: a stable code, the HTTP status it maps to, and fixed public copy."""

    _COPY = {
        "signature_ack_required": (409, "A signed field will lose its signature. Confirm before flattening."),
        "xfa_unsupported": (422, "XFA forms cannot be flattened by this tool."),
        "appearance_missing": (422, "A form field or annotation has no appearance that can be drawn."),
    }

    def __init__(self, code: str):
        self.code = code
        self.status, self.message = self._COPY[code]
        super().__init__(self.message)


def _is_widget(annotation) -> bool:
    return annotation.get("/Subtype") == pikepdf.Name.Widget


def _is_signed(widget) -> bool:
    return inherited_value(widget, "/FT") == _FIELD_TYPE_SIGNATURE and "/V" in widget


def _has_appearance(annotation) -> bool:
    appearance = annotation.get("/AP")
    return appearance is not None and appearance.get("/N") is not None


def _appearance_stream(annotation):
    """Normal appearance; a state dictionary is selected by /AS (an absent state draws nothing)."""
    normal = annotation.get("/AP", {}).get("/N")
    if normal is None:
        return None
    if isinstance(normal, pikepdf.Stream):
        return normal
    state = annotation.get("/AS")
    if state is None:
        return None
    selected = normal.get(state)
    return selected if isinstance(selected, pikepdf.Stream) else None


class PdfFlattenEngine:
    MAX_OUTPUT_BYTES = AdvancedPdfEngine.MAX_OUTPUT_BYTES
    SCOPES = ("all", "forms", "annotations")

    @classmethod
    def flatten(cls, content: bytes, scope: str, acknowledge_signature_loss: bool) -> tuple[bytes, int, int]:
        if scope not in cls.SCOPES:
            raise ValueError("Scope must be all, forms or annotations.")
        if not isinstance(acknowledge_signature_loss, bool):
            raise ValueError("The signature acknowledgement must be true or false.")
        touch_forms = scope in ("all", "forms")
        touch_annotations = scope in ("all", "annotations")

        with open_source_pdf(content) as pdf:
            acroform = pdf.Root.get("/AcroForm")
            if acroform is not None and "/XFA" in acroform:
                raise FlattenRefusedError("xfa_unsupported")

            if touch_forms:
                cls._check_signatures(pdf, acknowledge_signature_loss)
                cls._ensure_widget_appearances(pdf, acroform)

            flattened_fields = 0
            flattened_annotations = 0
            serial = 0
            for page in pdf.pages:
                kept = []
                draws = []
                for annotation in list(page.obj.get("/Annots", [])):
                    widget = _is_widget(annotation)
                    in_scope = touch_forms if widget else touch_annotations
                    if not in_scope:
                        kept.append(annotation)
                        continue
                    # Popups have no appearance of their own and links have no visual: both are removed.
                    if annotation.get("/Subtype") in (pikepdf.Name.Popup, pikepdf.Name.Link):
                        continue
                    flags = int(annotation.get("/F", 0))
                    if flags & (_FLAG_HIDDEN | _FLAG_NOVIEW):
                        continue
                    stream = _appearance_stream(annotation)
                    if stream is None and not widget:
                        raise FlattenRefusedError("appearance_missing")
                    if stream is not None:
                        draws.append((f"/OfficeKitFlat{serial}", stream, annotation.get("/Rect")))
                        serial += 1
                    if widget:
                        flattened_fields += 1
                    else:
                        flattened_annotations += 1
                page.obj["/Annots"] = pikepdf.Array(kept)
                if draws:
                    cls._draw_onto_page(pdf, page, draws)
            if touch_forms and "/AcroForm" in pdf.Root:
                del pdf.Root["/AcroForm"]

            output = save_bounded(pdf, cls.MAX_OUTPUT_BYTES)

        cls._verify_structure(output, scope)
        return output, flattened_fields, flattened_annotations

    @staticmethod
    def _check_signatures(pdf, acknowledged: bool) -> None:
        for page in pdf.pages:
            for annotation in page.obj.get("/Annots", []):
                if _is_widget(annotation) and _is_signed(annotation) and not acknowledged:
                    raise FlattenRefusedError("signature_ack_required")

    @staticmethod
    def _ensure_widget_appearances(pdf, acroform) -> None:
        if acroform is None:
            return
        needs = bool(acroform.get("/NeedAppearances", False))
        for page in pdf.pages:
            for annotation in page.obj.get("/Annots", []):
                if _is_widget(annotation) and not _has_appearance(annotation):
                    needs = True
        if needs:
            # pikepdf only regenerates appearance streams when the form asks for them.
            acroform.NeedAppearances = True
            pdf.generate_appearance_streams()
        for page in pdf.pages:
            for annotation in page.obj.get("/Annots", []):
                if _is_widget(annotation) and not _has_appearance(annotation):
                    raise FlattenRefusedError("appearance_missing")

    @staticmethod
    def _draw_onto_page(pdf, page, draws) -> None:
        xobjects = page_xobjects(page)
        commands = []
        for name, stream, rect in draws:
            xobjects[name] = stream
            matrix = [float(v) for v in stream.get("/Matrix", [1, 0, 0, 1, 0, 0])]
            bbox = [float(v) for v in stream.get("/BBox", [0, 0, 0, 0])]
            transformed = _transform_box(bbox, matrix)
            left, bottom, right, top = (float(v) for v in rect) if rect is not None else (0, 0, 0, 0)
            rect_left, rect_right = min(left, right), max(left, right)
            rect_bottom, rect_top = min(bottom, top), max(bottom, top)
            box_left, box_bottom, box_right, box_top = transformed
            scale_x = (rect_right - rect_left) / (box_right - box_left) if box_right > box_left else 1.0
            scale_y = (rect_top - rect_bottom) / (box_top - box_bottom) if box_top > box_bottom else 1.0
            translate_x = rect_left - scale_x * box_left
            translate_y = rect_bottom - scale_y * box_bottom
            commands.append(
                f"q {scale_x:.6f} 0 0 {scale_y:.6f} {translate_x:.6f} {translate_y:.6f} cm {name} Do Q\n"
            )
        wrap_page_content(pdf, page, "".join(commands).encode("ascii"))

    @staticmethod
    def _verify_structure(output: bytes, scope: str) -> None:
        with pikepdf.open(io.BytesIO(output)) as result:
            if scope in ("all", "forms"):
                if "/AcroForm" in result.Root:
                    raise RuntimeError("flatten self-check: AcroForm remains")
            for page in result.pages:
                for annotation in page.obj.get("/Annots", []):
                    if scope in ("all", "forms") and _is_widget(annotation):
                        raise RuntimeError("flatten self-check: widget remains")
                    if scope in ("all", "annotations") and not _is_widget(annotation):
                        raise RuntimeError("flatten self-check: annotation remains")


def _transform_box(bbox, matrix):
    """Bounding box of the BBox corners after the appearance Matrix (PDF 12.5.5)."""
    left, bottom, right, top = bbox
    a, b, c, d, e, f = matrix
    corners = [(left, bottom), (right, bottom), (left, top), (right, top)]
    xs = [a * x + c * y + e for x, y in corners]
    ys = [b * x + d * y + f for x, y in corners]
    return min(xs), min(ys), max(xs), max(ys)
