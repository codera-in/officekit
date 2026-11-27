"""
OmniConvert - Universal File & Data Conversion Engine
Handles any-to-any:
- Image formats (PNG, JPG, WebP, BMP, TIFF, ICO, PDF)
- Tabular data formats (CSV, Excel, JSON, TSV, HTML tables)
"""

import io
import json
import csv
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, Any, Tuple
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
try:
    import pylibjxl as _pylibjxl
    _pylibjxl.register_pillow()
except (ImportError, OSError, RuntimeError, ValueError) as error:
    _pylibjxl = None
    _JXL_PLUGIN_LOAD_ERROR = repr(error)
else:
    _JXL_PLUGIN_LOAD_ERROR = None
from officekit.engines.engine_devtools import DevToolsEngine
from officekit.engines.engine_sql_export import render_insert_script
from officekit.engines.engine_conversion_errors import ConversionInputError
from officekit.engines.engine_spreadsheet_safety import sanitize_spreadsheet_text


class ImageOutputLimitError(RuntimeError):
    """Raised before a resize encoder grows beyond the bounded response budget."""


class ImageWorkLimitError(RuntimeError):
    """Raised when a batch exceeds its cumulative decoded-pixel work budget."""


class _BoundedImageBuffer(io.BytesIO):
    def __init__(self, max_bytes: int):
        super().__init__()
        self.max_bytes = max_bytes

    def write(self, data):
        if self.tell() + len(data) > self.max_bytes:
            raise ImageOutputLimitError("Resized image output exceeds the supported limit.")
        return super().write(data)


@lru_cache(maxsize=1)
def avif_encoder_available() -> bool:
    """Probe the actual local Pillow encoder instead of assuming platform support."""
    if "AVIF" not in Image.SAVE:
        Image.init()
    if "AVIF" not in Image.SAVE:
        return False
    try:
        Image.new("RGB", (1, 1), (0, 0, 0)).save(io.BytesIO(), format="AVIF")
    except (OSError, ValueError, RuntimeError):
        return False
    return True


@lru_cache(maxsize=1)
def jxl_encoder_available() -> bool:
    """Probe the optional statically linked JPEG XL Pillow plugin."""
    if _pylibjxl is None:
        return False
    Image.init()
    if "JXL" not in Image.SAVE:
        return False
    try:
        Image.new("RGB", (1, 1), (0, 0, 0)).save(io.BytesIO(), format="JXL")
    except (OSError, ValueError, RuntimeError):
        return False
    return True


def _clear_jxl_metadata(image: Image.Image) -> None:
    """Prevent the JXL Pillow plugin from inheriting metadata from Image.info."""
    for key in ("exif", "xmp", "jumbf"):
        image.info.pop(key, None)
    try:
        image.getexif().clear()
    except (AttributeError, OSError, ValueError):
        pass


class FileConverterEngine:
    avif_encoder_available = staticmethod(avif_encoder_available)
    jxl_encoder_available = staticmethod(jxl_encoder_available)
    MAX_METADATA_FRAME_PIXELS = 40_000_000
    MAX_METADATA_TOTAL_PIXELS = 200_000_000
    MAX_METADATA_FRAMES = 500
    MAX_RESIZE_FRAME_PIXELS = 40_000_000
    MAX_RESIZE_TOTAL_PIXELS = 200_000_000
    MAX_RESIZE_FRAMES = 500
    MAX_RESIZE_DIMENSION = 10_000
    MAX_RESIZE_OUTPUT_BYTES = 64 * 1024 * 1024
    MAX_CONVERT_OUTPUT_BYTES = 64 * 1024 * 1024
    MAX_RESIZE_BATCH_FILES = 50
    MAX_RESIZE_BATCH_TOTAL_PIXELS = 400_000_000
    MAX_TABULAR_ROWS = 50_000
    MAX_TABULAR_COLUMNS = 256
    MAX_TABULAR_CELLS = 250_000
    MAX_XLSX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
    MAX_XLSX_ARCHIVE_ENTRIES = 10_000
    MAX_XLSX_SHEETS = 256
    MAX_JSON_DEPTH = 64
    MAX_JSON_NODES = 250_000

    @classmethod
    def _validate_delimited_shape(cls, input_bytes: bytes, delimiter: str) -> None:
        """Bound table dimensions before pandas allocates a DataFrame."""
        try:
            text = input_bytes.decode("utf-8-sig")
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
            expected_columns = None
            rows = 0
            cells = 0
            for row in reader:
                if not row or (len(row) == 1 and row[0] == ""):
                    continue
                if len(row) > cls.MAX_TABULAR_COLUMNS:
                    raise ConversionInputError()
                if expected_columns is None:
                    expected_columns = len(row)
                elif len(row) > expected_columns:
                    raise ConversionInputError()
                rows += 1
                cells += len(row)
                if rows - 1 > cls.MAX_TABULAR_ROWS or cells > cls.MAX_TABULAR_CELLS:
                    raise ConversionInputError()
        except (csv.Error, UnicodeError) as error:
            raise ConversionInputError() from error

    @classmethod
    def _validate_xlsx_shape(cls, input_bytes: bytes) -> None:
        """Bound an untrusted OpenXML workbook before pandas expands it in memory."""
        try:
            with zipfile.ZipFile(io.BytesIO(input_bytes)) as archive:
                entries = archive.infolist()
                if not entries or len(entries) > cls.MAX_XLSX_ARCHIVE_ENTRIES:
                    raise ConversionInputError()
                names = [entry.filename for entry in entries]
                if len(names) != len(set(names)):
                    raise ConversionInputError()
                if any(
                    not name or name.startswith(("/", "\\"))
                    or ".." in name.replace("\\", "/").split("/")
                    for name in names
                ):
                    raise ConversionInputError()
                uncompressed_bytes = sum(entry.file_size for entry in entries)
                if uncompressed_bytes > cls.MAX_XLSX_UNCOMPRESSED_BYTES:
                    raise ConversionInputError()

                sheet_entries = [
                    entry for entry in entries
                    if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", entry.filename)
                ]
                if not sheet_entries:
                    raise ConversionInputError()

                for sheet_entry in sheet_entries:
                    if sheet_entry.file_size > cls.MAX_XLSX_UNCOMPRESSED_BYTES:
                        raise ConversionInputError()
                    rows = 0
                    cells = 0
                    with archive.open(sheet_entry) as sheet_xml:
                        for event, element in ET.iterparse(sheet_xml, events=("start", "end")):
                            if event == "end":
                                element.clear()
                                continue
                            tag = element.tag.rsplit("}", 1)[-1]
                            if tag == "dimension":
                                reference = element.attrib.get("ref", "")
                                endpoints = reference.split(":")
                                for endpoint in endpoints:
                                    match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", endpoint)
                                    if not match:
                                        raise ConversionInputError()
                                    column, row = match.groups()
                                    column_number = 0
                                    for character in column.upper():
                                        column_number = column_number * 26 + ord(character) - ord("A") + 1
                                    if (
                                        int(row) > cls.MAX_TABULAR_ROWS + 1
                                        or column_number > cls.MAX_TABULAR_COLUMNS
                                    ):
                                        raise ConversionInputError()
                            elif tag == "row":
                                rows += 1
                                row_reference = element.attrib.get("r")
                                if (
                                    rows > cls.MAX_TABULAR_ROWS + 1
                                    or (row_reference is not None and int(row_reference) > cls.MAX_TABULAR_ROWS + 1)
                                ):
                                    raise ConversionInputError()
                            elif tag == "c":
                                cells += 1
                                reference = element.attrib.get("r", "")
                                match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", reference)
                                if not match:
                                    raise ConversionInputError()
                                column, row = match.groups()
                                column_number = 0
                                for character in column.upper():
                                    column_number = column_number * 26 + ord(character) - ord("A") + 1
                                if (
                                    column_number > cls.MAX_TABULAR_COLUMNS
                                    or int(row) > cls.MAX_TABULAR_ROWS + 1
                                ):
                                    raise ConversionInputError()
                                if cells > cls.MAX_TABULAR_CELLS:
                                    raise ConversionInputError()
        except ConversionInputError:
            raise
        except (
            zipfile.BadZipFile,
            zipfile.LargeZipFile,
            OSError,
            ET.ParseError,
            ValueError,
            RuntimeError,
            NotImplementedError,
            EOFError,
        ):
            raise ConversionInputError() from None

    @classmethod
    def list_xlsx_sheet_names(cls, input_bytes: bytes):
        """Return bounded worksheet names from a validated XLSX workbook."""
        from openpyxl import load_workbook
        from openpyxl.utils.exceptions import InvalidFileException

        if not isinstance(input_bytes, bytes) or not input_bytes:
            raise ConversionInputError()
        cls._validate_xlsx_shape(input_bytes)
        workbook = None
        try:
            workbook = load_workbook(io.BytesIO(input_bytes), read_only=True, data_only=True)
            names = [sheet.title for sheet in workbook.worksheets]
            if (
                not names
                or len(names) > cls.MAX_XLSX_SHEETS
                or any(
                    not isinstance(name, str)
                    or not name
                    or len(name) > 128
                    or any(ord(character) < 32 for character in name)
                    for name in names
                )
            ):
                raise ConversionInputError()
            return names
        except ConversionInputError:
            raise
        except (InvalidFileException, OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile):
            raise ConversionInputError() from None
        finally:
            if workbook is not None:
                workbook.close()

    @classmethod
    def _validate_xls_shape(cls, input_bytes: bytes) -> None:
        """Bound the first legacy Excel sheet before pandas materializes it."""
        import xlrd

        workbook = None
        try:
            workbook = xlrd.open_workbook(
                file_contents=input_bytes,
                on_demand=True,
                ragged_rows=True,
            )
            if workbook.nsheets < 1:
                raise ConversionInputError()
            sheet = workbook.sheet_by_index(0)
            if (
                sheet.nrows > cls.MAX_TABULAR_ROWS + 1
                or sheet.ncols > cls.MAX_TABULAR_COLUMNS
                or sheet.nrows * sheet.ncols > cls.MAX_TABULAR_CELLS
            ):
                raise ConversionInputError()
        except ConversionInputError:
            raise
        except (xlrd.biffh.XLRDError, OSError, ValueError, TypeError, IndexError):
            raise ConversionInputError() from None
        finally:
            if workbook is not None:
                workbook.release_resources()

    @staticmethod
    def _format_xlsx_number(value, number_format: str) -> str | None:
        """Render a conservative subset of common Excel numeric display formats."""
        if not isinstance(number_format, str) or not number_format or number_format.casefold() == "general":
            return None
        try:
            number = Decimal(str(value))
            if not number.is_finite():
                return None
        except (InvalidOperation, ValueError):
            return None

        sections = re.split(r';(?=(?:[^"]*"[^"]*")*[^"]*$)', number_format)
        if number == 0 and len(sections) > 2:
            zero_section = sections[2].strip()
            if zero_section in {'"-"', "'-'"}:
                return "-"
        negative = number < 0
        section_index = 1 if negative and len(sections) > 1 else 0
        section = sections[section_index].strip()
        section = re.sub(
            r"\[(?:black|blue|cyan|green|magenta|red|white|yellow|color\d+)\]",
            "",
            section,
            flags=re.IGNORECASE,
        )
        match = re.search(
            r'(?P<integer>#,##,##0|#,##0|0)(?P<fraction>\.[0#]+)?(?P<percent>%)?',
            section,
        )
        if not match:
            return None

        def decode_affix(raw):
            """Decode only explicit literal, currency and sign tokens; reject other Excel syntax."""
            output = []
            index = 0
            while index < len(raw):
                character = raw[index]
                if character == '"':
                    index += 1
                    literal = []
                    while index < len(raw):
                        if raw[index] == '"':
                            if index + 1 < len(raw) and raw[index + 1] == '"':
                                literal.append('"')
                                index += 2
                                continue
                            break
                        literal.append(raw[index])
                        index += 1
                    if index >= len(raw):
                        return None
                    output.extend(literal)
                    index += 1
                    continue
                if character == "\\":
                    if index + 1 >= len(raw):
                        return None
                    output.append(raw[index + 1])
                    index += 2
                    continue
                if raw.startswith("[$", index):
                    end = raw.find("]", index + 2)
                    if end < 0:
                        return None
                    currency = re.fullmatch(r"\[\$([€£¥₹$])(?:-[A-Za-z0-9-]+)?\]", raw[index:end + 1])
                    if not currency:
                        return None
                    output.append(currency.group(1))
                    index = end + 1
                    continue
                if character in "$€£¥₹()- ":
                    output.append(character)
                    index += 1
                    continue
                return None
            return "".join(output)

        prefix = decode_affix(section[:match.start()])
        suffix = decode_affix(section[match.end():])
        if prefix is None or suffix is None:
            return None
        if prefix.count("(") + suffix.count("(") != prefix.count(")") + suffix.count(")"):
            return None

        magnitude = abs(number)
        percent = bool(match.group("percent"))
        if percent:
            magnitude *= 100
        fraction_pattern = (match.group("fraction") or "")[1:]
        decimal_places = len(fraction_pattern)
        quantum = Decimal(1).scaleb(-decimal_places)
        try:
            rounded = magnitude.quantize(quantum, rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return None

        fixed = f"{rounded:.{decimal_places}f}"
        whole, dot, fraction = fixed.partition(".")
        if match.group("integer") == "#,##0":
            whole = f"{int(whole):,}"
        elif match.group("integer") == "#,##,##0":
            digits = str(int(whole))
            if len(digits) > 3:
                groups = [digits[-3:]]
                remaining = digits[:-3]
                while remaining:
                    groups.insert(0, remaining[-2:])
                    remaining = remaining[:-2]
                whole = ",".join(groups)
            else:
                whole = digits
        minimum_fraction_digits = fraction_pattern.count("0")
        while len(fraction) > minimum_fraction_digits and fraction.endswith("0"):
            fraction = fraction[:-1]
        numeric_text = whole + ("." + fraction if fraction else "")
        sign = "-" if negative and section_index == 0 and "-" not in prefix else ""
        return sign + prefix + numeric_text + ("%" if percent else "") + suffix

    @staticmethod
    def _preserve_xlsx_display_values(dataframe, input_bytes: bytes, sheet_name=None) -> None:
        """Keep common identifier/date cell semantics lost by DataFrame inference."""
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(input_bytes), read_only=True, data_only=True)
        try:
            worksheet = workbook[sheet_name] if sheet_name is not None else workbook.worksheets[0]
            data_row = 0
            for row_number, cells in enumerate(worksheet.iter_rows(), start=1):
                if row_number == 1:
                    continue
                if not any(cell.value is not None for cell in cells):
                    continue
                if data_row >= len(dataframe.index):
                    break
                for column, cell in enumerate(cells):
                    if column >= len(dataframe.columns):
                        break
                    value = cell.value
                    if isinstance(value, (datetime, date, time)):
                        dataframe.iat[data_row, column] = value.isoformat()
                    elif (
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and math.isfinite(float(value))
                        and float(value).is_integer()
                        and value >= 0
                        and re.fullmatch(r"0{2,}", cell.number_format or "")
                    ):
                        dataframe.iat[data_row, column] = str(int(value)).zfill(len(cell.number_format))
                    elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                        displayed = FileConverterEngine._format_xlsx_number(value, cell.number_format or "")
                        if displayed is not None:
                            dataframe.iat[data_row, column] = displayed
                data_row += 1
        finally:
            workbook.close()

    @staticmethod
    def _reject_duplicate_json_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("JSON object keys must be unique")
            result[key] = value
        return result

    @staticmethod
    def _reject_non_finite_json_number(value):
        raise ValueError("JSON numbers must be finite")

    @classmethod
    def _validate_json_limits(cls, value) -> None:
        pending = [(value, 0)]
        nodes = 0
        while pending:
            current, depth = pending.pop()
            nodes += 1
            if depth > cls.MAX_JSON_DEPTH or nodes > cls.MAX_JSON_NODES:
                raise ValueError("JSON exceeds supported complexity limits")
            if isinstance(current, dict):
                for key, child in current.items():
                    key.encode("utf-8")
                    pending.append((child, depth + 1))
            elif isinstance(current, list):
                pending.extend((child, depth + 1) for child in current)
            elif isinstance(current, str):
                current.encode("utf-8")
            elif isinstance(current, float) and not math.isfinite(current):
                raise ValueError("JSON numbers must be finite")

    @staticmethod
    def _serialize_nested_tabular_values(dataframe):
        """Represent nested JSON/YAML cells as compact JSON for flat outputs."""
        def encode_json(value):
            if value is None or isinstance(value, (str, bool, int)):
                return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if isinstance(value, Decimal):
                if not value.is_finite():
                    raise ValueError("Non-finite decimal")
                return str(value)
            if isinstance(value, float):
                if not math.isfinite(value):
                    raise ValueError("Non-finite number")
                return json.dumps(value, allow_nan=False, separators=(",", ":"))
            if isinstance(value, list):
                return "[" + ",".join(encode_json(item) for item in value) + "]"
            if isinstance(value, dict):
                if any(not isinstance(key, str) for key in value):
                    raise ValueError("Nested object keys must be strings")
                return "{" + ",".join(
                    json.dumps(key, ensure_ascii=False) + ":" + encode_json(item)
                    for key, item in value.items()
                ) + "}"
            raise ValueError("Nested value has an unsupported type")

        def serialize(value):
            if not isinstance(value, (dict, list)):
                return value
            try:
                return encode_json(value)
            except (TypeError, ValueError, RecursionError):
                raise ConversionInputError() from None

        return dataframe.map(serialize)

    @staticmethod
    def _infer_delimited_types(dataframe, pandas):
        """Infer only safe numeric columns; preserve identifiers and date-like text."""
        leading_zero_integer = re.compile(r"^[+-]?0\d+$")
        numeric_text = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")

        for column in dataframe.columns:
            values = dataframe[column].tolist()
            populated = [value for value in values if isinstance(value, str) and value != ""]
            if not populated or any(not numeric_text.fullmatch(value) for value in populated):
                continue
            if any(leading_zero_integer.fullmatch(value) for value in populated):
                continue
            try:
                if any(len(Decimal(value).normalize().as_tuple().digits) > 15 for value in populated):
                    continue
                numeric = pandas.to_numeric(dataframe[column].replace("", pandas.NA), errors="raise")
                if not numeric.map(
                    lambda value: pandas.isna(value) or math.isfinite(float(value))
                ).all():
                    continue
            except (InvalidOperation, OverflowError, TypeError, ValueError):
                continue
            dataframe[column] = numeric
        return dataframe

    @staticmethod
    def _validate_null_token(null_token):
        """Validate an optional CSV/TSV null marker without accepting controls."""
        if null_token is None:
            return
        if (
            not isinstance(null_token, str)
            or not null_token
            or len(null_token) > 64
            or any(ord(character) < 32 or ord(character) == 127 for character in null_token)
            or sanitize_spreadsheet_text(null_token) != null_token
        ):
            raise ConversionInputError()

    @staticmethod
    def _decode_delimited_null(value, null_token):
        """Decode the selected null token and the converter's escaped literal form."""
        if not isinstance(value, str):
            return value
        if value == null_token:
            return None
        if value.startswith("\\\\"):
            return value[1:]
        if value == "\\" + null_token:
            return null_token
        return value

    @staticmethod
    def _encode_delimited_null(value, null_token, pandas):
        """Encode nulls and escape literal marker/backslash-prefixed text."""
        try:
            is_null = value is None or bool(pandas.isna(value))
        except (TypeError, ValueError):
            is_null = value is None
        if is_null:
            return null_token
        if isinstance(value, str) and (value == null_token or value.startswith("\\")):
            return "\\" + value
        return value

    @staticmethod
    def resize_images_to_zip(images, max_width: int, max_height: int) -> bytes:
        """Resize a bounded batch and return safe, uniquely named ZIP members."""
        if not isinstance(images, (list, tuple)) or not 1 <= len(images) <= FileConverterEngine.MAX_RESIZE_BATCH_FILES:
            raise ConversionInputError()
        output = _BoundedImageBuffer(FileConverterEngine.MAX_RESIZE_OUTPUT_BYTES)
        supported_formats = {
            "JPEG": "jpg", "PNG": "png", "WEBP": "webp", "BMP": "bmp",
            "TIFF": "tiff", "GIF": "gif",
        }
        used_names = set()
        total_pixel_work = 0
        try:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
                for source_name, source_bytes in images:
                    if not isinstance(source_name, str) or not isinstance(source_bytes, bytes):
                        raise ConversionInputError()
                    base_name = source_name.replace("\\", "/").rsplit("/", 1)[-1]
                    stem = base_name.rsplit(".", 1)[0] if "." in base_name else base_name
                    stem = "".join(character for character in stem if character.isalnum() or character in " ._-")
                    stem = stem.strip(" .")[:100] or "image"
                    remaining_pixel_work = FileConverterEngine.MAX_RESIZE_BATCH_TOTAL_PIXELS - total_pixel_work
                    if remaining_pixel_work <= 0:
                        raise ImageWorkLimitError()
                    resized, _dimensions, image_pixel_work = FileConverterEngine._resize_image_with_pixel_work(
                        source_bytes,
                        max_width,
                        max_height,
                        max_total_pixels=remaining_pixel_work,
                    )
                    total_pixel_work += image_pixel_work
                    with Image.open(io.BytesIO(resized)) as image:
                        extension = supported_formats.get((image.format or "").upper())
                    if extension is None:
                        raise ConversionInputError()
                    candidate = f"{stem}_resized.{extension}"
                    suffix = 2
                    while candidate.casefold() in used_names:
                        candidate = f"{stem}_resized ({suffix}).{extension}"
                        suffix += 1
                    used_names.add(candidate.casefold())
                    archive.writestr(candidate, resized)
            return output.getvalue()
        except ImageOutputLimitError:
            raise
        except ImageWorkLimitError:
            raise
        except ConversionInputError:
            raise
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
            raise ConversionInputError() from None

    @staticmethod
    def convert_image(
        input_bytes: bytes, target_format: str, quality: int = 90,
        preserve_metadata: bool = False, preserve_color_profile: bool = True, lossless: bool = False,
    ) -> Tuple[bytes, str]:
        """Convert any image to another image format."""
        if isinstance(quality, bool) or not isinstance(quality, int) or not 1 <= quality <= 100:
            raise ConversionInputError()
        target_format = target_format.lower().replace('.', '')
        format_map = {
            'jpg': ('JPEG', 'image/jpeg'),
            'jpeg': ('JPEG', 'image/jpeg'),
            'png': ('PNG', 'image/png'),
            'webp': ('WEBP', 'image/webp'),
            'avif': ('AVIF', 'image/avif'),
            'jxl': ('JXL', 'image/jxl'),
            'bmp': ('BMP', 'image/bmp'),
            'ico': ('ICO', 'image/x-icon'),
            'tiff': ('TIFF', 'image/tiff'),
            'pdf': ('PDF', 'application/pdf')
        }

        if target_format not in format_map:
            raise ConversionInputError()
        if target_format == 'avif' and not avif_encoder_available():
            raise ConversionInputError()
        if target_format == 'jxl' and not jxl_encoder_available():
            raise ConversionInputError()

        pil_fmt, mime = format_map[target_format]
        if not isinstance(preserve_metadata, bool) or not isinstance(preserve_color_profile, bool):
            raise ConversionInputError()
        if not isinstance(lossless, bool) or (lossless and target_format not in {"webp", "jxl"}):
            raise ConversionInputError()
        try:
            img = Image.open(io.BytesIO(input_bytes))
            frame_count = getattr(img, 'n_frames', 1)
            if frame_count > 1:
                if pil_fmt not in {'WEBP', 'TIFF'}:
                    raise ConversionInputError()
                if frame_count > FileConverterEngine.MAX_METADATA_FRAMES:
                    raise ConversionInputError()

                frames = []
                frame_durations = []
                total_pixels = 0
                source_info = dict(img.info)
                for frame in ImageSequence.Iterator(img):
                    frame_pixels = frame.width * frame.height
                    total_pixels += frame_pixels
                    if (
                        frame.width <= 0
                        or frame.height <= 0
                        or frame_pixels > FileConverterEngine.MAX_METADATA_FRAME_PIXELS
                        or total_pixels > FileConverterEngine.MAX_METADATA_TOTAL_PIXELS
                    ):
                        raise ConversionInputError()
                    frame.load()
                    duration = frame.info.get(
                        'duration', img.info.get('duration', source_info.get('duration', 100))
                    )
                    frame_durations.append(duration)
                    frame = ImageOps.exif_transpose(frame.copy())
                    if pil_fmt == 'WEBP':
                        if frame.mode == 'CMYK':
                            frame = frame.convert('RGB')
                        elif frame.mode not in ('RGB', 'RGBA'):
                            frame = frame.convert('RGBA' if 'transparency' in frame.info else 'RGB')
                    frames.append(frame)

                output = _BoundedImageBuffer(FileConverterEngine.MAX_CONVERT_OUTPUT_BYTES)
                save_kwargs = {'save_all': True, 'append_images': frames[1:]}
                if pil_fmt == 'WEBP':
                    save_kwargs.update(quality=quality, duration=frame_durations)
                    if lossless:
                        save_kwargs['lossless'] = True
                    loop = source_info.get('loop')
                    if loop is not None:
                        save_kwargs['loop'] = loop
                if preserve_color_profile and pil_fmt in {'JPEG', 'PNG', 'WEBP', 'TIFF'}:
                    if source_info.get('icc_profile'):
                        save_kwargs['icc_profile'] = source_info['icc_profile']
                    if source_info.get('dpi'):
                        save_kwargs['dpi'] = source_info['dpi']
                frames[0].save(output, format=pil_fmt, **save_kwargs)
                return output.getvalue(), mime

            img.load()
            source_info = dict(img.info)
            img = ImageOps.exif_transpose(img)
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
            raise ConversionInputError() from None

        # JPEG and BMP do not preserve alpha; composite onto white instead of
        # silently discarding transparency or exposing the hidden RGB values.
        if pil_fmt in {'JPEG', 'BMP'} and img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1])
            img = background
        elif pil_fmt in {'AVIF', 'JXL'} and img.mode not in {'RGB', 'RGBA'}:
            has_alpha = 'A' in img.getbands() or 'transparency' in img.info
            img = img.convert('RGBA' if has_alpha else 'RGB')
        elif pil_fmt != 'JPEG' and img.mode == 'CMYK':
            img = img.convert('RGB')

        output = _BoundedImageBuffer(FileConverterEngine.MAX_CONVERT_OUTPUT_BYTES)
        save_kwargs = {}
        if pil_fmt in ('JPEG', 'WEBP', 'AVIF', 'JXL'):
            save_kwargs['quality'] = quality
        if lossless:
            save_kwargs['lossless'] = True
            save_kwargs['quality'] = 100
        if preserve_color_profile and pil_fmt in {'JPEG', 'PNG', 'WEBP', 'TIFF', 'AVIF', 'JXL'}:
            if source_info.get('icc_profile'):
                save_kwargs['icc_profile'] = source_info['icc_profile']
            if source_info.get('dpi'):
                save_kwargs['dpi'] = source_info['dpi']
        if preserve_metadata and pil_fmt in {'JPEG', 'PNG', 'WEBP', 'TIFF', 'AVIF', 'JXL'}:
            exif = img.getexif()
            exif.pop(274, None)  # Orientation was already applied by exif_transpose.
            if exif:
                save_kwargs['exif'] = exif
        elif pil_fmt == 'JXL':
            # pylibjxl falls back to Image.info for EXIF, XMP and JUMBF when
            # save kwargs are absent, so clear inherited metadata explicitly.
            _clear_jxl_metadata(img)

        img.save(output, format=pil_fmt, **save_kwargs)
        return output.getvalue(), mime

    @staticmethod
    def strip_exif(input_bytes: bytes) -> bytes:
        """Removes EXIF, camera, and GPS metadata from image bytes."""
        try:
            with Image.open(io.BytesIO(input_bytes)) as img:
                image_format = img.format or 'PNG'
                if getattr(img, 'n_frames', 1) > FileConverterEngine.MAX_METADATA_FRAMES:
                    raise ConversionInputError()
                frames = []
                frame_durations = []
                total_pixels = 0
                for frame in ImageSequence.Iterator(img):
                    frame_pixels = frame.width * frame.height
                    total_pixels += frame_pixels
                    if (
                        frame.width <= 0
                        or frame.height <= 0
                        or frame_pixels > FileConverterEngine.MAX_METADATA_FRAME_PIXELS
                        or total_pixels > FileConverterEngine.MAX_METADATA_TOTAL_PIXELS
                    ):
                        raise ConversionInputError()
                    frame.load()
                    frame_durations.append(frame.info.get('duration', img.info.get('duration', 0)))
                    cleaned_frame = ImageOps.exif_transpose(frame.copy())
                    if image_format.upper() == 'JXL':
                        _clear_jxl_metadata(cleaned_frame)
                    frames.append(cleaned_frame)
                if not frames:
                    raise ConversionInputError()

                # Copy complete frames rather than round-tripping raw pixel indices
                # into a blank image. This preserves palettes and animation/page data.
                out = io.BytesIO()
                save_kwargs = {}
                if image_format.upper() in {'JPEG', 'PNG', 'WEBP', 'TIFF'}:
                    save_kwargs['exif'] = b''
                icc_profile = img.info.get('icc_profile')
                if icc_profile:
                    save_kwargs['icc_profile'] = icc_profile
                dpi = img.info.get('dpi')
                if dpi:
                    save_kwargs['dpi'] = dpi
                if image_format.upper() == 'JPEG':
                    save_kwargs['quality'] = 'keep'
                elif image_format.upper() == 'WEBP':
                    # A lossless rewrite keeps the decoded pixels unchanged while
                    # removing EXIF; a lossy second encode can degrade the image.
                    save_kwargs['lossless'] = True

                if len(frames) > 1:
                    save_kwargs['save_all'] = True
                    save_kwargs['append_images'] = frames[1:]
                    if image_format.upper() in {'GIF', 'WEBP'}:
                        if any(frame_durations):
                            save_kwargs['duration'] = frame_durations
                        loop = img.info.get('loop')
                        if loop is not None:
                            save_kwargs['loop'] = loop
                frames[0].format = image_format
                frames[0].save(out, format=image_format, **save_kwargs)
                return out.getvalue()
        except ConversionInputError:
            raise
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
            raise ConversionInputError() from None

    @staticmethod
    def resize_image(input_bytes: bytes, max_width: int, max_height: int) -> Tuple[bytes, Tuple[int, int]]:
        """Resize every supported frame/page inside a no-upscale bounding box."""
        resized, dimensions, _pixel_work = FileConverterEngine._resize_image_with_pixel_work(
            input_bytes,
            max_width,
            max_height,
            max_total_pixels=FileConverterEngine.MAX_RESIZE_TOTAL_PIXELS,
        )
        return resized, dimensions

    @staticmethod
    def _resize_image_with_pixel_work(
        input_bytes: bytes,
        max_width: int,
        max_height: int,
        *,
        max_total_pixels: int,
    ) -> Tuple[bytes, Tuple[int, int], int]:
        """Resize one image and return decoded source pixels for batch budgeting."""
        if (
            not isinstance(input_bytes, bytes)
            or type(max_width) is not int
            or type(max_height) is not int
            or not 1 <= max_width <= FileConverterEngine.MAX_RESIZE_DIMENSION
            or not 1 <= max_height <= FileConverterEngine.MAX_RESIZE_DIMENSION
            or type(max_total_pixels) is not int
            or not 1 <= max_total_pixels <= FileConverterEngine.MAX_RESIZE_BATCH_TOTAL_PIXELS
        ):
            raise ConversionInputError()

        try:
            with Image.open(io.BytesIO(input_bytes)) as source:
                image_format = (source.format or "").upper()
                if image_format not in {"JPEG", "PNG", "WEBP", "AVIF", "JXL", "BMP", "TIFF", "GIF"}:
                    raise ConversionInputError()
                frame_count = getattr(source, "n_frames", 1)
                if frame_count < 1 or frame_count > FileConverterEngine.MAX_RESIZE_FRAMES:
                    raise ConversionInputError()

                source_info = dict(source.info)
                frames = []
                durations = []
                total_pixels = 0
                for frame in ImageSequence.Iterator(source):
                    frame_pixels = frame.width * frame.height
                    if (
                        frame.width <= 0
                        or frame.height <= 0
                        or frame_pixels > FileConverterEngine.MAX_RESIZE_FRAME_PIXELS
                    ):
                        raise ConversionInputError()
                    total_pixels += frame_pixels
                    if total_pixels > FileConverterEngine.MAX_RESIZE_TOTAL_PIXELS:
                        raise ConversionInputError()
                    if total_pixels > max_total_pixels:
                        raise ImageWorkLimitError()
                    frame.load()
                    duration = frame.info.get("duration")
                    if duration is None or duration <= 0:
                        duration = source_info.get("duration")
                    if duration is None or duration <= 0:
                        duration = 100
                    durations.append(duration)
                    frame = ImageOps.exif_transpose(frame.copy())

                    if frame.mode in {"RGBA", "LA"} or (
                        frame.mode == "P" and "transparency" in frame.info
                    ):
                        frame = frame.convert("RGBA")
                    elif frame.mode == "P" or frame.mode in {"1", "I", "F"}:
                        frame = frame.convert("RGB")

                    if image_format in {"JPEG", "BMP"} and frame.mode in {"RGBA", "LA"}:
                        rgba = frame.convert("RGBA")
                        background = Image.new("RGB", rgba.size, "white")
                        background.paste(rgba, mask=rgba.getchannel("A"))
                        frame = background
                    elif image_format == "WEBP" and frame.mode not in {"RGB", "RGBA"}:
                        frame = frame.convert("RGB")

                    scale = min(1.0, max_width / frame.width, max_height / frame.height)
                    resized_size = (
                        min(max_width, max(1, round(frame.width * scale))),
                        min(max_height, max(1, round(frame.height * scale))),
                    )
                    if frame.size != resized_size:
                        frame = frame.resize(resized_size, Image.Resampling.LANCZOS)
                    frames.append(frame)

                if not frames:
                    raise ConversionInputError()

                output = _BoundedImageBuffer(FileConverterEngine.MAX_RESIZE_OUTPUT_BYTES)
                save_kwargs = {}
                if image_format == "JPEG":
                    save_kwargs["quality"] = 90
                elif image_format == "WEBP":
                    save_kwargs["quality"] = 90
                if image_format in {"JPEG", "PNG", "WEBP", "AVIF", "JXL", "TIFF"}:
                    if source_info.get("icc_profile"):
                        save_kwargs["icc_profile"] = source_info["icc_profile"]
                    if source_info.get("dpi"):
                        save_kwargs["dpi"] = source_info["dpi"]

                if len(frames) > 1:
                    save_kwargs.update(save_all=True, append_images=frames[1:])
                    if image_format in {"GIF", "WEBP"}:
                        if any(durations):
                            save_kwargs["duration"] = durations
                        if source_info.get("loop") is not None:
                            save_kwargs["loop"] = source_info["loop"]

                frames[0].save(output, format=image_format, **save_kwargs)
                return output.getvalue(), frames[0].size, total_pixels
        except ConversionInputError:
            raise
        except ImageOutputLimitError:
            raise
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
            raise ConversionInputError() from None

    @staticmethod
    def convert_data_file(input_bytes: bytes, source_ext: str, target_ext: str, **kwargs) -> Tuple[bytes, str]:
        """Convert between tabular formats (CSV, Excel, JSON, TSV, HTML)."""
        import pandas as pd

        source_ext = source_ext.lower().replace('.', '')
        target_ext = target_ext.lower().replace('.', '')
        sheet_name = kwargs.get('sheet_name')
        null_token = kwargs.get('null_token')
        FileConverterEngine._validate_null_token(null_token)
        if sheet_name is not None and source_ext != 'xlsx':
            raise ConversionInputError()

        # Load DataFrame or data structure
        try:
            if source_ext in ('csv', 'txt'):
                FileConverterEngine._validate_delimited_shape(input_bytes, ",")
                df = pd.read_csv(io.BytesIO(input_bytes), dtype=str, keep_default_na=False)
                if null_token is not None:
                    df = df.map(lambda value: FileConverterEngine._decode_delimited_null(value, null_token))
                df = FileConverterEngine._infer_delimited_types(df, pd)
            elif source_ext in ('tsv', 'tab'):
                FileConverterEngine._validate_delimited_shape(input_bytes, "\t")
                df = pd.read_csv(io.BytesIO(input_bytes), sep='\t', dtype=str, keep_default_na=False)
                if null_token is not None:
                    df = df.map(lambda value: FileConverterEngine._decode_delimited_null(value, null_token))
                df = FileConverterEngine._infer_delimited_types(df, pd)
            elif source_ext in ('xlsx', 'xls'):
                if source_ext == 'xlsx':
                    sheet_names = FileConverterEngine.list_xlsx_sheet_names(input_bytes)
                    if sheet_name is not None and (not isinstance(sheet_name, str) or sheet_name not in sheet_names):
                        raise ConversionInputError()
                    selected_sheet = sheet_name if sheet_name is not None else 0
                else:
                    if sheet_name is not None:
                        raise ConversionInputError()
                    FileConverterEngine._validate_xls_shape(input_bytes)
                    selected_sheet = 0
                df = pd.read_excel(io.BytesIO(input_bytes), sheet_name=selected_sheet, dtype=object)
                if source_ext == 'xlsx':
                    FileConverterEngine._preserve_xlsx_display_values(
                        df, input_bytes, sheet_name if sheet_name is not None else sheet_names[0]
                    )
            elif source_ext == 'json':
                data = json.loads(
                    input_bytes.decode('utf-8'),
                    object_pairs_hook=FileConverterEngine._reject_duplicate_json_keys,
                    parse_constant=FileConverterEngine._reject_non_finite_json_number,
                )
                FileConverterEngine._validate_json_limits(data)
                df = pd.DataFrame(data)
            elif source_ext in ('yaml', 'yml'):
                parsed_yaml_json = DevToolsEngine.yaml_to_json(input_bytes.decode('utf-8'))
                if target_ext == 'json':
                    return parsed_yaml_json.encode('utf-8'), 'application/json'
                parsed_yaml = json.loads(parsed_yaml_json, parse_float=Decimal)
                if isinstance(parsed_yaml, list):
                    df = pd.DataFrame(parsed_yaml)
                elif isinstance(parsed_yaml, dict):
                    df = pd.DataFrame([parsed_yaml])
                else:
                    df = pd.DataFrame([{"value": parsed_yaml}])
            else:
                raise ConversionInputError()
        except (ImportError, UnicodeError, ValueError, RecursionError, OSError, zipfile.BadZipFile,
                pd.errors.ParserError, pd.errors.EmptyDataError):
            raise ConversionInputError() from None

        if target_ext not in {"json", "yaml", "yml"}:
            df = FileConverterEngine._serialize_nested_tabular_values(df)

        if target_ext in {'csv', 'tsv', 'xlsx', 'excel'}:
            df = df.map(sanitize_spreadsheet_text)

        if null_token is not None and target_ext in {'csv', 'tsv'}:
            df = df.map(lambda value: FileConverterEngine._encode_delimited_null(value, null_token, pd))

        # Export DataFrame
        out = io.BytesIO()
        if target_ext == 'csv':
            df.to_csv(out, index=False)
            return out.getvalue(), 'text/csv'
        elif target_ext == 'tsv':
            df.to_csv(out, sep='\t', index=False)
            return out.getvalue(), 'text/tab-separated-values'
        elif target_ext in ('xlsx', 'excel'):
            with pd.ExcelWriter(out, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            return out.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        elif target_ext == 'json':
            json_str = df.to_json(orient='records', indent=2)
            return json_str.encode('utf-8'), 'application/json'
        elif target_ext in ('yaml', 'yml'):
            import yaml
            records = df.to_dict(orient='records')
            yaml_str = yaml.dump(records, sort_keys=False)
            return yaml_str.encode('utf-8'), 'text/yaml'
        elif target_ext == 'html':
            html_str = df.to_html(classes="table table-striped", index=False)
            return html_str.encode('utf-8'), 'text/html'
        elif target_ext == 'sql':
            tbl = kwargs.get('table_name', 'exported_table')
            sql = render_insert_script(df.columns, df.itertuples(index=False, name=None), tbl)
            return sql.encode('utf-8'), 'application/sql'
        else:
            raise ConversionInputError()
