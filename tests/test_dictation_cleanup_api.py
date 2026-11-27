import unittest

from fastapi.testclient import TestClient

from app import app


class DictationCleanupApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_cleanup_returns_local_word_fixes_and_deterministic_punctuation(self):
        response = self.client.post(
            "/api/dictate/cleanup",
            json={
                "transcript": "jason comma send the notes period new paragraph we will ship Friday",
                "dictionary": {"jason": "JSON"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "cleaned_text": "JSON, send the notes.\n\nWe will ship Friday.",
            "engine": "rules",
            "fallback_reason": None,
        })

    def test_smart_mode_removes_fillers_and_reports_the_engine(self):
        response = self.client.post(
            "/api/dictate/cleanup",
            json={
                "transcript": "um we should ship it at three no four",
                "mode": "smart",
                "language": "en",
                "context": {"app_name": "Slack", "field_role": "AXTextArea"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "cleaned_text": "We should ship it at four.",
            "engine": "smart_rules",
            "fallback_reason": None,
        })

    def test_default_mode_keeps_fillers_even_when_context_is_sent(self):
        response = self.client.post(
            "/api/dictate/cleanup",
            json={"transcript": "um we should ship it", "context": {"app_name": "Mail"}},
        )

        self.assertEqual(response.json()["cleaned_text"], "Um we should ship it.")
        self.assertEqual(response.json()["engine"], "rules")

    def test_cleanup_rejects_extra_fields_invalid_dictionary_and_oversized_text(self):
        invalid_requests = (
            {"transcript": "hello", "unknown": True},
            {"transcript": "hello", "dictionary": {"word": 5}},
            {"transcript": "x" * 262_145},
            {"transcript": "hello", "mode": "llm"},
            {"transcript": "hello", "language": "english-us"},
            {"transcript": "hello", "context": {"surprise": "x"}},
            {"transcript": "hello", "context": {"app_name": "x" * 129}},
            {"transcript": "hello", "context": {"field_text": "x" * 1_001}},
            {"transcript": "hello", "context": {"app_name": 5}},
        )
        for payload in invalid_requests:
            with self.subTest(payload_keys=list(payload)):
                response = self.client.post("/api/dictate/cleanup", json=payload)
                self.assertEqual(response.status_code, 422)

    def test_context_control_characters_are_rejected_without_echoing_the_text(self):
        secret = "my private sentence\x00"
        response = self.client.post(
            "/api/dictate/cleanup",
            json={"transcript": "hello there", "context": {"field_text": secret}},
        )

        self.assertEqual(response.status_code, 422)
        self.assertNotIn("private", response.text)

    def test_cleanup_applies_the_plain_word_list_and_reports_steps_on_request(self):
        response = self.client.post(
            "/api/dictate/cleanup",
            json={
                "transcript": "um ship easy D P",
                "mode": "smart",
                "language": "en",
                "words": ["easydp"],
                "include_steps": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "cleaned_text": "Ship easydp.",
            "engine": "smart_rules",
            "fallback_reason": None,
            "steps": {
                "after_smart": "ship easy D P",
                "dictionary_changes": [{"from": "easy D P", "to": "easydp"}],
            },
        })

    def test_cleanup_rejects_an_oversized_word_list(self):
        response = self.client.post(
            "/api/dictate/cleanup",
            json={"transcript": "hello there", "words": [f"w{i}" for i in range(257)]},
        )

        self.assertEqual(response.status_code, 422)

    def test_cleanup_returns_safe_client_error_for_empty_transcript(self):
        response = self.client.post("/api/dictate/cleanup", json={"transcript": " \n "})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Transcript text cannot be empty."})


if __name__ == "__main__":
    unittest.main()
