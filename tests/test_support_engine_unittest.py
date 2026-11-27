import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from officekit.engines.engine_comms import SupportEngine, SupportStoreError


class SupportEngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.ticket_file = os.path.join(self.temporary.name, "officekit", "tickets.json")
        self.patch_file = patch("officekit.engines.engine_comms.TICKETS_FILE", self.ticket_file)
        self.patch_file.start()

    def tearDown(self):
        self.patch_file.stop()
        self.temporary.cleanup()

    @staticmethod
    def valid_ticket(**overrides):
        payload = {
            "user_email": "person@example.com",
            "ticket_type": "bug",
            "title": "A reproducible issue",
            "description": "Steps to reproduce the problem.",
            "system_info": {"os": "macOS", "app_version": "1.0.0"},
        }
        payload.update(overrides)
        return payload

    def create(self, **overrides):
        return SupportEngine.create_ticket(**self.valid_ticket(**overrides))

    def test_accepts_the_supported_feedback_categories_and_rejects_unknown_types(self):
        for ticket_type in ("bug", "support", "feature", "testimonial"):
            with self.subTest(ticket_type=ticket_type):
                ticket = self.create(ticket_type=ticket_type)
                self.assertEqual(ticket["ticket_type"], ticket_type)

        with self.assertRaisesRegex(ValueError, "Ticket type"):
            self.create(ticket_type="spam")

    def test_bounds_and_validates_email_title_description_and_system_info(self):
        invalid_cases = (
            {"user_email": "not-an-email"},
            {"user_email": "x" * 250 + "@example.com"},
            {"title": " \n "},
            {"title": "x" * 161},
            {"description": "\t"},
            {"description": "x" * 20_001},
            {"system_info": {"password": "secret"}},
            {"system_info": {"platform": "x" * 513}},
            {"system_info": ["not", "an", "object"]},
        )
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.create(**invalid)

    def test_local_drafts_allow_no_email_and_keep_testimonial_consent_separate(self):
        ticket = SupportEngine.create_ticket(
            user_email=None,
            ticket_type="testimonial",
            title="A helpful toolkit",
            description="OfficeKit helps me finish file tasks locally.",
            display_name="Sam",
            publication_consent=True,
        )

        self.assertIsNone(ticket["user_email"])
        self.assertEqual(ticket["display_name"], "Sam")
        self.assertIs(ticket["publication_consent"], True)
        self.assertEqual(ticket["status"], "saved_locally")
        self.assertEqual(ticket["timeline"][0]["status"], "saved_locally")
        self.assertEqual(ticket["timeline"][0]["message"], "Draft saved on this Mac. Nothing was sent or published.")

    def test_publication_consent_and_display_name_are_validated(self):
        invalid_cases = (
            {"publication_consent": True, "ticket_type": "bug"},
            {"publication_consent": True, "ticket_type": "testimonial", "display_name": None},
            {"publication_consent": 1},
            {"display_name": "x" * 81},
            {"display_name": 4},
        )
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.create(**invalid)

    def test_legacy_local_received_records_are_returned_with_truthful_status(self):
        os.makedirs(os.path.dirname(self.ticket_file), mode=0o700)
        legacy = {
            "OK-legacy": {
                "ticket_id": "OK-legacy", "user_email": "person@example.com", "ticket_type": "bug",
                "title": "Old local record", "description": "Previously mislabeled as received.",
                "system_info": {}, "status": "received", "created_at": 1,
                "timeline": [{"status": "received", "message": "Ticket saved in local queue.", "timestamp": 1}],
            }
        }
        Path(self.ticket_file).write_text(json.dumps(legacy), encoding="utf-8")

        fetched = SupportEngine.get_ticket("OK-legacy")
        listed = SupportEngine.list_user_tickets("person@example.com")

        self.assertEqual(fetched["status"], "saved_locally")
        self.assertEqual(fetched["timeline"][0]["status"], "saved_locally")
        self.assertIn("Nothing was sent", fetched["timeline"][0]["message"])
        self.assertIsNone(fetched["display_name"])
        self.assertIs(fetched["publication_consent"], False)
        self.assertEqual(listed[0], fetched)
        self.assertEqual(json.loads(Path(self.ticket_file).read_text(encoding="utf-8")), legacy)

    def test_persists_atomically_in_private_storage(self):
        ticket = self.create()

        saved = json.loads(Path(self.ticket_file).read_text(encoding="utf-8"))
        self.assertEqual(saved[ticket["ticket_id"]]["description"], "Steps to reproduce the problem.")
        self.assertEqual(SupportEngine.get_ticket(ticket["ticket_id"]), ticket)
        self.assertEqual(SupportEngine.list_user_tickets("person@example.com"), [ticket])
        self.assertTrue(os.path.isdir(os.path.dirname(self.ticket_file)))
        if os.name == "posix":
            self.assertEqual(os.stat(os.path.dirname(self.ticket_file)).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(self.ticket_file).st_mode & 0o777, 0o600)

    def test_corrupt_store_is_reported_and_never_replaced_with_an_empty_store(self):
        os.makedirs(os.path.dirname(self.ticket_file), mode=0o700)
        original = b"{truncated ticket store"
        Path(self.ticket_file).write_bytes(original)

        with self.assertRaisesRegex(SupportStoreError, "ticket store"):
            self.create()

        self.assertEqual(Path(self.ticket_file).read_bytes(), original)

    def test_oversized_store_is_rejected_without_unbounded_read_or_replacement(self):
        os.makedirs(os.path.dirname(self.ticket_file), mode=0o700)
        original = b" " * 33
        Path(self.ticket_file).write_bytes(original)

        with patch.object(SupportEngine, "MAX_TICKET_STORE_BYTES", 32):
            with self.assertRaisesRegex(SupportStoreError, "exceeds its supported size"):
                self.create()

        self.assertEqual(Path(self.ticket_file).read_bytes(), original)

    def test_failed_atomic_write_is_reported_and_leaves_no_partial_ticket_file(self):
        with patch("officekit.engines.engine_comms.os.replace", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.create()

        self.assertFalse(os.path.exists(self.ticket_file))
        self.assertEqual(os.listdir(os.path.dirname(self.ticket_file)), [])

    def test_concurrent_submissions_do_not_overwrite_each_other(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            created = list(executor.map(lambda index: self.create(title=f"Issue {index}"), range(24)))

        stored = SupportEngine.list_user_tickets("person@example.com")
        self.assertEqual(len(stored), 24)
        self.assertEqual({ticket["ticket_id"] for ticket in created}, {ticket["ticket_id"] for ticket in stored})
        self.assertEqual(len({ticket["ticket_id"] for ticket in stored}), 24)


if __name__ == "__main__":
    unittest.main()
