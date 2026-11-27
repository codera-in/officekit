"""
OfficeKit - Developer Tools & Privacy Security Engine (Pillars 7 & 8)
Supports:
- JSON / YAML / CSV format, minify & cross-conversions
- Base64 / URL string encode & decode
- Local JWT Inspector (Header, Payload, unverified notice)
- Multi-algorithm cryptographic hash generation (MD5, SHA-1, SHA-256, SHA-512, CRC32, HMAC)
- Cryptographically secure password & token generator
"""

import json
import base64
import urllib.parse
import hashlib
import zlib
import hmac
import secrets
import string
import math
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Any, Optional


class DevToolsEngine:

    MAX_TEXT_BYTES = 1_048_576
    MAX_JSON_DEPTH = 128
    MAX_JSON_NODES = 100_000
    MAX_YAML_DEPTH = 128
    MAX_YAML_NODES = 100_000

    @staticmethod
    def _text_bytes(text: str, label: str = "Input") -> bytes:
        if not isinstance(text, str):
            raise ValueError(f"{label} must be a string")
        if len(text) > DevToolsEngine.MAX_TEXT_BYTES:
            raise ValueError(f"{label} must not exceed 1,048,576 UTF-8 bytes")
        try:
            encoded = text.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError(f"{label} must contain valid UTF-8 text") from error
        if len(encoded) > DevToolsEngine.MAX_TEXT_BYTES:
            raise ValueError(f"{label} must not exceed 1,048,576 UTF-8 bytes")
        return encoded

    @staticmethod
    def _parse_json(raw_json: str):
        DevToolsEngine._text_bytes(raw_json, "JSON input")

        def reject_constant(_constant):
            raise ValueError("JSON numbers must be finite")

        def reject_duplicate_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("JSON object keys must be unique")
                result[key] = value
            return result

        def validate_text(value):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as error:
                raise ValueError("JSON strings must contain valid Unicode text") from error

        def parse_finite_decimal(value):
            return Decimal(value)

        try:
            data = json.loads(
                raw_json,
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_constant,
                parse_float=parse_finite_decimal,
            )
        except (json.JSONDecodeError, RecursionError) as error:
            raise ValueError("Input must be valid JSON within supported limits") from error

        pending = [(data, 0)]
        node_count = 0
        while pending:
            value, depth = pending.pop()
            node_count += 1
            if depth > DevToolsEngine.MAX_JSON_DEPTH:
                raise ValueError("JSON nesting limit exceeded")
            if node_count > DevToolsEngine.MAX_JSON_NODES:
                raise ValueError("JSON node limit exceeded")
            if isinstance(value, dict):
                for key, child in value.items():
                    validate_text(key)
                    pending.append((child, depth + 1))
            elif isinstance(value, list):
                pending.extend((child, depth + 1) for child in value)
            elif isinstance(value, str):
                validate_text(value)
        return data

    @staticmethod
    def _dump_json(value, indent: int = 2, sort_keys: bool = True, ensure_ascii: bool = True) -> str:
        def render(item, depth):
            if item is None:
                return "null"
            if item is True:
                return "true"
            if item is False:
                return "false"
            if isinstance(item, Decimal):
                if not item.is_finite():
                    raise ValueError("JSON numbers must be finite")
                return str(item)
            if type(item) is int:
                return str(item)
            if isinstance(item, (float,)):
                if not math.isfinite(item):
                    raise ValueError("JSON numbers must be finite")
                return json.dumps(item, allow_nan=False)
            if isinstance(item, str):
                return json.dumps(item, ensure_ascii=ensure_ascii)
            if isinstance(item, list):
                if not item:
                    return "[]"
                pad = " " * (indent * (depth + 1))
                close_pad = " " * (indent * depth)
                return "[\n" + ",\n".join(pad + render(child, depth + 1) for child in item) + "\n" + close_pad + "]"
            if isinstance(item, dict):
                if not item:
                    return "{}"
                keys = sorted(item) if sort_keys else item.keys()
                pad = " " * (indent * (depth + 1))
                close_pad = " " * (indent * depth)
                entries = (
                    pad + json.dumps(key, ensure_ascii=ensure_ascii) + ": " + render(item[key], depth + 1)
                    for key in keys
                )
                return "{\n" + ",\n".join(entries) + "\n" + close_pad + "}"
            raise ValueError("Value is not representable in JSON")

        return render(value, 0)

    @staticmethod
    def format_json(raw_json: str, indent: int = 2) -> str:
        if type(indent) is not int or not 0 <= indent <= 8:
            raise ValueError("JSON indentation must be an integer from 0 to 8")
        data = DevToolsEngine._parse_json(raw_json)
        return DevToolsEngine._dump_json(data, indent=indent, sort_keys=True)

    @staticmethod
    def json_to_yaml(raw_json: str) -> str:
        data = DevToolsEngine._parse_json(raw_json)
        import yaml

        class DecimalSafeDumper(yaml.SafeDumper):
            pass

        DecimalSafeDumper.add_representer(
            Decimal,
            lambda dumper, value: dumper.represent_scalar("tag:yaml.org,2002:float", str(value)),
        )
        return yaml.dump(data, Dumper=DecimalSafeDumper, sort_keys=True)

    @staticmethod
    def yaml_to_json(raw_yaml: str) -> str:
        DevToolsEngine._text_bytes(raw_yaml, "YAML input")
        import yaml

        class BoundedSafeLoader(yaml.SafeLoader):
            yaml_implicit_resolvers = {
                first_character: [
                    (tag, pattern)
                    for tag, pattern in resolvers
                    if tag not in {
                        "tag:yaml.org,2002:bool",
                        "tag:yaml.org,2002:int",
                        "tag:yaml.org,2002:float",
                        "tag:yaml.org,2002:timestamp",
                    }
                ]
                for first_character, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
            }

            def __init__(self, stream):
                self._officekit_depth = 0
                self._officekit_nodes = 0
                super().__init__(stream)

            def compose_node(self, parent, index):
                if self.check_event(yaml.AliasEvent):
                    raise yaml.YAMLError("YAML aliases are not supported")
                self._officekit_depth += 1
                self._officekit_nodes += 1
                try:
                    if self._officekit_depth > DevToolsEngine.MAX_YAML_DEPTH:
                        raise yaml.YAMLError("YAML nesting limit exceeded")
                    if self._officekit_nodes > DevToolsEngine.MAX_YAML_NODES:
                        raise yaml.YAMLError("YAML node limit exceeded")
                    return super().compose_node(parent, index)
                finally:
                    self._officekit_depth -= 1

            def construct_mapping(self, node, deep=False):
                mapping = {}
                for key_node, value_node in node.value:
                    if key_node.tag == "tag:yaml.org,2002:merge":
                        raise yaml.YAMLError("YAML merge keys are not supported")
                    key = self.construct_object(key_node, deep=deep)
                    if not isinstance(key, str) or key in mapping:
                        raise yaml.YAMLError("YAML mapping keys must be unique strings")
                    mapping[key] = self.construct_object(value_node, deep=deep)
                return mapping

        BoundedSafeLoader.add_implicit_resolver(
            "tag:yaml.org,2002:bool",
            re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
            list("tTfF"),
        )
        BoundedSafeLoader.add_implicit_resolver(
            "tag:yaml.org,2002:int",
            re.compile(
                r"^[-+]?(?:0|[1-9](?:_?[0-9])*|0b[01](?:_?[01])*|"
                r"0o[0-7](?:_?[0-7])*|0x[0-9a-fA-F](?:_?[0-9a-fA-F])*)$"
            ),
            list("-+0123456789"),
        )
        digits = r"[0-9](?:_?[0-9])*"
        BoundedSafeLoader.add_implicit_resolver(
            "tag:yaml.org,2002:float",
            re.compile(
                rf"^[-+]?(?:(?:{digits}\.(?:{digits})?|\.{digits})(?:[eE][-+]?{digits})?|"
                rf"{digits}[eE][-+]?{digits}|\.inf|\.nan)$",
                re.IGNORECASE,
            ),
            list("-+0123456789."),
        )
        BoundedSafeLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            BoundedSafeLoader.construct_mapping,
        )
        def construct_decimal(loader, node):
            scalar = loader.construct_scalar(node).replace("_", "")
            normalized = scalar.lower()
            if normalized in {".inf", "+.inf"}:
                return Decimal("Infinity")
            if normalized == "-.inf":
                return Decimal("-Infinity")
            if normalized in {".nan", "+.nan", "-.nan"}:
                return Decimal("NaN")
            try:
                return Decimal(scalar)
            except InvalidOperation as error:
                raise yaml.YAMLError("YAML float is not a valid JSON number") from error

        BoundedSafeLoader.add_constructor("tag:yaml.org,2002:float", construct_decimal)

        def validate_json_value(value):
            if value is None or type(value) in (str, bool, int):
                return
            if isinstance(value, Decimal):
                if value.is_finite():
                    return
                raise ValueError("YAML numbers must be finite")
            if type(value) is float:
                if math.isfinite(value):
                    return
                raise ValueError("YAML numbers must be finite")
            if isinstance(value, list):
                for item in value:
                    validate_json_value(item)
                return
            if isinstance(value, dict):
                for item in value.values():
                    validate_json_value(item)
                return
            raise ValueError("YAML values must be representable in JSON")

        try:
            data = yaml.load(raw_yaml, Loader=BoundedSafeLoader)
            validate_json_value(data)
            return DevToolsEngine._dump_json(data, indent=2, sort_keys=True, ensure_ascii=False)
        except (yaml.YAMLError, TypeError, ValueError, RecursionError) as error:
            raise ValueError(
                "YAML must contain one document with JSON-compatible values, unique string keys, and no aliases"
            ) from error

    @staticmethod
    def base64_encode(text: str) -> str:
        return base64.b64encode(DevToolsEngine._text_bytes(text)).decode('ascii')

    @staticmethod
    def base64_decode(b64_str: str) -> str:
        encoded = DevToolsEngine._text_bytes(b64_str, "Base64 input")
        try:
            ascii_input = encoded.decode("ascii")
            decoded = base64.b64decode(ascii_input, validate=True)
            return decoded.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("Base64 input must be valid Base64 containing UTF-8 text") from error

    @staticmethod
    def url_encode(text: str) -> str:
        DevToolsEngine._text_bytes(text)
        return urllib.parse.quote(text, safe="")

    @staticmethod
    def url_decode(text: str) -> str:
        DevToolsEngine._text_bytes(text)
        hex_digits = "0123456789abcdefABCDEF"
        for index, character in enumerate(text):
            if character == "%" and (
                index + 2 >= len(text)
                or text[index + 1] not in hex_digits
                or text[index + 2] not in hex_digits
            ):
                raise ValueError("URL input contains an invalid percent escape")
        return urllib.parse.unquote(text, errors="strict")

    @staticmethod
    def decode_jwt(jwt_str: str) -> Dict[str, Any]:
        """Safely inspects JWT payload and header without sending to server."""
        DevToolsEngine._text_bytes(jwt_str, "JWT input")
        parts = jwt_str.strip().split('.')
        if len(parts) != 3:
            raise ValueError("Invalid JWT format (expected header.payload.signature)")

        def b64_url_decode(segment: str, allow_empty: bool = False) -> bytes:
            if not segment and allow_empty:
                return b""
            if not segment or len(segment) % 4 == 1 or any(
                character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
                for character in segment
            ):
                raise ValueError("JWT contains an invalid Base64URL segment")
            padded = segment + '=' * (-len(segment) % 4)
            try:
                decoded = base64.b64decode(padded.encode('ascii'), altchars=b'-_', validate=True)
            except (UnicodeEncodeError, ValueError) as error:
                raise ValueError("JWT contains an invalid Base64URL segment") from error
            canonical = base64.urlsafe_b64encode(decoded).decode('ascii').rstrip('=')
            if canonical != segment:
                raise ValueError("JWT contains a non-canonical Base64URL segment")
            return decoded

        def parse_json_segment(segment: str) -> dict:
            try:
                raw_json = b64_url_decode(segment).decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("JWT header and payload must contain valid UTF-8 JSON") from error
            try:
                value = DevToolsEngine._parse_json(raw_json)
            except (ValueError, RecursionError) as error:
                raise ValueError("JWT header and payload must contain valid bounded JSON") from error
            if not isinstance(value, dict):
                raise ValueError("JWT header and payload must be JSON objects")
            return value

        header = parse_json_segment(parts[0])
        payload = parse_json_segment(parts[1])
        b64_url_decode(parts[2], allow_empty=True)

        return {
            "header": header,
            "payload": payload,
            "is_verified": False,
            "notice": "Decoded locally. Signature not verified against secret."
        }


class PrivacySecurityEngine:

    MAX_HASH_INPUT_BYTES = 1_048_576
    MAX_HMAC_SECRET_BYTES = 4_096
    MIN_PASSWORD_LENGTH = 12
    MAX_PASSWORD_LENGTH = 256
    PASSWORD_SYMBOLS = "!@#$%^&*()-_=+[]{}<>?"
    EFF_WORDLIST_FILENAME = "eff-large-wordlist.txt"
    EFF_WORDLIST_SIZE = 7_776
    EFF_WORDLIST_PATH = Path(__file__).resolve().parents[2] / "assets" / "wordlists" / EFF_WORDLIST_FILENAME
    MIN_PASSPHRASE_WORDS = 6
    MAX_PASSPHRASE_WORDS = 12
    # Keep delimiters disjoint from characters in the EFF list so each generated
    # word sequence has a unique serialized form and the entropy claim stays exact.
    PASSPHRASE_SEPARATORS = (" ", ".", "_")

    @staticmethod
    def _password_classes(length: int, include_symbols: bool) -> list[str]:
        if type(length) is not int or not PrivacySecurityEngine.MIN_PASSWORD_LENGTH <= length <= PrivacySecurityEngine.MAX_PASSWORD_LENGTH:
            raise ValueError(
                f"Password length must be between {PrivacySecurityEngine.MIN_PASSWORD_LENGTH} "
                f"and {PrivacySecurityEngine.MAX_PASSWORD_LENGTH} characters"
            )
        if type(include_symbols) is not bool:
            raise ValueError("include_symbols must be a boolean")
        classes = [string.ascii_lowercase, string.ascii_uppercase, string.digits]
        if include_symbols:
            classes.append(PrivacySecurityEngine.PASSWORD_SYMBOLS)
        return classes

    @staticmethod
    def password_search_space_bits(length: int = 16, include_symbols: bool = True) -> float:
        """Return exact theoretical entropy for this uniform, class-constrained generator."""
        classes = PrivacySecurityEngine._password_classes(length, include_symbols)
        alphabet_size = sum(len(character_class) for character_class in classes)
        valid_count = 0
        for mask in range(1 << len(classes)):
            excluded_size = sum(
                len(character_class)
                for index, character_class in enumerate(classes)
                if mask & (1 << index)
            )
            valid_count += (-1 if mask.bit_count() % 2 else 1) * (alphabet_size - excluded_size) ** length
        return math.log2(valid_count)

    @staticmethod
    def passphrase_wordlist() -> tuple[str, ...]:
        """Load and validate the bundled EFF Diceware list without network access."""
        frozen_root = getattr(sys, "_MEIPASS", None)
        path = (
            Path(frozen_root) / "wordlists" / PrivacySecurityEngine.EFF_WORDLIST_FILENAME
            if frozen_root is not None
            else PrivacySecurityEngine.EFF_WORDLIST_PATH
        )
        try:
            records = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise ValueError("The bundled passphrase word list is unavailable") from error
        except UnicodeError as error:
            raise ValueError("The bundled passphrase word list is invalid") from error

        columns = tuple(tuple(line.split("\t")) for line in records)
        words = tuple(columns[index][1] for index in range(len(columns)) if len(columns[index]) == 2)
        if (
            len(words) != PrivacySecurityEngine.EFF_WORDLIST_SIZE
            or len(set(words)) != PrivacySecurityEngine.EFF_WORDLIST_SIZE
            or len(columns) != PrivacySecurityEngine.EFF_WORDLIST_SIZE
            or any(
                len(columns[index]) != 2
                or re.fullmatch(r"[1-6]{5}", columns[index][0]) is None
                or re.fullmatch(r"[a-z]+(?:-[a-z]+)?", columns[index][1]) is None
                for index in range(len(columns))
            )
            or len({column[0] for column in columns if len(column) == 2}) != PrivacySecurityEngine.EFF_WORDLIST_SIZE
        ):
            raise ValueError("The bundled passphrase word list is invalid")
        return words

    @staticmethod
    def _validate_passphrase_word_count(word_count: int) -> None:
        if (
            type(word_count) is not int
            or not PrivacySecurityEngine.MIN_PASSPHRASE_WORDS <= word_count <= PrivacySecurityEngine.MAX_PASSPHRASE_WORDS
        ):
            raise ValueError(
                f"Passphrase word count must be between {PrivacySecurityEngine.MIN_PASSPHRASE_WORDS} "
                f"and {PrivacySecurityEngine.MAX_PASSPHRASE_WORDS}"
            )

    @staticmethod
    def generate_passphrase(word_count: int = 6, separator: str = " ") -> str:
        """Generate a passphrase from independent cryptographically random EFF list words."""
        PrivacySecurityEngine._validate_passphrase_word_count(word_count)
        if type(separator) is not str or separator not in PrivacySecurityEngine.PASSPHRASE_SEPARATORS:
            raise ValueError("Passphrase separator must be a space, period or underscore")
        words = PrivacySecurityEngine.passphrase_wordlist()
        return separator.join(secrets.choice(words) for _ in range(word_count))

    @staticmethod
    def passphrase_search_space_bits(word_count: int = 6) -> float:
        """Return the exact theoretical entropy of independent choices from the bundled list."""
        PrivacySecurityEngine._validate_passphrase_word_count(word_count)
        return word_count * math.log2(PrivacySecurityEngine.EFF_WORDLIST_SIZE)

    @staticmethod
    def generate_hashes(text: str, secret_key: Optional[str] = None) -> Dict[str, str]:
        """Calculates hashes for bounded UTF-8 text and an optional bounded HMAC key."""
        if not isinstance(text, str):
            raise ValueError("Hash input must be a string")
        if len(text) > PrivacySecurityEngine.MAX_HASH_INPUT_BYTES:
            raise ValueError("Hash input must not exceed 1,048,576 UTF-8 bytes")
        try:
            b = text.encode('utf-8')
        except UnicodeEncodeError as error:
            raise ValueError("Hash input must contain valid UTF-8 text") from error
        if len(b) > PrivacySecurityEngine.MAX_HASH_INPUT_BYTES:
            raise ValueError("Hash input must not exceed 1,048,576 UTF-8 bytes")

        secret_bytes = None
        if secret_key is not None:
            if not isinstance(secret_key, str):
                raise ValueError("HMAC secret must be a string")
            if len(secret_key) > PrivacySecurityEngine.MAX_HMAC_SECRET_BYTES:
                raise ValueError("HMAC secret must not exceed 4,096 UTF-8 bytes")
            try:
                secret_bytes = secret_key.encode('utf-8')
            except UnicodeEncodeError as error:
                raise ValueError("HMAC secret must contain valid UTF-8 text") from error
            if len(secret_bytes) > PrivacySecurityEngine.MAX_HMAC_SECRET_BYTES:
                raise ValueError("HMAC secret must not exceed 4,096 UTF-8 bytes")

        res = {
            "md5": hashlib.md5(b).hexdigest(),
            "sha1": hashlib.sha1(b).hexdigest(),
            "sha256": hashlib.sha256(b).hexdigest(),
            "sha512": hashlib.sha512(b).hexdigest(),
            "crc32": format(zlib.crc32(b) & 0xffffffff, '08x')
        }
        if secret_bytes:
            res["hmac_sha256"] = hmac.new(secret_bytes, b, hashlib.sha256).hexdigest()
        return res

    @staticmethod
    def generate_password(length: int = 16, include_symbols: bool = True) -> str:
        """Generate a bounded cryptographically random password with required character classes."""
        classes = PrivacySecurityEngine._password_classes(length, include_symbols)
        alphabet = "".join(classes)
        while True:
            password = "".join(secrets.choice(alphabet) for _ in range(length))
            if all(any(character in character_class for character in password) for character_class in classes):
                return password
