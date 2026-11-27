"""Resource-bounded local OCR for image-only PDF pages."""

import io
import math
import re
import time

from officekit.engines.engine_ocr import ImageTextRecognitionError, ImageTextRecognitionUnavailable


class ScannedPdfOcrError(ValueError):
    status_code = 422
    public_message = "Could not read this scanned PDF. Try a clearer scan or a text PDF."


class ScannedPdfOcrUnavailable(RuntimeError):
    status_code = 503
    public_message = "Scanned PDF recognition is unavailable on this computer."


class _BoundedPngBuffer(io.BytesIO):
    def __init__(self, max_bytes: int):
        super().__init__()
        self.max_bytes = max_bytes

    def write(self, data):
        if self.tell() + len(data) > self.max_bytes:
            raise ScannedPdfOcrError()
        return super().write(data)


class ScannedPdfOcrEngine:
    MAX_PDF_BYTES = 64 * 1024 * 1024
    MAX_PAGES = 20
    MAX_DOCUMENT_PAGES = 500
    DPI = 150
    MAX_PAGE_PIXELS = 8_000_000
    MAX_TOTAL_PIXELS = 40_000_000
    MAX_PAGE_PNG_BYTES = 16 * 1024 * 1024
    MAX_ROWS = 20_000
    MAX_TEXT_CHARACTERS = 1_000_000
    MAX_OCR_DURATION_SECONDS = 120
    ORIENTATION_RETRY_ROTATIONS = (90, 180, 270)
    _DATE_CELL = re.compile(r"\b(?:\d{1,4}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})\b")
    _AMOUNT_CELL = re.compile(r"(?<!\w)(?:[₹$€£]\s*)?[-+]?\(?\d[\d,]*(?:\.\d{1,4})?\)?(?:\s*(?:DR|CR))?(?!\w)", re.IGNORECASE)

    @staticmethod
    def _encode_page_png(image):
        encoded = _BoundedPngBuffer(ScannedPdfOcrEngine.MAX_PAGE_PNG_BYTES)
        image.save(encoded, format="PNG", optimize=False)
        return encoded.getvalue()

    @staticmethod
    def _validate_ocr_rows(rows):
        if not isinstance(rows, list) or any(
            not isinstance(row, list)
            or any(not isinstance(cell, str) for cell in row)
            for row in rows
        ):
            raise ScannedPdfOcrError()

    @staticmethod
    def _contains_ocr_text(rows):
        return any(cell.strip() for row in rows for cell in row)

    @classmethod
    def _statement_row_score(cls, rows):
        """Prefer orientations that keep a transaction date and amount in separate cells."""
        transaction_rows = 0
        for row in rows:
            date_cells = [index for index, cell in enumerate(row) if cls._DATE_CELL.search(cell)]
            amount_cells = [index for index, cell in enumerate(row) if cls._AMOUNT_CELL.search(cell)]
            if any(date_index != amount_index for date_index in date_cells for amount_index in amount_cells):
                transaction_rows += 1

        header_direction = 0
        for row in rows:
            labels = []
            for cell in row:
                normalized = re.sub(r"[^a-z]+", " ", cell.casefold()).strip()
                if normalized in {"date", "transaction date", "value date"}:
                    labels.append(("date", len(labels)))
                elif normalized in {"description", "particulars", "narration", "details"}:
                    labels.append(("description", len(labels)))
                elif normalized in {"debit", "withdrawal", "withdrawals"}:
                    labels.append(("debit", len(labels)))
                elif normalized in {"credit", "deposit", "deposits"}:
                    labels.append(("credit", len(labels)))
                elif normalized == "balance":
                    labels.append(("balance", len(labels)))
            positions = dict(labels)
            if "date" in positions and "description" in positions:
                header_direction += 2 if positions["date"] < positions["description"] else -2
            if "description" in positions and "balance" in positions:
                header_direction += 1 if positions["description"] < positions["balance"] else -1
            if "debit" in positions and "credit" in positions:
                header_direction += 1 if positions["debit"] < positions["credit"] else -1
        return transaction_rows, header_direction

    @classmethod
    def extract_rows(cls, pdf_bytes: bytes, image_text_extractor=None, pdfium_module=None, page_indexes=None):
        """Render selected pages and flatten their OCR rows in source order."""
        return [
            row
            for page_rows in cls.extract_page_rows(pdf_bytes, image_text_extractor, pdfium_module, page_indexes)
            for row in page_rows
        ]

    @classmethod
    def extract_page_rows(cls, pdf_bytes: bytes, image_text_extractor=None, pdfium_module=None, page_indexes=None):
        """Render selected pages in order without writing files or retaining page images."""
        if not isinstance(pdf_bytes, bytes) or not pdf_bytes or len(pdf_bytes) > cls.MAX_PDF_BYTES:
            raise ScannedPdfOcrError()
        if image_text_extractor is None:
            from officekit.engines.engine_parser import extract_text_from_image

            image_text_extractor = extract_text_from_image
        if pdfium_module is None:
            try:
                import pypdfium2 as pdfium_module
            except ImportError as error:
                raise ScannedPdfOcrUnavailable() from error

        try:
            document = pdfium_module.PdfDocument(pdf_bytes)
        except Exception as error:
            raise ScannedPdfOcrError() from error

        page_rows_results = []
        total_pixels = 0
        text_characters = 0
        deadline = time.monotonic() + cls.MAX_OCR_DURATION_SECONDS
        try:
            page_count = len(document)
            if page_count < 1 or page_count > cls.MAX_DOCUMENT_PAGES:
                raise ScannedPdfOcrError()
            if page_indexes is None:
                pages_to_process = list(range(page_count))
            elif (
                not isinstance(page_indexes, (list, tuple))
                or not 1 <= len(page_indexes) <= cls.MAX_PAGES
                or any(type(index) is not int for index in page_indexes)
                or len(set(page_indexes)) != len(page_indexes)
                or any(index < 0 or index >= page_count for index in page_indexes)
            ):
                raise ScannedPdfOcrError()
            else:
                pages_to_process = list(page_indexes)
            if len(pages_to_process) > cls.MAX_PAGES:
                raise ScannedPdfOcrError()
            scale = cls.DPI / 72
            for page_index in pages_to_process:
                page = None
                bitmap = None
                image = None
                try:
                    page = document[page_index]
                    width_points, height_points = page.get_size()
                    if not all(math.isfinite(value) and value > 0 for value in (width_points, height_points)):
                        raise ScannedPdfOcrError()
                    width = math.ceil(width_points * scale)
                    height = math.ceil(height_points * scale)
                    page_pixels = width * height
                    total_pixels += page_pixels
                    if page_pixels > cls.MAX_PAGE_PIXELS or total_pixels > cls.MAX_TOTAL_PIXELS:
                        raise ScannedPdfOcrError()

                    bitmap = page.render(
                        scale=scale,
                        fill_color=(255, 255, 255, 255),
                        rev_byteorder=True,
                        maybe_alpha=False,
                        draw_annots=True,
                        limit_image_cache=True,
                    )
                    image = bitmap.to_pil().copy()
                    if image.size != (width, height):
                        raise ScannedPdfOcrError()
                    remaining_seconds = deadline - time.monotonic()
                    if remaining_seconds <= 0:
                        raise ScannedPdfOcrError()
                    page_rows = image_text_extractor(
                        cls._encode_page_png(image), timeout_seconds=min(60, remaining_seconds)
                    )
                    cls._validate_ocr_rows(page_rows)
                    best_rows = page_rows
                    best_score = cls._statement_row_score(page_rows)
                    if (
                        not cls._contains_ocr_text(page_rows)
                        or best_score[0] == 0
                        or best_score[1] < 0
                    ):
                        for rotation in cls.ORIENTATION_RETRY_ROTATIONS:
                            rotated = None
                            try:
                                rotated = image.rotate(rotation, expand=True)
                                rotated_pixels = rotated.width * rotated.height
                                if total_pixels + rotated_pixels > cls.MAX_TOTAL_PIXELS:
                                    raise ScannedPdfOcrError()
                                total_pixels += rotated_pixels
                                remaining_seconds = deadline - time.monotonic()
                                if remaining_seconds <= 0:
                                    raise ScannedPdfOcrError()
                                candidate_rows = image_text_extractor(
                                    cls._encode_page_png(rotated),
                                    timeout_seconds=min(60, remaining_seconds),
                                )
                                cls._validate_ocr_rows(candidate_rows)
                                candidate_score = cls._statement_row_score(candidate_rows)
                                if candidate_score > best_score:
                                    best_rows = candidate_rows
                                    best_score = candidate_score
                            finally:
                                if rotated is not None:
                                    rotated.close()
                    page_rows = best_rows
                    page_rows_results.append(page_rows)
                    text_characters += sum(
                        len(cell) for row in page_rows if isinstance(row, list)
                        for cell in row if isinstance(cell, str)
                    )
                    if sum(len(rows) for rows in page_rows_results) > cls.MAX_ROWS or text_characters > cls.MAX_TEXT_CHARACTERS:
                        raise ScannedPdfOcrError()
                except (ImageTextRecognitionUnavailable, ScannedPdfOcrUnavailable) as error:
                    raise ScannedPdfOcrUnavailable() from error
                except (ImageTextRecognitionError, ScannedPdfOcrError):
                    raise
                except Exception as error:
                    raise ScannedPdfOcrError() from error
                finally:
                    if image is not None:
                        image.close()
                    if bitmap is not None:
                        bitmap.close()
                    if page is not None:
                        page.close()
            return page_rows_results
        finally:
            document.close()
