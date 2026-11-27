# Audio and screenshot toolbar fixes

**Status:** Approved by the product owner on 2026-10-17.

Meeting Notes presents one explicit **Generate meeting notes** action. Remove the
misleading “Insights & notes” control because it was wired to the same formatter
instead of switching a view, and duplicated the actual generate action. When the
transcript is empty, keep the user in the editor, focus the transcript field, and
show an inline instruction.

Screenshot Editor controls provide a descriptive hover title, including their
shortcut when one exists. Shape and callout menus use an opaque theme background
so toolbar text behind an open menu cannot show through.
