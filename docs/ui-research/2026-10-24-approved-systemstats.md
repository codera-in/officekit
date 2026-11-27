# Approved: System Stats dashboard and laptop battery

Version: 1.0.1 · 2026-10-24 · Owner approved the Stats-inspired in-app and tray mock: “Approve this mock”. Earlier: 1.0.0.

The request was “we need stats like on in app and add battert stats for laptops” and “ideally i want it like that so u re free to copy for both inapp and system tray as well”.

The approved mock is `design/mocks/systemstats-laptop-battery.html` (removed from the worktree after implementation as required by `AGENTS.md`). It places CPU, GPU, memory, disk, sensors, battery, network and process telemetry in the app, and presents GPU/battery drawers in the tray while preserving existing Quick Controls. The battery drawer keeps its Activity Monitor header shortcut and adds a Battery settings footer action. Example readings are illustrative; unsupported metrics stay unavailable. The mock was checked with the repository button-count checker and inspected in Superset Browser at desktop and compact layout.
