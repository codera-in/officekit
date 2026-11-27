"""
TDD Tests for Module 2: Voice Dictation & Local Meeting Minutes
- Action items extraction
- Decision logging
- Clean Markdown formatting
"""

import json
import unittest
from pathlib import Path
from officekit.engines.engine_dictate import MeetingDictateEngine

class TestModule2DictateEngine(unittest.TestCase):

    def test_curated_meeting_notes_classification_benchmark(self):
        benchmark_path = Path(__file__).parent / "fixtures" / "meeting-notes" / "heuristic-benchmark.json"
        cases = json.loads(benchmark_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 20)

        for case in cases:
            with self.subTest(case=case["id"]):
                result = MeetingDictateEngine.format_meeting_notes(case["transcript"])
                self.assertEqual(result["action_items"], case["action_items"])
                self.assertEqual(result["decisions"], case["decisions"])

    def test_meeting_notes_action_items_extraction(self):
        transcript = (
            "Good morning team. We reviewed the quarterly roadmap. "
            "We decided to launch the desktop application next Tuesday. "
            "Sarah will prepare the AppSumo listing copy and screenshots. "
            "David needs to finish the Windows NSIS installer setup. "
            "Everyone agreed that privacy is our primary marketing angle."
        )
        res = MeetingDictateEngine.format_meeting_notes(transcript)

        # Check action items detected
        self.assertGreaterEqual(len(res["action_items"]), 2)
        action_text = " ".join(res["action_items"]).lower()
        self.assertTrue("sarah" in action_text or "appsumo" in action_text)
        self.assertTrue("david" in action_text or "installer" in action_text)

        # Check decisions logged
        self.assertGreaterEqual(len(res["decisions"]), 1)
        decisions_text = " ".join(res["decisions"]).lower()
        self.assertTrue("launch" in decisions_text or "privacy" in decisions_text)

        # Check markdown format
        md = res["markdown"]
        self.assertIn("# Meeting Notes & Transcript", md)
        self.assertIn("## ✅ Action Items & Next Steps", md)
        self.assertIn("## 🎯 Key Decisions", md)
        self.assertIn("- [ ]", md)

    def test_empty_transcript_handling(self):
        text = "Quick one on one catchup today."
        res = MeetingDictateEngine.format_meeting_notes(text)
        self.assertEqual(res["word_count"], 6)
        self.assertIn("Quick one on one catchup today", res["markdown"])

    def test_meeting_notes_do_not_invent_actions_or_decisions(self):
        result = MeetingDictateEngine.format_meeting_notes("The room is ready. The agenda is on the screen.")

        self.assertEqual(result["action_items"], [])
        self.assertEqual(result["decisions"], [])
        self.assertIn("No action items were identified.", result["markdown"])
        self.assertIn("No formal decisions were recorded.", result["markdown"])
        self.assertNotIn("Review transcript notes with team", result["markdown"])

    def test_questions_suggestions_and_passive_future_are_not_confirmed_actions(self):
        result = MeetingDictateEngine.format_meeting_notes(
            "Should we review the proposal? We should consider another vendor. "
            "The updated installer will be available next week."
        )

        self.assertEqual(result["action_items"], [])
        self.assertIn("Should we review the proposal", result["summary"])

    def test_yes_no_questions_and_negated_need_to_are_not_confirmed_actions(self):
        result = MeetingDictateEngine.format_meeting_notes(
            "Will the service restart tonight? We don't need to launch the new build. "
            "We do not need to merge today. Sarah will update the release notes."
        )

        self.assertEqual(result["action_items"], ["Sarah will update the release notes"])
        self.assertIn("Will the service restart tonight", result["summary"])
        self.assertIn("We don't need to launch the new build", result["summary"])

    def test_explicit_commitment_remains_an_action(self):
        result = MeetingDictateEngine.format_meeting_notes(
            "Sarah will review the proposal by Friday. The team must publish the report."
        )

        self.assertEqual(
            result["action_items"],
            ["Sarah will review the proposal by Friday", "The team must publish the report"],
        )

        progressive = MeetingDictateEngine.format_meeting_notes(
            "Sarah will be reviewing the proposal by Friday."
        )
        self.assertEqual(
            progressive["action_items"],
            ["Sarah will be reviewing the proposal by Friday"],
        )

    def test_tentative_will_language_is_not_promoted_to_confirmed_action(self):
        result = MeetingDictateEngine.format_meeting_notes(
            "Sarah will try to finish the test run. David will probably share the build tomorrow. "
            "We will maybe move the launch to Friday. Alex will attempt to reproduce it. "
            "Priya will hopefully send the results. Omar will be trying to resolve it. "
            "Sarah will review the release checklist."
        )

        self.assertEqual(result["action_items"], ["Sarah will review the release checklist"])
        self.assertIn("Sarah will try to finish the test run", result["summary"])
        self.assertIn("David will probably share the build tomorrow", result["summary"])
        self.assertIn("We will maybe move the launch to Friday", result["summary"])
        self.assertIn("Alex will attempt to reproduce it", result["markdown"])
        self.assertIn("Priya will hopefully send the results", result["markdown"])
        self.assertIn("Omar will be trying to resolve it", result["markdown"])

    def test_conditional_future_commitments_are_not_reported_as_confirmed_actions(self):
        transcript = (
            "If the client approves the budget, Sarah will sign the order. "
            "Only if QA passes will David publish the release. "
            "Sarah will send the final draft on Friday."
        )

        result = MeetingDictateEngine.format_meeting_notes(transcript)

        self.assertEqual(result["action_items"], ["Sarah will send the final draft on Friday"])
        self.assertIn("If the client approves the budget", result["summary"])
        self.assertIn("Only if QA passes", result["summary"])

    def test_approved_as_a_draft_modifier_is_not_misclassified_as_a_decision(self):
        result = MeetingDictateEngine.format_meeting_notes(
            "Sarah will send the approved draft on Friday. "
            "Sarah will present the chosen plan tomorrow. "
            "We approved the privacy approach."
        )

        self.assertEqual(
            result["action_items"],
            [
                "Sarah will send the approved draft on Friday",
                "Sarah will present the chosen plan tomorrow",
            ],
        )
        self.assertEqual(result["decisions"], ["We approved the privacy approach"])

    def test_action_and_decision_can_both_be_extracted_from_one_sentence(self):
        result = MeetingDictateEngine.format_meeting_notes(
            "We decided that Sara will send the reviewed proposal by Friday."
        )

        self.assertEqual(result["action_items"], ["We decided that Sara will send the reviewed proposal by Friday"])
        self.assertEqual(result["decisions"], ["We decided that Sara will send the reviewed proposal by Friday"])

    def test_negated_commitments_and_decisions_are_not_reported_as_confirmed(self):
        result = MeetingDictateEngine.format_meeting_notes(
            "We will not publish the report today. We have not decided whether to launch."
        )

        self.assertEqual(result["action_items"], [])
        self.assertEqual(result["decisions"], [])
        self.assertEqual(
            result["summary"],
            "We will not publish the report today We have not decided whether to launch",
        )

    def test_negated_clause_does_not_hide_a_separate_positive_action(self):
        transcript = "We will not ship today, but Sarah will publish the docs tomorrow."
        result = MeetingDictateEngine.format_meeting_notes(transcript)

        self.assertEqual(result["action_items"], ["Sarah will publish the docs tomorrow"])
        self.assertNotIn("will not ship", " ".join(result["action_items"]).lower())

    def test_negated_commitment_does_not_hide_a_new_subject_after_and(self):
        transcript = "Sarah won't send the file and she will update the release notes."
        result = MeetingDictateEngine.format_meeting_notes(transcript)

        self.assertEqual(result["action_items"], ["she will update the release notes"])
        self.assertNotIn("won't send", " ".join(result["action_items"]).lower())

        comma_and = MeetingDictateEngine.format_meeting_notes(
            "Sarah won't send the file, and she will update the release notes."
        )
        self.assertEqual(comma_and["action_items"], ["she will update the release notes"])

        grouped_subject = MeetingDictateEngine.format_meeting_notes(
            "Sarah won't send the file, and the team will update the release notes."
        )
        self.assertEqual(grouped_subject["action_items"], ["the team will update the release notes"])

        shared_subject = MeetingDictateEngine.format_meeting_notes(
            "Alice and Bob will review the release notes."
        )
        self.assertEqual(shared_subject["action_items"], ["Alice and Bob will review the release notes"])

    def test_negated_clause_does_not_hide_a_separate_positive_decision(self):
        transcript = "We have not chosen a launch date, but we approved the privacy approach."
        result = MeetingDictateEngine.format_meeting_notes(transcript)

        self.assertEqual(result["decisions"], ["we approved the privacy approach"])
        self.assertNotIn("not chosen", " ".join(result["decisions"]).lower())

    def test_pending_decision_is_not_reported_as_a_completed_decision(self):
        result = MeetingDictateEngine.format_meeting_notes(
            "There is no decision on the launch until the review is complete."
        )

        self.assertEqual(result["decisions"], [])

    def test_decision_needed_is_not_reported_as_a_decision_already_made(self):
        result = MeetingDictateEngine.format_meeting_notes(
            "We need a decision on pricing by Friday. "
            "The team must make a decision before launch. Decision is required by Friday. "
            "The team reached a decision to retain the current price."
        )

        self.assertEqual(
            result["decisions"],
            ["The team reached a decision to retain the current price"],
        )
        self.assertEqual(
            result["action_items"],
            ["The team must make a decision before launch"],
        )

    def test_pending_or_unfinalized_decision_is_not_reported_as_confirmed(self):
        result = MeetingDictateEngine.format_meeting_notes(
            "The decision is still pending. No final decision has been made. "
            "No final decision on the launch. The launch decision is not final. "
            "We decided the launch date is Friday."
        )

        self.assertEqual(result["decisions"], ["We decided the launch date is Friday"])
        self.assertEqual(
            result["summary"],
            "The decision is still pending No final decision has been made No final decision on the launch",
        )
        self.assertIn("The decision is still pending", result["summary"])
        self.assertIn("No final decision has been made", result["summary"])
        self.assertIn("No final decision on the launch", result["summary"])

    def test_transcript_is_kept_inside_a_safe_dynamic_markdown_fence(self):
        transcript = "Review the proposal.\n# Fake heading\n- [ ] Fake task\n```html\n<img src=x>\n```"
        result = MeetingDictateEngine.format_meeting_notes(transcript)

        self.assertIn("\n````text\n", result["markdown"])
        self.assertTrue(result["markdown"].endswith("\n````"))
        self.assertIn(transcript, result["markdown"])
        self.assertEqual(result["markdown"].count("## 🎯 Key Decisions"), 1)

    def test_transcript_escapes_markdown_and_html_in_generated_bullets(self):
        result = MeetingDictateEngine.format_meeting_notes(
            "<img src=x> will review `release` & report the result."
        )

        self.assertIn("&lt;img src=x&gt; will review \\`release\\` &amp; report the result", result["markdown"])
        self.assertNotIn("<img src=x>", result["markdown"].split("## 🎙️ Full Transcript", 1)[0])

    def test_transcript_type_and_character_limit_are_enforced_by_engine(self):
        for value in (None, 3, ["meeting"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MeetingDictateEngine.format_meeting_notes(value)
        with self.assertRaisesRegex(ValueError, "262144"):
            MeetingDictateEngine.format_meeting_notes("a" * 262145)
        with self.assertRaisesRegex(ValueError, "empty"):
            MeetingDictateEngine.format_meeting_notes(" \n\t ")
        at_limit = MeetingDictateEngine.format_meeting_notes("x" * 262144)
        self.assertEqual(at_limit["word_count"], 1)

    def test_short_fragments_do_not_become_discussion_points(self):
        result = MeetingDictateEngine.format_meeting_notes("Yes. No.")

        self.assertEqual(result["summary"], "")
        self.assertIn("No discussion points were extracted.", result["markdown"])

    def test_summary_uses_at_most_three_of_six_discussion_points(self):
        transcript = " ".join(f"Discussion point number {number}." for number in range(1, 8))
        result = MeetingDictateEngine.format_meeting_notes(transcript)

        self.assertEqual(result["summary"], "Discussion point number 1 Discussion point number 2 Discussion point number 3")
        self.assertEqual(result["markdown"].count("- Discussion point number"), 6)

if __name__ == "__main__":
    unittest.main()
