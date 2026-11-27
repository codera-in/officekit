"""Pure page-range parsing helpers shared by PDF tools and tests."""

import re

def parse_page_ranges(
    range_str: str, max_pages: int, max_selected_pages: int | None = None
) -> list[int]:
    """Parse 1-based page numbers/ranges into zero-based page indices."""
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("The PDF must contain at least one page.")
    if max_selected_pages is not None and (
        isinstance(max_selected_pages, bool)
        or not isinstance(max_selected_pages, int)
        or max_selected_pages < 1
    ):
        raise ValueError("The selected-page limit must be a positive integer.")
    if not isinstance(range_str, str) or not range_str.strip():
        raise ValueError("Select at least one page or page range.")
    if len(range_str) > 4096:
        raise ValueError("The page selection is too long.")

    parts = range_str.split(',')
    pages = []
    selected = set()
    part_pattern = re.compile(r"([0-9]+)(?:\s*-\s*([0-9]+))?")
    for part in parts:
        match = part_pattern.fullmatch(part.strip())
        if match is None:
            raise ValueError("Use page numbers and ascending ranges, for example 1-3, 5.")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start < 1 or end > max_pages:
            raise ValueError("A selected page is outside this PDF.")
        if end < start:
            raise ValueError("Page ranges must be in ascending order.")
        if max_selected_pages is not None and len(pages) + (end - start + 1) > max_selected_pages:
            raise ValueError("The page selection exceeds the supported page limit.")
        for page in range(start, end + 1):
            index = page - 1
            if index in selected:
                raise ValueError("A page was selected more than once.")
            selected.add(index)
            pages.append(index)
    return pages
