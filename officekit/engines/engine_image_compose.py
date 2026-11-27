"""Composition engines for the image slice: collage, contact sheets and icon packs.

These engines reuse the bounded loader and budget from ``engine_image_tools``.
Output carries no EXIF, and every output is bounded by the shared encoder buffer.
"""

from __future__ import annotations

import io
import math
import sys
import unicodedata
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image, ImageDraw, ImageFont, ImageOps

from officekit.engines.engine_file_converter import FileConverterEngine, ImageWorkLimitError, _BoundedImageBuffer
from officekit.engines.engine_image_tools import (
    MAX_SIDE,
    ImageToolInputError,
    _check_geometry,
    _hex_rgb,
    _invalid_operation,
    _open_source,
    _reserve,
    decoding,
)
from officekit.engines.engine_similar_images import SimilarImagePixelBudget

COLLAGE_MIN_IMAGES = 2
COLLAGE_MAX_IMAGES = 50
COLLAGE_MAX_AREA = 40_000_000
CONTACT_SHEET_MAX_FILES = 200
CONTACT_SHEET_DPI = 150
CONTACT_SHEET_FONT_PATH = "assets/fonts/NotoSans-Regular.ttf"
CONTACT_SHEET_FONT_SIZE = 22
CONTACT_SHEET_MARGIN_RATIO = 0.04
CONTACT_SHEET_GAP_RATIO = 0.012
CONTACT_SHEET_NAME_CHARACTERS = 200
# The PDF writer holds every page bitmap at once; this ceiling refuses sheets whose summed pages exceed it.
CONTACT_SHEET_RETAINED_PAGE_BYTES = 256 * 1024 * 1024
ELLIPSIS = "…"
PAGE_SIZES_INCHES = {"a4": (210 / 25.4, 297 / 25.4), "letter": (8.5, 11.0)}
PLATFORMS = ("web", "windows", "macos")
ICON_FITS = ("pad", "crop")

WEB_PNG_SIZES = (
    ("web/favicon-16x16.png", 16),
    ("web/favicon-32x32.png", 32),
    ("web/android-chrome-192x192.png", 192),
    ("web/android-chrome-512x512.png", 512),
)
WEB_ICO_NAME = "web/favicon.ico"
WEB_ICO_SIZES = (16, 32, 48)
APPLE_TOUCH_NAME = "web/apple-touch-icon.png"
APPLE_TOUCH_SIZE = 180
WINDOWS_ICO_NAME = "windows/app.ico"
WINDOWS_ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
MACOS_ICONSET = (
    (16, "16x16"), (32, "16x16@2x"), (32, "32x32"), (64, "32x32@2x"),
    (128, "128x128"), (256, "128x128@2x"), (256, "256x256"), (512, "256x256@2x"),
    (512, "512x512"), (1024, "512x512@2x"),
)
MEDIA_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "PDF": "application/pdf", "ZIP": "application/zip"}


@dataclass(frozen=True)
class CollageLayout:
    columns: int
    cell_width: int
    cell_height: int
    fit: str
    gap: int
    padding: int
    background: str
    format: str


@dataclass(frozen=True)
class ContactSheetLayout:
    page: str
    orientation: str
    columns: int
    rows: int
    show_names: bool
    format: str


def clean_name(name: str) -> str:
    """NFC-normalise a file name, drop control characters, and cap its length."""
    normalised = unicodedata.normalize("NFC", name)
    cleaned = "".join(character for character in normalised if unicodedata.category(character) != "Cc")
    return cleaned.strip()[:CONTACT_SHEET_NAME_CHARACTERS] or "image"


def truncate_middle(text: str, max_width: float, measure: Callable[[str], float]) -> str:
    """Keep the head and tail of a label and join them with an ellipsis that fits the width."""
    if measure(text) <= max_width:
        return text
    for keep in range(len(text) - 1, 0, -1):
        head = (keep + 1) // 2
        tail = keep // 2
        candidate = text[:head] + ELLIPSIS + (text[len(text) - tail:] if tail else "")
        if measure(candidate) <= max_width:
            return candidate
    return ELLIPSIS


def _font_candidates() -> list[Path]:
    """Bundled sidecar copy first (PyInstaller), then the repo asset for development runs."""
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "fonts" / Path(CONTACT_SHEET_FONT_PATH).name)
    candidates.append(Path(__file__).resolve().parents[2] / CONTACT_SHEET_FONT_PATH)
    return candidates


def _label_font(size: int):
    for path in _font_candidates():
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except (TypeError, OSError):
        return ImageFont.load_default()


def _to_rgba(frame: Image.Image) -> Image.Image:
    return frame.convert("RGBA")


def _first_frame(content: bytes, budget: SimilarImagePixelBudget) -> Image.Image:
    """Decode frame 0 after the header checks, with EXIF orientation applied."""
    with _open_source(content) as source:
        _check_geometry(source.width, source.height, 0)
        _reserve(budget, source.width * source.height)
        with decoding():
            source.load()
            return _to_rgba(ImageOps.exif_transpose(source))


def _thumbnail(content: bytes, box: tuple[int, int], budget: SimilarImagePixelBudget) -> Image.Image:
    """Decode a contact-sheet thumbnail that fits its cell box; JPEG is reduced by draft() first."""
    with _open_source(content) as source:
        _check_geometry(source.width, source.height, 0)
        with decoding():
            if source.format == "JPEG":
                source.draft("RGB", box)
            source.load()
            _reserve(budget, source.width * source.height)
            frame = _to_rgba(ImageOps.exif_transpose(source))
    frame.thumbnail(box, Image.Resampling.LANCZOS)
    return frame


def _encode_bounded(image: Image.Image, image_format: str, **options) -> bytes:
    output = _BoundedImageBuffer(FileConverterEngine.MAX_RESIZE_OUTPUT_BYTES)
    image.save(output, format=image_format, **options)
    return output.getvalue()


def _fit_tile(frame: Image.Image, width: int, height: int, fit: str) -> tuple[Image.Image, tuple[int, int]]:
    """Return the tile and its offset inside the cell; ``contain`` centres, ``cover`` crops."""
    if fit == "cover":
        # Crop the source to the cell's aspect ratio first, then resize that crop once to the
        # cell. The intermediate can never exceed the cell, however elongated the source is.
        if frame.width * height > frame.height * width:
            crop_height = frame.height
            crop_width = max(1, min(frame.width, round(frame.height * width / height)))
        else:
            crop_width = frame.width
            crop_height = max(1, min(frame.height, round(frame.width * height / width)))
        left = (frame.width - crop_width) // 2
        top = (frame.height - crop_height) // 2
        cropped = frame.crop((left, top, left + crop_width, top + crop_height))
        tile = cropped if cropped.size == (width, height) else cropped.resize((width, height), Image.Resampling.LANCZOS)
        return tile, (0, 0)
    scale = min(width / frame.width, height / frame.height)
    fitted_size = (max(1, round(frame.width * scale)), max(1, round(frame.height * scale)))
    fitted = frame if fitted_size == frame.size else frame.resize(fitted_size, Image.Resampling.LANCZOS)
    return fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2)


def _square(frame: Image.Image, fit: str) -> Image.Image:
    width, height = frame.size
    if fit == "pad":
        side = max(width, height)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(frame, ((side - width) // 2, (side - height) // 2))
        return canvas
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return frame.crop((left, top, left + side, top + side))


class ImageComposeEngine:
    @staticmethod
    def collage_canvas(count: int, layout: CollageLayout) -> tuple[int, int]:
        """Exact canvas from the layout, checked before any image is decoded."""
        if type(count) is not int or not COLLAGE_MIN_IMAGES <= count <= COLLAGE_MAX_IMAGES:
            raise _invalid_operation()
        if type(layout.columns) is not int or not 1 <= layout.columns <= 10:
            raise _invalid_operation()
        rows = math.ceil(count / layout.columns)
        width = 2 * layout.padding + layout.columns * layout.cell_width + (layout.columns - 1) * layout.gap
        height = 2 * layout.padding + rows * layout.cell_height + (rows - 1) * layout.gap
        if width > MAX_SIDE or height > MAX_SIDE or width * height > COLLAGE_MAX_AREA:
            raise ImageToolInputError("CANVAS_TOO_LARGE")
        return width, height

    @staticmethod
    def build_collage(
        images: Sequence[bytes], layout: CollageLayout, preview_max_edge: int | None = None,
    ) -> tuple[bytes, str, tuple[int, int]]:
        """Compose images in upload order. A preview scales every layout dimension by one factor."""
        full_width, full_height = ImageComposeEngine.collage_canvas(len(images), layout)
        working = layout
        if preview_max_edge is not None and max(full_width, full_height) > preview_max_edge:
            factor = preview_max_edge / max(full_width, full_height)
            working = replace(
                layout,
                cell_width=max(1, round(layout.cell_width * factor)),
                cell_height=max(1, round(layout.cell_height * factor)),
                gap=round(layout.gap * factor),
                padding=round(layout.padding * factor),
            )
        width, height = ImageComposeEngine.collage_canvas(len(images), working)
        background = (0, 0, 0, 0) if working.background == "transparent" else (*_hex_rgb(working.background), 255)
        canvas = Image.new("RGBA", (width, height), background)
        budget = SimilarImagePixelBudget(FileConverterEngine.MAX_RESIZE_BATCH_TOTAL_PIXELS)
        for index, content in enumerate(images):
            frame = _first_frame(content, budget)
            column = index % working.columns
            row = index // working.columns
            cell_x = working.padding + column * (working.cell_width + working.gap)
            cell_y = working.padding + row * (working.cell_height + working.gap)
            tile, (offset_x, offset_y) = _fit_tile(frame, working.cell_width, working.cell_height, working.fit)
            canvas.alpha_composite(tile, (cell_x + offset_x, cell_y + offset_y))

        if preview_max_edge is not None and max(full_width, full_height) > preview_max_edge:
            image_format = "PNG"
        else:
            image_format = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}[working.format]
        if image_format == "JPEG":
            flat = Image.new("RGB", canvas.size, background[:3] if background[3] else (255, 255, 255))
            flat.paste(canvas, mask=canvas.getchannel("A"))
            canvas = flat
        return _encode_bounded(canvas, image_format), MEDIA_TYPES[image_format], (width, height)

    @staticmethod
    def build_contact_sheet(
        files: Sequence[tuple[str, bytes]], sheet: ContactSheetLayout, first_page_only: bool = False,
    ) -> tuple[bytes, str, int]:
        """Paged thumbnail grid as a PDF or a ZIP of PNG pages. Returns (bytes, media type, pages).

        ``first_page_only`` returns page 1 as one PNG for the preview; the page count still covers every page.
        """
        if not 1 <= len(files) <= CONTACT_SHEET_MAX_FILES:
            raise _invalid_operation()
        if sheet.page not in PAGE_SIZES_INCHES or sheet.orientation not in {"portrait", "landscape"}:
            raise _invalid_operation()
        if type(sheet.columns) is not int or not 1 <= sheet.columns <= 10:
            raise _invalid_operation()
        if type(sheet.rows) is not int or not 1 <= sheet.rows <= 20:
            raise _invalid_operation()
        page_width_in, page_height_in = PAGE_SIZES_INCHES[sheet.page]
        page_width = round(page_width_in * CONTACT_SHEET_DPI)
        page_height = round(page_height_in * CONTACT_SHEET_DPI)
        if sheet.orientation == "landscape":
            page_width, page_height = page_height, page_width
        short_edge = min(page_width, page_height)
        margin = round(short_edge * CONTACT_SHEET_MARGIN_RATIO)
        gap = round(short_edge * CONTACT_SHEET_GAP_RATIO)
        cell_width = (page_width - 2 * margin - (sheet.columns - 1) * gap) // sheet.columns
        label_height = CONTACT_SHEET_FONT_SIZE + 10 if sheet.show_names else 0
        cell_height = (page_height - 2 * margin - (sheet.rows - 1) * gap) // sheet.rows
        thumb_height = cell_height - label_height
        if cell_width < 8 or thumb_height < 8:
            raise _invalid_operation()

        budget = SimilarImagePixelBudget(FileConverterEngine.MAX_RESIZE_BATCH_TOTAL_PIXELS)
        labelled = [(clean_name(name), content) for name, content in files]
        font = _label_font(CONTACT_SHEET_FONT_SIZE) if sheet.show_names else None
        capacity = sheet.columns * sheet.rows
        page_count = math.ceil(len(labelled) / capacity)
        if sheet.format == "pdf" and not first_page_only and page_count * page_width * page_height * 3 > CONTACT_SHEET_RETAINED_PAGE_BYTES:
            # The PDF writer needs every page at once; refuse before any page is drawn.
            raise ImageWorkLimitError()

        def render_page(chunk: Sequence[tuple[str, bytes]]) -> Image.Image:
            # Thumbnails are decoded one page at a time and sized to their cell, so none are retained.
            page = Image.new("RGB", (page_width, page_height), (255, 255, 255))
            draw = ImageDraw.Draw(page)
            for slot, (label, content) in enumerate(chunk):
                thumb = _thumbnail(content, (cell_width, thumb_height), budget)
                column = slot % sheet.columns
                row = slot // sheet.columns
                cell_x = margin + column * (cell_width + gap)
                cell_y = margin + row * (cell_height + gap)
                offset_x = cell_x + (cell_width - thumb.width) // 2
                offset_y = cell_y + (thumb_height - thumb.height) // 2
                page.paste(thumb, (offset_x, offset_y), thumb.getchannel("A"))
                if font is not None:
                    text = truncate_middle(label, cell_width, font.getlength)
                    draw.text((cell_x + cell_width // 2, cell_y + thumb_height + 4), text, fill=(0, 0, 0), font=font, anchor="mt")
            return page

        chunks = [labelled[start:start + capacity] for start in range(0, len(labelled), capacity)]
        if first_page_only:
            return _encode_bounded(render_page(chunks[0]), "PNG"), MEDIA_TYPES["PNG"], len(chunks)
        if sheet.format == "pdf":
            pages = [render_page(chunk) for chunk in chunks]
            output = _BoundedImageBuffer(FileConverterEngine.MAX_RESIZE_OUTPUT_BYTES)
            pages[0].save(output, format="PDF", resolution=float(CONTACT_SHEET_DPI), save_all=True, append_images=pages[1:])
            return output.getvalue(), MEDIA_TYPES["PDF"], len(pages)
        archive_output = _BoundedImageBuffer(FileConverterEngine.MAX_RESIZE_OUTPUT_BYTES)
        with zipfile.ZipFile(archive_output, "w", compression=zipfile.ZIP_STORED) as archive:
            for number, chunk in enumerate(chunks, start=1):
                archive.writestr(f"contact-sheet-{number:03d}.png", _encode_bounded(render_page(chunk), "PNG"))
        return archive_output.getvalue(), MEDIA_TYPES["ZIP"], len(chunks)

    @staticmethod
    def build_icon_pack(content: bytes, platforms: Sequence[str], fit: str = "pad") -> tuple[bytes, list[int]]:
        """Web, Windows and macOS icon sets in one ZIP. Returns (zip bytes, upscaled sizes)."""
        if fit not in ICON_FITS:
            raise _invalid_operation()
        if not isinstance(platforms, (list, tuple)) or not 1 <= len(platforms) <= len(PLATFORMS):
            raise _invalid_operation()
        if len(set(platforms)) != len(platforms) or any(platform not in PLATFORMS for platform in platforms):
            raise _invalid_operation()

        budget = SimilarImagePixelBudget(FileConverterEngine.MAX_RESIZE_BATCH_TOTAL_PIXELS)
        square = _square(_first_frame(content, budget), fit)
        base = square.width

        def master_for(sizes: Sequence[int]) -> Image.Image:
            largest = max(sizes)
            return square if largest <= base else square.resize((largest, largest), Image.Resampling.LANCZOS)

        def scaled(size: int) -> Image.Image:
            if size == base:
                return square
            return square.resize((size, size), Image.Resampling.LANCZOS)

        def ico_bytes(sizes: Sequence[int]) -> bytes:
            output = io.BytesIO()
            master_for(sizes).save(output, format="ICO", sizes=[(size, size) for size in sizes])
            return output.getvalue()

        entries: list[tuple[str, bytes]] = []
        produced_sizes: set[int] = set()
        if "web" in platforms:
            for name, size in WEB_PNG_SIZES:
                entries.append((name, _encode_bounded(scaled(size), "PNG")))
                produced_sizes.add(size)
            touch = Image.new("RGBA", (APPLE_TOUCH_SIZE, APPLE_TOUCH_SIZE), (255, 255, 255, 255))
            touch.alpha_composite(scaled(APPLE_TOUCH_SIZE))
            entries.append((APPLE_TOUCH_NAME, _encode_bounded(touch.convert("RGB"), "PNG")))
            produced_sizes.add(APPLE_TOUCH_SIZE)
            entries.append((WEB_ICO_NAME, ico_bytes(WEB_ICO_SIZES)))
            produced_sizes.update(WEB_ICO_SIZES)
        if "windows" in platforms:
            entries.append((WINDOWS_ICO_NAME, ico_bytes(WINDOWS_ICO_SIZES)))
            produced_sizes.update(WINDOWS_ICO_SIZES)
        if "macos" in platforms:
            for size, label in MACOS_ICONSET:
                entries.append((f"macos/icon.iconset/icon_{label}.png", _encode_bounded(scaled(size), "PNG")))
                produced_sizes.add(size)

        archive_output = _BoundedImageBuffer(FileConverterEngine.MAX_RESIZE_OUTPUT_BYTES)
        with zipfile.ZipFile(archive_output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in entries:
                archive.writestr(name, data)
        upscaled = sorted(size for size in produced_sizes if size > base)
        return archive_output.getvalue(), upscaled
