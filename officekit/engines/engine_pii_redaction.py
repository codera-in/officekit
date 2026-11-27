"""Local PII discovery and irreversible redaction for common shareable files."""

from __future__ import annotations

import hashlib
import io
import os
import re
import zipfile
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree


class PiiRedactionError(ValueError):
    """A file or redaction request cannot be processed safely."""

    public_message = "This file could not be scanned safely. Check its format and try another copy."

    def __init__(self, public_message: str | None = None):
        super().__init__(public_message or self.public_message)
        self.public_message = public_message or type(self).public_message


class PiiOcrUnavailable(PiiRedactionError):
    public_message = "Local text recognition is unavailable. Install the OfficeKit speech and OCR resources, then try again."


class PiiRedactionEngine:
    MAX_INPUT_BYTES = 64 * 1024 * 1024
    MAX_TEXT_BYTES = 8 * 1024 * 1024
    MAX_MATCHES = 2_000
    MAX_ARCHIVE_ENTRIES = 10_000
    MAX_ARCHIVE_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
    MAX_PDF_PAGES = 100
    MAX_PDF_TOTAL_PIXELS = 120_000_000
    MAX_IMAGE_PIXELS = 40_000_000
    MAX_OUTPUT_BYTES = 128 * 1024 * 1024
    SUPPORTED = frozenset({".txt", ".md", ".csv", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif", ".docx", ".xlsx", ".pptx"})
    _context_detector = None
    _context_detector_path = None
    _english_entity_detector = None

    _PATTERNS = (
        ("email", "Email address", "high", re.compile(r"(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+", re.I)),
        ("ssn", "Social Security number", "high", re.compile(r"(?<!\d)(?!000|666|9\d\d)\d{3}[- ]?(?!00)\d{2}[- ]?(?!0000)\d{4}(?!\d)")),
        ("card", "Payment card number", "high", re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")),
        ("iban", "IBAN", "high", re.compile(r"(?<![A-Z0-9])[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}(?![A-Z0-9])", re.I)),
        ("phone", "Phone number", "high", re.compile(r"(?<!\w)\+?\d[\d(). -]{7,}\d(?!\w)")),
        ("passport", "Passport number", "high", re.compile(r"(?i)\bpassport(?:\s*(?:no\.?|number|#))?\s*[:#-]?\s*([A-Z0-9][A-Z0-9 -]{4,15})")),
        ("tax_id", "Tax identifier", "high", re.compile(r"(?i)\b(?:tax\s*id|ein|national\s*id|identity\s*(?:no\.?|number))\s*[:#-]?\s*([A-Z0-9][A-Z0-9 -]{4,19})")),
        ("person", "Person name", "possible", re.compile(r"(?i)\b(?:name|contact|employee|patient|customer|recipient)\s*[:#-]\s*([A-Z][\w'’-]*(?:[ -][A-Z][\w'’-]*){0,3})")),
        ("address", "Street address", "possible", re.compile(r"(?i)\b(?:home\s+address|mailing\s+address|street\s+address|address)\s*[:#-]\s*([^\r\n]{5,120})")),
        ("dob", "Date of birth", "possible", re.compile(r"(?i)\b(?:date\s+of\s+birth|birth\s+date|dob)\s*[:#-]?\s*((?:\d{1,4}[/-]){1,2}\d{1,4}|[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})")),
        ("date", "Date · possible birth date", "possible", re.compile(r"(?i)(?<!\w)(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{4})?)(?!\w)")),
    )

    @classmethod
    def scan(cls, filename: str, content: bytes, ocr_observations=None) -> dict[str, Any]:
        extension = cls._validate_input(filename, content)
        if extension in {".txt", ".md", ".csv"}:
            text = cls._decode_text(content)
            matches = cls._find_matches(text, "Text", "text")
            return {"filename": cls._display_name(filename), "format": extension[1:].upper(), "matches": cls._public_matches(matches), "page_count": None}
        if extension in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}:
            image, observations = cls._open_image(content, ocr_observations)
            matches = cls._matches_in_ocr(observations, "Image")
            return {"filename": cls._display_name(filename), "format": extension[1:].upper(), "matches": cls._public_matches(matches), "page_count": None}
        if extension == ".pdf":
            matches, page_count = cls._scan_pdf(content, ocr_observations)
            return {"filename": cls._display_name(filename), "format": "PDF", "matches": cls._public_matches(matches), "page_count": page_count}
        matches = cls._scan_office_archive(content, extension, collect_only=True)
        return {"filename": cls._display_name(filename), "format": extension[1:].upper(), "matches": cls._public_matches(matches), "page_count": None}

    @classmethod
    def redact(cls, filename: str, content: bytes, selected_ids: list[str], ocr_observations=None, mode: str = "mask") -> tuple[bytes, str, str]:
        extension = cls._validate_input(filename, content)
        if not isinstance(mode, str) or mode not in {"mask", "redact"}:
            raise PiiRedactionError("Choose either partial masking or full redaction.")
        if not isinstance(selected_ids, list) or len(selected_ids) > cls.MAX_MATCHES or any(
            not isinstance(item, str) or not re.fullmatch(r"[a-f0-9]{24}", item) for item in selected_ids
        ) or len(set(selected_ids)) != len(selected_ids):
            raise PiiRedactionError("Select at least one detected item before creating the redacted copy.")

        report = cls.scan(filename, content, ocr_observations)
        known_ids = {item["id"] for item in report["matches"]}
        if not set(selected_ids) <= known_ids:
            raise PiiRedactionError("The file changed after scanning. Scan it again before redacting.")

        if extension in {".txt", ".md", ".csv"}:
            text = cls._decode_text(content)
            hits = [match for match in cls._find_matches(text, "Text", "text") if match["id"] in selected_ids]
            output = cls._replace_matches(text, hits, mode).encode("utf-8")
            target_extension, media_type = extension, "text/plain; charset=utf-8"
        elif extension in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}:
            output = cls._redact_image(content, selected_ids, ocr_observations, mode)
            target_extension, media_type = ".png", "image/png"
        elif extension == ".pdf":
            output = cls._redact_pdf(content, selected_ids, ocr_observations, mode)
            target_extension, media_type = ".pdf", "application/pdf"
        else:
            output = cls._scan_office_archive(content, extension, selected_ids=selected_ids, mode=mode)
            media_type = {
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            }[extension]
            target_extension = extension

        if not output or len(output) > cls.MAX_OUTPUT_BYTES:
            raise PiiRedactionError("The redacted copy exceeds OfficeKit’s safe output limit. Try a smaller file.")
        suffix = "masked" if mode == "mask" else "redacted"
        output_name = f"{PurePosixPath(cls._display_name(filename)).stem}-{suffix}{target_extension}"
        return output, output_name, media_type

    @classmethod
    def _validate_input(cls, filename: str, content: bytes) -> str:
        if not isinstance(filename, str) or not filename or len(filename) > 255 or any(ord(ch) < 32 for ch in filename):
            raise PiiRedactionError("Choose a file with a valid filename.")
        extension = PurePosixPath(filename).suffix.lower()
        if extension not in cls.SUPPORTED:
            raise PiiRedactionError("Choose a TXT, CSV, Markdown, PDF, image, DOCX, XLSX or PPTX file.")
        if not isinstance(content, bytes) or not content or len(content) > cls.MAX_INPUT_BYTES:
            raise PiiRedactionError("The selected file is empty or exceeds the 64 MiB limit.")
        return extension

    @staticmethod
    def _display_name(filename: str) -> str:
        return PurePosixPath(filename.replace("\\", "/")).name

    @classmethod
    def _decode_text(cls, content: bytes) -> str:
        if len(content) > cls.MAX_TEXT_BYTES:
            raise PiiRedactionError("Text files must be 8 MiB or smaller.")
        try:
            return content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as error:
            raise PiiRedactionError("This text file is not valid UTF-8. Save a UTF-8 copy and scan it again.") from error

    @staticmethod
    def _luhn(value: str) -> bool:
        digits = [int(ch) for ch in value if ch.isdigit()]
        if not 13 <= len(digits) <= 19:
            return False
        total = 0
        parity = len(digits) % 2
        for index, digit in enumerate(digits):
            if index % 2 == parity:
                digit *= 2
                if digit > 9:
                    digit -= 9
            total += digit
        return total % 10 == 0

    @staticmethod
    def _valid_iban(value: str) -> bool:
        compact = re.sub(r"\s", "", value).upper()
        if not 15 <= len(compact) <= 34 or not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", compact):
            return False
        rearranged = compact[4:] + compact[:4]
        remainder = 0
        for character in rearranged:
            digits = str(ord(character) - 55) if character.isalpha() else character
            for digit in digits:
                remainder = (remainder * 10 + int(digit)) % 97
        return remainder == 1

    @classmethod
    def _find_matches(cls, text: str, location: str, group_key: str, offset_base: int = 0) -> list[dict[str, Any]]:
        if not isinstance(text, str) or len(text.encode("utf-8", errors="replace")) > cls.MAX_TEXT_BYTES:
            raise PiiRedactionError("The selected document contains too much text to scan safely.")
        matches = []
        seen = set()
        for kind, label, confidence, pattern in cls._PATTERNS:
            for match in pattern.finditer(text):
                start, end = match.span(1) if match.lastindex and kind in {"passport", "tax_id", "person", "address", "dob"} else match.span()
                value = text[start:end].strip()
                if not value or len(value) > 160:
                    continue
                compact_digits = "".join(ch for ch in value if ch.isdigit())
                if kind == "card" and not cls._luhn(value):
                    continue
                if kind == "iban" and not cls._valid_iban(value):
                    continue
                if kind == "phone" and not 9 <= len(compact_digits) <= 15:
                    continue
                if kind == "ssn" and (len(compact_digits) != 9 or value[:3] in {"000", "666"}):
                    continue
                key = (start, end)
                if key in seen:
                    continue
                seen.add(key)
                absolute_start, absolute_end = offset_base + start, offset_base + end
                identifier = hashlib.sha256(f"{group_key}\0{kind}\0{absolute_start}\0{absolute_end}\0{value}".encode("utf-8")).hexdigest()[:24]
                matches.append({
                    "id": identifier,
                    "type": kind,
                    "label": label,
                    "confidence": confidence,
                    "value": value,
                    "location": location,
                    "_start": start,
                    "_end": end,
                    "_group": group_key,
                })
                if len(matches) > cls.MAX_MATCHES:
                    raise PiiRedactionError("This file contains too many possible matches to review in one pass.")
        matches.sort(key=lambda item: (item["_start"], item["_end"], item["type"]))
        from officekit.engines.pii_span_resolver import resolve_spans

        spans = []
        for match in matches:
            spans.append({
                **match, "_source": "baseline",
                "_validation": "checksum" if match["type"] in {"card", "iban"} else "format",
                "_score": 1.0,
            })
        try:
            english_findings = cls._get_english_entity_detector().detect(text)
        except ValueError as error:
            raise PiiRedactionError("The English entity detector returned invalid results. Check the file and try again.") from error
        for finding in english_findings:
            spans.append({
                **finding,
                "location": location,
                "_group": group_key,
                "_source": finding.get("_source", "heuristic"),
                "_validation": "context",
                "_score": finding["_score"],
            })

        detector = cls._get_context_detector()
        if detector is not None:
            try:
                contextual_findings = detector.detect(text)
            except RuntimeError as error:
                raise PiiRedactionError("The optional local PII context model failed during detection. Check the local model and retry.") from error
            except ValueError as error:
                raise PiiRedactionError("The optional local PII context model returned invalid results. Check the model and try again.") from error
            for finding in contextual_findings:
                if finding["type"] not in {"email", "ssn", "card", "iban", "phone", "passport", "tax_id", "person", "organization", "address", "dob", "date", "username", "ip_address"}:
                    continue
                spans.append({
                    **finding,
                    "location": location,
                    "_group": group_key,
                    "_source": "neural",
                    "_validation": "none",
                    "_score": finding["_score"],
                })
        matches = resolve_spans(text, spans, group_key)
        if len(matches) > cls.MAX_MATCHES:
            raise PiiRedactionError("This file contains too many possible matches to review in one pass.")
        for match in matches:
            if match["_source"] in {"neural", "heuristic"}:
                match["label"] = f"{match['label']} · Context match"
                match["confidence"] = "possible"
        matches.sort(key=lambda item: (item["_start"], item["_end"], item["type"]))
        return matches

    @classmethod
    def _get_english_entity_detector(cls):
        if cls._english_entity_detector is not None:
            return cls._english_entity_detector
        from officekit.engines.pii_english_entities import PiiEnglishEntityDetector

        cls._english_entity_detector = PiiEnglishEntityDetector()
        return cls._english_entity_detector

    @classmethod
    def _get_context_detector(cls):
        model_path = os.environ.get("OFFICEKIT_PII_CONTEXT_MODEL")
        if not model_path:
            return None
        if cls._context_detector is not None and cls._context_detector_path == model_path:
            return cls._context_detector
        from officekit.engines.pii_context_detector import PiiContextDetector, PiiContextModelUnavailable

        try:
            raw_threads = os.environ.get("OFFICEKIT_PII_CONTEXT_THREADS", "1")
            if not raw_threads.isascii() or not raw_threads.isdecimal() or not 1 <= int(raw_threads) <= 4:
                raise PiiContextModelUnavailable("The local PII model thread setting is invalid.")
            cls._context_detector = PiiContextDetector.from_local_path(model_path, threads=int(raw_threads))
        except PiiContextModelUnavailable as error:
            cls._context_detector = None
            cls._context_detector_path = None
            raise PiiRedactionError("The optional local PII context model is unavailable. Check its local model path.") from error
        cls._context_detector_path = model_path
        return cls._context_detector

    @staticmethod
    def _public_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{key: value for key, value in match.items() if not key.startswith("_")} for match in matches]

    @staticmethod
    def _replace_spans(text: str, spans: list[tuple[int, int]]) -> str:
        merged = []
        for start, end in sorted(spans):
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        for start, end in reversed(merged):
            text = text[:start] + "[REDACTED]" + text[end:]
        return text

    @classmethod
    def _mask_value(cls, value: str, kind: str) -> str:
        if kind == "email" and "@" in value:
            local, domain = value.rsplit("@", 1)
            return (local[:1] + "•" * max(3, len(local) - 1)) + "@" + domain
        if kind == "person":
            return re.sub(r"[A-Za-z][A-Za-z'’-]*", lambda match: match.group(0)[:1] + "•" * max(2, len(match.group(0)) - 1), value)
        if kind in {"phone", "card", "ssn", "iban", "passport", "tax_id"}:
            chars = list(value)
            indices = [index for index, char in enumerate(chars) if char.isalnum()]
            for index in indices[:-4]:
                chars[index] = "•"
            return "".join(chars)
        if kind in {"dob", "date"}:
            return re.sub(r"\d", "•", value[:-4]) + value[-4:] if len(value) > 4 else "•" * len(value)
        return re.sub(r"\S", "•", value[1:]) if len(value) < 2 else value[:1] + re.sub(r"\S", "•", value[1:])

    @classmethod
    def _replace_matches(cls, text: str, matches: list[dict[str, Any]], mode: str) -> str:
        # Overlapping classifications are conservatively replaced as one fully redacted span.
        spans = []
        for hit in sorted(matches, key=lambda item: (item["_start"], item["_end"])):
            if spans and hit["_start"] < spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], hit["_end"])
                spans[-1][2] = "[REDACTED]"
            else:
                replacement = "[REDACTED]" if mode == "redact" else cls._mask_value(hit["value"], hit["type"])
                spans.append([hit["_start"], hit["_end"], replacement])
        for start, end, replacement in reversed(spans):
            text = text[:start] + replacement + text[end:]
        return text

    @classmethod
    def _open_image(cls, content: bytes, ocr_observations=None):
        try:
            from PIL import Image, ImageOps, UnidentifiedImageError

            with Image.open(io.BytesIO(content)) as source:
                if getattr(source, "n_frames", 1) != 1 or source.width <= 0 or source.height <= 0 or source.width * source.height > cls.MAX_IMAGE_PIXELS:
                    raise PiiRedactionError("Animated or oversized images are not supported. Export a single frame and scan it again.")
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.load()
            if ocr_observations is None:
                ocr_observations = cls._run_ocr(image)
            if not isinstance(ocr_observations, list):
                raise PiiOcrUnavailable()
            return image, ocr_observations
        except PiiRedactionError:
            raise
        except Exception as error:
            if type(error).__name__ == "UnidentifiedImageError":
                raise PiiRedactionError("OfficeKit could not open this image.") from error
            raise PiiRedactionError() from error

    @staticmethod
    def _run_ocr(image):
        try:
            from officekit.engines.engine_rapidocr import recognize_observations
            return recognize_observations(image)
        except Exception as error:
            if isinstance(error, PiiRedactionError):
                raise
            raise PiiOcrUnavailable() from error

    @classmethod
    def _matches_in_ocr(cls, observations: list[dict], location: str) -> list[dict]:
        ordered = sorted(observations, key=lambda item: (item["center_y"], item["x"]))
        lines = []
        for observation in ordered:
            if lines and abs(lines[-1]["center_y"] - observation["center_y"]) <= max(5, lines[-1]["height"] * 0.45):
                lines[-1]["items"].append(observation)
                lines[-1]["center_y"] = sum(item["center_y"] for item in lines[-1]["items"]) / len(lines[-1]["items"])
            else:
                lines.append({"center_y": observation["center_y"], "height": observation["height"], "items": [observation]})
        matches = []
        for index, line in enumerate(lines, 1):
            items = sorted(line["items"], key=lambda item: item["x"])
            text = " ".join(item["text"] for item in items)
            for match in cls._find_matches(text, f"{location} · line {index}", f"{location}:{index}"):
                start, end = match["_start"], match["_end"]
                offset = 0
                boxes = []
                for item in items:
                    item_start, item_end = offset, offset + len(item["text"])
                    if item_start < end and item_end > start:
                        boxes.append(item)
                    offset = item_end + 1
                if boxes:
                    match["_box"] = {
                        "x0": min(item["x"] for item in boxes),
                        "y0": min(item["center_y"] - item["height"] / 2 for item in boxes),
                        "x1": max(item["x"] + item["width"] for item in boxes),
                        "y1": max(item["center_y"] + item["height"] / 2 for item in boxes),
                    }
                    matches.append(match)
                    if len(matches) > cls.MAX_MATCHES:
                        raise PiiRedactionError("This file contains too many possible matches to review in one pass.")
        return matches

    @classmethod
    def _scan_pdf(cls, content: bytes, ocr_observations=None):
        try:
            import pdfplumber
        except ImportError as error:
            raise PiiRedactionError("PDF scanning is unavailable in this installation.") from error
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                if not 1 <= len(pdf.pages) <= cls.MAX_PDF_PAGES:
                    raise PiiRedactionError("PDF files must contain between 1 and 100 pages.")
                matches = []
                total_ocr_pixels = 0
                for page_index, page in enumerate(pdf.pages, 1):
                    words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
                    if words:
                        lines = []
                        for word in sorted(words, key=lambda row: (row["top"], row["x0"])):
                            if lines and abs(lines[-1]["top"] - word["top"]) <= 3:
                                lines[-1]["words"].append(word)
                            else:
                                lines.append({"top": word["top"], "words": [word]})
                        for line_index, line in enumerate(lines, 1):
                            line_words = sorted(line["words"], key=lambda row: row["x0"])
                            line_text = " ".join(word["text"] for word in line_words)
                            for match in cls._find_matches(line_text, f"Page {page_index} · line {line_index}", f"pdf:{page_index}:{line_index}"):
                                selected_words = []
                                offset = 0
                                for word in line_words:
                                    word_start, word_end = offset, offset + len(word["text"])
                                    if word_start < match["_end"] and word_end > match["_start"]:
                                        selected_words.append(word)
                                    offset = word_end + 1
                                if selected_words:
                                    match["_page"] = page_index - 1
                                    match["_box"] = {
                                        "x0": min(word["x0"] for word in selected_words),
                                        "y0": min(word["top"] for word in selected_words),
                                        "x1": max(word["x1"] for word in selected_words),
                                        "y1": max(word["bottom"] for word in selected_words),
                                    }
                                    matches.append(match)
                    else:
                        pixel_count = round(page.width * 2) * round(page.height * 2)
                        total_ocr_pixels += pixel_count
                        if pixel_count <= 0 or pixel_count > 20_000_000 or total_ocr_pixels > cls.MAX_PDF_TOTAL_PIXELS:
                            raise PiiRedactionError("The PDF exceeds the safe OCR rendering limit.")
                        image, observations = cls._render_pdf_page(content, page_index - 1, 144)
                        page_ocr = ocr_observations.get(page_index, []) if isinstance(ocr_observations, dict) else None
                        if page_ocr is None:
                            page_ocr = cls._run_ocr(image)
                        for match in cls._matches_in_ocr(page_ocr, f"Page {page_index}"):
                            match["_page"] = page_index - 1
                            match["_box"] = {key: value * 72 / 144 for key, value in match["_box"].items()}
                            matches.append(match)
                if len(matches) > cls.MAX_MATCHES:
                    raise PiiRedactionError("This file contains too many possible matches to review in one pass.")
                return matches, len(pdf.pages)
        except PiiRedactionError:
            raise
        except Exception as error:
            raise PiiRedactionError("OfficeKit could not read this PDF. It may be password-protected or damaged.") from error

    @classmethod
    def _render_pdf_page(cls, content: bytes, page_index: int, dpi: int):
        document = None
        try:
            import pypdfium2 as pdfium
            document = pdfium.PdfDocument(content)
            page = document[page_index]
            width_points, height_points = page.get_size()
            width, height = round(width_points * dpi / 72), round(height_points * dpi / 72)
            if width <= 0 or height <= 0 or width * height > 20_000_000:
                raise PiiRedactionError("A PDF page is too large to scan safely.")
            bitmap = page.render(scale=dpi / 72, fill_color=(255, 255, 255, 255), rev_byteorder=True, maybe_alpha=False, draw_annots=True)
            image = bitmap.to_pil().convert("RGB")
            if image.size != (width, height):
                raise PiiRedactionError()
            return image, {"width_points": width_points, "height_points": height_points}
        except PiiRedactionError:
            raise
        except Exception as error:
            raise PiiRedactionError("OfficeKit could not render a PDF page.") from error
        finally:
            if document is not None:
                document.close()

    @classmethod
    def _redact_image(cls, content: bytes, selected_ids: list[str], ocr_observations=None, mode: str = "redact") -> bytes:
        image, observations = cls._open_image(content, ocr_observations)
        matches = cls._matches_in_ocr(observations, "Image")
        from PIL import ImageDraw
        draw = ImageDraw.Draw(image)
        for match in matches:
            if match["id"] not in selected_ids:
                continue
            box = match.get("_box")
            if not box:
                raise PiiRedactionError("A selected image match has no safe mask position. Scan the image again.")
            rect = (max(0, int(box["x0"] - 2)), max(0, int(box["y0"] - 2)), min(image.width, int(box["x1"] + 2)), min(image.height, int(box["y1"] + 2)))
            draw.rectangle(rect, fill="black")
            if mode == "mask":
                from PIL import ImageFont
                label = cls._mask_value(match["value"], match["type"])
                font = ImageFont.load_default(size=max(8, min(14, rect[3] - rect[1] - 2)))
                region = image.crop(rect)
                ImageDraw.Draw(region).text((2, 1), label, fill="white", font=font)
                image.paste(region, rect[:2])
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=False)
        return output.getvalue()

    @classmethod
    def _redact_pdf(cls, content: bytes, selected_ids: list[str], ocr_observations=None, mode: str = "redact") -> bytes:
        try:
            import pypdfium2 as pdfium
            from PIL import ImageDraw
            from reportlab.pdfgen import canvas
            from reportlab.lib.utils import ImageReader
            import pdfplumber
            report, _ = cls._scan_pdf(content, ocr_observations)
            selected = [match for match in report if match["id"] in selected_ids]
            document = pdfium.PdfDocument(content)
            output = io.BytesIO()
            pdf = canvas.Canvas(output, pageCompression=1)
            total_pixels = 0
            with pdfplumber.open(io.BytesIO(content)) as source_pdf:
                for page_index, page in enumerate(document):
                    source_page = source_pdf.pages[page_index]
                    width_points, height_points = source_page.width, source_page.height
                    width, height = round(width_points * 144 / 72), round(height_points * 144 / 72)
                    total_pixels += width * height
                    if width <= 0 or height <= 0 or total_pixels > cls.MAX_PDF_TOTAL_PIXELS:
                        raise PiiRedactionError("The PDF is too large to redact safely. Try a smaller document.")
                    bitmap = page.render(scale=2, fill_color=(255, 255, 255, 255), rev_byteorder=True, maybe_alpha=False, draw_annots=True)
                    image = bitmap.to_pil().convert("RGB")
                    draw = ImageDraw.Draw(image)
                    for match in (item for item in selected if item["_page"] == page_index):
                        box = match["_box"]
                        x0, y0, x1, y1 = (int(box[key] * 2) for key in ("x0", "y0", "x1", "y1"))
                        rect = (max(0, x0 - 3), max(0, y0 - 3), min(image.width, x1 + 3), min(image.height, y1 + 3))
                        draw.rectangle(rect, fill="black")
                        if mode == "mask":
                            from PIL import ImageFont
                            label = cls._mask_value(match["value"], match["type"])
                            region = image.crop(rect)
                            ImageDraw.Draw(region).text((2, 1), label, fill="white", font=ImageFont.load_default(size=max(8, min(14, rect[3] - rect[1] - 2))))
                            image.paste(region, rect[:2])
                    pdf.setPageSize((width_points, height_points))
                    pdf.drawImage(ImageReader(image), 0, 0, width=width_points, height=height_points, preserveAspectRatio=False, mask="auto")
                    pdf.showPage()
                    if output.tell() > cls.MAX_OUTPUT_BYTES:
                        raise PiiRedactionError("The redacted PDF exceeds OfficeKit’s safe output limit.")
            pdf.save()
            return output.getvalue()
        except PiiRedactionError:
            raise
        except Exception as error:
            raise PiiRedactionError("OfficeKit could not create a flattened redacted PDF.") from error

    @classmethod
    def _scan_office_archive(cls, content: bytes, extension: str, collect_only: bool = False, selected_ids: list[str] | None = None, mode: str = "redact"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                if not 1 <= len(entries) <= cls.MAX_ARCHIVE_ENTRIES or sum(item.file_size for item in entries) > cls.MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise PiiRedactionError("This Office document exceeds the safe archive limits.")
                required_prefix = {".docx": "word/", ".xlsx": "xl/", ".pptx": "ppt/"}[extension]
                if not any(item.filename.startswith(required_prefix) for item in entries):
                    raise PiiRedactionError("The selected file does not match its Office document format.")
                results, rewritten = [], []
                for info in entries:
                    if info.is_dir():
                        rewritten.append((info, b""))
                        continue
                    data = archive.read(info)
                    if not info.filename.lower().endswith(".xml") or not (
                        info.filename.startswith(required_prefix) or info.filename.startswith("docProps/") or info.filename.startswith("customXml/")
                    ):
                        rewritten.append((info, data))
                        continue
                    try:
                        root = ElementTree.fromstring(data)
                    except ElementTree.ParseError as error:
                        raise PiiRedactionError("An Office document XML part is damaged.") from error
                    groups, covered = cls._office_text_groups(root, extension)
                    for group_index, (nodes, location) in enumerate(groups, 1):
                        strings = [node.text or "" for node in nodes]
                        text = "".join(strings)
                        group_key = f"{info.filename}:{group_index}"
                        hits = cls._find_matches(text, location, group_key)
                        if collect_only:
                            results.extend(hits)
                            continue
                        chosen = [hit for hit in hits if selected_ids and hit["id"] in selected_ids]
                        if chosen:
                            replaced = cls._replace_matches(text, chosen, mode)
                            cls._distribute_text(nodes, replaced)
                    # Scan any standalone leaf text, including document metadata and drawing descriptions.
                    for node_index, node in enumerate(root.iter(), 1):
                        if node in covered or not node.text or len(node) > 0:
                            continue
                        group_key = f"{info.filename}:leaf:{node_index}"
                        hits = cls._find_matches(node.text, f"{info.filename}", group_key)
                        if collect_only:
                            results.extend(hits)
                        elif selected_ids:
                            chosen = [hit for hit in hits if hit["id"] in selected_ids]
                            if chosen:
                                node.text = cls._replace_matches(node.text, chosen, mode)
                    rewritten.append((info, ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)))
                if collect_only:
                    if len(results) > cls.MAX_MATCHES:
                        raise PiiRedactionError("This file contains too many possible matches to review in one pass.")
                    return results
                output = io.BytesIO()
                with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
                    for info, data in rewritten:
                        clean = zipfile.ZipInfo(info.filename, info.date_time)
                        clean.compress_type = zipfile.ZIP_DEFLATED
                        clean.external_attr = info.external_attr
                        target.writestr(clean, data)
                return output.getvalue()
        except PiiRedactionError:
            raise
        except (zipfile.BadZipFile, OSError, KeyError, ValueError) as error:
            raise PiiRedactionError("OfficeKit could not read this Office document.") from error

    @staticmethod
    def _office_text_groups(root, extension: str):
        local = lambda element: element.tag.rsplit("}", 1)[-1]
        group_names = {".docx": {"p"}, ".xlsx": {"si", "is", "c"}, ".pptx": {"p"}}[extension]
        groups, covered = [], set()
        for element in root.iter():
            if local(element) not in group_names:
                continue
            nodes = [child for child in element.iter() if child not in covered and local(child) in {"t", "v"} and child.text]
            if not nodes:
                continue
            groups.append((nodes, f"{local(element)}"))
            covered.update(nodes)
        return groups, covered

    @staticmethod
    def _distribute_text(nodes, replacement: str) -> None:
        if not nodes:
            return
        nodes[0].text = replacement
        for node in nodes[1:]:
            node.text = ""
