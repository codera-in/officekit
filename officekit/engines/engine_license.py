"""Local license status storage for OfficeKit.

Paid activation is intentionally unavailable until this client verifies
server-issued signed entitlements. A license file by itself is never proof of
an entitlement.
"""

import json
import os
import tempfile
from typing import Any, Dict

LICENSE_FILE = os.path.expanduser("~/.officekit_license.json")


class LicenseManager:
    """Expose the safe free status while hosted activation is not integrated."""

    @staticmethod
    def save_license(data: Dict[str, Any]) -> None:
        """Atomically persist a future entitlement payload without trusting it."""
        destination = os.path.abspath(os.path.expanduser(LICENSE_FILE))
        directory = os.path.dirname(destination)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        descriptor, staged_path = tempfile.mkstemp(
            prefix=".officekit-license-", suffix=".tmp", dir=directory
        )
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as license_file:
                descriptor = -1
                json.dump(data, license_file, indent=2, ensure_ascii=False)
                license_file.write("\n")
                license_file.flush()
                os.fsync(license_file.fileno())
            os.replace(staged_path, destination)
            staged_path = ""
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if staged_path:
                try:
                    os.unlink(staged_path)
                except FileNotFoundError:
                    pass

    @staticmethod
    def get_current_license() -> Dict[str, Any]:
        """Return free status until a cryptographic entitlement verifier exists."""
        return {
            "valid": False,
            "tier": 0,
            "tier_name": "Free Starter",
            "features": {
                "unlimited_statements": False,
                "ocr_priority": False,
                "batch_processing": False,
                "api_access": False,
                "offline_mode": True,
            },
        }
