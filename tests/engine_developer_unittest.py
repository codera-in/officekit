"""Engine tests for the developer slice (D04, D10, D11, D15, D16, D17)."""

import base64
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock
from xml.etree import ElementTree

import cv2
import numpy as np

from officekit.engines import _myers, engine_developer
from officekit.engines._myers import DELETE, EQUAL, INSERT, EditDistanceExceeded, WorkBudget, diff_ops


def lcs_length(a, b):
    previous = [0] * (len(b) + 1)
    for x in a:
        current = [0]
        for j, y in enumerate(b, 1):
            current.append(previous[j - 1] + 1 if x == y else max(previous[j], current[j - 1]))
        previous = current
    return previous[-1]


def apply_ops(a, b, ops):
    rebuilt_a, rebuilt_b = [], []
    for kind, i, j in ops:
        if kind == EQUAL:
            assert a[i] == b[j]
            rebuilt_a.append(a[i])
            rebuilt_b.append(b[j])
        elif kind == DELETE:
            rebuilt_a.append(a[i])
        else:
            rebuilt_b.append(b[j])
    return rebuilt_a, rebuilt_b


class MyersDiffTests(unittest.TestCase):
    def test_default_bound_is_the_hld_limit(self):
        self.assertEqual(_myers.MAX_EDIT_DISTANCE, 10_000)

    def test_empty_and_one_sided_inputs(self):
        self.assertEqual(diff_ops([], []), [])
        self.assertEqual(diff_ops([], ["x", "y"]), [(INSERT, None, 0), (INSERT, None, 1)])
        self.assertEqual(diff_ops(["x"], []), [(DELETE, 0, None)])

    def test_equal_sequences_are_all_equal_ops(self):
        self.assertEqual(diff_ops(list("abc"), list("abc")), [(EQUAL, 0, 0), (EQUAL, 1, 1), (EQUAL, 2, 2)])

    def test_single_insert_in_the_middle(self):
        ops = diff_ops(["a", "c"], ["a", "b", "c"])
        self.assertEqual(ops, [(EQUAL, 0, 0), (INSERT, None, 1), (EQUAL, 1, 2)])

    def test_matches_brute_force_lcs_on_random_small_sequences(self):
        rng = random.Random(20261022)
        for _ in range(400):
            a = [rng.randrange(4) for _ in range(rng.randrange(0, 12))]
            b = [rng.randrange(4) for _ in range(rng.randrange(0, 12))]
            ops = diff_ops(a, b)
            edits = sum(1 for kind, _, _ in ops if kind != EQUAL)
            self.assertEqual(edits, len(a) + len(b) - 2 * lcs_length(a, b), (a, b))
            rebuilt_a, rebuilt_b = apply_ops(a, b, ops)
            self.assertEqual(rebuilt_a, a)
            self.assertEqual(rebuilt_b, b)

    def test_matches_brute_force_lcs_on_longer_mixed_alphabets(self):
        rng = random.Random(41)
        for _ in range(60):
            alphabet = rng.randrange(2, 7)
            a = [rng.randrange(alphabet) for _ in range(rng.randrange(0, 70))]
            b = [rng.randrange(alphabet) for _ in range(rng.randrange(0, 70))]
            ops = diff_ops(a, b)
            edits = sum(1 for kind, _, _ in ops if kind != EQUAL)
            self.assertEqual(edits, len(a) + len(b) - 2 * lcs_length(a, b))

    def test_indices_are_in_order_and_cover_both_sides(self):
        rng = random.Random(7)
        for _ in range(50):
            a = [rng.randrange(3) for _ in range(rng.randrange(0, 30))]
            b = [rng.randrange(3) for _ in range(rng.randrange(0, 30))]
            ops = diff_ops(a, b)
            a_indices = [i for kind, i, _ in ops if kind != INSERT]
            b_indices = [j for kind, _, j in ops if kind != DELETE]
            self.assertEqual(a_indices, list(range(len(a))))
            self.assertEqual(b_indices, list(range(len(b))))

    def test_length_gap_above_bound_is_rejected_before_searching(self):
        with self.assertRaises(EditDistanceExceeded):
            diff_ops([], list(range(11)), max_edits=10)

    def test_edit_distance_above_bound_is_rejected(self):
        a = [f"a{i}" for i in range(20)]
        b = [f"b{i}" for i in range(20)]
        with self.assertRaises(EditDistanceExceeded):
            diff_ops(a, b, max_edits=39)
        self.assertEqual(len(diff_ops(a, b, max_edits=40)), 40)

    def test_bound_at_exact_edit_count_is_accepted(self):
        ops = diff_ops(["x"], ["y"], max_edits=2)
        self.assertEqual(sum(1 for kind, _, _ in ops if kind != EQUAL), 2)

    def test_default_search_work_budget_is_named(self):
        self.assertEqual(_myers.MAX_SEARCH_WORK, 4_000_000)

    def test_work_budget_rejects_unrelated_inputs_once_spent(self):
        a = [f"a{i}" for i in range(50)]
        b = [f"b{i}" for i in range(50)]
        with self.assertRaises(EditDistanceExceeded):
            diff_ops(a, b, budget=WorkBudget(10))
        self.assertEqual(len(diff_ops(a, b, budget=WorkBudget(10_000_000))), 100)

    def test_default_work_budget_rejects_maximum_size_unrelated_inputs(self):
        a = [f"a{i}" for i in range(10_000)]
        b = [f"b{i}" for i in range(10_000)]
        budget = WorkBudget()
        with self.assertRaises(EditDistanceExceeded):
            diff_ops(a, b, budget=budget)
        self.assertLess(budget.left, 0)

    def test_default_work_budget_accepts_long_inputs_with_few_edits(self):
        a = list(range(50_000))
        b = list(a)
        for index in range(0, 50_000, 500):
            b[index] = -1
        ops = diff_ops(a, b)
        self.assertEqual(sum(1 for kind, _, _ in ops if kind != EQUAL), 200)


class JsonCompareTests(unittest.TestCase):
    def compare(self, original, changed, **options):
        return engine_developer.compare_json(original, changed, **options)

    def kinds(self, result):
        return [(change["kind"], change["path"]) for change in result["changes"]]

    def test_reordered_object_keys_are_equal_at_every_depth(self):
        result = self.compare('{"a":1,"b":{"x":[1,2],"y":true}}', '{"b":{"y":true,"x":[1,2]},"a":1}')
        self.assertTrue(result["equal"])
        self.assertEqual(result["changes"], [])
        self.assertFalse(result["truncated"])

    def test_missing_key_and_null_are_reported_differently(self):
        removed = self.compare('{"a":null}', "{}")
        added = self.compare("{}", '{"a":null}')
        self.assertEqual(self.kinds(removed), [("removed", "/a")])
        self.assertEqual(self.kinds(added), [("added", "/a")])
        self.assertEqual(removed["changes"][0]["before"], "null")
        self.assertNotIn("before", added["changes"][0])
        self.assertEqual(added["changes"][0]["after"], "null")

    def test_ordered_array_insert_does_not_cascade(self):
        result = self.compare("[1,2,3]", "[1,9,2,3]")
        self.assertEqual(self.kinds(result), [("added", "/1")])
        self.assertEqual(result["changes"][0]["after"], "9")

    def test_ordered_array_move_is_one_removal_and_one_addition(self):
        result = self.compare("[1,2,3]", "[2,3,1]")
        self.assertEqual(result["counts"], {"added": 1, "removed": 1, "changed": 0, "type_changed": 0})
        self.assertEqual(self.kinds(result), [("removed", "/0"), ("added", "/2")])

    def test_unordered_array_ignores_position(self):
        self.assertTrue(self.compare("[1,2,3]", "[3,1,2]", array_order="unordered")["equal"])

    def test_unordered_array_reports_original_indices(self):
        insert = self.compare("[1,2]", "[2,1,5]", array_order="unordered")
        self.assertEqual(self.kinds(insert), [("added", "/2")])
        removal = self.compare("[1,2,2]", "[2,1]", array_order="unordered")
        self.assertEqual(self.kinds(removal), [("removed", "/2")])

    def test_unordered_counts_do_not_depend_on_element_order(self):
        rng = random.Random(3)
        for _ in range(40):
            left = [rng.randrange(4) for _ in range(rng.randrange(0, 8))]
            right = [rng.randrange(4) for _ in range(rng.randrange(0, 8))]
            shuffled = right[:]
            rng.shuffle(shuffled)
            base = self.compare(json.dumps(left), json.dumps(right), array_order="unordered")
            again = self.compare(json.dumps(left), json.dumps(shuffled), array_order="unordered")
            self.assertEqual(base["counts"], again["counts"])

    def test_aligned_array_items_recurse_as_changed(self):
        result = self.compare('[{"a":1}]', '[{"a":2}]')
        self.assertEqual(self.kinds(result), [("changed", "/0/a")])
        self.assertEqual(result["changes"][0]["before"], "1")
        self.assertEqual(result["changes"][0]["after"], "2")

    def test_string_and_number_are_a_type_change(self):
        result = self.compare("1", '"1"')
        self.assertEqual(self.kinds(result), [("type_changed", "")])

    def test_number_value_equality_and_lexical_policy(self):
        self.assertTrue(self.compare("1", "1.0")["equal"])
        lexical = self.compare("1", "1.0", numeric="lexical")
        self.assertEqual(self.kinds(lexical), [("changed", "")])
        self.assertTrue(self.compare("100", "1e2")["equal"])
        self.assertFalse(self.compare("100", "1e2", numeric="lexical")["equal"])
        self.assertFalse(self.compare("1.00000000000000000000000000001", "1")["equal"])

    def test_boolean_is_never_equal_to_a_number(self):
        self.assertEqual(self.kinds(self.compare("true", "1")), [("type_changed", "")])
        self.assertEqual(self.kinds(self.compare("false", "0")), [("type_changed", "")])

    def test_scalar_change_reports_previews(self):
        result = self.compare('{"name":"old"}', '{"name":"new"}')
        self.assertEqual(result["counts"]["changed"], 1)
        self.assertEqual(result["changes"][0]["before"], '"old"')
        self.assertEqual(result["changes"][0]["after"], '"new"')

    def test_pointer_paths_escape_tilde_and_slash(self):
        result = self.compare('{"a/b":1,"c~d":1}', '{"a/b":2,"c~d":2}')
        self.assertEqual(self.kinds(result), [("changed", "/a~1b"), ("changed", "/c~0d")])

    def test_previews_are_capped_at_256_characters(self):
        long_text = "x" * 1000
        result = self.compare(json.dumps({"v": long_text}), json.dumps({"v": long_text + "y"}))
        self.assertLessEqual(len(result["changes"][0]["before"]), 256)

    def test_invalid_or_duplicate_json_is_a_controlled_input_error(self):
        for original, changed in (('{"a":1', "{}"), ('{"a":1,"a":2}', "{}"), ("NaN", "1")):
            with self.assertRaises(engine_developer.DeveloperInputError):
                self.compare(original, changed)

    def test_changes_stop_at_ten_thousand_and_counts_keep_going(self):
        original = json.dumps([f"a{i}" for i in range(10_001)])
        changed = json.dumps([f"b{i}" for i in range(10_001)])
        result = self.compare(original, changed, array_order="unordered")
        self.assertTrue(result["truncated"])
        self.assertFalse(result["equal"])
        self.assertEqual(len(result["changes"]), engine_developer.MAX_JSON_CHANGES)
        self.assertEqual(result["counts"]["added"], 10_001)
        self.assertEqual(result["counts"]["removed"], 10_001)

    def test_array_alignment_beyond_the_edit_bound_is_rejected(self):
        original = json.dumps([f"a{i}" for i in range(200)])
        changed = json.dumps([f"b{i}" for i in range(200)])
        with mock.patch.object(_myers, "MAX_EDIT_DISTANCE", 10):
            with self.assertRaises(engine_developer.DeveloperInputError):
                self.compare(original, changed)


class TextDiffTests(unittest.TestCase):
    def diff(self, original, changed, **options):
        return engine_developer.compare_text(original, changed, **options)

    def ops(self, result):
        return [row["op"] for row in result["rows"]]

    def test_insert_delete_and_change_rows_with_line_numbers(self):
        result = self.diff("a\nb\nc\n", "a\nB\nc\nd\n")
        self.assertEqual(self.ops(result), ["equal", "change", "equal", "insert"])
        change = result["rows"][1]
        self.assertEqual((change["left_no"], change["right_no"], change["left"], change["right"]), (2, 2, "b", "B"))
        self.assertEqual(result["rows"][3]["right_no"], 4)
        self.assertEqual(result["stats"], {"inserted": 1, "deleted": 0, "changed": 1})
        self.assertFalse(result["equal"])

    def test_deletions_are_reported_with_left_numbers(self):
        result = self.diff("a\nb\nc\n", "a\nc\n")
        self.assertEqual(self.ops(result), ["equal", "delete", "equal"])
        self.assertEqual(result["rows"][1]["left_no"], 2)
        self.assertEqual(result["stats"], {"inserted": 0, "deleted": 1, "changed": 0})

    def test_identical_and_empty_inputs(self):
        same = self.diff("x\ny", "x\ny")
        self.assertTrue(same["equal"])
        self.assertEqual((same["patch"], same["hunks"]), ("", 0))
        empty = self.diff("", "")
        self.assertTrue(empty["equal"])
        self.assertEqual(empty["rows"], [])
        self.assertEqual(empty["line_endings"], {"original": "none", "changed": "none"})

    def test_unicode_lines_are_compared_and_reported_as_text(self):
        result = self.diff("naïve café 👍🏽\n", "naïve café 👍\n")
        self.assertEqual(self.ops(result), ["change"])
        self.assertEqual(result["rows"][0]["left"], "naïve café 👍🏽")

    def test_line_ending_policy_normalize_versus_exact(self):
        self.assertTrue(self.diff("a\r\nb\r\n", "a\nb\n")["equal"])
        exact = self.diff("a\r\nb\r\n", "a\nb\n", line_endings="exact")
        self.assertEqual(self.ops(exact), ["change", "change"])
        self.assertEqual(exact["rows"][0]["left"], "a")

    def test_line_ending_styles_are_reported_per_side(self):
        result = self.diff("a\r\nb\nc\r", "a\n")
        self.assertEqual(result["line_endings"], {"original": "mixed", "changed": "lf"})
        self.assertEqual(self.diff("a\rb", "a")["line_endings"]["original"], "cr")
        self.assertEqual(self.diff("a\r\n", "a")["line_endings"]["original"], "crlf")

    def test_whitespace_policies_affect_equality_only(self):
        trailing = self.diff("a  \nb\n", "a\nb\n", whitespace="ignore_trailing")
        self.assertTrue(trailing["equal"])
        self.assertEqual(self.diff("a  \nb\n", "a\nb\n")["stats"]["changed"], 1)
        self.assertTrue(self.diff("a b\n", "ab\n", whitespace="ignore_all")["equal"])
        self.assertEqual(self.diff("a b\n", "ab\n", whitespace="exact")["rows"][0]["left"], "a b")

    def test_unicode_normalization_is_optional(self):
        self.assertFalse(self.diff("é\n", "é\n")["equal"])
        self.assertTrue(self.diff("é\n", "é\n", unicode_nfc=True)["equal"])

    def test_inline_spans_cover_changed_code_points(self):
        result = self.diff("hello world\n", "hello there\n")
        change = result["rows"][0]
        # Only "w", "o", "l", "d" are absent from "there" in the code-point LCS, so they are two runs.
        self.assertEqual(change["left_spans"], [{"start": 6, "end": 8}, {"start": 9, "end": 11}])
        self.assertEqual(change["right_spans"], [{"start": 6, "end": 9}, {"start": 10, "end": 11}])

    def test_inline_spans_are_skipped_for_long_lines(self):
        long_line = "x" * 1001
        change = self.diff(long_line + "\n", long_line + "y\n")["rows"][0]
        self.assertNotIn("left_spans", change)

    def test_script_markup_stays_text(self):
        payload = '<script>alert("x")</script>'
        result = self.diff("safe\n", payload + "\n")
        self.assertEqual(result["rows"][0]["right"], payload)
        self.assertIn("+" + payload, result["patch"])
        self.assertNotIn("<", result["markdown"].split("\n")[0])

    def test_one_mebibyte_per_side_is_accepted_and_one_byte_more_is_rejected(self):
        at_limit = "a" * engine_developer.MAX_TEXT_BYTES
        self.assertTrue(self.diff(at_limit, at_limit)["equal"])
        with self.assertRaises(engine_developer.DeveloperInputError):
            self.diff(at_limit + "a", at_limit)

    def test_line_count_limit_is_50000_per_side(self):
        at_limit = "\n" * engine_developer.MAX_DIFF_LINES
        self.assertTrue(self.diff(at_limit, at_limit)["equal"])
        with self.assertRaises(engine_developer.DeveloperInputError):
            self.diff(at_limit + "\n", at_limit)

    def test_too_different_inputs_are_rejected_at_the_bound(self):
        original = "".join(f"a{i}\n" for i in range(30))
        changed = "".join(f"b{i}\n" for i in range(30))
        with self.assertRaises(engine_developer.DeveloperInputError):
            self.diff(original, changed, max_edits=10)
        self.assertEqual(self.diff(original, changed, max_edits=60)["stats"]["changed"], 30)

    def test_context_controls_hunks_and_patch_body(self):
        original = "".join(f"line{i}\n" for i in range(10))
        changed = original.replace("line5\n", "LINE5\n")
        narrow = self.diff(original, changed, context=0)
        wide = self.diff(original, changed, context=3)
        self.assertEqual((narrow["hunks"], wide["hunks"]), (1, 1))
        body = narrow["patch"].split("\n")[2:]
        self.assertEqual(sum(1 for line in body if line[:1] in ("-", "+")), 2)
        self.assertIn("@@ -6,1 +6,1 @@", narrow["patch"])
        self.assertIn(" line4", wide["patch"])
        self.assertNotIn(" line4", narrow["patch"])

    def test_distant_changes_form_separate_hunks(self):
        original = "".join(f"line{i}\n" for i in range(30))
        changed = original.replace("line1\n", "x\n").replace("line28\n", "y\n")
        self.assertEqual(self.diff(original, changed, context=2)["hunks"], 2)

    def test_patch_applies_with_patch_p0(self):
        self.assertIsNotNone(shutil.which("patch"), "patch(1) is required for the D17 export check")
        original = "one\ntwo\nthree\nfour\n"
        changed = "one\n2\nthree\nfour\nfive\n"
        result = self.diff(original, changed)
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, "original")
            patch_file = os.path.join(folder, "change.patch")
            with open(target, "w", encoding="utf-8", newline="") as handle:
                handle.write(original)
            with open(patch_file, "w", encoding="utf-8", newline="") as handle:
                handle.write(result["patch"])
            completed = subprocess.run(
                ["patch", "-p0", "-i", patch_file],
                cwd=folder,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            with open(target, encoding="utf-8", newline="") as handle:
                self.assertEqual(handle.read(), changed)

    def test_patch_round_trip_handles_missing_final_newline(self):
        self.assertIsNotNone(shutil.which("patch"), "patch(1) is required for the D17 export check")
        original = "keep\nold"
        changed = "keep\nnew"
        result = self.diff(original, changed)
        self.assertIn("\\ No newline at end of file", result["patch"])
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, "original")
            patch_file = os.path.join(folder, "change.patch")
            with open(target, "w", encoding="utf-8", newline="") as handle:
                handle.write(original)
            with open(patch_file, "w", encoding="utf-8", newline="") as handle:
                handle.write(result["patch"])
            completed = subprocess.run(["patch", "-p0", "-i", patch_file], cwd=folder, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            with open(target, encoding="utf-8", newline="") as handle:
                self.assertEqual(handle.read(), changed)

    def test_markdown_fence_is_longer_than_any_backtick_run(self):
        content = "use ``` and ````` here\n"
        result = self.diff("plain\n", content)
        longest_run = 5
        markdown = result["markdown"]
        opening = re.match(r"`+", markdown).group(0)
        self.assertGreater(len(opening), longest_run)
        self.assertEqual(markdown.split("\n")[0], opening + "diff")
        self.assertTrue(markdown.endswith(opening + "\n"))

    def test_markdown_fence_has_at_least_three_backticks(self):
        result = self.diff("a\n", "b\n")
        self.assertEqual(result["markdown"].split("\n")[0], "```diff")


class TextMetricsTests(unittest.TestCase):
    def test_empty_input_is_all_zero(self):
        self.assertEqual(
            engine_developer.text_metrics(""),
            {
                "graphemes": 0,
                "code_points": 0,
                "utf8_bytes": 0,
                "utf16_units": 0,
                "words": 0,
                "lines": 0,
                "blank_lines": 0,
                "whitespace": 0,
                "longest_line_graphemes": 0,
            },
        )

    def test_code_points_bytes_and_utf16_units(self):
        metrics = engine_developer.text_metrics("é👍")
        self.assertEqual((metrics["code_points"], metrics["utf8_bytes"], metrics["utf16_units"]), (2, 6, 3))

    def test_line_breaks_are_crlf_cr_and_lf_only(self):
        self.assertEqual(engine_developer.text_metrics("a\r\nb\rc\u2028d\u2029e")["lines"], 3)
        self.assertEqual(engine_developer.text_metrics("a\n")["lines"], 1)
        self.assertEqual(engine_developer.text_metrics("a\n\n")["lines"], 2)

    def test_blank_lines_and_single_break(self):
        metrics = engine_developer.text_metrics("\n")
        self.assertEqual((metrics["lines"], metrics["blank_lines"]), (1, 1))
        metrics = engine_developer.text_metrics("a\n  \nb")
        self.assertEqual((metrics["lines"], metrics["blank_lines"]), (3, 1))

    def test_words_need_a_letter_or_number(self):
        self.assertEqual(engine_developer.text_metrics("Hello, world! 123 --- ...")["words"], 3)
        self.assertEqual(engine_developer.text_metrics("  \t ")["words"], 0)

    def test_whitespace_counts_python_whitespace(self):
        self.assertEqual(engine_developer.text_metrics("a b\tc\u2028")["whitespace"], 3)

    def test_graphemes_follow_extended_clusters(self):
        count = engine_developer.count_graphemes
        self.assertEqual(count("é"), 1)
        self.assertEqual(count("👩‍👩‍👧"), 1)
        self.assertEqual(count("🇮🇳"), 1)
        self.assertEqual(count("👍🏽"), 1)
        self.assertEqual(count("\r\n"), 1)
        self.assertEqual(count("áb"), 2)
        self.assertEqual(count(""), 0)

    def test_mock_example_counts_match_the_approved_metrics(self):
        metrics = engine_developer.text_metrics("Café 👩‍👩‍👧 flag 🇮🇳\ndéjà vu\n")
        self.assertEqual(metrics["graphemes"], 22)
        self.assertEqual(metrics["code_points"], 27)
        self.assertEqual(metrics["words"], 4)
        self.assertEqual(metrics["lines"], 2)
        self.assertEqual(metrics["blank_lines"], 0)
        self.assertEqual(metrics["longest_line_graphemes"], 13)
        self.assertEqual(metrics["utf8_bytes"], len("Café 👩‍👩‍👧 flag 🇮🇳\ndéjà vu\n".encode("utf-8")))

    def test_empty_text_has_zero_graphemes_and_longest_line(self):
        metrics = engine_developer.text_metrics("")
        self.assertEqual((metrics["graphemes"], metrics["longest_line_graphemes"]), (0, 0))


class TextCaseTests(unittest.TestCase):
    def convert(self, text, style, locale="root"):
        return engine_developer.convert_case(text, style, locale)["result"]

    def test_nine_styles_on_mixed_input(self):
        text = "hello WORLD foo_bar"
        self.assertEqual(self.convert(text, "lower"), "hello world foo_bar")
        self.assertEqual(self.convert(text, "upper"), "HELLO WORLD FOO_BAR")
        self.assertEqual(self.convert(text, "title"), "Hello World Foo_Bar")
        self.assertEqual(self.convert("hELLO. wORLD", "sentence"), "Hello. world")
        self.assertEqual(self.convert(text, "camel"), "helloWorldFooBar")
        self.assertEqual(self.convert(text, "pascal"), "HelloWorldFooBar")
        self.assertEqual(self.convert(text, "snake"), "hello_world_foo_bar")
        self.assertEqual(self.convert(text, "kebab"), "hello-world-foo-bar")
        self.assertEqual(self.convert(text, "constant"), "HELLO_WORLD_FOO_BAR")

    def test_identifier_styles_handle_digits_and_punctuation(self):
        text = "hello world-foo_bar2"
        self.assertEqual(self.convert(text, "camel"), "helloWorldFooBar2")
        self.assertEqual(self.convert("  ", "snake"), "")

    def test_apostrophes_do_not_split_words_in_title_case(self):
        self.assertEqual(self.convert("don't STOP", "title"), "Don't Stop")
        self.assertEqual(self.convert("don't stop", "camel"), "dontStop")

    def test_sharp_s_uses_full_case_mapping(self):
        self.assertEqual(self.convert("straße", "upper"), "STRASSE")
        self.assertEqual(self.convert("ßa", "title"), "Ssa")

    def test_turkish_and_azeri_dotted_i_overrides(self):
        for locale in ("tr", "az"):
            self.assertEqual(self.convert("I İ i", "lower", locale), "ı i i")
            self.assertEqual(self.convert("i", "upper", locale), "İ")
            self.assertEqual(self.convert("istanbul", "title", locale), "İstanbul")
            self.assertEqual(self.convert("DIYARBAKIR", "lower", locale), "dıyarbakır")
        self.assertEqual(self.convert("İ", "lower"), "i̇")
        self.assertEqual(self.convert("i", "upper"), "I")

    def test_empty_input_is_empty_for_every_style(self):
        for style in engine_developer.CASE_STYLES:
            self.assertEqual(self.convert("", style), "")

    def test_response_echoes_style_and_locale(self):
        result = engine_developer.convert_case("x", "snake", "tr")
        self.assertEqual(result, {"result": "x", "style": "snake", "locale": "tr"})

    def test_invalid_style_or_locale_is_rejected(self):
        with self.assertRaises(engine_developer.DeveloperInputError):
            engine_developer.convert_case("x", "shout")
        with self.assertRaises(engine_developer.DeveloperInputError):
            engine_developer.convert_case("x", "lower", "de")

    def test_output_growth_above_one_mebibyte_is_rejected(self):
        growing = "ŉ" * 524_288
        self.assertEqual(len(growing.encode("utf-8")), engine_developer.MAX_TEXT_BYTES)
        with self.assertRaises(engine_developer.DeveloperInputError):
            engine_developer.convert_case(growing, "upper")
        self.assertEqual(len(self.convert("a" * 1000, "upper")), 1000)


class TimestampConverterTests(unittest.TestCase):
    def convert(self, value, input_type, zones=("UTC",), source_zone=None, fold="reject"):
        return engine_developer.convert_timestamp(value, input_type, source_zone, fold, list(zones))

    def assertRejected(self, *args, **kwargs):
        with self.assertRaises(engine_developer.DeveloperInputError):
            self.convert(*args, **kwargs)

    def test_epoch_zero_in_every_unit(self):
        result = self.convert("0", "unix_seconds")
        self.assertEqual(result["instant_utc"], "1970-01-01T00:00:00Z")
        self.assertEqual(
            (result["unix_seconds"], result["unix_milliseconds"], result["unix_microseconds"]),
            ("0", "0", "0"),
        )
        self.assertEqual(result["warnings"], [])

    def test_negative_epochs_are_supported(self):
        result = self.convert("-1", "unix_seconds")
        self.assertEqual(result["instant_utc"], "1969-12-31T23:59:59Z")
        self.assertEqual(result["unix_microseconds"], "-1000000")
        self.assertEqual(self.convert("-0.5", "unix_seconds")["unix_seconds"], "-0.5")

    def test_seconds_range_bounds_are_inclusive(self):
        low = self.convert("-62135596800", "unix_seconds")
        self.assertEqual(low["instant_utc"], "0001-01-01T00:00:00Z")
        high = self.convert("253402300799.999999", "unix_seconds")
        self.assertEqual(high["instant_utc"], "9999-12-31T23:59:59.999999Z")
        self.assertRejected("-62135596801", "unix_seconds")
        self.assertRejected("253402300800", "unix_seconds")

    def test_fraction_digits_are_capped_per_unit(self):
        self.assertEqual(self.convert("1.123456", "unix_seconds")["unix_microseconds"], "1123456")
        self.assertRejected("1.1234567", "unix_seconds")
        self.assertEqual(self.convert("1700000000000.123", "unix_milliseconds")["unix_microseconds"], "1700000000000123")
        self.assertRejected("1700000000000.1234", "unix_milliseconds")
        self.assertRejected("1.5", "unix_microseconds")

    def test_milliseconds_and_microseconds_inputs(self):
        ms = self.convert("1700000000000", "unix_milliseconds")
        self.assertEqual(ms["instant_utc"], "2023-11-14T22:13:20Z")
        self.assertEqual(ms["unix_seconds"], "1700000000")
        self.assertEqual(ms["warnings"], [])
        us = self.convert("1700000000000000", "unix_microseconds")
        self.assertEqual(us["instant_utc"], "2023-11-14T22:13:20Z")

    def test_seconds_value_that_looks_like_milliseconds_warns_and_is_not_reinterpreted(self):
        result = self.convert("150000000000", "unix_seconds")
        self.assertEqual(result["warnings"], ["magnitude_suggests_milliseconds"])
        expected = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=150_000_000_000)
        self.assertEqual(result["instant_utc"], expected.isoformat().replace("+00:00", "Z"))
        self.assertRejected("1700000000000", "unix_seconds")

    def test_milliseconds_value_that_looks_like_seconds_warns_but_is_not_zero(self):
        result = self.convert("1500", "unix_milliseconds")
        self.assertEqual(result["warnings"], ["magnitude_suggests_seconds"])
        self.assertEqual(result["instant_utc"], "1970-01-01T00:00:01.500000Z")
        self.assertEqual(self.convert("0", "unix_milliseconds")["warnings"], [])

    def test_malformed_numbers_are_rejected(self):
        for value in ("", "abc", "1e5", "+5", "01", "1.", ".5", " 1", "١٢"):
            self.assertRejected(value, "unix_seconds")

    def test_iso_with_offset_and_z(self):
        zulu = self.convert("2024-02-29T12:00:00Z", "iso_8601")
        self.assertEqual(zulu["instant_utc"], "2024-02-29T12:00:00Z")
        offset = self.convert("2024-02-29T12:00:00+05:30", "iso_8601")
        self.assertEqual(offset["instant_utc"], "2024-02-29T06:30:00Z")
        fractional = self.convert("2024-01-01T00:00:00.5Z", "iso_8601")
        self.assertEqual(fractional["unix_seconds"], "1704067200.5")

    def test_iso_rejects_naive_invalid_dates_and_bad_offsets(self):
        self.assertRejected("2024-02-29T12:00:00", "iso_8601")
        self.assertRejected("2023-02-29T00:00:00Z", "iso_8601")
        self.assertRejected("2024-01-01T24:00:00Z", "iso_8601")
        self.assertRejected("2024-01-01T00:00:60Z", "iso_8601")
        self.assertRejected("2024-01-01T00:00:00+24:00", "iso_8601")
        self.assertRejected("0001-01-01T00:00:00+01:00", "iso_8601")

    def test_local_datetime_uses_the_source_zone(self):
        result = self.convert("2024-07-01T12:00:00", "local_datetime", source_zone="Europe/Berlin")
        self.assertEqual(result["instant_utc"], "2024-07-01T10:00:00Z")
        epoch = self.convert("1970-01-01T00:00:00", "local_datetime", source_zone="UTC")
        self.assertEqual(epoch["unix_seconds"], "0")
        before_epoch = self.convert("1969-12-31T23:59:59", "local_datetime", source_zone="UTC")
        self.assertEqual(before_epoch["unix_seconds"], "-1")

    def test_local_datetime_requires_a_known_zone(self):
        self.assertRejected("2024-07-01T12:00:00", "local_datetime")
        self.assertRejected("2024-07-01T12:00:00", "local_datetime", source_zone="Mars/Olympus")

    def test_dst_gap_is_rejected_for_every_fold(self):
        for fold in ("reject", "earlier", "later"):
            self.assertRejected("2024-03-10T02:30:00", "local_datetime", source_zone="America/New_York", fold=fold)

    def test_dst_fold_is_rejected_unless_resolved_explicitly(self):
        self.assertRejected("2024-11-03T01:30:00", "local_datetime", source_zone="America/New_York")
        earlier = self.convert("2024-11-03T01:30:00", "local_datetime", source_zone="America/New_York", fold="earlier")
        self.assertEqual(earlier["instant_utc"], "2024-11-03T05:30:00Z")
        later = self.convert("2024-11-03T01:30:00", "local_datetime", source_zone="America/New_York", fold="later")
        self.assertEqual(later["instant_utc"], "2024-11-03T06:30:00Z")

    def test_fold_is_ignored_when_the_local_time_is_not_ambiguous(self):
        result = self.convert("2024-07-01T12:00:00", "local_datetime", source_zone="America/New_York", fold="later")
        self.assertEqual(result["instant_utc"], "2024-07-01T16:00:00Z")

    def test_out_of_range_local_datetime_is_rejected(self):
        self.assertRejected("0001-01-01T00:00:00", "local_datetime", source_zone="Europe/Berlin")
        self.assertRejected("9999-12-31T23:59:59", "local_datetime", source_zone="America/New_York")

    def test_target_zone_conversions_include_offset_dst_and_weekday(self):
        result = self.convert(
            "1719835200",
            "unix_seconds",
            zones=("Asia/Kolkata", "America/New_York"),
        )
        india, new_york = result["conversions"]
        self.assertEqual(india["zone"], "Asia/Kolkata")
        self.assertEqual(india["local_iso"], "2024-07-01T17:30:00+05:30")
        self.assertEqual(india["offset"], "+05:30")
        self.assertFalse(india["is_dst"])
        self.assertEqual(india["weekday"], "Monday")
        self.assertEqual(new_york["local_iso"], "2024-07-01T08:00:00-04:00")
        self.assertTrue(new_york["is_dst"])
        self.assertEqual(new_york["abbreviation"], "EDT")

    def test_zone_list_has_between_one_and_eight_unique_entries(self):
        self.assertRejected("0", "unix_seconds", zones=())
        self.assertRejected("0", "unix_seconds", zones=("UTC", "UTC"))
        many = tuple(sorted(engine_developer.list_time_zones()["zones"]))[:9]
        self.assertRejected("0", "unix_seconds", zones=many)

    def test_unknown_input_type_and_fold_policy_are_rejected(self):
        self.assertRejected("0", "unix_days")
        self.assertRejected("2024-01-01T00:00:00", "local_datetime", source_zone="UTC", fold="first")

    def test_time_zone_list_is_sorted_and_bounded(self):
        listing = engine_developer.list_time_zones()
        self.assertEqual(listing["zones"], sorted(listing["zones"]))
        self.assertLessEqual(len(listing["zones"]), engine_developer.MAX_TIME_ZONE_LIST)
        self.assertIn("UTC", listing["zones"])

    def test_local_zone_is_reported_or_null(self):
        with mock.patch.object(engine_developer.tzlocal, "get_localzone_name", return_value="Europe/London"):
            self.assertEqual(engine_developer.list_time_zones()["local_zone"], "Europe/London")
        with mock.patch.object(engine_developer.tzlocal, "get_localzone_name", side_effect=ValueError("no zone")):
            self.assertIsNone(engine_developer.list_time_zones()["local_zone"])


CANONICAL_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class UuidGeneratorTests(unittest.TestCase):
    def generate(self, version, count=1, **options):
        return engine_developer.generate_uuids(version, count, **options)["uuids"]

    def test_v4_format_version_nibble_and_variant_bits(self):
        for text in self.generate(4, 50):
            match = CANONICAL_UUID.fullmatch(text)
            self.assertIsNotNone(match, text)
            self.assertEqual(text[14], "4")
            self.assertIn(text[19], "89ab")

    def test_v7_format_version_nibble_and_variant_bits(self):
        for text in self.generate(7, 50):
            self.assertIsNotNone(CANONICAL_UUID.fullmatch(text), text)
            self.assertEqual(text[14], "7")
            self.assertIn(text[19], "89ab")

    def test_ten_thousand_v4_and_v7_have_no_duplicates(self):
        for version in (4, 7):
            seen = set()
            for _ in range(10):
                batch = self.generate(version, 1000)
                self.assertEqual(len(batch), 1000)
                seen.update(batch)
            self.assertEqual(len(seen), 10_000, version)

    def test_v7_is_monotonic_within_a_batch(self):
        batch = self.generate(7, 1000)
        self.assertEqual(batch, sorted(batch))
        self.assertEqual(len(set(batch)), 1000)

    def test_v7_timestamp_follows_the_clock_and_never_goes_backwards(self):
        clock = iter([1_700_000_000_000, 1_700_000_000_000, 1_699_999_999_000, 1_700_000_000_500])
        values = engine_developer._uuid7_ints(4, lambda: next(clock), lambda bits: 1)
        millis = [value >> 80 for value in values]
        self.assertEqual(millis[0], 1_700_000_000_000)
        self.assertEqual(millis[1], 1_700_000_000_000)
        self.assertEqual(millis[2], 1_700_000_000_000)
        self.assertEqual(millis[3], 1_700_000_000_500)
        self.assertEqual(values, sorted(values))

    def test_v7_counter_overflow_borrows_the_next_millisecond(self):
        seeds = iter([0xFFE, 0])

        def fake_bits(width):
            if width == 11:
                return next(seeds)
            return 0

        values = engine_developer._uuid7_ints(3, lambda: 5_000, fake_bits)
        self.assertEqual([value >> 80 for value in values], [5_000, 5_000, 5_001])
        self.assertEqual(values, sorted(values))
        self.assertEqual((values[1] >> 64) & 0xFFF, 0xFFF)
        self.assertEqual((values[2] >> 64) & 0xFFF, 0)

    def test_v5_matches_rfc_9562_dns_vector_and_hashlib_recomputation(self):
        self.assertEqual(
            self.generate(5, 1, namespace="dns", name="python.org"),
            ["886313e1-3b8a-5372-9b90-0c9aee199e5d"],
        )
        name = "www.example.com"
        digest = hashlib.sha1(uuid.NAMESPACE_DNS.bytes + name.encode("utf-8")).digest()[:16]
        expected = bytearray(digest)
        expected[6] = (expected[6] & 0x0F) | 0x50
        expected[8] = (expected[8] & 0x3F) | 0x80
        self.assertEqual(self.generate(5, 1, namespace="dns", name=name), [str(uuid.UUID(bytes=bytes(expected)))])

    def test_v5_accepts_a_canonical_namespace_uuid(self):
        self.assertEqual(
            self.generate(5, 1, namespace=str(uuid.NAMESPACE_URL), name="https://example.com/"),
            self.generate(5, 1, namespace="url", name="https://example.com/"),
        )

    def test_v5_rejects_bad_namespace_name_and_count(self):
        bad_calls = [
            dict(version=5, count=2, namespace="dns", name="a"),
            dict(version=5, count=1, namespace=None, name="a"),
            dict(version=5, count=1, namespace="dns", name=None),
            dict(version=5, count=1, namespace="dns", name=""),
            dict(version=5, count=1, namespace="dns", name="é" * 513),
            dict(version=5, count=1, namespace="nope", name="a"),
            dict(version=5, count=1, namespace="ABCDEF", name="a"),
        ]
        for call in bad_calls:
            with self.assertRaises(engine_developer.DeveloperInputError, msg=str(call)):
                engine_developer.generate_uuids(
                    call["version"],
                    call["count"],
                    namespace=call["namespace"],
                    name=call["name"],
                    case="lower",
                    style="canonical",
                )

    def test_name_is_limited_to_1024_utf8_bytes(self):
        self.assertEqual(len(self.generate(5, 1, namespace="dns", name="a" * 1024)), 1)
        with self.assertRaises(engine_developer.DeveloperInputError):
            self.generate(5, 1, namespace="dns", name="a" * 1025)

    def test_v4_and_v7_reject_namespace_or_name(self):
        for version in (4, 7):
            with self.assertRaises(engine_developer.DeveloperInputError):
                self.generate(version, 1, name="a")
            with self.assertRaises(engine_developer.DeveloperInputError):
                self.generate(version, 1, namespace="dns")

    def test_batch_limits_and_unsupported_versions(self):
        self.assertEqual(len(self.generate(4, 1000)), 1000)
        for count in (0, 1001):
            with self.assertRaises(engine_developer.DeveloperInputError):
                self.generate(4, count)
        for version in (1, 3, 6, 8, "4", True):
            with self.assertRaises(engine_developer.DeveloperInputError):
                self.generate(version, 1)

    def test_case_and_style_formatting(self):
        text = str(uuid.UUID("886313e1-3b8a-5372-9b90-0c9aee199e5d"))
        ns = dict(version=5, name="python.org", namespace="dns")
        self.assertEqual(self.generate(**ns, case="upper")[0], text.upper())
        self.assertEqual(self.generate(**ns, style="braces")[0], "{" + text + "}")
        self.assertEqual(self.generate(**ns, style="urn")[0], "urn:uuid:" + text)
        self.assertEqual(self.generate(**ns, style="compact")[0], text.replace("-", ""))
        self.assertEqual(self.generate(**ns, case="upper", style="urn")[0], "urn:uuid:" + text.upper())

    def test_response_shape(self):
        result = engine_developer.generate_uuids(4, 3, namespace=None, name=None, case="lower", style="canonical")
        self.assertEqual(set(result), {"uuids", "version", "count"})
        self.assertEqual((result["version"], result["count"], len(result["uuids"])), (4, 3, 3))


SVG_NAMESPACE = "{http://www.w3.org/2000/svg}"
SVG_ALLOWED_ELEMENTS = {"svg", "rect", "path"}
SVG_ALLOWED_ATTRIBUTES = {"xmlns", "viewBox", "width", "height", "fill", "d"}
SVG_MODULE = re.compile(r"M([0-9]+) ([0-9]+)h1v1h-1z")


def decode_png(png_bytes):
    """Read a PNG with OpenCV's default detector.

    OpenCV's default detector misreads one ECC-L matrix produced by ``qrcode`` for
    "hello lowercase bytes" (empty result). The Aruco-based detector, a separate
    OpenCV algorithm, reads that same matrix, so it is the fallback.
    """
    image = cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
    if not text:
        text, _, _ = cv2.QRCodeDetectorAruco().detectAndDecode(image)
    return text


def rasterize_svg_modules(svg_text, scale=8):
    """Draw only the path's module squares, the way a rasterizer would, then upscale."""
    root = ElementTree.fromstring(svg_text)
    modules_count = int(root.get("viewBox").split()[2])
    grid = np.full((modules_count, modules_count), 255, dtype=np.uint8)
    path = root.find(f"{SVG_NAMESPACE}path")
    for match in SVG_MODULE.finditer(path.get("d")):
        grid[int(match.group(2)), int(match.group(1))] = 0
    return np.repeat(np.repeat(grid, scale, axis=0), scale, axis=1)


class QrGeneratorTests(unittest.TestCase):
    def generate(self, payload, ecc="M", size=512, fmt="png"):
        return engine_developer.generate_qr(payload, ecc, size, fmt)

    def test_ascii_and_url_payloads_decode_from_png(self):
        payloads = [
            "https://example.com/path?q=1&r=two",
            "HELLO WORLD 12345",
            "hello lowercase bytes",
            "x" * 300,
        ]
        for payload in payloads:
            for ecc in engine_developer.QR_ERROR_LEVELS:
                png = base64.b64decode(self.generate(payload, ecc, 512)["data"])
                self.assertEqual(decode_png(png), payload, (payload[:20], ecc))

    def test_png_is_a_valid_png_with_requested_module_scale(self):
        result = self.generate("hello", "M", 512)
        png = base64.b64decode(result["data"])
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(result["modules"], 21)
        self.assertEqual(result["qr_version"], 1)
        modules_with_border = 21 + 2 * engine_developer.QR_BORDER
        module_px = round(512 / modules_with_border)
        self.assertEqual(result["size_px"], modules_with_border * module_px)
        self.assertEqual(result["payload_bytes"], 5)

    def test_unicode_payloads_decode_as_utf8(self):
        for payload in ("Café ☕ 你好", "é", "naïve 👍🏽"):
            for ecc in ("L", "M"):
                result = self.generate(payload, ecc, 512)
                self.assertEqual(decode_png(base64.b64decode(result["data"])), payload, (payload, ecc))
                self.assertEqual(result["payload_bytes"], len(payload.encode("utf-8")))

    def test_module_matrix_has_finder_patterns_and_a_quiet_zone(self):
        matrix = engine_developer.qr_matrix("Café", "M")
        size = len(matrix)
        version = (size - 2 * engine_developer.QR_BORDER - 17) // 4
        self.assertEqual(size, 17 + 4 * version + 2 * engine_developer.QR_BORDER)
        for row in range(7):
            for col in range(7):
                finder_dark = row in (0, 6) or col in (0, 6) or (2 <= row <= 4 and 2 <= col <= 4)
                self.assertEqual(matrix[4 + row][4 + col], finder_dark)
        self.assertFalse(any(matrix[row][col] for row in range(4) for col in range(size)))

    def test_capacity_limit_per_error_correction_level(self):
        for level, limit in engine_developer.QR_BYTE_CAPACITY.items():
            self.assertEqual(self.generate("a" * limit, level, 512)["qr_version"], 40)
            with self.assertRaises(engine_developer.DeveloperInputError, msg=level):
                self.generate("a" * (limit + 1), level, 512)

    def test_capacity_counts_utf8_bytes_not_characters(self):
        self.assertEqual(engine_developer.QR_BYTE_CAPACITY["L"], 2953)
        with self.assertRaises(engine_developer.DeveloperInputError):
            self.generate("é" * 1477, "L", 512)
        self.generate("é" * 1476 + "a", "L", 512)

    def test_svg_has_only_allow_listed_elements_and_no_payload_text(self):
        payload = "https://example.com/secret-token"
        svg = self.generate(payload, "Q", 512, "svg")["data"]
        root = ElementTree.fromstring(svg)
        elements = {element.tag.replace(SVG_NAMESPACE, "") for element in root.iter()}
        self.assertLessEqual(elements, SVG_ALLOWED_ELEMENTS)
        for element in root.iter():
            self.assertLessEqual(set(element.attrib), SVG_ALLOWED_ATTRIBUTES)
            self.assertFalse((element.text or "").strip())
        lowered = svg.lower()
        for forbidden in ("<script", "<text", "<title", "href", "style", "foreignobject", "payload", "secret-token"):
            self.assertNotIn(forbidden, lowered)

    def test_svg_rasterized_modules_decode_to_the_payload(self):
        payload = "SVG-PAYLOAD-2026"
        result = self.generate(payload, "H", 512, "svg")
        raster = rasterize_svg_modules(result["data"])
        padded = np.pad(raster, 32, constant_values=255)
        text, _, _ = cv2.QRCodeDetector().detectAndDecode(padded)
        self.assertEqual(text, payload)

    def test_svg_and_png_describe_the_same_module_matrix(self):
        payload = "same modules"
        matrix = engine_developer.qr_matrix(payload, "M")
        svg = self.generate(payload, "M", 512, "svg")["data"]
        dark = {(int(x), int(y)) for x, y in SVG_MODULE.findall(svg)}
        expected = {(x, y) for y, row in enumerate(matrix) for x, value in enumerate(row) if value}
        self.assertEqual(dark, expected)

    def test_rejections(self):
        for call in (
            ("", "M", 512, "png"),
            ("x", "X", 512, "png"),
            ("x", "M", 127, "png"),
            ("x", "M", 2049, "png"),
            ("x", "M", 512, "gif"),
            ("x", "M", True, "png"),
        ):
            with self.assertRaises(engine_developer.DeveloperInputError, msg=str(call)):
                engine_developer.generate_qr(*call)

    def test_size_bounds_are_accepted(self):
        self.assertTrue(self.generate("x", "M", 128)["data"])
        self.assertTrue(self.generate("x", "M", 2048)["data"])

    def test_response_shape(self):
        result = self.generate("abc", "L", 256, "png")
        self.assertEqual(set(result), {"format", "data", "qr_version", "modules", "payload_bytes", "size_px"})
        self.assertEqual(result["format"], "png")


class DeveloperEdgeCaseTests(unittest.TestCase):
    def test_json_nulls_and_nested_arrays_compare_by_canonical_value(self):
        self.assertTrue(engine_developer.compare_json("[null, [1, {\"a\": null}]]", "[null, [1.0, {\"a\": null}]]")["equal"])
        result = engine_developer.compare_json("[[1]]", "[[2]]")
        self.assertEqual([change["path"] for change in result["changes"]], ["/0/0"])
        self.assertTrue(engine_developer.compare_json("null", "null")["equal"])

    def test_text_diff_rejects_unknown_policies_and_bad_context(self):
        for options in (
            {"whitespace": "ignore_case"},
            {"line_endings": "crlf"},
            {"context": 21},
            {"context": -1},
            {"context": True},
            {"unicode_nfc": "yes"},
        ):
            with self.assertRaises(engine_developer.DeveloperInputError, msg=str(options)):
                engine_developer.compare_text("a\n", "b\n", **options)

    def test_patch_marks_a_final_context_line_without_newline(self):
        self.assertIsNotNone(shutil.which("patch"), "patch(1) is required for the D17 export check")
        original = "one\ntwo\nlast"
        changed = "one\nTWO\nlast"
        result = engine_developer.compare_text(original, changed)
        self.assertIn(" last\n\\ No newline at end of file\n", result["patch"])
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, "original")
            patch_file = os.path.join(folder, "change.patch")
            with open(target, "w", encoding="utf-8", newline="") as handle:
                handle.write(original)
            with open(patch_file, "w", encoding="utf-8", newline="") as handle:
                handle.write(result["patch"])
            completed = subprocess.run(["patch", "-p0", "-i", patch_file], cwd=folder, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            with open(target, encoding="utf-8", newline="") as handle:
                self.assertEqual(handle.read(), changed)

    def test_local_datetime_rejects_bad_shapes_and_impossible_dates(self):
        for value in ("2024-07-01 12:00:00", "2024-02-30T00:00:00", "2024-07-01T12"):
            with self.assertRaises(engine_developer.DeveloperInputError, msg=value):
                engine_developer.convert_timestamp(value, "local_datetime", None, "reject", ["UTC"])
            with self.assertRaises(engine_developer.DeveloperInputError, msg=value):
                engine_developer.convert_timestamp(value, "local_datetime", "UTC", "reject", ["UTC"])

    def test_zone_that_the_system_lists_but_cannot_load_is_rejected(self):
        with mock.patch.object(engine_developer, "ZoneInfo", side_effect=ValueError("bad")):
            with self.assertRaises(engine_developer.DeveloperInputError):
                engine_developer.convert_timestamp("0", "unix_seconds", None, "reject", ["UTC"])

    def test_target_zone_conversion_overflow_is_rejected(self):
        with self.assertRaises(engine_developer.DeveloperInputError):
            engine_developer.convert_timestamp("253402300799", "unix_seconds", None, "reject", ["Pacific/Kiritimati"])

    def test_uuid_rejects_unknown_case_or_style(self):
        for options in ({"case": "mixed"}, {"style": "base64"}):
            with self.assertRaises(engine_developer.DeveloperInputError, msg=str(options)):
                engine_developer.generate_uuids(4, 1, namespace=None, name=None, **({"case": "lower", "style": "canonical"} | options))

    def test_qr_overflow_inside_the_encoder_maps_to_the_input_error(self):
        from qrcode.exceptions import DataOverflowError

        with mock.patch.object(engine_developer.qrcode.QRCode, "make", side_effect=DataOverflowError("full")):
            with self.assertRaises(engine_developer.DeveloperInputError):
                engine_developer.generate_qr("abc", "M", 512, "png")
        with self.assertRaises(engine_developer.DeveloperInputError):
            engine_developer.generate_qr("abc", "M", 512.0, "png")

class QrSizeRangeTests(unittest.TestCase):
    def test_returned_side_is_clamped_into_the_documented_range_at_both_ends(self):
        low = engine_developer.generate_qr("hi", "M", 128, "png")
        high = engine_developer.generate_qr("hi", "M", 2048, "png")
        self.assertEqual(low["modules"], 21)
        self.assertEqual((low["size_px"], high["size_px"]), (145, 2030))

    def test_every_side_in_the_range_stays_inside_it(self):
        for size_px in (128, 129, 500, 1023, 2047, 2048):
            side = engine_developer.generate_qr("hi", "L", size_px, "svg")["size_px"]
            self.assertTrue(128 <= side <= 2048, (size_px, side))


class TextMetricLineModelTests(unittest.TestCase):
    def test_metrics_and_text_diff_share_one_line_model(self):
        text = "one\u2028two\u2029three\n"
        self.assertEqual(engine_developer.text_metrics(text)["lines"], 1)
        self.assertEqual(len(engine_developer.compare_text(text, text)["rows"]), 1)

    def test_combining_marks_join_their_base_into_one_grapheme(self):
        count = engine_developer.count_graphemes
        self.assertEqual(count("é"), 1)
        self.assertEqual(count("ä́"), 1)
        self.assertEqual(count("éa"), 2)
        self.assertEqual(count("👋🏽"), 1)


class SharedJsonSearchBudgetTests(unittest.TestCase):
    def test_arrays_in_one_document_share_one_search_budget(self):
        left = [f"a{i}" for i in range(40)]
        right = [f"b{i}" for i in range(40)]
        probe = _myers.WorkBudget(10**9)
        _myers.diff_ops(left, right, budget=probe)
        one_array_cost = 10**9 - probe.left
        with mock.patch.object(engine_developer, "MAX_JSON_SEARCH_WORK", one_array_cost * 3 // 2):
            # One array fits the request budget on its own.
            engine_developer.compare_json(json.dumps(left), json.dumps(right))
            # Two arrays, each within the per-diff bound, exceed it together.
            with self.assertRaises(engine_developer.DeveloperInputError):
                engine_developer.compare_json(
                    json.dumps({"x": left, "y": left}),
                    json.dumps({"x": right, "y": right}),
                )


class WorkBudgetTests(unittest.TestCase):
    def test_text_diff_spans_stop_at_the_shared_budget_and_say_so(self):
        original = "".join(f"{'a' * 40}{i}\n" for i in range(3))
        changed = "".join(f"{'b' * 40}{i}\n" for i in range(3))
        with mock.patch.object(engine_developer, "MAX_INLINE_SPAN_WORK", 1):
            result = engine_developer.compare_text(original, changed)
        self.assertTrue(result["spans_omitted"])
        self.assertEqual(result["stats"]["changed"], 3)
        for row in result["rows"]:
            self.assertNotIn("left_spans", row)
            self.assertNotIn("right_spans", row)

    def test_text_diff_keeps_every_span_when_the_budget_is_ample(self):
        original = "".join(f"{'a' * 40}{i}\n" for i in range(3))
        changed = "".join(f"{'b' * 40}{i}\n" for i in range(3))
        with mock.patch.object(engine_developer, "MAX_INLINE_SPAN_WORK", 10**9):
            result = engine_developer.compare_text(original, changed)
        self.assertFalse(result["spans_omitted"])
        for row in result["rows"]:
            self.assertIn("left_spans", row)
            self.assertIn("right_spans", row)

    def test_worst_case_changed_lines_keep_spans_inside_the_default_budget(self):
        original = "".join(f"L{i:04d}" + "a" * 995 + "\n" for i in range(1000))
        changed = "".join(f"R{i:04d}" + "b" * 995 + "\n" for i in range(1000))
        result = engine_developer.compare_text(original, changed)
        self.assertEqual(result["stats"]["changed"], 1000)
        self.assertTrue(result["spans_omitted"])
        self.assertLess(sum(1 for row in result["rows"] if "left_spans" in row), 1000)

    def test_json_change_paths_are_capped_in_bytes_and_the_rest_are_counted(self):
        key = "k" * 5_000
        original = json.dumps({key: {str(i): i for i in range(50)}})
        changed = json.dumps({key: {str(i): i + 1 for i in range(50)}})
        with mock.patch.object(engine_developer, "MAX_JSON_OUTPUT_BYTES", 20_000):
            result = engine_developer.compare_json(original, changed)
        self.assertEqual(result["counts"]["changed"], 50)
        self.assertEqual(len(result["changes"]), 3)
        self.assertTrue(result["truncated"])
        listed = sum(
            len((change["path"] + change.get("before", "") + change.get("after", "")).encode("utf-8"))
            for change in result["changes"]
        )
        self.assertLessEqual(listed, 20_000)


if __name__ == "__main__":
    unittest.main()
