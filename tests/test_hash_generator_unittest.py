import unittest

from officekit.engines.engine_devtools import PrivacySecurityEngine


class HashGeneratorEngineTests(unittest.TestCase):
    def test_known_digest_vectors_and_empty_input(self):
        hashes = PrivacySecurityEngine.generate_hashes("The quick brown fox jumps over the lazy dog")

        self.assertEqual(hashes["md5"], "9e107d9d372bb6826bd81d3542a419d6")
        self.assertEqual(hashes["sha1"], "2fd4e1c67a2d28fced849ee1bb76e7391b93eb12")
        self.assertEqual(hashes["sha256"], "d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592")
        self.assertEqual(hashes["crc32"], "414fa339")

        empty = PrivacySecurityEngine.generate_hashes("")
        self.assertEqual(empty["sha256"], "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        self.assertNotIn("hmac_sha256", empty)

    def test_hmac_known_vector(self):
        hashes = PrivacySecurityEngine.generate_hashes(
            "The quick brown fox jumps over the lazy dog", "key"
        )

        self.assertEqual(
            hashes["hmac_sha256"],
            "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8",
        )

    def test_hash_text_limit_counts_utf8_bytes_and_includes_boundary(self):
        at_limit = "é" * (PrivacySecurityEngine.MAX_HASH_INPUT_BYTES // 2)
        result = PrivacySecurityEngine.generate_hashes(at_limit)
        self.assertEqual(len(result["sha256"]), 64)

        with self.assertRaisesRegex(ValueError, "1,048,576 UTF-8 bytes"):
            PrivacySecurityEngine.generate_hashes(at_limit + "x")

    def test_hmac_secret_limit_counts_utf8_bytes_and_includes_boundary(self):
        at_limit = "é" * (PrivacySecurityEngine.MAX_HMAC_SECRET_BYTES // 2)
        result = PrivacySecurityEngine.generate_hashes("data", at_limit)
        self.assertEqual(len(result["hmac_sha256"]), 64)

        with self.assertRaisesRegex(ValueError, "4,096 UTF-8 bytes"):
            PrivacySecurityEngine.generate_hashes("data", at_limit + "x")

    def test_invalid_types_and_unencodable_surrogates_are_rejected(self):
        for text, secret in ((None, None), (7, None), (True, None), ("data", 7), ("data", False)):
            with self.subTest(text=text, secret=secret):
                with self.assertRaises(ValueError):
                    PrivacySecurityEngine.generate_hashes(text, secret)

        with self.assertRaisesRegex(ValueError, "valid UTF-8"):
            PrivacySecurityEngine.generate_hashes("\ud800")


if __name__ == "__main__":
    unittest.main()
