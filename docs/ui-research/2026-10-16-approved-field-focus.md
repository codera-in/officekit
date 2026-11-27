# Border-only field focus

2026-10-16. User reported an odd rounded inner outline in Home search. The before/after mock `design/mocks/home-search-focus-review.html` was opened in a new Superset Browser tab and visually inspected in light/dark themes at desktop and compact widths.

Refinement after the mock: user “do we need it ?”; proposed “change the search box’s existing border to blue when focused, with no extra outer ring.” Approval: “ok mock approved.. check it across the whole app”. This written refinement supersedes the mock's additional outer ring.

- Text inputs, selects and textareas use their existing border in the shared focus colour, with no additional ring, shadow or outline and no focus-induced geometry change.
- Composite fields follow daisyUI's input-on-parent pattern. Home/gallery search focus their enclosing field border. Quick Search focuses its existing bottom divider. Child input backgrounds are transparent and have no independent border/ring.
- Buttons, checkboxes, radios, ranges, canvas and other non-text interactive controls retain visible keyboard focus. A focus audit must not remove keyboard access cues globally.
- Verify the authenticated registry and shared screens in light/dark themes at desktop/compact widths. Distinguish this focus/layout audit from complete tool operation or installed-native acceptance.
