import unittest

from officekit.engines.engine_api_security import (
    is_api_authorization_valid,
    is_trusted_api_origin,
    load_sidecar_api_token,
)


class ApiOriginPolicyTests(unittest.TestCase):
    def test_allows_native_requests_without_browser_origin(self):
        self.assertTrue(is_trusted_api_origin(None))

    def test_allows_only_exact_desktop_and_local_launcher_origins(self):
        self.assertTrue(is_trusted_api_origin("tauri://localhost"))
        self.assertTrue(is_trusted_api_origin("http://tauri.localhost"))

    def test_allows_the_exact_same_origin_of_the_local_python_launcher(self):
        self.assertTrue(is_trusted_api_origin("http://127.0.0.1:8000"))

    def test_ui_test_origin_is_available_only_with_explicit_isolated_test_environment(self):
        origin = "http://127.0.0.1:19874"
        self.assertFalse(is_trusted_api_origin(origin))
        self.assertFalse(is_trusted_api_origin(origin, {
            "OFFICEKIT_UI_TEST_ORIGIN": origin,
            "OFFICEKIT_API_TOKEN": "test-api-token",
        }))
        self.assertFalse(is_trusted_api_origin(origin, {
            "OFFICEKIT_UI_TEST_ORIGIN": "http://127.0.0.1:19875",
            "OFFICEKIT_UI_TEST_TOKEN": "test-ui-token",
            "OFFICEKIT_API_TOKEN": "test-api-token",
        }))
        self.assertTrue(is_trusted_api_origin(origin, {
            "OFFICEKIT_UI_TEST_ORIGIN": origin,
            "OFFICEKIT_UI_TEST_TOKEN": "test-ui-token",
            "OFFICEKIT_API_TOKEN": "test-api-token",
        }))

    def test_ui_test_origin_supports_isolated_dynamic_ports_only_on_loopback(self):
        environment = {
            "OFFICEKIT_UI_TEST_ORIGIN": "http://127.0.0.1:19887",
            "OFFICEKIT_UI_TEST_TOKEN": "test-ui-token",
            "OFFICEKIT_API_TOKEN": "test-api-token",
        }
        self.assertTrue(is_trusted_api_origin("http://127.0.0.1:19887", environment))
        for invalid in (
            "http://localhost:19887",
            "https://127.0.0.1:19887",
            "http://127.0.0.1:19887/path",
            "http://127.0.0.1:80",
            "http://127.0.0.1:19887.attacker.example",
        ):
            with self.subTest(origin=invalid):
                self.assertFalse(is_trusted_api_origin(invalid, {**environment, "OFFICEKIT_UI_TEST_ORIGIN": invalid}))

    def test_rejects_untrusted_and_spoofed_origins(self):
        for origin in (
            "https://attacker.example",
            "http://127.0.0.1:8001",
            "http://localhost:8000",
            "http://127.0.0.1:8000.attacker.example",
            "http://tauri.localhost.attacker.example",
            "tauri://localhost/attacker",
            " tauri://localhost",
            "null",
        ):
            with self.subTest(origin=origin):
                self.assertFalse(is_trusted_api_origin(origin))

    def test_api_token_requires_exact_bearer_credentials_when_configured(self):
        expected = "officekit-test-token-with-at-least-32-characters"
        self.assertTrue(is_api_authorization_valid(f"Bearer {expected}", expected))
        self.assertTrue(is_api_authorization_valid(f"bearer {expected}", expected))
        for header in (
            None, "", "Basic " + expected, "Bearer wrong", f"Bearer {expected} extra",
            expected, f"Bearer {expected[:-1]}ñ",
        ):
            with self.subTest(header=header):
                self.assertFalse(is_api_authorization_valid(header, expected))

    def test_unconfigured_auth_is_development_only_and_empty_secret_fails_closed(self):
        self.assertTrue(is_api_authorization_valid(None, None))
        self.assertFalse(is_api_authorization_valid(None, ""))
        self.assertFalse(is_api_authorization_valid("Bearer token", ""))

    def test_sidecar_requires_a_strong_bounded_environment_token(self):
        token = "0123456789abcdef0123456789abcdef"
        self.assertEqual(load_sidecar_api_token({"OFFICEKIT_API_TOKEN": token}), token)
        for environment in (
            {},
            {"OFFICEKIT_API_TOKEN": ""},
            {"OFFICEKIT_API_TOKEN": "too-short"},
            {"OFFICEKIT_API_TOKEN": "x" * 129},
            {"OFFICEKIT_API_TOKEN": "x" * 31 + "\n"},
        ):
            with self.subTest(environment=environment), self.assertRaises(RuntimeError):
                load_sidecar_api_token(environment)


if __name__ == "__main__":
    unittest.main()
