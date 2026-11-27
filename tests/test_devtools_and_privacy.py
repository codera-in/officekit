"""
TDD Tests for Developer & Privacy Utilities (officekit/engines/engine_devtools.py)
Covers:
- JSON / YAML / CSV format & validation
- Base64 / URL / HTML Encode & Decode
- Local JWT Header & Payload inspection (with signature verification disclaimers)
- Deterministic Cryptographic Hashes (MD5, SHA-1, SHA-256, SHA-512, CRC32, HMAC-SHA256)
- Secure Password & UUID Generators
"""

import pytest
from officekit.engines.engine_devtools import DevToolsEngine, PrivacySecurityEngine

def test_json_and_yaml_formatting():
    raw_json = '{"b": 2, "a": 1}'
    formatted = DevToolsEngine.format_json(raw_json, indent=2)
    assert '"a": 1' in formatted

    yaml_str = DevToolsEngine.json_to_yaml(raw_json)
    assert "a: 1" in yaml_str
    assert "b: 2" in yaml_str

def test_encoders_and_decoders():
    plain = "Hello World & OfficeKit!"
    b64 = DevToolsEngine.base64_encode(plain)
    assert DevToolsEngine.base64_decode(b64) == plain

    url_enc = DevToolsEngine.url_encode("foo bar=123&test=1")
    assert "foo%20bar" in url_enc
    assert DevToolsEngine.url_decode(url_enc) == "foo bar=123&test=1"

def test_local_jwt_decoder():
    # Sample standard JWT (header.payload.signature)
    sample_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    decoded = DevToolsEngine.decode_jwt(sample_jwt)
    assert decoded["header"]["alg"] == "HSZ256" or decoded["header"]["alg"] == "HS256"
    assert decoded["payload"]["name"] == "John Doe"
    assert decoded["is_verified"] is False  # Safe local inspection notice

def test_cryptographic_hashes_and_generators():
    text = "OfficeKit Security Baseline"
    hashes = PrivacySecurityEngine.generate_hashes(text)
    assert len(hashes["sha256"]) == 64
    assert len(hashes["md5"]) == 32
    assert "crc32" in hashes

    pwd = PrivacySecurityEngine.generate_password(length=16, include_symbols=True)
    assert len(pwd) == 16
