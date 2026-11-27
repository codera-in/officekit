"""Bounded local screenshot editing for selected image bytes."""

from __future__ import annotations

import io
import json
import math
import re
from typing import Any


class ScreenshotEditError(ValueError):
    """An image or requested edit cannot be applied safely."""

    public_message = "The image or edit request is invalid. Check the image and selected regions."

    def __str__(self) -> str:
        return self.public_message


class ScreenshotOutputLimitError(ScreenshotEditError):
    """The encoded image exceeded its bounded output budget."""

    public_message = "Edited PNG exceeds the 64 MiB output limit."

    def __init__(self, target_format: str = "png"):
        self.public_message = (
            "Edited JPEG exceeds the 64 MiB output limit."
            if target_format == "jpeg"
            else type(self).public_message
        )


class BoundedImageBuffer(io.BytesIO):
    """An in-memory image target that rejects bytes before the cap is crossed."""

    def __init__(self, max_bytes: int, target_format: str = "png"):
        super().__init__()
        self.max_bytes = max_bytes
        self.target_format = target_format

    def write(self, data: bytes) -> int:
        if self.tell() + len(data) > self.max_bytes:
            raise ScreenshotOutputLimitError(self.target_format)
        return super().write(data)

    def truncate(self, size: int | None = None) -> int:
        target = self.tell() if size is None else size
        if target > self.max_bytes:
            raise ScreenshotOutputLimitError(self.target_format)
        return super().truncate(size)


BoundedPngBuffer = BoundedImageBuffer


class ScreenshotEditorEngine:
    MAX_INPUT_BYTES = 64 * 1024 * 1024
    MAX_OUTPUT_BYTES = 64 * 1024 * 1024
    MAX_PIXELS = 40_000_000
    MAX_OPERATION_PIXELS = 60_000_000
    MAX_OPERATION_JSON_BYTES = 32_768
    MAX_DIMENSION = 40_000
    MAX_OPERATIONS = 50
    MAX_BLUR_RADIUS = 100
    MAX_PIXEL_BLOCK_SIZE = 64
    FIXED_BLUR_RADIUS = 24
    MAX_PATH_POINTS = 512
    MAX_TOTAL_POINTS = 1024
    _MASK_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

    @classmethod
    def parse_operations_json(cls, value: Any) -> list[Any]:
        if not isinstance(value, str):
            raise ScreenshotEditError()
        try:
            if len(value.encode("utf-8")) > cls.MAX_OPERATION_JSON_BYTES:
                raise ScreenshotEditError()
        except UnicodeEncodeError as error:
            raise ScreenshotEditError() from error
        try:
            operations = json.loads(value)
        except (json.JSONDecodeError, RecursionError, UnicodeError) as error:
            raise ScreenshotEditError() from error
        if (
            not isinstance(operations, list)
            or not 1 <= len(operations) <= cls.MAX_OPERATIONS
            or any(not isinstance(operation, dict) for operation in operations)
        ):
            raise ScreenshotEditError()
        return operations

    @classmethod
    def validate_operations(cls, operations: Any, image_size: tuple[int, int]) -> list[dict[str, Any]]:
        if (
            not isinstance(image_size, tuple)
            or len(image_size) != 2
            or any(type(value) is not int or value <= 0 or value > cls.MAX_DIMENSION for value in image_size)
            or image_size[0] * image_size[1] > cls.MAX_PIXELS
        ):
            raise ScreenshotEditError()
        if (
            not isinstance(operations, list)
            or not 1 <= len(operations) <= cls.MAX_OPERATIONS
        ):
            raise ScreenshotEditError()

        canvas_width, canvas_height = image_size
        validated: list[dict[str, Any]] = []
        processed_pixels = 0
        total_points = 0
        for operation in operations:
            if not isinstance(operation, dict):
                raise ScreenshotEditError()
            action = operation.get("type")
            allowed_fields = {
                "crop": {"type", "x", "y", "width", "height"},
                "blur": {"type", "x", "y", "width", "height", "radius"},
                "pixelate": {"type", "x", "y", "width", "height", "block_size"},
                "mask": {"type", "x", "y", "width", "height", "color"},
                "rectangle": {"type", "x", "y", "width", "height", "color"},
                "rounded_rectangle": {"type", "x", "y", "width", "height", "color"},
                "highlight": {"type", "x", "y", "width", "height", "color"},
                "circle": {"type", "x", "y", "width", "height", "color"},
                "text": {"type", "x", "y", "width", "height", "color", "text"},
                "line": {"type", "x", "y", "width", "height", "color", "points"},
                "arrow": {"type", "x", "y", "width", "height", "color", "points"},
                "freehand": {"type", "x", "y", "width", "height", "color", "points"},
                "stamp": {"type", "stamp", "x", "y", "width", "height", "points"},
                "rotate": {"type"},
            }.get(action)
            if action == "rotate":
                if set(operation) != {"type"}:
                    raise ScreenshotEditError()
                processed_pixels += canvas_width * canvas_height
                if processed_pixels > cls.MAX_OPERATION_PIXELS:
                    raise ScreenshotEditError()
                validated.append({"type": "rotate"})
                canvas_width, canvas_height = canvas_height, canvas_width
                continue
            if allowed_fields is not None and action in (
                "rectangle", "rounded_rectangle", "highlight", "circle", "text", "line", "arrow", "freehand"
            ):
                allowed_fields |= {"outer_color", "stroke_width", "outer_width"}
                if action == "text":
                    allowed_fields |= {"font_size"}
            required_fields = {"type", "x", "y", "width", "height"}
            if (
                allowed_fields is None
                or set(operation) - allowed_fields
                or required_fields - set(operation)
            ):
                raise ScreenshotEditError()

            x, y, width, height = (operation.get(key) for key in ("x", "y", "width", "height"))
            if (
                any(type(value) is not int for value in (x, y, width, height))
                or x < 0
                or y < 0
                or width <= 0
                or height <= 0
                or width > cls.MAX_DIMENSION
                or height > cls.MAX_DIMENSION
                or x + width > canvas_width
                or y + height > canvas_height
            ):
                raise ScreenshotEditError()
            processed_pixels += width * height
            if processed_pixels > cls.MAX_OPERATION_PIXELS:
                raise ScreenshotEditError()

            normalized = dict(operation)
            if action == "blur":
                radius = operation.get("radius", cls.FIXED_BLUR_RADIUS)
                if type(radius) is not int or not 1 <= radius <= cls.MAX_BLUR_RADIUS:
                    raise ScreenshotEditError()
                normalized["radius"] = radius
            elif action == "pixelate":
                block_size = operation.get("block_size", 12)
                if type(block_size) is not int or not 2 <= block_size <= cls.MAX_PIXEL_BLOCK_SIZE:
                    raise ScreenshotEditError()
                normalized["block_size"] = block_size
            elif action == "stamp":
                stamp = operation.get("stamp")
                if not isinstance(stamp, str) or stamp not in ("check", "question", "x", "alert", "heart"):
                    raise ScreenshotEditError()
                points = operation.get("points")
                if not isinstance(points, list) or len(points) != 2:
                    raise ScreenshotEditError()
                for point in points:
                    if (not isinstance(point, list) or len(point) != 2
                        or any(type(value) is not int for value in point)
                        or not x <= point[0] < x + width or not y <= point[1] < y + height):
                        raise ScreenshotEditError()
                if points[0] == points[1]:
                    raise ScreenshotEditError()
                total_points += len(points)
                if total_points > cls.MAX_TOTAL_POINTS:
                    raise ScreenshotEditError()
            elif action in (
                "mask", "rectangle", "rounded_rectangle", "highlight", "circle", "text", "line", "arrow", "freehand"
            ):
                color = operation.get("color", "#000000")
                if not isinstance(color, str) or not cls._MASK_COLOR.fullmatch(color):
                    raise ScreenshotEditError()
                normalized["color"] = color.upper()
                if action != "mask":
                    for field, default in (("stroke_width", 3), ("outer_width", 2)):
                        value = operation.get(field, default)
                        if type(value) is not int or not 1 <= value <= 32:
                            raise ScreenshotEditError()
                        normalized[field] = value
                    if "outer_color" in operation:
                        outer = operation["outer_color"]
                        if not isinstance(outer, str) or not cls._MASK_COLOR.fullmatch(outer):
                            raise ScreenshotEditError()
                        normalized["outer_color"] = outer.upper()
                if action in ("line", "arrow", "freehand"):
                    points = operation.get("points")
                    if not isinstance(points, list) or not 2 <= len(points) <= (2 if action in ("line", "arrow") else cls.MAX_PATH_POINTS):
                        raise ScreenshotEditError()
                    for point in points:
                        if (not isinstance(point, list) or len(point) != 2
                            or any(type(value) is not int for value in point)
                            or not x <= point[0] < x + width or not y <= point[1] < y + height):
                            raise ScreenshotEditError()
                    total_points += len(points)
                    if total_points > cls.MAX_TOTAL_POINTS:
                        raise ScreenshotEditError()
                    if action in ("line", "arrow") and points[0] == points[1]:
                        raise ScreenshotEditError()
                if action == "text":
                    font_size = operation.get("font_size", 24)
                    if type(font_size) is not int or not 8 <= font_size <= 96:
                        raise ScreenshotEditError()
                    normalized["font_size"] = font_size
                    text = operation.get("text")
                    if not isinstance(text, str) or not text.strip() or len(text) > 200 or any(ord(character) < 32 for character in text):
                        raise ScreenshotEditError()
            validated.append(normalized)

            if action == "crop":
                canvas_width, canvas_height = width, height
        return validated

    @classmethod
    def edit_image(cls, image_bytes: bytes, operations: Any, target_format: str = "png") -> tuple[bytes, tuple[int, int]]:
        if (
            not isinstance(image_bytes, bytes)
            or not image_bytes
            or len(image_bytes) > cls.MAX_INPUT_BYTES
            or target_format not in ("png", "jpeg")
        ):
            raise ScreenshotEditError()
        try:
            from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, UnidentifiedImageError
        except ImportError as error:
            raise ScreenshotEditError() from error

        try:
            with Image.open(io.BytesIO(image_bytes)) as source:
                if (
                    source.width <= 0
                    or source.height <= 0
                    or source.width > cls.MAX_DIMENSION
                    or source.height > cls.MAX_DIMENSION
                    or source.width * source.height > cls.MAX_PIXELS
                ):
                    raise ScreenshotEditError()
                source.seek(0)
                image = ImageOps.exif_transpose(source.copy())
                if (
                    image.width > cls.MAX_DIMENSION
                    or image.height > cls.MAX_DIMENSION
                    or image.width * image.height > cls.MAX_PIXELS
                ):
                    raise ScreenshotEditError()
                image.load()

            has_transparency = (
                image.mode in ("RGBA", "LA")
                or (image.mode == "P" and "transparency" in image.info)
            )
            image = image.convert("RGBA" if has_transparency else "RGB")
            image.info.clear()
            validated = cls.validate_operations(operations, image.size)
            for operation in validated:
                if operation["type"] == "rotate":
                    image = image.rotate(-90, expand=True)
                    continue
                x, y, width, height = (operation[key] for key in ("x", "y", "width", "height"))
                box = (x, y, x + width, y + height)
                rgb = tuple(int(operation["color"][index:index + 2], 16) for index in (1, 3, 5)) if "color" in operation else (0, 0, 0)
                color = (*rgb, 255) if image.mode == "RGBA" else rgb
                if operation["type"] == "crop":
                    image = image.crop(box)
                elif operation["type"] == "blur":
                    region = image.crop(box).filter(ImageFilter.GaussianBlur(operation["radius"]))
                    image.paste(region, (x, y))
                elif operation["type"] == "pixelate":
                    region = image.crop(box)
                    small_size = (max(1, math.ceil(width / operation["block_size"])),
                                  max(1, math.ceil(height / operation["block_size"])))
                    region = region.resize(small_size, Image.Resampling.BOX).resize((width, height), Image.Resampling.NEAREST)
                    image.paste(region, (x, y))
                elif operation["type"] == "highlight":
                    region = image.crop(box).convert("RGBA")
                    overlay = Image.new("RGBA", region.size, (*rgb, 88))
                    region = Image.alpha_composite(region, overlay)
                    if "outer_color" in operation:
                        ImageDraw.Draw(region).rectangle((0, 0, width - 1, height - 1), outline=operation["outer_color"], width=operation["outer_width"])
                    image.paste(region if image.mode == "RGBA" else region.convert("RGB"), (x, y))
                else:
                    if operation["type"] == "text":
                        region = image.crop(box)
                        outline = operation.get("outer_color")
                        padding = int(operation.get("outer_width", 2)) if outline else 0
                        font_size = int(operation.get("font_size", 24))
                        ImageDraw.Draw(region).text((padding, padding), operation["text"], fill=color,
                            font=ImageFont.load_default(size=font_size), anchor="lt",
                            stroke_width=padding, stroke_fill=outline or color)
                        image.paste(region, (x, y))
                    else:
                        region = image.crop(box)
                        coords = (0, 0, width - 1, height - 1)
                        stroke = operation.get("stroke_width", 3)
                        outer = operation.get("outer_color")
                        if operation["type"] == "mask":
                            draw = ImageDraw.Draw(region)
                            draw.rectangle(coords, fill=color)
                            image.paste(region, (x, y))
                        else:
                            # 1) Base 1x raster pass (preserves exact test colors and centroid pixels)
                            base_draw = ImageDraw.Draw(region)
                            if operation["type"] == "stamp":
                                stamp_colors = {
                                    "check": (31, 166, 91), "question": (45, 115, 221), "x": (218, 48, 57),
                                    "alert": (238, 108, 44), "heart": (226, 67, 125),
                                }
                                stamp_color_rgb = stamp_colors[operation["stamp"]]
                                stamp_color = (*stamp_color_rgb, 255) if image.mode == "RGBA" else stamp_color_rgb
                                (anchor_x, anchor_y), (tip_x, tip_y) = [(px - x, py - y) for px, py in operation["points"]]
                                base_draw.line([(anchor_x, anchor_y), (tip_x, tip_y)], fill=stamp_color, width=4)
                                angle = math.atan2(tip_y - anchor_y, tip_x - anchor_x)
                                wings = [(tip_x - 8 * math.cos(angle + offset), tip_y - 8 * math.sin(angle + offset)) for offset in (-0.55, 0.55)]
                                base_draw.polygon([wings[0], (tip_x, tip_y), wings[1]], fill=stamp_color)
                                radius = 12
                                base_draw.ellipse((anchor_x - radius, anchor_y - radius, anchor_x + radius, anchor_y + radius),
                                                  fill=(255, 255, 255, 255) if image.mode == "RGBA" else (255, 255, 255), outline=stamp_color, width=3)
                                if operation["stamp"] == "check":
                                    base_draw.line([(anchor_x - 5, anchor_y), (anchor_x - 1, anchor_y + 4), (anchor_x + 6, anchor_y - 5)], fill=stamp_color, width=3)
                                elif operation["stamp"] == "x":
                                    base_draw.line([(anchor_x - 4, anchor_y - 4), (anchor_x + 4, anchor_y + 4)], fill=stamp_color, width=3)
                                    base_draw.line([(anchor_x + 4, anchor_y - 4), (anchor_x - 4, anchor_y + 4)], fill=stamp_color, width=3)
                                elif operation["stamp"] == "heart":
                                    base_draw.polygon([(anchor_x, anchor_y + 6), (anchor_x - 7, anchor_y - 1),
                                                       (anchor_x - 5, anchor_y - 6), (anchor_x, anchor_y - 3),
                                                       (anchor_x + 5, anchor_y - 6), (anchor_x + 7, anchor_y - 1)], fill=stamp_color)
                                else:
                                    glyph = "?" if operation["stamp"] == "question" else "!"
                                    base_draw.text((anchor_x, anchor_y), glyph, fill=stamp_color,
                                                   font=ImageFont.load_default(size=15), anchor="mm")
                            elif operation["type"] in ("line", "arrow", "freehand"):
                                points = [(px - x, py - y) for px, py in operation["points"]]
                                if operation["type"] == "arrow":
                                    start, end = points
                                    angle = math.atan2(end[1] - start[1], end[0] - start[0])
                                    length = min(math.dist(start, end) / 2, max(8, stroke * 4))
                                    wings = [(end[0] - length * math.cos(angle + offset), end[1] - length * math.sin(angle + offset)) for offset in (-0.5, 0.5)]
                                    paths = [points, [wings[0], end, wings[1]]]
                                else:
                                    paths = [points]
                                if outer:
                                    for path in paths:
                                        base_draw.line(path, fill=outer, width=stroke + 2 * operation["outer_width"], joint="curve")
                                for path in paths:
                                    base_draw.line(path, fill=color, width=stroke, joint="curve")
                            else:
                                if operation["type"] == "circle":
                                    shape = base_draw.ellipse
                                elif operation["type"] == "rounded_rectangle":
                                    shape = base_draw.rounded_rectangle
                                else:
                                    shape = base_draw.rectangle
                                shape_options = {"radius": min(12, width // 4, height // 4)} if operation["type"] == "rounded_rectangle" else {}
                                if outer:
                                    shape(coords, outline=outer, width=stroke + 2 * operation["outer_width"], **shape_options)
                                    inset = operation["outer_width"]
                                    if width > 2 * inset and height > 2 * inset:
                                        shape((inset, inset, width - 1 - inset, height - 1 - inset), outline=color, width=stroke, **shape_options)
                                else:
                                    shape(coords, outline=color, width=stroke, **shape_options)

                            # 2) Anti-aliasing overlay pass (smooths diagonal lines, curves, corners)
                            scale = 3
                            overlay = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
                            draw = ImageDraw.Draw(overlay)
                            s_coords = (0, 0, width * scale - 1, height * scale - 1)
                            s_stroke = stroke * scale
                            s_outer_width = operation.get("outer_width", 2) * scale
                            color_rgba = (*rgb, 255)
                            outer_rgba = (*tuple(int(outer[i:i+2], 16) for i in (1, 3, 5)), 255) if outer else None
                            if operation["type"] == "stamp":
                                (anchor_x, anchor_y), (tip_x, tip_y) = [
                                    (round((px - x) * scale), round((py - y) * scale)) for px, py in operation["points"]
                                ]
                                draw.line([(anchor_x, anchor_y), (tip_x, tip_y)], fill=stamp_color, width=4 * scale)
                                angle = math.atan2(tip_y - anchor_y, tip_x - anchor_x)
                                wings = [
                                    (tip_x - 8 * scale * math.cos(angle + offset), tip_y - 8 * scale * math.sin(angle + offset))
                                    for offset in (-0.55, 0.55)
                                ]
                                draw.polygon([wings[0], (tip_x, tip_y), wings[1]], fill=stamp_color)
                                radius = 12 * scale
                                draw.ellipse((anchor_x - radius, anchor_y - radius, anchor_x + radius, anchor_y + radius),
                                             fill=(255, 255, 255, 255), outline=stamp_color, width=3 * scale)
                                if operation["stamp"] == "check":
                                    draw.line([(anchor_x - 5 * scale, anchor_y), (anchor_x - 1 * scale, anchor_y + 4 * scale), (anchor_x + 6 * scale, anchor_y - 5 * scale)], fill=stamp_color, width=3 * scale)
                                elif operation["stamp"] == "x":
                                    draw.line([(anchor_x - 4 * scale, anchor_y - 4 * scale), (anchor_x + 4 * scale, anchor_y + 4 * scale)], fill=stamp_color, width=3 * scale)
                                    draw.line([(anchor_x + 4 * scale, anchor_y - 4 * scale), (anchor_x - 4 * scale, anchor_y + 4 * scale)], fill=stamp_color, width=3 * scale)
                                elif operation["stamp"] == "heart":
                                    draw.polygon([(anchor_x, anchor_y + 6 * scale), (anchor_x - 7 * scale, anchor_y - 1 * scale),
                                                  (anchor_x - 5 * scale, anchor_y - 6 * scale), (anchor_x, anchor_y - 3 * scale),
                                                  (anchor_x + 5 * scale, anchor_y - 6 * scale), (anchor_x + 7 * scale, anchor_y - 1 * scale)], fill=stamp_color)
                                else:
                                    glyph = "?" if operation["stamp"] == "question" else "!"
                                    draw.text((anchor_x, anchor_y), glyph, fill=stamp_color,
                                              font=ImageFont.load_default(size=15 * scale), anchor="mm")
                            elif operation["type"] in ("line", "arrow", "freehand"):
                                points = [(round((px - x) * scale), round((py - y) * scale)) for px, py in operation["points"]]
                                if operation["type"] == "arrow":
                                    start, end = points
                                    angle = math.atan2(end[1] - start[1], end[0] - start[0])
                                    length = min(math.dist(start, end) / 2, max(8 * scale, s_stroke * 4))
                                    wings = [(end[0] - length * math.cos(angle + offset), end[1] - length * math.sin(angle + offset)) for offset in (-0.5, 0.5)]
                                    paths = [points, [wings[0], end, wings[1]]]
                                else:
                                    paths = [points]
                                if outer_rgba:
                                    for path in paths:
                                        draw.line(path, fill=outer_rgba, width=s_stroke + 2 * s_outer_width, joint="curve")
                                for path in paths:
                                    draw.line(path, fill=color_rgba, width=s_stroke, joint="curve")
                            else:
                                if operation["type"] == "circle":
                                    shape = draw.ellipse
                                elif operation["type"] == "rounded_rectangle":
                                    shape = draw.rounded_rectangle
                                else:
                                    shape = draw.rectangle
                                shape_options = {"radius": min(12, width // 4, height // 4) * scale} if operation["type"] == "rounded_rectangle" else {}
                                if outer_rgba:
                                    shape(s_coords, outline=outer_rgba, width=s_stroke + 2 * s_outer_width, **shape_options)
                                    inset = s_outer_width
                                    if width * scale > 2 * inset and height * scale > 2 * inset:
                                        shape((inset, inset, width * scale - 1 - inset, height * scale - 1 - inset), outline=color_rgba, width=s_stroke, **shape_options)
                                else:
                                    shape(s_coords, outline=color_rgba, width=s_stroke, **shape_options)

                            smooth = overlay.resize((width, height), Image.Resampling.BILINEAR)
                            region_orig_mode = region.mode
                            if region.mode != "RGBA":
                                region = region.convert("RGBA")
                            region = Image.alpha_composite(region, smooth)
                            if region_orig_mode != "RGBA":
                                region = region.convert(region_orig_mode)
                            image.paste(region, (x, y))

            if target_format == "jpeg" and image.mode == "RGBA":
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            output = BoundedImageBuffer(cls.MAX_OUTPUT_BYTES, target_format)
            image.info.clear()
            if target_format == "jpeg":
                image.save(output, format="JPEG", quality=92, optimize=False)
            else:
                image.save(output, format="PNG")
            result = output.getvalue()
            return result, image.size
        except ScreenshotOutputLimitError:
            raise
        except ScreenshotEditError:
            raise
        except (UnidentifiedImageError, OSError, EOFError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
            raise ScreenshotEditError() from error
