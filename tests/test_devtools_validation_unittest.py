import base64
import json
import unittest
from decimal import Decimal
from unittest.mock import patch

from officekit.engines.engine_devtools import DevToolsEngine


class DeveloperToolsValidationTests(unittest.TestCase):
    def test_text_limit_accepts_exact_utf8_boundary_and_rejects_one_byte_over(self):
        exact = "é" * (DevToolsEngine.MAX_TEXT_BYTES // 2)
        self.assertEqual(DevToolsEngine.base64_encode(exact), base64.b64encode(exact.encode()).decode())

        with self.assertRaisesRegex(ValueError, "1,048,576 UTF-8 bytes"):
            DevToolsEngine.base64_encode(exact + "x")

    def test_every_text_engine_rejects_wrong_types_and_invalid_unicode(self):
        operations = (
            DevToolsEngine.format_json,
            DevToolsEngine.json_to_yaml,
            DevToolsEngine.yaml_to_json,
            DevToolsEngine.base64_encode,
            DevToolsEngine.base64_decode,
            DevToolsEngine.url_encode,
            DevToolsEngine.url_decode,
            DevToolsEngine.decode_jwt,
        )
        for operation in operations:
            with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                operation(42)
            with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                operation("\ud800")

    def test_invalid_base64_alphabet_and_utf8_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "valid Base64"):
            DevToolsEngine.base64_decode("a?==")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            DevToolsEngine.base64_decode("/w==")
        self.assertEqual(DevToolsEngine.base64_decode(""), "")

    def test_json_to_yaml_validates_json_before_loading_optional_serializer(self):
        with self.assertRaises(ValueError):
            DevToolsEngine.json_to_yaml("{")

    def test_json_text_operations_reject_duplicate_keys_and_non_finite_numbers(self):
        invalid_values = (
            '{"value": 1, "value": 2}',
            '{"outer": {"value": 1, "value": 2}}',
            '{"value": NaN}',
            '{"value": Infinity}',
            '{"value": -Infinity}',
        )
        for raw_json in invalid_values:
            for operation in (DevToolsEngine.format_json, DevToolsEngine.json_to_yaml):
                with self.subTest(value=raw_json, operation=operation.__name__), self.assertRaises(ValueError):
                    operation(raw_json)

    def test_json_and_yaml_conversions_preserve_decimal_precision_and_exponents(self):
        raw_json = '{"precise": 0.12345678901234567890123456789, "large": 1e999, "small": 1e-9999}'
        expected = json.loads(raw_json, parse_float=Decimal)
        formatted = DevToolsEngine.format_json(raw_json)
        self.assertEqual(json.loads(formatted, parse_float=Decimal), expected)
        converted = DevToolsEngine.yaml_to_json(DevToolsEngine.json_to_yaml(raw_json))
        self.assertEqual(json.loads(converted, parse_float=Decimal), expected)

    def test_json_text_operations_reject_escaped_unpaired_surrogates(self):
        raw_json = '{"value": "\\ud800"}'
        for operation in (DevToolsEngine.format_json, DevToolsEngine.json_to_yaml):
            with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                operation(raw_json)

    def test_json_parser_normalizes_valid_escaped_surrogate_pairs(self):
        raw_json = '{"value": "\\ud83d\\ude00"}'
        self.assertEqual(DevToolsEngine._parse_json(raw_json), {"value": "😀"})

    def test_strict_json_parser_enforces_exact_depth_and_node_bounds(self):
        at_depth_limit = "[" * DevToolsEngine.MAX_JSON_DEPTH + "0" + "]" * DevToolsEngine.MAX_JSON_DEPTH
        over_depth_limit = "[" * (DevToolsEngine.MAX_JSON_DEPTH + 1) + "0" + "]" * (DevToolsEngine.MAX_JSON_DEPTH + 1)
        parsed = DevToolsEngine._parse_json(at_depth_limit)
        for _ in range(DevToolsEngine.MAX_JSON_DEPTH):
            self.assertEqual(len(parsed), 1)
            parsed = parsed[0]
        self.assertEqual(parsed, 0)
        with self.assertRaisesRegex(ValueError, "nesting limit"):
            DevToolsEngine._parse_json(over_depth_limit)

        at_node_limit = "[" + ",".join(["0"] * (DevToolsEngine.MAX_JSON_NODES - 1)) + "]"
        over_node_limit = "[" + ",".join(["0"] * DevToolsEngine.MAX_JSON_NODES) + "]"
        self.assertEqual(len(DevToolsEngine._parse_json(at_node_limit)), DevToolsEngine.MAX_JSON_NODES - 1)
        with self.assertRaisesRegex(ValueError, "node limit"):
            DevToolsEngine._parse_json(over_node_limit)

    def test_strict_json_parser_normalizes_syntax_and_recursion_errors(self):
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            DevToolsEngine._parse_json("{")
        with patch("officekit.engines.engine_devtools.json.loads", side_effect=RecursionError("deep")):
            with self.assertRaisesRegex(ValueError, "valid JSON"):
                DevToolsEngine._parse_json("{}")

    def test_yaml_to_json_preserves_nested_json_values_and_unicode(self):
        result = DevToolsEngine.yaml_to_json(
            "name: OfficeKit\ncount: 2\nactive: true\nratio: 1.25\nitems:\n  - café\n  - null\n"
        )
        self.assertEqual(
            result,
            '{\n  "active": true,\n  "count": 2,\n  "items": [\n    "café",\n    null\n  ],\n  "name": "OfficeKit",\n  "ratio": 1.25\n}',
        )

    def test_yaml_to_json_rejects_ambiguous_or_non_json_yaml(self):
        invalid_values = (
            "value: one\nvalue: two\n",
            "value: .nan\n",
            "value: .inf\n",
            "<<: value\n",
            "first: &value text\nsecond: *value\n",
            "---\na: 1\n---\na: 2\n",
            "value: !!python/object/apply:os.system ['true']\n",
            "value: !!binary YQ==\n",
            "value: !!set {one: null}\n",
            "? [unhashable, key]\n: value\n",
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                DevToolsEngine.yaml_to_json(value)

    def test_yaml_to_json_uses_yaml_12_scalar_resolution_to_preserve_text(self):
        result = DevToolsEngine.yaml_to_json(
            "values:\n  - yes\n  - no\n  - on\n  - off\n  - TrUe\n  - 2026-10-07\n  - 0123\n"
            "  - 1_000\n  - 0b101\n  - 0x10\n  - 0o17\n  - 1_2.5_0\n"
        )
        self.assertEqual(
            json.loads(result),
            {"values": ["yes", "no", "on", "off", "TrUe", "2026-10-07", "0123", 1000, 5, 16, 15, 12.5]},
        )

    def test_json_yaml_round_trip_preserves_strings_and_numeric_types(self):
        source = {"count": 12, "enabled": True, "text": ["yes", "on", "2026-10-07", "0123"]}
        as_json = json.dumps(source, ensure_ascii=False)
        as_yaml = DevToolsEngine.json_to_yaml(as_json)
        self.assertEqual(json.loads(DevToolsEngine.yaml_to_json(as_yaml)), source)

    def test_yaml_parser_failures_become_safe_value_errors(self):
        import yaml

        for failure in (yaml.YAMLError("bad input"), TypeError("bad value"), RecursionError("deep input")):
            with self.subTest(error=type(failure).__name__), patch("yaml.load", side_effect=failure):
                with self.assertRaisesRegex(ValueError, "JSON-compatible"):
                    DevToolsEngine.yaml_to_json("value: 1\n")

    def test_yaml_to_json_enforces_utf8_byte_limit_and_scalar_input(self):
        exact = "é" * (DevToolsEngine.MAX_TEXT_BYTES // 2)
        self.assertEqual(DevToolsEngine.yaml_to_json(exact), json.dumps(exact, ensure_ascii=False))
        with self.assertRaisesRegex(ValueError, "1,048,576 UTF-8 bytes"):
            DevToolsEngine.yaml_to_json(exact + "x")
        for value in (42, "\ud800"):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                DevToolsEngine.yaml_to_json(value)

    def test_yaml_to_json_rejects_depth_and_node_count_overruns(self):
        deep_yaml = "".join(
            f"{'  ' * level}value:\n" for level in range(DevToolsEngine.MAX_YAML_DEPTH)
        ) + f"{'  ' * DevToolsEngine.MAX_YAML_DEPTH}null\n"
        many_nodes_yaml = "- 1\n" * DevToolsEngine.MAX_YAML_NODES
        for value in (deep_yaml, many_nodes_yaml):
            with self.subTest(length=len(value)), self.assertRaisesRegex(ValueError, "JSON-compatible"):
                DevToolsEngine.yaml_to_json(value)

    def test_url_decode_rejects_malformed_percent_escapes_and_invalid_utf8(self):
        for text in ("%", "%2", "%2G", "%FF"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                DevToolsEngine.url_decode(text)
        self.assertEqual(DevToolsEngine.url_decode("foo%20bar%3D1"), "foo bar=1")

    def test_url_component_encoding_round_trips_reserved_unicode_and_plus_characters(self):
        original = "folder/file name+a?b=c&city=東京"
        encoded = "folder%2Ffile%20name%2Ba%3Fb%3Dc%26city%3D%E6%9D%B1%E4%BA%AC"
        self.assertEqual(DevToolsEngine.url_encode(original), encoded)
        self.assertEqual(DevToolsEngine.url_decode(encoded), original)
        self.assertEqual(DevToolsEngine.url_encode("AZaz09-_.~"), "AZaz09-_.~")
        self.assertEqual(DevToolsEngine.url_decode("a+b"), "a+b")

    def test_jwt_must_have_valid_base64url_segments_and_object_json(self):
        valid_header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
        valid_payload = base64.urlsafe_b64encode(b'{"sub":"local"}').decode().rstrip("=")
        result = DevToolsEngine.decode_jwt(f"{valid_header}.{valid_payload}.c2ln")
        self.assertEqual(result["header"], {"alg": "none"})
        self.assertEqual(result["payload"], {"sub": "local"})
        self.assertIs(result["is_verified"], False)

        for malformed in (
            "one.two",
            "?.e30.c2ln",
            "bnVsbA.e30.c2ln",  # JSON null is not a JWT header object
            "e30.W10.c2ln",  # JSON array is not a JWT payload object
            "e30.bm90LWpzb24.c2ln",
            "e30.e30.signature",  # invalid Base64URL signature is rejected
        ):
            with self.subTest(token=malformed), self.assertRaises(ValueError):
                DevToolsEngine.decode_jwt(malformed)

    def test_jwt_rejects_duplicate_keys_nonfinite_numbers_and_noncanonical_base64url(self):
        def encode_segment(value):
            return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

        duplicate_header = encode_segment('{"alg":"HS256","alg":"none"}')
        duplicate_payload = encode_segment('{"sub":"first","sub":"second"}')
        nonfinite_payload = encode_segment('{"exp":NaN}')
        tokens = (
            f"{duplicate_header}.e30.c2ln",
            f"e30.{duplicate_payload}.c2ln",
            f"e30.{nonfinite_payload}.c2ln",
            "e31.e30.c2ln",  # Same bytes as {} but non-zero unused Base64URL pad bits.
        )
        for token in tokens:
            with self.subTest(token=token), self.assertRaises(ValueError):
                DevToolsEngine.decode_jwt(token)

    def test_jwt_rejects_nested_claims_over_the_shared_json_limit(self):
        payload = '{"nested":' + "[" * (DevToolsEngine.MAX_JSON_DEPTH + 1) + "0" + "]" * (DevToolsEngine.MAX_JSON_DEPTH + 1) + "}"
        segment = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        with self.assertRaisesRegex(ValueError, "valid bounded JSON"):
            DevToolsEngine.decode_jwt(f"e30.{segment}.c2ln")

    def test_json_indent_is_bounded_and_rejects_boolean_or_non_integer_values(self):
        self.assertEqual(DevToolsEngine.format_json('{"b":2}', indent=0), '{\n"b": 2\n}')
        for indent in (-1, 9, True, 1.5):
            with self.subTest(indent=indent), self.assertRaises(ValueError):
                DevToolsEngine.format_json("{}", indent=indent)


if __name__ == "__main__":
    unittest.main()
