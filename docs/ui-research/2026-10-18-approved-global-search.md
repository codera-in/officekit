# Approved global search behavior

On 2026-10-18, the user asked for the global search to match the Spotlight-style reference and clarified, “both search should have same behaviour”. The user approved the revised mock with “approved”.

The approved mock was shown from `design/mocks/global-search-spotlight.html`; its screenshot is retained at `docs/ui-research/2026-10-18-global-search-approved-mock.png`. The approval is mirrored in `review/global-search/requirements.md`. The temporary HTML preview is removed after approval per the repository mock-review workflow.

- The catalogue and ⌘K palette use the same tool-search endpoint and return the same query matches. The palette keeps endpoint relevance order; catalogue category groups follow their first appearance in the ranked results.
- Opening ⌘K with an empty query does not load the full catalogue into the palette.
- ⌘K shows compact, scrollable result rows with names, descriptions, categories and availability.
- Catalogue cards remain grouped by category, with matching categories ordered by their first relevant result.
- Available results remain selectable by mouse, Tab, Enter, and the Up/Down keys.
