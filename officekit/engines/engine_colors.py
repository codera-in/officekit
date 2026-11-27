"""Bounded sRGB color conversion for HEX, RGB, HSL and HSV values."""

import colorsys
import math
import re


class ColorConverterEngine:
    MAX_INPUT_LENGTH = 128
    FORMATS = frozenset(("hex", "rgb", "hsl", "hsv"))
    HEX_PATTERN = re.compile(r"#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\Z")
    RGB_PATTERN = re.compile(
        r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})"
        r"(?:\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?|\.\d+))?\s*\)\Z",
        re.IGNORECASE,
    )
    HSL_PATTERN = re.compile(
        r"hsla?\(\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*,\s*"
        r"(\d+(?:\.\d*)?|\.\d+)%\s*,\s*(\d+(?:\.\d*)?|\.\d+)%"
        r"(?:\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?|\.\d+))?\s*\)\Z",
        re.IGNORECASE,
    )
    HSV_PATTERN = re.compile(
        r"hsva?\(\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*,\s*"
        r"(\d+(?:\.\d*)?|\.\d+)%\s*,\s*(\d+(?:\.\d*)?|\.\d+)%"
        r"(?:\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?|\.\d+))?\s*\)\Z",
        re.IGNORECASE,
    )

    @classmethod
    def convert(cls, value, source_format, target_format):
        if (
            not isinstance(source_format, str)
            or not isinstance(target_format, str)
            or source_format not in cls.FORMATS
            or target_format not in cls.FORMATS
        ):
            raise ValueError("Supported color formats are hex, rgb, hsl and hsv")
        red, green, blue, alpha = cls._parse(value, source_format)
        return cls._format(red, green, blue, alpha, target_format)

    @classmethod
    def _parse(cls, value, source_format):
        if not isinstance(value, str) or not value or len(value) > cls.MAX_INPUT_LENGTH:
            raise ValueError(f"Color value must be a string of 1 to {cls.MAX_INPUT_LENGTH} characters")
        if source_format == "hex":
            match = cls.HEX_PATTERN.fullmatch(value)
            if not match:
                raise ValueError("HEX color must use #RGB, #RGBA, #RRGGBB or #RRGGBBAA")
            digits = match.group(1)
            if len(digits) in (3, 4):
                digits = "".join(char * 2 for char in digits)
            channels = [int(digits[index:index + 2], 16) / 255 for index in (0, 2, 4)]
            alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
            return *channels, alpha

        pattern = {"rgb": cls.RGB_PATTERN, "hsl": cls.HSL_PATTERN, "hsv": cls.HSV_PATTERN}[source_format]
        match = pattern.fullmatch(value.strip())
        if not match:
            raise ValueError(f"Invalid {source_format.upper()} color syntax")
        first, second, third = (float(match.group(index)) for index in (1, 2, 3))
        alpha = float(match.group(4)) if match.group(4) is not None else 1.0
        if not math.isfinite(alpha) or not 0 <= alpha <= 1:
            raise ValueError("Alpha must be between 0 and 1")
        if source_format == "rgb":
            if any(not value.is_integer() or not 0 <= value <= 255 for value in (first, second, third)):
                raise ValueError("RGB channels must be whole numbers between 0 and 255")
            return first / 255, second / 255, third / 255, alpha
        if not 0 <= second <= 100 or not 0 <= third <= 100:
            raise ValueError(f"{source_format.upper()} percentages must be between 0 and 100")
        hue = (first % 360) / 360
        if source_format == "hsv":
            red, green, blue = colorsys.hsv_to_rgb(hue, second / 100, third / 100)
        else:
            red, green, blue = colorsys.hls_to_rgb(hue, third / 100, second / 100)
        return red, green, blue, alpha

    @classmethod
    def _format(cls, red, green, blue, alpha, target_format):
        if target_format == "hex":
            channels = "".join(f"{cls._round_channel(value):02x}" for value in (red, green, blue))
            if alpha < 1:
                channels += f"{cls._round_channel(alpha):02x}"
            return f"#{channels}"
        if target_format == "rgb":
            channels = ", ".join(str(cls._round_channel(value)) for value in (red, green, blue))
            if alpha < 1:
                return f"rgba({channels}, {cls._decimal(alpha, 3)})"
            return f"rgb({channels})"
        if target_format == "hsv":
            hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
        else:
            hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
            value = lightness
        hue_degrees = (hue * 360) % 360
        pieces = f"{cls._decimal(hue_degrees, 2)}, {cls._decimal(saturation * 100, 2)}%, {cls._decimal(value * 100, 2)}%"
        function = "hsv" if target_format == "hsv" else "hsl"
        if alpha < 1:
            return f"{function}a({pieces}, {cls._decimal(alpha, 3)})"
        return f"{function}({pieces})"

    @staticmethod
    def _round_channel(value):
        return math.floor(value * 255 + 0.5)

    @staticmethod
    def _decimal(value, places):
        rounded = round(value, places)
        return f"{rounded:.{places}f}".rstrip("0").rstrip(".") or "0"
