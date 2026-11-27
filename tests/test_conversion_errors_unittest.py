"""The conversion error sent to callers never includes parser/runtime details."""

import unittest

from officekit.engines.engine_conversion_errors import ConversionInputError


class ConversionInputErrorTests(unittest.TestCase):
    def test_public_message_is_stable_and_contains_no_exception_details(self):
        private_path = "/Users/private/customer statement.json"
        error = ConversionInputError(private_path)

        self.assertEqual(
            str(error),
            "The file or requested format cannot be converted. Check the input and try again.",
        )
        self.assertNotIn(private_path, str(error))


if __name__ == "__main__":
    unittest.main()
