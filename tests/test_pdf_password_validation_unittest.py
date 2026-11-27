"""PDF passwords have explicit empty, type, character and byte boundaries."""

import unittest
import unicodedata

from officekit.engines.engine_pdf_validation import (
    MAX_PDF_PASSWORD_BYTES,
    MAX_PDF_PASSWORD_CHARACTERS,
    is_valid_pdf_password,
)


class PdfPasswordValidationTests(unittest.TestCase):
    def test_empty_password_is_allowed_only_for_unlock(self):
        self.assertTrue(is_valid_pdf_password("", require_non_empty=False))
        self.assertFalse(is_valid_pdf_password("", require_non_empty=True))

    def test_password_accepts_exact_127_byte_limit_for_ascii_and_unicode(self):
        ascii_password = "x" * MAX_PDF_PASSWORD_CHARACTERS
        unicode_password = "😀" * 31 + "abc"

        self.assertEqual(len(ascii_password.encode("utf-8")), MAX_PDF_PASSWORD_BYTES)
        self.assertEqual(len(unicode_password.encode("utf-8")), MAX_PDF_PASSWORD_BYTES)
        self.assertTrue(is_valid_pdf_password(ascii_password, require_non_empty=True))
        self.assertTrue(is_valid_pdf_password(unicode_password, require_non_empty=True))

    def test_password_rejects_either_character_or_utf8_byte_overflow(self):
        self.assertFalse(is_valid_pdf_password("x" * (MAX_PDF_PASSWORD_CHARACTERS + 1), require_non_empty=True))
        self.assertFalse(is_valid_pdf_password("😀" * 32, require_non_empty=True))

    def test_password_rejects_nfkc_expansion_over_the_pdf_byte_limit(self):
        password = "ﷺ" * 16

        self.assertLessEqual(len(password.encode("utf-8")), MAX_PDF_PASSWORD_BYTES)
        self.assertGreater(len(unicodedata.normalize("NFKC", password).encode("utf-8")), MAX_PDF_PASSWORD_BYTES)
        self.assertFalse(is_valid_pdf_password(password, require_non_empty=True))

    def test_password_over_character_limit_is_rejected(self):
        password = "x" * (MAX_PDF_PASSWORD_CHARACTERS + 1)

        self.assertFalse(is_valid_pdf_password(password, require_non_empty=True))
        self.assertFalse(is_valid_pdf_password(password, require_non_empty=False))

    def test_wrong_types_and_unpaired_surrogates_are_rejected(self):
        for value in (None, 123, True, b"password", "\ud800"):
            with self.subTest(value=repr(value)):
                self.assertFalse(is_valid_pdf_password(value, require_non_empty=True))


if __name__ == "__main__":
    unittest.main()
