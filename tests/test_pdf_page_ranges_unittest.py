import unittest

from officekit.engines.engine_pdf_ranges import parse_page_ranges
from officekit.engines.engine_pdf_advanced import AdvancedPdfEngine


class PageRangeParserTests(unittest.TestCase):
    def test_preserves_the_explicit_selection_order(self):
        self.assertEqual(parse_page_ranges("3, 1-2", 5), [2, 0, 1])

    def test_rejects_empty_selections(self):
        for value in ("", "  ", ", ,"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_page_ranges(value, 5)

    def test_rejects_malformed_and_reversed_ranges(self):
        for value in ("1,,2", "1-a", "1-2-3", "3-2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_page_ranges(value, 5)

    def test_rejects_pages_outside_the_document(self):
        for value in ("0", "6", "1-6"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_page_ranges(value, 5)

    def test_rejects_duplicate_pages_in_overlapping_or_repeated_selections(self):
        for value in ("1,1", "1-3,3-4"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_page_ranges(value, 5)

    def test_rejects_invalid_document_page_count(self):
        for count in (-1, 0, True, None):
            with self.subTest(count=count), self.assertRaises(ValueError):
                parse_page_ranges("1", count)

    def test_rejects_non_string_and_overlong_selections(self):
        for value in (None, 5, "1" * 4097):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                parse_page_ranges(value, 5)

    def test_selected_page_budget_accepts_the_boundary_and_rejects_one_over(self):
        self.assertEqual(parse_page_ranges("1-3", 5, max_selected_pages=3), [0, 1, 2])
        with self.assertRaisesRegex(ValueError, "supported page limit"):
            parse_page_ranges("1-4", 5, max_selected_pages=3)
        for limit in (0, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                parse_page_ranges("1", 5, max_selected_pages=limit)

    def test_grouped_split_rejects_group_count_before_opening_a_pdf(self):
        for groups in ([], [{"name": "one.pdf", "page_ranges": "1"}], [
            {"name": f"page-{index}.pdf", "page_ranges": "1"}
            for index in range(AdvancedPdfEngine.MAX_SPLIT_GROUPS + 1)
        ]):
            with self.subTest(group_count=len(groups)), self.assertRaises(ValueError):
                AdvancedPdfEngine.split_by_groups(b"not opened", groups)


if __name__ == "__main__":
    unittest.main()
