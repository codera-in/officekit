"""Bounded extraction of selectable text from PDF pages."""

from __future__ import annotations

import io

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException

from officekit.engines.engine_pdf_ranges import parse_page_ranges


MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_PDF_PAGES = 50
MAX_SELECTED_PAGES = 50
MAX_PAGE_CHARACTERS = 100_000
MAX_DOCUMENT_CHARACTERS = 500_000
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


class PdfTextError(ValueError):
    """Invalid PDF or unsupported text-extraction request."""


def extract_pdf_text(pdf_bytes: bytes, page_ranges: str = "", output_format: str = "txt") -> dict:
    """Extract selectable text in requested order; never run OCR implicitly."""
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
        raise PdfTextError("Choose a non-empty PDF file.")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise PdfTextError("The PDF exceeds the 64 MiB processing limit.")
    if output_format not in {"txt", "md"}:
        raise PdfTextError("Choose plain text or Markdown output.")
    if not isinstance(page_ranges, str) or len(page_ranges) > 4096:
        raise PdfTextError("The page selection is too long.")
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page_count = len(pdf.pages)
            if not 1 <= page_count <= MAX_PDF_PAGES:
                raise PdfTextError("PDF text extraction supports 1–50 pages.")
            if page_ranges.strip():
                try:
                    selected = parse_page_ranges(page_ranges, page_count, MAX_SELECTED_PAGES)
                except ValueError as error:
                    raise PdfTextError(str(error)) from error
            else:
                selected = list(range(page_count))
            sections: list[str] = []
            missing_pages: list[int] = []
            character_count = 0
            for page_index in selected:
                text = pdf.pages[page_index].extract_text() or ""
                text = text.replace("\x00", "").strip()
                if len(text) > MAX_PAGE_CHARACTERS:
                    raise PdfTextError("A selected page exceeds the supported text limit.")
                if not text:
                    missing_pages.append(page_index + 1)
                    continue
                character_count += len(text)
                if character_count > MAX_DOCUMENT_CHARACTERS:
                    raise PdfTextError("The extracted document exceeds the supported text limit.")
                heading = f"## Page {page_index + 1}" if output_format == "md" else f"--- Page {page_index + 1} ---"
                sections.append(f"{heading}\n\n{text}")
            if not sections:
                raise PdfTextError(
                    "No selectable text was found on the selected pages. This may be a scanned image PDF; OCR is not available in this tool."
                )
            output = "\n\n".join(sections) + "\n"
            if len(output.encode("utf-8")) > MAX_OUTPUT_BYTES:
                raise PdfTextError("The extracted text exceeds the 8 MiB download limit.")
            return {
                "text": output,
                "page_count": page_count,
                "selected_pages": [page + 1 for page in selected],
                "missing_text_pages": missing_pages,
                "character_count": character_count,
            }
    except PdfTextError:
        raise
    except (PDFSyntaxError, PDFPasswordIncorrect, MalformedPDFException, PdfminerException, OSError, ValueError) as error:
        raise PdfTextError("The PDF is invalid, encrypted, or could not be read.") from error
