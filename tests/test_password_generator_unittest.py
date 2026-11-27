"""Bounded cryptographic password generation tests."""

import string
import math
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from officekit.engines.engine_devtools import PrivacySecurityEngine


class PasswordGeneratorTests(unittest.TestCase):
    def test_generates_at_minimum_and_maximum_length(self):
        for length in (12, 16, 256):
            with self.subTest(length=length):
                self.assertEqual(len(PrivacySecurityEngine.generate_password(length)), length)

    def test_symbol_free_mode_uses_only_letters_and_digits(self):
        password = PrivacySecurityEngine.generate_password(64, include_symbols=False)
        self.assertTrue(all(character in string.ascii_letters + string.digits for character in password))
        self.assertTrue(any(character in string.ascii_lowercase for character in password))
        self.assertTrue(any(character in string.ascii_uppercase for character in password))
        self.assertTrue(any(character in string.digits for character in password))

    def test_symbol_mode_uses_only_the_documented_alphabet(self):
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}<>?"
        password = PrivacySecurityEngine.generate_password(256, include_symbols=True)
        self.assertTrue(all(character in alphabet for character in password))
        self.assertTrue(any(character in PrivacySecurityEngine.PASSWORD_SYMBOLS for character in password))

    def test_rejects_out_of_range_and_non_integer_lengths(self):
        for length in (0, 11, 257, 10**100, True, 12.0, "16", None):
            with self.subTest(length=length), self.assertRaises(ValueError):
                PrivacySecurityEngine.generate_password(length)

    def test_rejects_non_boolean_symbol_switch(self):
        for include_symbols in (1, 0, "false", None):
            with self.subTest(include_symbols=include_symbols), self.assertRaises(ValueError):
                PrivacySecurityEngine.generate_password(16, include_symbols=include_symbols)

    def test_search_space_bits_match_the_exact_valid_password_space(self):
        for include_symbols in (False, True):
            with self.subTest(include_symbols=include_symbols):
                classes = [26, 26, 10] + ([len(PrivacySecurityEngine.PASSWORD_SYMBOLS)] if include_symbols else [])
                alphabet_size = sum(classes)
                valid_count = sum(
                    (-1 if mask.bit_count() % 2 else 1)
                    * (alphabet_size - sum(size for index, size in enumerate(classes) if mask & (1 << index))) ** 12
                    for mask in range(1 << len(classes))
                )
                expected = math.log2(valid_count)
                self.assertAlmostEqual(
                    PrivacySecurityEngine.password_search_space_bits(12, include_symbols), expected
                )

    def test_search_space_validates_the_same_bounds_as_generation(self):
        for length, include_symbols in ((11, True), (257, False), (12, 1), (True, False)):
            with self.subTest(length=length, include_symbols=include_symbols), self.assertRaises(ValueError):
                PrivacySecurityEngine.password_search_space_bits(length, include_symbols)

    def test_rejection_sampling_retries_when_a_required_class_is_missing(self):
        choices = iter("a" * 12 + "abcDEF123!@x")
        with patch("officekit.engines.engine_devtools.secrets.choice", side_effect=lambda alphabet: next(choices)):
            password = PrivacySecurityEngine.generate_password(12, include_symbols=True)
        self.assertEqual(password, "abcDEF123!@x")

    def test_eff_wordlist_has_the_documented_size_and_known_dice_mapping(self):
        words = PrivacySecurityEngine.passphrase_wordlist()
        self.assertEqual(len(words), 7776)
        self.assertEqual(len(set(words)), 7776)
        self.assertEqual(words[0], "abacus")
        dice_code_index = sum((int(digit) - 1) * 6 ** (4 - index) for index, digit in enumerate("43463"))
        self.assertEqual(words[dice_code_index], "panoramic")
        self.assertIn("drop-down", words)
        self.assertIn("felt-tip", words)
        self.assertIn("t-shirt", words)
        self.assertIn("yo-yo", words)

    def test_passphrase_uses_uniform_secure_choices_and_configured_separator(self):
        words = PrivacySecurityEngine.passphrase_wordlist()
        selected = [words[0], words[1], words[2], words[3], words[4], words[5]]
        with patch("officekit.engines.engine_devtools.secrets.choice", side_effect=selected) as choice:
            result = PrivacySecurityEngine.generate_passphrase(6, separator="_")
        self.assertEqual(result, "abacus_abdomen_abdominal_abide_abiding_ability")
        self.assertEqual(choice.call_count, 6)
        for index, call in enumerate(choice.call_args_list):
            self.assertEqual(call.args, (words,))

    def test_passphrase_search_space_is_exact_for_its_selected_word_count(self):
        expected = 6 * math.log2(7776)
        self.assertAlmostEqual(PrivacySecurityEngine.passphrase_search_space_bits(6), expected)
        self.assertAlmostEqual(PrivacySecurityEngine.passphrase_search_space_bits(12), 2 * expected)

    def test_passphrase_rejects_unsafe_counts_and_separators(self):
        for word_count in (0, 5, 13, True, 6.0, "6", None):
            with self.subTest(word_count=word_count), self.assertRaises(ValueError):
                PrivacySecurityEngine.generate_passphrase(word_count)
        for separator in ("", "-", "__", "\n", 1, None):
            with self.subTest(separator=separator), self.assertRaises(ValueError):
                PrivacySecurityEngine.generate_passphrase(6, separator=separator)

    def test_malformed_or_missing_wordlist_fails_closed(self):
        with patch.object(PrivacySecurityEngine, "EFF_WORDLIST_PATH", Path("/missing/eff-words.txt")):
            with self.assertRaisesRegex(ValueError, "word list is unavailable"):
                PrivacySecurityEngine.passphrase_wordlist()

        with patch.object(PrivacySecurityEngine, "EFF_WORDLIST_PATH", Path(__file__)):
            with self.assertRaisesRegex(ValueError, "word list is invalid"):
                PrivacySecurityEngine.passphrase_wordlist()

    def test_wordlist_with_invalid_utf8_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            invalid_path = Path(temp_directory) / "invalid.txt"
            invalid_path.write_bytes(b"\xff\xfe")
            with patch.object(PrivacySecurityEngine, "EFF_WORDLIST_PATH", invalid_path):
                with self.assertRaisesRegex(ValueError, "word list is invalid"):
                    PrivacySecurityEngine.passphrase_wordlist()

    def test_frozen_sidecar_loads_the_wordlist_from_its_resource_directory(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            wordlist_directory = Path(temp_directory) / "wordlists"
            wordlist_directory.mkdir()
            shutil.copyfile(PrivacySecurityEngine.EFF_WORDLIST_PATH, wordlist_directory / PrivacySecurityEngine.EFF_WORDLIST_FILENAME)
            with patch.object(__import__("sys"), "_MEIPASS", temp_directory, create=True):
                words = PrivacySecurityEngine.passphrase_wordlist()
        self.assertEqual(len(words), PrivacySecurityEngine.EFF_WORDLIST_SIZE)


if __name__ == "__main__":
    unittest.main()
