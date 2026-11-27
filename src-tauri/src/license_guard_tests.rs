//! Drives the real `license_guarded` wrapper through a Tauri mock-runtime IPC invoke, so the
//! native default-deny is executed rather than only text-scanned.

use super::{license_gate, license_guarded, license_guarded_with_clock};
use crate::license_gate::{Evaluation, GateSummary, LicenseGate};
use tauri::ipc::{CallbackFn, Invoke, InvokeBody};
use tauri::test::{mock_builder, mock_context, noop_assets, INVOKE_KEY};
use tauri::webview::InvokeRequest;
use tauri::{WebviewWindow, WebviewWindowBuilder};

const NOW: u64 = 1_800_000_000;

struct NoSidecar;
impl license_gate::EntitlementTransport for NoSidecar {
    fn put(&self, _body: &license_gate::EntitlementPush) -> Result<(), license_gate::PushError> {
        Ok(())
    }
    fn delete(&self) -> Result<(), license_gate::PushError> {
        Ok(())
    }
}

fn active_gate(expires_at: Option<u64>) -> LicenseGate {
    let gate = LicenseGate::new();
    gate.refresh(
        NOW,
        Evaluation::Active(GateSummary {
            activation_id: "CQkJCQkJCQkJCQkJCQkJCQ".into(),
            features: vec!["image.convert".into()],
            expires_at,
        }),
        &NoSidecar,
    )
    .unwrap();
    gate
}

/// The inner handler answers "ran" so a pass-through is distinguishable from a rejection.
fn ran(invoke: Invoke<tauri::test::MockRuntime>) -> bool {
    invoke.resolver.resolve("ran");
    true
}

fn webview_with<F>(
    handler: F,
) -> (
    tauri::App<tauri::test::MockRuntime>,
    WebviewWindow<tauri::test::MockRuntime>,
)
where
    F: Fn(Invoke<tauri::test::MockRuntime>) -> bool + Send + Sync + 'static,
{
    let app = mock_builder()
        .invoke_handler(handler)
        .build(mock_context(noop_assets()))
        .unwrap();
    let window = WebviewWindowBuilder::new(&app, "main", Default::default())
        .build()
        .unwrap();
    (app, window)
}

fn invoke(
    window: &WebviewWindow<tauri::test::MockRuntime>,
    command: &str,
) -> Result<String, String> {
    let response = tauri::test::get_ipc_response(
        window,
        InvokeRequest {
            cmd: command.into(),
            callback: CallbackFn(0),
            error: CallbackFn(1),
            url: if cfg!(any(windows, target_os = "android")) {
                "http://tauri.localhost"
            } else {
                "tauri://localhost"
            }
            .parse()
            .unwrap(),
            body: InvokeBody::default(),
            headers: Default::default(),
            invoke_key: INVOKE_KEY.to_string(),
        },
    );
    match response {
        Ok(body) => Ok(body.deserialize::<String>().unwrap()),
        Err(value) => Err(value.as_str().unwrap().to_string()),
    }
}

#[test]
fn the_wrapper_rejects_paid_commands_while_locked_and_lets_exempt_ones_run() {
    let (_app, window) = webview_with(license_guarded(LicenseGate::new(), ran));
    assert_eq!(
        invoke(&window, "agent_settings_read"),
        Err("license_required".into())
    );
    assert_eq!(
        invoke(&window, "a_future_unclassified_command"),
        Err("license_required".into())
    );
    assert_eq!(invoke(&window, "license_activate"), Ok("ran".into()));
    assert_eq!(invoke(&window, "result_copy_text"), Ok("ran".into()));
}

#[test]
fn the_wrapper_lets_paid_commands_run_only_while_the_licence_is_active() {
    let (_app, window) = webview_with(license_guarded(active_gate(None), ran));
    assert_eq!(invoke(&window, "agent_settings_read"), Ok("ran".into()));
}

#[test]
fn an_unreadable_clock_denies_paid_commands_even_for_an_active_licence() {
    for expires_at in [None, Some(NOW + 100_000)] {
        let (_app, window) = webview_with(license_guarded_with_clock(
            active_gate(expires_at),
            || None,
            ran,
        ));
        assert_eq!(
            invoke(&window, "agent_settings_read"),
            Err("license_required".into()),
            "{expires_at:?}"
        );
        assert_eq!(invoke(&window, "license_state"), Ok("ran".into()));
    }
}

#[test]
fn an_expired_licence_is_denied_at_the_wrapper_using_the_injected_clock() {
    let gate = active_gate(Some(NOW + 600));
    let (_app, window) = webview_with(license_guarded_with_clock(gate, || Some(NOW + 600), ran));
    assert_eq!(
        invoke(&window, "agent_settings_read"),
        Err("license_required".into())
    );
}

#[test]
fn the_production_clock_reads_the_system_time_and_never_substitutes_a_default() {
    let source = include_str!("lib.rs");
    let header = "fn unix_now() -> Option<u64> {";
    let start = source.find(header).expect("unix_now is defined") + header.len();
    let body = source[start..]
        .split("\n}")
        .next()
        .expect("unix_now has a body");
    assert_eq!(
        body.trim(),
        "license_gate::epoch_seconds(std::time::SystemTime::now())"
    );
    for fallback in [".or(", ".unwrap_or(", ".unwrap_or_default("] {
        assert!(
            !body.contains(fallback),
            "unix_now must fail closed: {fallback}"
        );
    }
}
