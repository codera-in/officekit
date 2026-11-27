"""Grayscale conversion (P16): exact vector rewrite, or an explicit rasterized alternative.

Vector mode converts content streams, Form XObjects, Type3 glyph procedures, annotation appearances
and raster images. Any construct it cannot convert exactly (shadings, patterns, separation or
device-N spaces, Lab, JPX/JBIG2 images, inline colour images) is refused before anything is written,
so the output is never partly coloured.
"""

import io
import math
import zlib

import pikepdf
import pypdfium2 as pdfium
from PIL import Image

from officekit.engines.engine_pdf_advanced import AdvancedPdfEngine
from officekit.engines.engine_pdf_images import PdfImageExportEngine
from officekit.engines.engine_pdf_tool_common import (
    PdfOptionError,
    inherited_value,
    open_source_pdf,
    page_rotation,
    save_bounded,
)

GRAYSCALE_REFUSAL_CODE = "grayscale_needs_raster"
GRAYSCALE_REFUSAL_MESSAGE = (
    "This PDF uses colour features that vector grayscale cannot convert exactly. "
    "Use the rasterized option instead; its text will no longer be selectable."
)
_GRAY_SPACES = {"/DeviceGray", "/CalGray", "/G"}
_RGB_SPACES = {"/DeviceRGB", "/CalRGB", "/RGB"}
_CMYK_SPACES = {"/DeviceCMYK", "/CMYK"}
_RESOURCE_DEPTH = 32
_MAX_IMAGE_PIXELS = 40_000_000
_DCT_QUALITY = 90


class GrayscaleRefusedError(ValueError):
    """The requested conversion cannot be exact; carries a stable code and fixed copy."""

    code = GRAYSCALE_REFUSAL_CODE
    message = GRAYSCALE_REFUSAL_MESSAGE


class GrayscaleLimitError(ValueError):
    """A fixed page-count, pixel or image-size limit was exceeded; carries its own 422 copy (CR-4)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _luma(red: float, green: float, blue: float) -> float:
    return 0.299 * red + 0.587 * green + 0.114 * blue


def _cmyk_to_gray(cyan: float, magenta: float, yellow: float, black: float) -> float:
    return _luma((1 - cyan) * (1 - black), (1 - magenta) * (1 - black), (1 - yellow) * (1 - black))


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


class _ColourState:
    """Current fill or stroke space as the rewriter understands it."""

    __slots__ = ("kind", "palette")

    def __init__(self, kind: str, palette=None):
        self.kind = kind
        self.palette = palette


class PdfGrayscaleEngine:
    MAX_OUTPUT_BYTES = AdvancedPdfEngine.MAX_OUTPUT_BYTES
    MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS
    METHODS = ("vector", "raster")
    DPI_CHOICES = (150, 300)

    # ------------------------------------------------------------- public

    @classmethod
    def convert(cls, content: bytes, method: str, dpi=None) -> tuple[bytes, str]:
        if method not in cls.METHODS:
            raise PdfOptionError("Grayscale method must be vector or raster.")
        if method == "vector":
            if dpi is not None:
                raise PdfOptionError("DPI applies only to rasterized grayscale.")
            return cls._vector(content), "vector"
        if isinstance(dpi, bool) or dpi not in cls.DPI_CHOICES:
            raise PdfOptionError("Rasterized grayscale supports 150 or 300 DPI.")
        return cls._raster(content, dpi), "raster"

    # ------------------------------------------------------------- vector

    @classmethod
    def _vector(cls, content: bytes) -> bytes:
        with open_source_pdf(content) as pdf:
            walker = _Walker(pdf)
            for page in pdf.pages:
                resources = inherited_value(page.obj, "/Resources")
                walker.convert_page(page, resources)
                for annotation in page.obj.get("/Annots", []):
                    walker.convert_annotation(annotation)
            walker.commit()
            return save_bounded(pdf, cls.MAX_OUTPUT_BYTES)

    # ------------------------------------------------------------- raster

    @classmethod
    def _raster(cls, content: bytes, dpi: int) -> bytes:
        geometry = []
        with open_source_pdf(content) as source:
            for page in source.pages:
                x0, y0, x1, y1 = (float(value) for value in page.cropbox)
                geometry.append((x1 - x0, y1 - y0, page_rotation(page.obj)))
        page_count = len(geometry)
        if page_count > PdfImageExportEngine.MAX_PAGES:
            raise GrayscaleLimitError("Rasterized grayscale supports up to 100 pages.")
        total_pixels = 0
        for width_pt, height_pt, _ in geometry:
            pixels = math.ceil(width_pt * dpi / 72) * math.ceil(height_pt * dpi / 72)
            if pixels > PdfImageExportEngine.MAX_PAGE_PIXELS:
                raise GrayscaleLimitError("A page is too large to rasterize at this DPI.")
            total_pixels += pixels
        if total_pixels > PdfImageExportEngine.MAX_TOTAL_PIXELS:
            raise GrayscaleLimitError("The rasterized pages exceed the pixel budget.")

        document = pdfium.PdfDocument(content)
        try:
            output = pikepdf.new()
            for index in range(page_count):
                width_pt, height_pt, rotation = geometry[index]
                page = document[index]
                try:
                    bitmap = page.render(scale=dpi / 72, grayscale=True)
                    try:
                        image = bitmap.to_pil().convert("L")
                    finally:
                        bitmap.close()
                finally:
                    page.close()
                image = _unrotate(image, rotation)
                width_px, height_px = image.size
                image_stream = pikepdf.Stream(output, b"")
                image_stream.Type = pikepdf.Name.XObject
                image_stream.Subtype = pikepdf.Name.Image
                image_stream.Width = width_px
                image_stream.Height = height_px
                image_stream.ColorSpace = pikepdf.Name.DeviceGray
                image_stream.BitsPerComponent = 8
                image_stream.write(zlib.compress(image.tobytes()), filter=pikepdf.Name.FlateDecode)
                out_page = output.add_blank_page(page_size=(width_pt, height_pt))
                if rotation:
                    out_page.obj.Rotate = rotation
                out_page.obj.Resources = pikepdf.Dictionary(
                    XObject=pikepdf.Dictionary(Im0=output.make_indirect(image_stream))
                )
                out_page.obj.Contents = output.make_stream(
                    f"q {width_pt:.6f} 0 0 {height_pt:.6f} 0 0 cm /Im0 Do Q".encode("ascii")
                )
            return save_bounded(output, cls.MAX_OUTPUT_BYTES)
        finally:
            document.close()


def _unrotate(image: Image.Image, rotation: int) -> Image.Image:
    """pdfium renders the displayed orientation; store the image in the page's own axes."""
    if rotation == 90:
        return image.transpose(Image.Transpose.ROTATE_90)
    if rotation == 180:
        return image.transpose(Image.Transpose.ROTATE_180)
    if rotation == 270:
        return image.transpose(Image.Transpose.ROTATE_270)
    return image


class _Walker:
    """Collects every rewrite in memory; nothing is written to the document until commit()."""

    def __init__(self, pdf):
        self.pdf = pdf
        self.visited: set = set()
        self.pending_streams: list[tuple[object, bytes]] = []
        self.pending_pages: list[tuple[object, bytes]] = []
        self.pending_images: list[tuple[object, bytes, str]] = []
        self.pending_groups: list[object] = []

    # -- entry points -----------------------------------------------------

    def convert_page(self, page, resources, depth: int = 0):
        instructions = pikepdf.parse_content_stream(page)
        rewritten = self._rewrite(instructions, resources, _ColourState("gray"), depth)
        self.pending_pages.append((page.obj, pikepdf.unparse_content_stream(rewritten)))
        self._walk_resources(resources, depth + 1)

    def convert_annotation(self, annotation):
        appearance = annotation.get("/AP")
        if appearance is None:
            return
        for key in ("/N", "/D", "/R"):
            node = appearance.get(key)
            if node is None:
                continue
            if isinstance(node, pikepdf.Stream) or "/Subtype" in node:
                self._convert_form(node, None)
            else:
                for state in node.values():
                    if isinstance(state, pikepdf.Stream):
                        self._convert_form(state, None)

    def commit(self):
        for stream, data in self.pending_streams:
            stream.write(data, filter=None)
        for page_obj, data in self.pending_pages:
            page_obj.Contents = self.pdf.make_stream(data)
        for image, data, filter_name in self.pending_images:
            if filter_name == "DCTDecode":
                image.write(data, filter=pikepdf.Name.DCTDecode)
            else:
                image.write(data, filter=pikepdf.Name.FlateDecode)
            for key in ("/Decode", "/DecodeParms"):
                if key in image:
                    del image[key]
            image.ColorSpace = pikepdf.Name.DeviceGray
            image.BitsPerComponent = 8
        for group in self.pending_groups:
            group.CS = pikepdf.Name.DeviceGray

    # -- resources ------------------------------------------------------------

    def _walk_resources(self, resources, depth: int):
        if resources is None or depth > _RESOURCE_DEPTH:
            return
        if "/Pattern" in resources and len(resources["/Pattern"]) > 0:
            raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
        if "/Shading" in resources and len(resources["/Shading"]) > 0:
            raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
        for stream in (resources.get("/XObject") or {}).values():
            self._convert_xobject(stream, resources, depth)
        for font in (resources.get("/Font") or {}).values():
            if font.get("/Subtype") == pikepdf.Name.Type3:
                font_resources = inherited_value(font, "/Resources") or resources
                for proc in (font.get("/CharProcs") or {}).values():
                    if isinstance(proc, pikepdf.Stream) and proc.objgen not in self.visited:
                        self.visited.add(proc.objgen)
                        self._convert_stream_content(proc, font_resources, _ColourState("unknown"), depth + 1)
        for state in (resources.get("/ExtGState") or {}).values():
            smask = state.get("/SMask")
            if isinstance(smask, pikepdf.Dictionary) and isinstance(smask.get("/G"), pikepdf.Stream):
                self._convert_form(smask.G, resources, depth + 1)

    def _convert_xobject(self, stream, resources, depth: int):
        if stream.get("/Subtype") == pikepdf.Name.Form:
            # _convert_form owns the visited bookkeeping for forms.
            self._convert_form(stream, resources, depth + 1)
        elif stream.get("/Subtype") == pikepdf.Name.Image:
            if stream.objgen in self.visited:
                return
            self.visited.add(stream.objgen)
            self._convert_image(stream, resources)

    def _convert_form(self, stream, parent_resources, depth: int = 1):
        key = stream.objgen
        if key != (0, 0):
            if key in self.visited:
                return
            self.visited.add(key)
        group = stream.get("/Group")
        if isinstance(group, pikepdf.Dictionary) and "/CS" in group:
            kind = self._classify(group["/CS"], parent_resources)[0]
            if kind in ("rgb", "cmyk"):
                self.pending_groups.append(group)
            elif kind != "gray":
                raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
        resources = stream.get("/Resources") or parent_resources
        self._convert_stream_content(stream, resources, _ColourState("unknown"), depth)
        self._walk_resources(resources, depth + 1)

    def _convert_stream_content(self, stream, resources, state, depth: int):
        instructions = pikepdf.parse_content_stream(stream)
        rewritten = self._rewrite(instructions, resources, state, depth)
        self.pending_streams.append((stream, pikepdf.unparse_content_stream(rewritten)))

    # -- images -----------------------------------------------------------------

    def _convert_image(self, image, resources):
        if image.get("/ImageMask"):
            return
        filters = image.get("/Filter")
        names = [str(f) for f in filters] if isinstance(filters, pikepdf.Array) else (
            [str(filters)] if filters is not None else [])
        if "/JPXDecode" in names or "/JBIG2Decode" in names:
            raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
        if isinstance(image.get("/Mask"), pikepdf.Array):
            # Colour-key masks hold values in the source space; they cannot be carried over to gray exactly.
            raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
        colour = image.get("/ColorSpace")
        if colour is None:
            return
        kind, _ = self._classify(colour, resources)
        if kind == "gray":
            return
        if int(image.get("/Width", 0)) * int(image.get("/Height", 0)) > _MAX_IMAGE_PIXELS:
            raise GrayscaleLimitError("An embedded image is too large to convert.")
        try:
            pil = pikepdf.PdfImage(image).as_pil_image()
        except Exception as error:
            raise ValueError("An embedded image could not be decoded.") from error
        if pil.mode not in ("L",):
            pil = pil.convert("RGB").convert("L")
        if "/DCTDecode" in names:
            buffer = io.BytesIO()
            pil.save(buffer, format="JPEG", quality=_DCT_QUALITY)
            self.pending_images.append((image, buffer.getvalue(), "DCTDecode"))
        else:
            self.pending_images.append((image, zlib.compress(pil.tobytes()), "FlateDecode"))

    # -- classification ---------------------------------------------------------

    def _classify(self, space, resources):
        """Return (kind, palette) where kind is gray, rgb, cmyk, indexed or refused."""
        if isinstance(space, pikepdf.Name):
            name = str(space)
            if name in _GRAY_SPACES:
                return "gray", None
            if name in _RGB_SPACES:
                return "rgb", None
            if name in _CMYK_SPACES:
                return "cmyk", None
            colour_spaces = (resources or {}).get("/ColorSpace") if resources is not None else None
            if colour_spaces is not None and name in colour_spaces:
                return self._classify(colour_spaces[name], None)
            raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
        if isinstance(space, pikepdf.Array) and len(space) >= 1:
            family = str(space[0])
            if family == "/ICCBased":
                components = int(space[1].get("/N", 0))
                if components == 1:
                    return "gray", None
                if components == 3:
                    return "rgb", None
                if components == 4:
                    return "cmyk", None
                raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
            if family in ("/CalRGB",):
                return "rgb", None
            if family in ("/CalGray",):
                return "gray", None
            if family in ("/Indexed", "/I"):
                base_kind, _ = self._classify(space[1], resources)
                if base_kind not in ("rgb", "cmyk", "gray"):
                    raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
                lookup = space[3]
                palette = bytes(lookup) if isinstance(lookup, pikepdf.String) else lookup.read_bytes()
                return "indexed", (base_kind, palette)
            raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
        raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)

    # -- content rewriting ------------------------------------------------------

    def _rewrite(self, instructions, resources, state, depth: int):
        fill = state
        stroke = _ColourState(state.kind, state.palette)
        output = []
        for instruction in instructions:
            operator = str(instruction.operator)
            operands = list(instruction.operands)
            if operator == "INLINE IMAGE":
                colour = operands[0].obj.get("/ColorSpace")
                if colour is not None:
                    kind, _ = self._classify(colour, resources)
                    if kind != "gray":
                        raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
                output.append(instruction)
                continue
            if operator == "sh":
                raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
            if operator in ("cs", "CS"):
                kind, palette = self._classify(operands[0], resources)
                target = fill if operator == "cs" else stroke
                if kind == "gray":
                    target.kind, target.palette = "gray", None
                    output.append(instruction)
                else:
                    target.kind = kind
                    target.palette = palette
                    output.append(pikepdf.ContentStreamInstruction(
                        [pikepdf.Name.DeviceGray], pikepdf.Operator(operator)))
                continue
            if operator in ("sc", "scn", "SC", "SCN"):
                target = fill if operator in ("sc", "scn") else stroke
                if any(isinstance(operand, pikepdf.Name) for operand in operands):
                    raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
                gray = self._gray_for(target, operands)
                output.append(pikepdf.ContentStreamInstruction([gray], pikepdf.Operator(operator)))
                continue
            if operator in ("rg", "RG", "k", "K"):
                if operator in ("rg", "RG"):
                    values = [_clamp(v) for v in operands[:3]]
                    gray = _luma(*values)
                else:
                    values = [_clamp(v) for v in operands[:4]]
                    gray = _cmyk_to_gray(*values)
                target = fill if operator in ("rg", "k") else stroke
                target.kind, target.palette = "gray", None
                output.append(pikepdf.ContentStreamInstruction(
                    [round(gray, 6)], pikepdf.Operator("g" if operator in ("rg", "k") else "G")))
                continue
            output.append(instruction)
        return output

    @staticmethod
    def _gray_for(target: _ColourState, operands):
        if target.kind == "gray" and len(operands) == 1:
            return operands[0]
        if target.kind == "rgb" and len(operands) == 3:
            return round(_luma(*(_clamp(v) for v in operands)), 6)
        if target.kind == "cmyk" and len(operands) == 4:
            return round(_cmyk_to_gray(*(_clamp(v) for v in operands)), 6)
        if target.kind == "indexed" and len(operands) == 1 and target.palette is not None:
            base_kind, palette = target.palette
            components = 3 if base_kind == "rgb" else (4 if base_kind == "cmyk" else 1)
            index = int(operands[0])
            start = index * components
            entry = palette[start:start + components]
            if len(entry) != components:
                raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
            values = [b / 255.0 for b in entry]
            if base_kind == "rgb":
                return round(_luma(*values), 6)
            if base_kind == "cmyk":
                return round(_cmyk_to_gray(*values), 6)
            return round(values[0], 6)
        raise GrayscaleRefusedError(GRAYSCALE_REFUSAL_MESSAGE)
