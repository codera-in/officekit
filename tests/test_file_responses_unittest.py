"""Download headers remain portable, bounded and safe for untrusted filenames."""

import unittest
from unittest.mock import patch

import officekit.engines.engine_file_responses as engine_file_responses
from officekit.engines.engine_file_responses import MAX_ATTACHMENT_NAME_LENGTH, content_disposition_attachment


class ContentDispositionTests(unittest.TestCase):
    def test_windows_and_posix_paths_keep_only_the_final_filename(self):
        for filename in ("/private/reports/monthly.csv", r"C:\private\reports\monthly.csv"):
            with self.subTest(filename=filename):
                header = content_disposition_attachment(filename)
                self.assertEqual(
                    header,
                    'attachment; filename="monthly.csv"; filename*=UTF-8\'\'monthly.csv',
                )
                self.assertNotIn("private", header)

    def test_unicode_filename_has_ascii_fallback_and_encoded_original(self):
        header = content_disposition_attachment("résumé 📄.pdf")

        self.assertIn('filename="resume_.pdf"', header)
        self.assertIn("filename*=UTF-8''r%C3%A9sum%C3%A9%20%F0%9F%93%84.pdf", header)
        self.assertTrue(header.isascii())

    def test_control_characters_quotes_and_header_delimiters_cannot_inject_headers(self):
        header = content_disposition_attachment('report\r\nX-Injected: yes"; filename="bad.csv')

        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)
        self.assertTrue(header.startswith('attachment; filename="'))
        self.assertEqual(header.count('filename="'), 1)
        self.assertNotIn("X-Injected:", header)
        self.assertIn("%22", header)

    def test_long_filename_is_bounded_and_keeps_its_suffix(self):
        header = content_disposition_attachment(f"{'a' * 500}.xlsx")
        fallback = header.split('filename="', 1)[1].split('"', 1)[0]
        encoded = header.split("filename*=UTF-8''", 1)[1]

        self.assertLessEqual(len(fallback), MAX_ATTACHMENT_NAME_LENGTH)
        self.assertLessEqual(len(encoded), MAX_ATTACHMENT_NAME_LENGTH * 12)
        self.assertTrue(fallback.endswith(".xlsx"))
        self.assertTrue(encoded.endswith(".xlsx"))

    def test_unicode_normalization_expansion_keeps_the_ascii_fallback_suffix(self):
        header = content_disposition_attachment(f"{'ﬃ' * 200}.pdf")
        fallback = header.split('filename="', 1)[1].split('"', 1)[0]

        self.assertLessEqual(len(fallback), MAX_ATTACHMENT_NAME_LENGTH)
        self.assertTrue(fallback.endswith(".pdf"))

    def test_oversized_input_is_bounded_before_unicode_normalization(self):
        original_normalize = engine_file_responses.unicodedata.normalize
        with patch("officekit.engines.engine_file_responses.unicodedata.normalize", wraps=original_normalize) as normalize:
            header = content_disposition_attachment(f"{'a' * 100_000}.pdf")

        self.assertTrue(header.endswith("filename*=UTF-8''" + "a" * 176 + ".pdf"))
        self.assertLessEqual(max(len(call.args[1]) for call in normalize.call_args_list), MAX_ATTACHMENT_NAME_LENGTH)

    def test_empty_or_non_text_names_fall_back_to_download(self):
        for filename in ("", None, "../..", "📄"):
            with self.subTest(filename=filename):
                header = content_disposition_attachment(filename)
                self.assertTrue(header.startswith('attachment; filename="download'))


if __name__ == "__main__":
    unittest.main()
