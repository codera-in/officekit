# Approved persistent tool actions

Approved 2026-10-16. The user reviewed `design/mocks/persistent-tool-actions-review.html` in a new Superset Browser tab and answered **“Approve the layout”**. They clarified **“this is for all tools accross the app”**. Temporary mock and preview files are removed after recording this decision.

Every active tool gets a permanent action area between its scrolling workspace and the application footer. Task actions, result actions and status share that area; the workspace reserves its actual height so controls never cover results. Controls wrap at narrow widths. Browsing screens have no empty action bar. Field-specific editing controls, table sorting/pagination and Finder actions stay beside their content.

Duplicate Finder uses a compact chooser, scope/mode controls and one report heading with Complete/Partial status. Details contains scan coverage, matching rules and path/Finder guidance. Results scroll with the workspace; page-size and pagination controls remain after the table. File selection spans all pages and preserves a keeper. Folder matches remain inspection-only. This supersedes the earlier bounded inner table and normal-flow result-action decision.

Implementation: `#officekit-workspace-column` reserves space for `#officekit-tool-actions`. The shared controller positions existing controls in that area, keeping form ownership, listeners and result snapshots intact. It removes fixed-position containing-block effects only along the active controls' ancestors. Nested result actions remain inside their existing task group. Hidden tools and closed Details sections cannot contribute controls.

Acceptance: registry-based tests cover every allowed tool route in both themes at desktop/compact widths; complete-flow tests cover generated results and exports. Source/browser evidence does not establish installed desktop behavior.
