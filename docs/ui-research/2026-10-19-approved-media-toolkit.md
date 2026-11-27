# Approved Media Toolkit consolidation

**Version:** 1.0.0

On 2026-10-19 the user reviewed the consolidated Media Toolkit design in a new Superset Browser tab and replied **“looks good to me”**. The reviewed mock was `design/mocks/media-clop-parity-review.html`; its temporary HTML and preview server are removed after approval. This decision preserves the scope independently of temporary preview files.

![Approved workbench design](2026-10-19-approved-media-toolkit.png)

Approved direction:

- A selected-file list, per-type preparation settings, and recent results share one workspace.
- Mixed image, video, PDF, and audio batches keep compatible settings per type. Files can be excluded, and failed items can be retried independently.
- Formats follow actual local encoder availability. Originals remain unchanged.
- Image/video logos have placement, size, margin, and opacity controls and are explicitly selected for one job.
- Result handoffs require an explicit action and a native save location. Upload dispatch does not imply upload completion.
- An Option cursor panel, Command compression modifier, numeric size controls, and quick crop remain part of the approved scope.

Implemented source acceptance: 38 desktop/compact WebKit checks pass for the existing workbench and new mixed-batch, retry, one-use logo, and explicit handoff flows. Loudness results show LUFS and the measured true/sample peak rather than byte-target wording. The source layout now separates selection, settings, and results and retains the existing navigation and automation controls.

The current UI is included in a freshly signed app/DMG. Mounted acceptance passes the 28-operation catalog and media/CLI/MCP checks. Full gate-6 passes 656 Node tests, 42 macOS checks and 2,211 Python tests. Six focused screenshot/flow checks also pass after the final narrow-column adjustment.

Remaining: the native cursor panel and global quick gestures, native installed-window acceptance, and formal review. Browser and mounted-sidecar checks do not establish those behaviors. Shipping authorization was received on 2026-10-19; changes are committed and main is merged. Preflight has no failures. Formal shipping review remains gated on the measured backend coverage shortfall (83% combined across media modules versus the harness's 100% bar), with an explicit owner exception requested.
