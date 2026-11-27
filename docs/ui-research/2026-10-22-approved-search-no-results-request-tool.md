# Approved search no-results request action

Version: 1.0.0 · Approved Quick Search no-results request action, 2026-10-22.

On 2026-10-22 the user approved the empty-state mock after requesting to see it. The approved design adds one **Request this tool** button when Quick Search has no matches. The button opens Help & feedback with the feature request type selected and the search query included in the title and draft prompt. The request remains a local draft and is never sent automatically.

The empty state contains one visible button, within the repository limit. The temporary standalone mock was reviewed as the approval artifact and removed after implementation.

## Implementation

`index.html` renders the approved call to action only for a successful zero-result search. Clicking it closes Quick Search and opens the existing support modal with a prefilled feature draft. Search failure keeps its separate Retry state. `tests/ui-search-routing.test.mjs` guards the zero-result action and draft behavior.
