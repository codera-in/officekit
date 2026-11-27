import unittest

from backend_main import sidecar_api_port


class BackendPortConfigurationTests(unittest.TestCase):
    def test_defaults_to_the_desktop_port_and_accepts_an_isolated_loopback_port(self):
        self.assertEqual(sidecar_api_port({}), 8000)
        self.assertEqual(sidecar_api_port({"OFFICEKIT_API_PORT": "49152"}), 49152)
        self.assertEqual(sidecar_api_port({"OFFICEKIT_API_PORT": "65535"}), 65535)

    def test_rejects_malformed_or_out_of_range_port_values(self):
        for value in ("", "0", "65536", "8000.5", "-1", "+8000", "８０００", "port"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    sidecar_api_port({"OFFICEKIT_API_PORT": value})


if __name__ == "__main__":
    unittest.main()
