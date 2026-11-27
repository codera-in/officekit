"""Content-versus-extension tests for the selected-file type detector."""

import unittest

from officekit.engines.engine_file_type import FileTypeDetector


class FileTypeDetectorTests(unittest.TestCase):
    @staticmethod
    def _ftyp(brand: bytes, compatible: tuple[bytes, ...] = ()) -> bytes:
        brands = b"".join(compatible)
        box_size = 16 + len(brands)
        return box_size.to_bytes(4, "big") + b"ftyp" + brand + b"\x00\x00\x00\x00" + brands

    def test_recognizes_common_signatures_independently_of_the_extension(self):
        bitmap = bytearray(26)
        bitmap[:2] = b"BM"
        bitmap[2:6] = (26).to_bytes(4, "little")
        bitmap[10:14] = (26).to_bytes(4, "little")
        bitmap[14:18] = (12).to_bytes(4, "little")
        cases = (
            ("report.pdf", b"%PDF-1.7\n", "PDF", "application/pdf", True),
            ("picture.jpg", b"\x89PNG\r\n\x1a\nrest", "PNG", "image/png", False),
            ("photo.bin", b"\xff\xd8\xff\xe0\x00\x10JFIF", "JPEG", "image/jpeg", None),
            ("image.webp", b"RIFF\x08\x00\x00\x00WEBP", "WebP", "image/webp", True),
            ("archive.png", b"PK\x03\x04\x00\x00", "ZIP archive", "application/zip", False),
            ("bitmap.bmp", bytes(bitmap), "BMP", "image/bmp", True),
        )
        for filename, header, label, mime, matches in cases:
            with self.subTest(filename=filename):
                result = FileTypeDetector.detect(filename, header)
                self.assertEqual(result["detected_type"], label)
                self.assertEqual(result["mime_type"], mime)
                self.assertEqual(result["extension_matches"], matches)
                self.assertEqual(result["method"], "magic-bytes+utf8")

    def test_truncated_bitmap_magic_is_not_mistaken_for_an_image(self):
        result = FileTypeDetector.detect("broken.bmp", b"BM", file_size=2)

        self.assertEqual(result["detected_type"], "Unknown binary")
        self.assertFalse(result["extension_matches"])

    def test_iso_base_media_brands_distinguish_images_audio_and_video(self):
        cases = (
            ("photo.heic", b"heic", (), "HEIC image", "image/heic", True),
            ("photo.heif", b"mif1", (b"heic",), "HEIC image", "image/heic", True),
            ("photo.avif", b"avif", (), "AVIF image", "image/avif", True),
            ("clip.mov", b"isom", (b"qt  ",), "QuickTime video", "video/quicktime", True),
            ("audio.m4a", b"M4A ", (), "M4A audio", "audio/mp4", True),
            ("clip.mp4", b"isom", (b"mp42",), "MP4 media", "application/mp4", True),
            ("clip.m4v", b"M4V ", (), "MP4 video", "video/mp4", True),
            ("photo.avif", b"mif1", (b"avif",), "AVIF image", "image/avif", True),
            ("wrong.mp4", b"heic", (), "HEIC image", "image/heic", False),
        )
        for filename, brand, compatible, label, mime, matches in cases:
            with self.subTest(filename=filename, brand=brand):
                result = FileTypeDetector.detect(filename, self._ftyp(brand, compatible))
                self.assertEqual(result["detected_type"], label)
                self.assertEqual(result["mime_type"], mime)
                self.assertEqual(result["extension_matches"], matches)

    def test_malformed_iso_base_media_headers_are_not_claimed_as_mp4(self):
        for filename, header, file_size in (
            ("short.mp4", b"\x00\x00\x00\x08ftyp", 8),
            ("short.mp4", b"\x00\x00\x00\x10ftypisom", 16),
            ("short.mp4", b"\x00\x00\x00\x20ftypisom\x00\x00\x00\x00", 20),
        ):
            with self.subTest(header=header):
                result = FileTypeDetector.detect(filename, header, file_size=file_size)
                self.assertEqual(result["detected_type"], "Unknown binary")
                self.assertIsNone(result["extension_matches"])

    def test_iso_base_media_supports_extended_size_and_unknown_brands_conservatively(self):
        extended_ftyp = (
            b"\x00\x00\x00\x01ftyp"
            + (24).to_bytes(8, "big")
            + b"avif\x00\x00\x00\x00"
        )
        extended = FileTypeDetector.detect("photo.avif", extended_ftyp)
        unknown = FileTypeDetector.detect("file.mp4", self._ftyp(b"zzzz"))

        self.assertEqual(extended["detected_type"], "AVIF image")
        self.assertTrue(extended["extension_matches"])
        self.assertEqual(unknown["detected_type"], "ISO base media")
        self.assertEqual(unknown["mime_type"], "application/octet-stream")
        self.assertIsNone(unknown["extension_matches"])

    def test_text_and_empty_files_are_distinguished_from_unknown_binary(self):
        text = FileTypeDetector.detect("notes.txt", "Hello café\n".encode("utf-8"))
        csv_text = FileTypeDetector.detect("table.csv", b"name,value\na,1\n")
        empty = FileTypeDetector.detect("empty.bin", b"", file_size=0)
        binary = FileTypeDetector.detect("mystery.dat", b"\x00\xff\x02\x80", file_size=4)
        invalid_utf8 = FileTypeDetector.detect("broken.txt", b"\xc3", file_size=1)

        self.assertEqual(text["detected_type"], "Text")
        self.assertTrue(text["extension_matches"])
        self.assertEqual(csv_text["mime_type"], "text/plain")
        self.assertIsNone(csv_text["extension_matches"])
        self.assertEqual(empty["detected_type"], "Empty file")
        self.assertEqual(empty["mime_type"], "application/x-empty")
        self.assertIsNone(empty["extension_matches"])
        self.assertEqual(binary["detected_type"], "Unknown binary")
        self.assertIsNone(binary["extension_matches"])
        self.assertEqual(invalid_utf8["detected_type"], "Unknown binary")

    def test_utf8_codepoint_split_at_the_header_limit_is_handled_as_truncated_text(self):
        header = b"a" * (FileTypeDetector.MAX_HEADER_BYTES - 1) + b"\xc3"

        result = FileTypeDetector.detect("long.txt", header, file_size=len(header) + 3)

        self.assertEqual(result["detected_type"], "Text")
        self.assertTrue(result["extension_matches"])

    def test_long_but_bounded_extension_is_preserved_without_changing_detection(self):
        filename = "file." + ("x" * 1000)

        result = FileTypeDetector.detect(filename, b"%PDF-1.7\n", file_size=len(b"%PDF-1.7\n"))

        self.assertEqual(len(result["extension"]), 1001)  # The leading dot is preserved.
        self.assertEqual(result["detected_type"], "PDF")
        self.assertIsNone(result["extension_matches"])

    def test_rejects_invalid_or_oversized_detection_inputs(self):
        for filename, prefix, size in (
            ("../secret.pdf", b"%PDF", 4),
            ("", b"", 0),
            ("file.txt", "not bytes", 10),
            ("file.txt", b"x" * 16_385, 16_385),
            ("file.txt", b"x", -1),
            ("file.txt", b"x", True),
        ):
            with self.subTest(filename=filename, size=size), self.assertRaises(ValueError):
                FileTypeDetector.detect(filename, prefix, file_size=size)


if __name__ == "__main__":
    unittest.main()
