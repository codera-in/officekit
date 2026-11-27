import pytest

from app import resolve_api_version


def test_api_version_follows_the_desktop_app_version():
    assert resolve_api_version({"OFFICEKIT_APP_VERSION": "1.0.1"}) == "1.0.1"
    assert resolve_api_version({"OFFICEKIT_APP_VERSION": "12.345.6789"}) == "12.345.6789"


@pytest.mark.parametrize(
    "value",
    ["", "1.0", "1.0.0-beta", "v1.0.1", "1.0.1\n", "99999.0.0", "1.0.1; rm", "1.0.x"],
)
def test_api_version_falls_back_for_missing_or_invalid_values(value):
    assert resolve_api_version({"OFFICEKIT_APP_VERSION": value}) == "1.0.0"


def test_api_version_falls_back_when_unset():
    assert resolve_api_version({}) == "1.0.0"
