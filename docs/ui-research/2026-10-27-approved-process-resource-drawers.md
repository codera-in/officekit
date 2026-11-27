# Approved: Menu-bar process resource attribution

Version: 1.0.0 · 2026-10-27 · Owner approved the title-bar overlay direction: “approved”.

The request was: “improve the procssor , gpu, ram with actual application name instead greeky process names” and “show me the overlay screens from title bar”. The approved mock was `design/mocks/process-resource-drawers.html`; it was inspected in Superset Browser at desktop and narrow widths and passed `node scripts/check-mock-buttons.mjs` before implementation. The temporary mock and preview server are removed after implementation.

CPU and RAM rows group helper processes under local app display names and show combined totals with a short underlying-process detail. GPU retains the whole-device reading and shows best-effort per-process/app activity only when available; missing readings stay unavailable. App bundle paths stay local and are not returned.
