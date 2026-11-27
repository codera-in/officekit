"""
Full End-to-End Test Suite for Newly Implemented Modular & Batch API Endpoints
"""

import base64
import json

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_system_resources_api():
    res = client.get("/api/system/resources")
    assert res.status_code == 200
    data = res.json()
    assert "cpu_count" in data
    assert "total_ram_gb" in data
    assert "available_ram_gb" in data
    assert data["optimal_workers"] >= 1

def test_units_convert_api():
    payload = {
        "value": 100,
        "category": "length",
        "from_unit": "meter",
        "to_unit": "kilometer"
    }
    res = client.post("/api/units/convert", json=payload)
    assert res.status_code == 200
    assert res.json()["result"] == 0.1

    for sample, expected in (
        ({**payload, "value": 1, "category": "area", "from_unit": "acre", "to_unit": "square_foot"}, 43560.0),
        ({**payload, "value": 1, "category": "volume", "from_unit": "gallon_us", "to_unit": "liter"}, 3.785411784),
        ({**payload, "value": 36, "category": "speed", "from_unit": "km/h", "to_unit": "m/s"}, 10.0),
        ({**payload, "value": 1, "category": "time", "from_unit": "year_365d", "to_unit": "day"}, 365.0),
        ({**payload, "value": 1, "category": "digital_storage", "from_unit": "MB", "to_unit": "B"}, 1_000_000.0),
        ({**payload, "value": 1, "category": "digital_storage", "from_unit": "Mb", "to_unit": "B"}, 125_000.0),
        ({**payload, "value": 8, "category": "digital_storage", "from_unit": "b", "to_unit": "B"}, 1.0),
        ({**payload, "value": 1, "category": "digital_storage", "from_unit": "MiB", "to_unit": "B"}, 1_048_576.0),
        ({**payload, "value": 1, "category": "digital_storage", "from_unit": "Mib", "to_unit": "B"}, 131_072.0),
        ({**payload, "value": -273.15, "category": "temperature", "from_unit": "celsius", "to_unit": "kelvin"}, 0.0),
    ):
        converted = client.post("/api/units/convert", json=sample)
        assert converted.status_code == 200
        assert abs(converted.json()["result"] - expected) <= max(1e-10, abs(expected) * 1e-12)

    for invalid in (
        {**payload, "category": "unknown", "from_unit": "meter", "to_unit": "meter"},
        {**payload, "from_unit": "unknown", "to_unit": "unknown"},
        {**payload, "value": True},
        {**payload, "value": float("inf")},
        {**payload, "category": "time", "from_unit": "month", "to_unit": "day"},
        {**payload, "category": "temperature", "value": -0.001, "from_unit": "kelvin", "to_unit": "kelvin"},
        {**payload, "category": "digital_storage", "from_unit": "KIB", "to_unit": "bytes"},
        {**payload, "debug": True},
    ):
        if invalid.get("value") == float("inf"):
            invalid_response = client.post(
                "/api/units/convert",
                content=json.dumps(invalid).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        else:
            invalid_response = client.post("/api/units/convert", json=invalid)
        assert invalid_response.status_code == 422

def test_math_eval_api():
    payload = {"expression": "(25 * 4) + 10"}
    res = client.post("/api/math/eval", json=payload)
    assert res.status_code == 200
    assert res.json()["result"] == 110

def test_devtools_api_bounded_inputs_and_typed_outputs():
    encoded = client.post("/api/devtools/process", json={"content": "OfficeKit", "operation": "base64_encode"})
    assert encoded.status_code == 200
    assert encoded.json() == {"result": "T2ZmaWNlS2l0"}

    decoded = client.post("/api/devtools/process", json={"content": "T2ZmaWNlS2l0", "operation": "base64_decode"})
    assert decoded.status_code == 200
    assert decoded.json() == {"result": "OfficeKit"}

    jwt_header = "eyJhbGciOiJub25lIn0"
    jwt_payload = "eyJzdWIiOiJsb2NhbCJ9"
    inspected = client.post(
        "/api/devtools/process",
        json={"content": f"{jwt_header}.{jwt_payload}.c2ln", "operation": "jwt_decode"},
    )
    assert inspected.status_code == 200
    assert inspected.json()["header"] == {"alg": "none"}
    assert inspected.json()["payload"] == {"sub": "local"}
    assert inspected.json()["is_verified"] is False

    boundary = client.post(
        "/api/devtools/process",
        json={"content": "é" * 524288, "operation": "base64_encode"},
    )
    assert boundary.status_code == 200

    invalid_requests = (
        {"content": "é" * 524288 + "x", "operation": "base64_encode"},
        {"content": 123, "operation": "base64_encode"},
        {"content": "a?==", "operation": "base64_decode"},
        {"content": "{", "operation": "format_json"},
        {"content": '{"value": 1, "value": 2}', "operation": "format_json"},
        {"content": '{"value": 1, "value": 2}', "operation": "json_to_yaml"},
        {"content": '{"value": NaN}', "operation": "format_json"},
        {"content": '{"value": Infinity}', "operation": "json_to_yaml"},
        {"content": "[" * 129 + "0" + "]" * 129, "operation": "format_json"},
        {"content": "value: .nan\n", "operation": "yaml_to_json"},
        {"content": "", "operation": "unknown"},
        {"content": "", "operation": "format_json", "extra": True},
    )
    for invalid in invalid_requests:
        response = client.post("/api/devtools/process", json=invalid)
        assert response.status_code == 422

def test_jwt_api_rejects_ambiguous_json_and_noncanonical_base64url_safely():
    def encode_segment(value):
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    duplicate_header = encode_segment('{"alg":"HS256","alg":"none"}')
    duplicate_payload = encode_segment('{"role":"user","role":"admin"}')
    nonfinite_payload = encode_segment('{"exp":NaN}')
    invalid_tokens = (
        f"{duplicate_header}.e30.c2ln",
        f"e30.{duplicate_payload}.c2ln",
        f"e30.{nonfinite_payload}.c2ln",
        "e31.e30.c2ln",
    )
    for token in invalid_tokens:
        response = client.post(
            "/api/devtools/process",
            json={"content": token, "operation": "jwt_decode"},
        )
        assert response.status_code == 422
        assert response.json() == {"detail": "Developer-tool input is invalid or exceeds supported limits."}

def test_devtools_api_json_and_hashes():
    # JSON formatting
    res_fmt = client.post("/api/devtools/process", json={"content": "{\"z\":1,\"a\":2}", "operation": "format_json"})
    assert res_fmt.status_code == 200
    assert '"a": 2' in res_fmt.json()["result"]

    exact_number = '{"large": 1e999, "small": 1e-9999, "precise": 0.12345678901234567890123456789}'
    converted_yaml = client.post(
        "/api/devtools/process", json={"content": exact_number, "operation": "json_to_yaml"}
    )
    assert converted_yaml.status_code == 200
    round_trip = client.post(
        "/api/devtools/process",
        json={"content": converted_yaml.json()["result"], "operation": "yaml_to_json"},
    )
    assert round_trip.status_code == 200
    assert '1E+999' in round_trip.json()["result"]
    assert '1E-9999' in round_trip.json()["result"]
    assert '0.12345678901234567890123456789' in round_trip.json()["result"]

    res_yaml_json = client.post(
        "/api/devtools/process",
        json={"content": "name: OfficeKit\nactive: true\n", "operation": "yaml_to_json"},
    )
    assert res_yaml_json.status_code == 200
    assert res_yaml_json.json()["result"] == '{\n  "active": true,\n  "name": "OfficeKit"\n}'
    for content in ("value: one\nvalue: two\n", "value: !!python/object/apply:os.system ['true']\n"):
        invalid_yaml = client.post(
            "/api/devtools/process", json={"content": content, "operation": "yaml_to_json"}
        )
        assert invalid_yaml.status_code == 422

    # Crypto Hashes
    res_hash = client.post("/api/crypto/hashes", json={"text": "OfficeKit"})
    assert res_hash.status_code == 200
    assert len(res_hash.json()["sha256"]) == 64
    assert "hmac_sha256" not in res_hash.json()

def test_hash_api_contract_limits_and_hmac_response():
    boundary = client.post("/api/crypto/hashes", json={"text": "é" * 524288})
    assert boundary.status_code == 200
    assert len(boundary.json()["sha512"]) == 128

    with_hmac = client.post("/api/crypto/hashes", json={"text": "data", "secret": "key"})
    assert with_hmac.status_code == 200
    assert with_hmac.json()["hmac_sha256"] == "5031fe3d989c6d1537a013fa6e739da23463fdaec3b70137d828e36ace221bd0"

    for invalid in (
        {"text": "é" * 524288 + "x"},  # one UTF-8 byte over the engine limit
        {"text": "x" * 1048577},
        {"text": "data", "secret": "é" * 2049},
        {"text": 123},
        {"text": "data", "secret": 123},
        {"text": "data", "extra": True},
    ):
        response = client.post("/api/crypto/hashes", json=invalid)
        assert response.status_code == 422

def test_password_generator_api_bounds_and_symbol_option():
    symbol_free = client.post("/api/crypto/password?length=12&include_symbols=false")
    assert symbol_free.status_code == 200
    assert set(symbol_free.json()) == {"password", "theoretical_search_space_bits"}
    password = symbol_free.json()["password"]
    assert len(password) == 12
    assert password.isalnum()
    assert any(character.islower() for character in password)
    assert any(character.isupper() for character in password)
    assert any(character.isdigit() for character in password)

    maximum = client.post("/api/crypto/password?length=256&include_symbols=true")
    assert maximum.status_code == 200
    assert len(maximum.json()["password"]) == 256
    assert maximum.json()["theoretical_search_space_bits"] > symbol_free.json()["theoretical_search_space_bits"]

    for query in (
        "length=11",
        "length=257",
        "length=-1",
        "length=1000000000",
        "include_symbols=perhaps",
    ):
        response = client.post(f"/api/crypto/password?{query}")
        assert response.status_code == 422

def test_file_rename_plan_api():
    payload = {
        "filenames": ["doc a.txt", "doc b.txt"],
        "pattern_type": "sequence",
        "prefix": "receipt_",
        "start_num": 1,
        "digits": 2
    }
    res = client.post("/api/files/rename-plan", json=payload)
    assert res.status_code == 200
    assert res.json()["renamed"] == ["receipt_01.txt", "receipt_02.txt"]
