# OfficeKit Tauri patch

Base crate: Tauri 2.12.1, MIT or Apache-2.0.

`src/manager/window.rs` and `src/manager/webview.rs` keep native
drag-and-drop paths in Rust. Tauri's upstream managers serialize dropped
paths into webview events and grant them to the webview filesystem scope.
OfficeKit's native handlers use the OS paths to create a read-only
file-selection grant and emit only its opaque ID to the webview, so these
patches clear the path payload and skip filesystem-scope grants.

To refresh this vendored crate, copy the matching Tauri release and reapply
the `window.rs` and `webview.rs` changes. Keep the upstream LICENSE files
and review the diff before updating the lockfile.
