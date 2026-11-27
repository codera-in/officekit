import re
import unittest

from officekit.engines.engine_dictation_cleanup import DictationCleanupEngine, validate_context


class DictationCleanupTests(unittest.TestCase):
    def test_normalizes_spoken_punctuation_and_paragraphs_without_rewriting_words(self):
        cleaned = DictationCleanupEngine.clean(
            "  hello   comma world period new paragraph we will ship Friday  "
        )

        self.assertEqual(cleaned, "Hello, world.\n\nWe will ship Friday.")

    def test_applies_dictionary_before_punctuation_and_matches_whole_words(self):
        cleaned = DictationCleanupEngine.clean(
            "jason, send jsonish to Jason.",
            dictionary={"jason": "JSON"},
        )

        self.assertEqual(cleaned, "JSON, send jsonish to JSON.")

    def test_preserves_fillers_and_self_corrections_instead_of_guessing_intent(self):
        cleaned = DictationCleanupEngine.clean(
            "um, ship it Friday, actually Monday."
        )

        self.assertEqual(cleaned, "Um, ship it Friday, actually Monday.")

    def test_rejects_invalid_text_and_dictionary_shapes(self):
        for transcript in (None, 12, "", " \n "):
            with self.subTest(transcript=transcript):
                with self.assertRaises(ValueError):
                    DictationCleanupEngine.clean(transcript)

        for dictionary in (
            {"": "value"},
            {"source": ""},
            {"source": 3},
            {"x" * 65: "value"},
            {"source": "y" * 65},
        ):
            with self.subTest(dictionary=dictionary):
                with self.assertRaises(ValueError):
                    DictationCleanupEngine.clean("Some words.", dictionary=dictionary)

    def test_keeps_punctuation_inside_numbers_but_still_spaces_sentences(self):
        self.assertEqual(
            DictationCleanupEngine.clean("meet at 4:15 and pay 3.5 or 1,000 then go.Next"),
            "Meet at 4:15 and pay 3.5 or 1,000 then go. Next.",
        )
        self.assertEqual(DictationCleanupEngine.clean("it is 5 .6 later"), "It is 5. 6 later.")

    def test_rejects_input_over_the_transcript_limit(self):
        with self.assertRaises(ValueError):
            DictationCleanupEngine.clean("x" * 262_145)

    def test_rejects_casefold_duplicate_and_control_character_dictionary_entries(self):
        with self.assertRaises(ValueError):
            DictationCleanupEngine.clean("Hello.", dictionary={"jason": "Jason", "Jason": "JSON"})
        with self.assertRaises(ValueError):
            DictationCleanupEngine.clean("Hello.", dictionary={"name": "bad\nvalue"})
        with self.assertRaises(ValueError):
            DictationCleanupEngine.clean("hello\x00 world")

    def test_rejects_non_mapping_and_oversized_dictionaries(self):
        with self.assertRaises(ValueError):
            DictationCleanupEngine.clean("Hello.", dictionary=[("hello", "hi")])
        with self.assertRaises(ValueError):
            DictationCleanupEngine.clean(
                "Hello.", dictionary={f"word{index}": "fix" for index in range(257)}
            )

    def test_cleanup_is_idempotent_and_does_not_strip_ambiguous_fillers(self):
        once = DictationCleanupEngine.clean("um comma I will ship it Friday")
        twice = DictationCleanupEngine.clean(once)

        self.assertEqual(once, "Um, I will ship it Friday.")
        self.assertEqual(twice, once)


def smart(text, **kwargs):
    return DictationCleanupEngine.clean(text, mode="smart", **kwargs)


class SmartCleanupTests(unittest.TestCase):
    def test_rules_mode_is_unchanged_and_unknown_modes_are_rejected(self):
        self.assertEqual(
            DictationCleanupEngine.clean("um, ship it Friday, actually Monday.", mode="rules"),
            "Um, ship it Friday, actually Monday.",
        )
        with self.assertRaises(ValueError):
            DictationCleanupEngine.clean("Hello there.", mode="llm")

    def test_removes_standalone_fillers_with_their_commas(self):
        self.assertEqual(smart("um, we should ship the build"), "We should ship the build.")
        self.assertEqual(smart("I think, uh, we should wait for the team"), "I think, we should wait for the team.")
        self.assertEqual(smart("so erm that is the plan"), "So that is the plan.")
        self.assertEqual(smart("we agreed to ship it umm"), "We agreed to ship it.")

    def test_keeps_words_that_only_contain_a_filler(self):
        text = "the umbrella and the uhura crew are in the summit"
        self.assertEqual(smart(text), "The umbrella and the uhura crew are in the summit.")

    def test_applies_explicit_number_corrections_only_between_numbers(self):
        self.assertEqual(smart("let us meet at three, no, four"), "Let us meet at four.")
        self.assertEqual(smart("the room is 12 no wait 14 on the left"), "The room is 14 on the left.")
        self.assertEqual(smart("call at 3:30 I mean 4:15 to confirm"), "Call at 4:15 to confirm.")
        self.assertEqual(smart("I have one, no problem at all with the plan"), "I have one, no problem at all with the plan.")
        self.assertEqual(smart("that is a no brainer for the team"), "That is a no brainer for the team.")

    def test_scratch_that_removes_the_dictated_statement_it_cancels(self):
        self.assertEqual(
            smart("We ship Friday. Scratch that. We ship Monday."),
            "We ship Monday.",
        )
        self.assertEqual(
            smart("send it to the team scratch that send it to the client"),
            "Send it to the client.",
        )
        self.assertEqual(smart("Scratch that. Send it to the client."), "Send it to the client.")

    def test_scratch_that_as_an_ordinary_verb_is_left_alone(self):
        for sentence in (
            "She will scratch that sofa when the cat wakes up",
            "Please do not scratch that surface with the key",
            "I need to scratch that itch before the meeting",
            "Please do not scratch that email draft again",
            "He tried to scratch that call out of the log",
            "We should scratch that text from the page",
            "You can scratch that book with a pencil",
        ):
            with self.subTest(sentence=sentence):
                result = smart(sentence)
                self.assertIn("scratch that", result.lower())
        self.assertEqual(smart("strike that. We ship on Monday."), "We ship on Monday.")
        self.assertEqual(
            smart("We ship Friday, strike that, we ship Monday"),
            "We ship Monday.",
        )

    def test_german_sentences_with_shared_words_are_not_treated_as_english(self):
        sentence = "Ich weiss in diesem Fall nicht, was er will, um zu helfen"
        self.assertEqual(smart(sentence), "Ich weiss in diesem Fall nicht, was er will, um zu helfen.")

    def test_no_one_after_the_number_one_is_not_a_correction(self):
        self.assertEqual(
            smart("It is the one, no one else was there at five"),
            "It is the one, no one else was there at five.",
        )
        self.assertEqual(smart("Let us meet at three, no, four"), "Let us meet at four.")

    def test_collapses_only_repeated_function_words(self):
        self.assertEqual(smart("I I think the the plan is good"), "I think the plan is good.")
        self.assertEqual(smart("he said that that was the plan and the end"), "He said that that was the plan and the end.")

    def test_rules_apply_to_english_only_and_fail_open_for_other_languages(self):
        german = "ich komme um drei und er kommt um vier"
        self.assertEqual(smart(german), "Ich komme um drei und er kommt um vier.")
        self.assertEqual(
            smart("um we should ship the build", language="de"),
            "Um we should ship the build.",
        )
        self.assertEqual(smart("um we should ship the build", language="en-GB"), "We should ship the build.")
        self.assertEqual(smart("um we should ship the build", language="EN"), "We should ship the build.")

    def test_smart_output_never_adds_words(self):
        samples = (
            "um so I I think we should uh ship it at three no four",
            "We ship Friday. Scratch that. We ship Monday and the team agrees.",
            "send it to the team scratch that send it to the client and the board",
            "erm the the plan is to meet at 12 I mean 14 for the review",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                output_words = set(re.findall(r"[a-z0-9:']+", smart(sample).lower()))
                input_words = set(re.findall(r"[a-z0-9:']+", sample.lower()))
                self.assertLessEqual(output_words, input_words)

    def test_a_transcript_made_only_of_fillers_is_kept_instead_of_emptied(self):
        self.assertEqual(smart("um uh", language="en"), "Um uh.")

    def test_smart_cleanup_is_idempotent_and_dictionary_still_applies(self):
        once = smart("um jason comma we ship it at three no four", dictionary={"jason": "JSON"})
        self.assertEqual(once, "JSON, we ship it at four.")
        self.assertEqual(smart(once), once)


class ContextValidationTests(unittest.TestCase):
    def test_accepts_bounded_labels_and_text_and_ignores_missing_values(self):
        self.assertEqual(validate_context(None), {})
        self.assertEqual(
            validate_context({"app_name": "Slack", "bundle_id": None, "field_text": "hello\nworld"}),
            {"app_name": "Slack", "field_text": "hello\nworld"},
        )

    def test_rejects_unknown_fields_non_text_control_characters_and_oversize(self):
        for context in (
            "Slack",
            {"surprise": "x"},
            {"app_name": 5},
            {"app_name": "bad\x00name"},
            {"app_name": "x" * 129},
            {"field_text": "x" * 1_001},
            {"field_text": "bad\x00text"},
        ):
            with self.subTest(context=str(context)[:40]):
                with self.assertRaises(ValueError):
                    validate_context(context)


class WordListSnapTests(unittest.TestCase):
    def test_spelled_out_letters_snap_to_the_listed_word(self):
        cleaned = DictationCleanupEngine.clean("we shipped easy D P today", words=["easydp"])

        self.assertEqual(cleaned, "We shipped easydp today.")

    def test_sound_alike_word_snaps_and_casing_follows_the_list(self):
        cleaned = DictationCleanupEngine.clean("run cubernetes and kubernetes", words=["Kubernetes"])

        self.assertEqual(cleaned, "Run Kubernetes and Kubernetes.")

    def test_unrelated_words_and_short_words_are_left_alone(self):
        for text in ("we should ship it today", "the sedan was late"):
            with self.subTest(text=text):
                self.assertEqual(
                    DictationCleanupEngine.clean(text, words=["Sedhu", "easydp", "API"]),
                    text[0].upper() + text[1:] + ".",
                )

    def test_a_word_that_is_only_the_start_of_a_listed_term_is_left_alone(self):
        for text, words in (
            ("the whisper was quiet", ["whisper.cpp"]),
            ("we use post every day", ["postgres"]),
            ("open source is fine", ["OpenAI Codex"]),
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    DictationCleanupEngine.clean(text, words=words),
                    text[0].upper() + text[1:] + ".",
                )

    def test_close_sound_alikes_with_a_small_length_gap_still_snap(self):
        self.assertEqual(
            DictationCleanupEngine.clean("we run postgres here", words=["PostgreSQL"]),
            "We run PostgreSQL here.",
        )
        self.assertEqual(
            DictationCleanupEngine.clean("ask open a i", words=["OpenAI"]),
            "Ask OpenAI.",
        )

    def test_replace_entries_win_over_the_plain_word_list(self):
        cleaned = DictationCleanupEngine.clean(
            "ship ecdp now", dictionary={"ecdp": "EasyDP"}, words=["easydp"]
        )

        self.assertEqual(cleaned, "Ship EasyDP now.")

    def test_steps_report_smart_text_and_every_dictionary_change(self):
        cleaned, steps = DictationCleanupEngine.clean_with_steps(
            "um ship easy D P and ecdp", dictionary={"ecdp": "EasyDP"}, mode="smart", language="en",
            words=["easydp"],
        )

        self.assertEqual(steps["after_smart"], "ship easy D P and ecdp")
        self.assertEqual(
            steps["dictionary_changes"],
            [{"from": "easy D P", "to": "easydp"}, {"from": "ecdp", "to": "EasyDP"}],
        )
        self.assertEqual(cleaned, "Ship easydp and EasyDP.")

    def test_rules_mode_has_no_smart_step(self):
        _, steps = DictationCleanupEngine.clean_with_steps("hello world")

        self.assertIsNone(steps["after_smart"])
        self.assertEqual(steps["dictionary_changes"], [])

    def test_rejects_invalid_word_lists_and_skips_oversized_transcripts(self):
        for words in ("easydp", [""], [5], ["x" * 65], ["a\x00b"], [f"w{i}" for i in range(257)]):
            with self.subTest(words=str(words)[:20]):
                with self.assertRaises(ValueError):
                    DictationCleanupEngine.clean("hello there", words=words)
        long_text = "easy D P " * 3_000
        self.assertNotIn("easydp", DictationCleanupEngine.clean(long_text, words=["easydp"]))


if __name__ == "__main__":
    unittest.main()
