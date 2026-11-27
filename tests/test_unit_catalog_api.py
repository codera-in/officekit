from fastapi.testclient import TestClient

import app as officekit_app
from officekit.engines.engine_units import UnitConverterEngine


client = TestClient(officekit_app.app)


def test_unit_catalog_exposes_canonical_convertible_choices_for_every_category():
    response = client.get("/api/units/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"categories"}
    categories = payload["categories"]
    assert len(categories) == len(UnitConverterEngine.CONVERSION_TREES) + 1
    assert {item["id"] for item in categories} == set(UnitConverterEngine.CONVERSION_TREES) | {"temperature"}
    for category in categories:
        assert set(category) == {"id", "label", "units"}
        assert category["label"]
        assert len(category["units"]) >= 2
        ids = [unit["id"] for unit in category["units"]]
        assert len(ids) == len(set(ids))
        for unit in category["units"]:
            assert set(unit) == {"id", "label"}
            assert unit["label"]
            assert UnitConverterEngine.convert(1, category["id"], unit["id"], unit["id"]) == 1


def test_unit_catalog_preserves_case_sensitive_bit_byte_choices_and_temperature():
    categories = {item["id"]: {unit["id"] for unit in item["units"]} for item in client.get("/api/units/catalog").json()["categories"]}

    assert {"bit", "byte", "kB", "kb", "KiB", "Kib"}.issubset(categories["digital_storage"])
    assert categories["temperature"] == {"celsius", "fahrenheit", "kelvin"}
