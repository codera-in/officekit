"""Regression coverage for reliable, private local license persistence."""

import json
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import officekit.engines.engine_license as engine_license


class LicenseStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temporary.name, "officekit-license.json")

    def tearDown(self):
        self.temporary.cleanup()

    def test_save_writes_private_json_without_leaving_staging_files(self):
        license_data = {"valid": True, "tier": 2, "features": {"offline_mode": True}}
        with patch.object(engine_license, "LICENSE_FILE", self.path):
            engine_license.LicenseManager.save_license(license_data)

        with open(self.path, "r", encoding="utf-8") as stored:
            self.assertEqual(json.load(stored), license_data)
        if os.name != "nt":
            self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertEqual(os.listdir(self.temporary.name), ["officekit-license.json"])

    def test_replace_failure_is_reported_and_preserves_the_previous_license(self):
        with open(self.path, "w", encoding="utf-8") as stored:
            stored.write('{"valid": false, "tier": 0}')
        with patch.object(engine_license, "LICENSE_FILE", self.path), \
             patch.object(engine_license.os, "replace", side_effect=OSError("simulated disk failure")):
            with self.assertRaisesRegex(OSError, "simulated disk failure"):
                engine_license.LicenseManager.save_license({"valid": True, "tier": 1})

        with open(self.path, "r", encoding="utf-8") as stored:
            self.assertEqual(json.load(stored), {"valid": False, "tier": 0})
        self.assertEqual(os.listdir(self.temporary.name), ["officekit-license.json"])

    def test_flush_failure_is_reported_and_preserves_the_previous_license(self):
        with open(self.path, "w", encoding="utf-8") as stored:
            json.dump({"valid": False, "tier": 0}, stored)
        with patch.object(engine_license, "LICENSE_FILE", self.path), \
             patch.object(engine_license.os, "fsync", side_effect=OSError("simulated disk full")):
            with self.assertRaisesRegex(OSError, "simulated disk full"):
                engine_license.LicenseManager.save_license({"valid": True, "tier": 1})

        with open(self.path, "r", encoding="utf-8") as stored:
            self.assertEqual(json.load(stored), {"valid": False, "tier": 0})
        self.assertEqual(os.listdir(self.temporary.name), ["officekit-license.json"])

    def test_fchmod_failure_closes_descriptor_and_removes_staging_file(self):
        with patch.object(engine_license, "LICENSE_FILE", self.path), \
             patch.object(engine_license.os, "fchmod", side_effect=OSError("permission denied")):
            with self.assertRaisesRegex(OSError, "permission denied"):
                engine_license.LicenseManager.save_license({"valid": False})

        self.assertEqual(os.listdir(self.temporary.name), [])

    def test_platform_without_fchmod_can_still_save_license(self):
        portable_os = SimpleNamespace(
            path=os.path,
            makedirs=os.makedirs,
            fdopen=os.fdopen,
            fsync=os.fsync,
            replace=os.replace,
            close=os.close,
            unlink=os.unlink,
        )
        with patch.object(engine_license, "LICENSE_FILE", self.path), \
             patch.object(engine_license, "os", portable_os):
            engine_license.LicenseManager.save_license({"valid": False, "tier": 0})

        with open(self.path, "r", encoding="utf-8") as stored:
            self.assertEqual(json.load(stored), {"valid": False, "tier": 0})

    def test_cleanup_ignores_staging_file_already_removed_by_another_actor(self):
        real_unlink = os.unlink

        def unlink_then_report_missing(path):
            real_unlink(path)
            raise FileNotFoundError(path)

        with patch.object(engine_license, "LICENSE_FILE", self.path), \
             patch.object(engine_license.os, "replace", side_effect=OSError("simulated replace failure")), \
             patch.object(engine_license.os, "unlink", side_effect=unlink_then_report_missing):
            with self.assertRaisesRegex(OSError, "simulated replace failure"):
                engine_license.LicenseManager.save_license({"valid": False})

        self.assertEqual(os.listdir(self.temporary.name), [])

    def test_status_does_not_trust_a_forged_legacy_valid_json_record(self):
        with open(self.path, "w", encoding="utf-8") as stored:
            json.dump({"valid": True, "tier": 3, "features": {"api_access": True}}, stored)

        with patch.object(engine_license, "LICENSE_FILE", self.path):
            status = engine_license.LicenseManager.get_current_license()

        self.assertFalse(status["valid"])
        self.assertEqual(status["tier"], 0)
        self.assertFalse(status["features"]["api_access"])

    def test_the_client_does_not_expose_a_local_hmac_key_issuer(self):
        self.assertFalse(hasattr(engine_license.LicenseManager, "generate_appsumo_code"))
        self.assertFalse(hasattr(engine_license, "LICENSE_SECRET"))


if __name__ == "__main__":
    unittest.main()
