"""
OfficeKit - PDF Password Remover & Security Manager
Removes password protection from encrypted bank statements, salary slips, and PDF documents.
Supports:
- Unlocking with known password (e.g. DOB, PAN, Account No)
- Removing owner/restriction permissions passwords
- Adding encryption/passwords to unprotected PDFs
- 100% offline & local using pikepdf (QPDF)
"""

import io
from typing import Tuple, Optional
import pikepdf
from officekit.engines.engine_pdf_validation import is_valid_pdf_password

PDF_PROCESSING_ERROR = "The PDF could not be processed. Verify that it is valid and try again."
PDF_PASSWORD_ERROR = "Password must be non-empty and within the supported size limit."
PDF_OUTPUT_LIMIT_ERROR = "The processed PDF exceeds the supported 64 MiB output limit."


class PdfOutputLimitError(RuntimeError):
    """Raised before a PDF encoder writes beyond the bounded response budget."""


class BoundedPdfBuffer(io.BytesIO):
    def __init__(self, max_bytes: int):
        super().__init__()
        self.max_bytes = max_bytes

    def write(self, data):
        if self.tell() + len(data) > self.max_bytes:
            raise PdfOutputLimitError()
        return super().write(data)

class PdfSecurityEngine:
    MAX_OUTPUT_BYTES = 64 * 1024 * 1024

    @staticmethod
    def remove_password(pdf_bytes: bytes, password: str = "") -> Tuple[bytes, bool, str]:
        """
        Unlocks and decrypts a password-protected PDF.
        Returns: (unlocked_pdf_bytes, success, message)
        """
        if not is_valid_pdf_password(password, require_non_empty=False):
            return b"", False, PDF_PASSWORD_ERROR
        try:
            # Attempt to open with provided password (or empty string for restriction-only passwords)
            with pikepdf.open(io.BytesIO(pdf_bytes), password=password) as pdf:
                out = BoundedPdfBuffer(PdfSecurityEngine.MAX_OUTPUT_BYTES)
                pdf.save(out)
                return out.getvalue(), True, "PDF successfully unlocked and password removed."
        except pikepdf.PasswordError:
            return b"", False, "Incorrect password. Please enter the valid password provided by your bank or institution."
        except PdfOutputLimitError:
            return b"", False, PDF_OUTPUT_LIMIT_ERROR
        except Exception:
            return b"", False, PDF_PROCESSING_ERROR

    @staticmethod
    def protect_pdf(pdf_bytes: bytes, user_password: str, owner_password: Optional[str] = None) -> Tuple[bytes, bool, str]:
        """Adds AES-256 password encryption to any PDF file."""
        if not is_valid_pdf_password(user_password, require_non_empty=True):
            return b"", False, PDF_PASSWORD_ERROR
        if owner_password is not None and not is_valid_pdf_password(owner_password, require_non_empty=False):
            return b"", False, PDF_PASSWORD_ERROR
        try:
            with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
                out = BoundedPdfBuffer(PdfSecurityEngine.MAX_OUTPUT_BYTES)
                encryption = pikepdf.Encryption(
                    user=user_password,
                    owner=owner_password or user_password,
                    R=6 # AES-256 bit encryption
                )
                pdf.save(out, encryption=encryption)
                return out.getvalue(), True, "PDF successfully password protected."
        except PdfOutputLimitError:
            return b"", False, PDF_OUTPUT_LIMIT_ERROR
        except Exception:
            return b"", False, PDF_PROCESSING_ERROR

    @staticmethod
    def merge_pdfs(pdf_list: list[bytes]) -> Tuple[bytes, bool, str]:
        """Merges multiple PDF byte arrays into a single PDF document."""
        try:
            merged = pikepdf.new()
            for b in pdf_list:
                with pikepdf.open(io.BytesIO(b)) as src:
                    merged.pages.extend(src.pages)
            out = BoundedPdfBuffer(PdfSecurityEngine.MAX_OUTPUT_BYTES)
            merged.save(out)
            return out.getvalue(), True, "PDFs merged successfully."
        except PdfOutputLimitError:
            return b"", False, PDF_OUTPUT_LIMIT_ERROR
        except Exception:
            return b"", False, PDF_PROCESSING_ERROR

    @staticmethod
    def split_pdf(pdf_bytes: bytes) -> Tuple[list[bytes], bool, str]:
        """Splits a multi-page PDF into single page PDF byte arrays."""
        try:
            pages_output = []
            total_output_bytes = 0
            with pikepdf.open(io.BytesIO(pdf_bytes)) as src:
                for p in src.pages:
                    single = pikepdf.new()
                    single.pages.append(p)
                    out = BoundedPdfBuffer(PdfSecurityEngine.MAX_OUTPUT_BYTES - total_output_bytes)
                    single.save(out)
                    page_bytes = out.getvalue()
                    total_output_bytes += len(page_bytes)
                    pages_output.append(page_bytes)
            return pages_output, True, f"Successfully split into {len(pages_output)} pages."
        except PdfOutputLimitError:
            return [], False, PDF_OUTPUT_LIMIT_ERROR
        except Exception:
            return [], False, PDF_PROCESSING_ERROR
