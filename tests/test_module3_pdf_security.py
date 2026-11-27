"""
TDD Tests for Module 3: PDF Security, Decryption & Utilities
- Unlocking password-protected PDFs (bank statements, salary slips)
- Error handling on incorrect passwords
- AES-256 PDF encryption
- PDF Merge and Page Split utilities
"""

import io
import unittest
import pikepdf
from unittest.mock import patch
from officekit.engines.engine_pdf_security import PDF_PASSWORD_ERROR, PDF_PROCESSING_ERROR, PdfSecurityEngine

class TestModule3PdfSecurityEngine(unittest.TestCase):

    def _create_sample_pdf(self) -> bytes:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        buf = io.BytesIO()
        pdf.save(buf)
        return buf.getvalue()

    def test_protect_and_unlock_pdf_lifecycle(self):
        raw_pdf = self._create_sample_pdf()
        password = "SecretPassword2026!"

        # 1. Protect PDF with password
        enc_pdf, enc_ok, _ = PdfSecurityEngine.protect_pdf(raw_pdf, password)
        self.assertTrue(enc_ok)
        self.assertGreater(len(enc_pdf), len(raw_pdf))

        # 2. Try unlocking with wrong password
        _, wrong_ok, wrong_msg = PdfSecurityEngine.remove_password(enc_pdf, "wrong_password")
        self.assertFalse(wrong_ok)
        self.assertIn("Incorrect password", wrong_msg)

        # 3. Unlock with correct password
        unlocked_pdf, unl_ok, _ = PdfSecurityEngine.remove_password(enc_pdf, password)
        self.assertTrue(unl_ok)
        self.assertGreater(len(unlocked_pdf), 0)

        # 4. Verify unlocked PDF can be opened with NO password
        with pikepdf.open(io.BytesIO(unlocked_pdf)) as test_pdf:
            self.assertEqual(len(test_pdf.pages), 1)

    def test_merge_pdfs(self):
        pdf1 = self._create_sample_pdf()
        pdf2 = self._create_sample_pdf()
        merged_pdf, ok, _ = PdfSecurityEngine.merge_pdfs([pdf1, pdf2])
        self.assertTrue(ok)
        with pikepdf.open(io.BytesIO(merged_pdf)) as merged:
            self.assertEqual(len(merged.pages), 2)

    def test_split_pdf(self):
        # Create 2-page PDF
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.add_blank_page()
        buf = io.BytesIO()
        pdf.save(buf)

        split_pages, ok, _ = PdfSecurityEngine.split_pdf(buf.getvalue())
        self.assertTrue(ok)
        self.assertEqual(len(split_pages), 2)

    def test_malformed_pdf_failures_are_generic_and_do_not_echo_runtime_details(self):
        malformed_pdf = b"not a PDF: /Users/private/customer-document.pdf"
        outcomes = (
            PdfSecurityEngine.remove_password(malformed_pdf, "secret"),
            PdfSecurityEngine.protect_pdf(malformed_pdf, "secret"),
            PdfSecurityEngine.merge_pdfs([malformed_pdf]),
            PdfSecurityEngine.split_pdf(malformed_pdf),
        )

        for outcome in outcomes:
            with self.subTest(outcome=outcome):
                self.assertFalse(outcome[-2])
                self.assertEqual(outcome[-1], PDF_PROCESSING_ERROR)
                self.assertNotIn("/Users/private", outcome[-1])

    def test_pdf_password_engine_rejects_empty_protection_and_oversized_passwords(self):
        raw_pdf = self._create_sample_pdf()
        _, empty_ok, empty_message = PdfSecurityEngine.protect_pdf(raw_pdf, "")
        _, oversized_ok, oversized_message = PdfSecurityEngine.remove_password(
            b"not parsed because the password is too long",
            "x" * 1025,
        )

        self.assertFalse(empty_ok)
        self.assertFalse(oversized_ok)
        self.assertEqual(empty_message, PDF_PASSWORD_ERROR)
        self.assertEqual(oversized_message, PDF_PASSWORD_ERROR)

    def test_protect_and_unlock_fail_cleanly_when_encoded_output_exceeds_limit(self):
        raw_pdf = self._create_sample_pdf()
        encrypted_pdf, encrypted_ok, _ = PdfSecurityEngine.protect_pdf(raw_pdf, "secret")
        self.assertTrue(encrypted_ok)

        with patch.object(PdfSecurityEngine, "MAX_OUTPUT_BYTES", 32, create=True):
            protected = PdfSecurityEngine.protect_pdf(raw_pdf, "secret")
            unlocked = PdfSecurityEngine.remove_password(encrypted_pdf, "secret")

        for output, succeeded, message in (protected, unlocked):
            with self.subTest(operation=message):
                self.assertEqual(output, b"")
                self.assertFalse(succeeded)
                self.assertEqual(message, "The processed PDF exceeds the supported 64 MiB output limit.")

    def test_legacy_merge_and_split_helpers_share_the_pdf_output_limit(self):
        first = self._create_sample_pdf()
        two_page = pikepdf.new()
        two_page.add_blank_page()
        two_page.add_blank_page()
        source = io.BytesIO()
        two_page.save(source)

        with patch.object(PdfSecurityEngine, "MAX_OUTPUT_BYTES", 32):
            merged = PdfSecurityEngine.merge_pdfs([first, first])
            split = PdfSecurityEngine.split_pdf(source.getvalue())

        for outcome in (merged, split):
            self.assertFalse(outcome[-2])
            self.assertEqual(outcome[-1], "The processed PDF exceeds the supported 64 MiB output limit.")

if __name__ == "__main__":
    unittest.main()
