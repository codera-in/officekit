//! Native licence gate: holds the verified lock state, pushes the entitlement summary to the
//! local sidecar (which enforces the same gate for its HTTP routes), and decides which webview
//! commands are usable while locked.
//!
//! Trust model: the receipt in the Keychain is the only source of truth. This module never logs
//! or returns the licence key, the email, the signed token or either loopback token.

use crate::license_client::{validate_slot_counts, DeviceKey, ReceiptStore};
use crate::licensing::{verify_entitlement, LicenseVerificationError};
use serde::Serialize;
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

/// How long the sidecar honours one push. Two pushes per lifetime (see `PUSH_INTERVAL`) means a
/// single failed or skipped tick is retried before the sidecar locks itself, while a sidecar that
/// stops hearing from Rust (crashed shell, revoked receipt we could not DELETE) is locked within
/// half an hour. The sidecar accepts 60..=3600 seconds (API-CONTRACT EN).
pub const ENTITLEMENT_LIFETIME_SECONDS: u64 = 1800;
pub const MIN_VALID_FOR_SECONDS: u64 = 60;
pub const MAX_VALID_FOR_SECONDS: u64 = 3600;
/// Half of `ENTITLEMENT_LIFETIME_SECONDS`.
pub const PUSH_INTERVAL: Duration = Duration::from_secs(15 * 60);
/// Waits before each retry of a failed push, in order. After the last one the normal
/// `PUSH_INTERVAL` cadence applies and the retry sequence re-arms.
pub const PUSH_RETRY_BACKOFF: [Duration; 3] = [
    Duration::from_secs(15),
    Duration::from_secs(30),
    Duration::from_secs(60),
];
/// The Tauri event emitted whenever the native gate changes state. Payload: the lowercase
/// `LockState` word only (`"checking"`, `"locked"`, `"active"`, `"expired"`, `"revoked"`).
pub const STATE_CHANGED_EVENT: &str = "license-state-changed";

const PUSH_CONNECT_TIMEOUT: Duration = Duration::from_millis(500);
const PUSH_IO_TIMEOUT: Duration = Duration::from_secs(5);
const MAX_PUSH_RESPONSE_BYTES: usize = 16 * 1024;
const MIN_GRANT_TOKEN_BYTES: usize = 32;
const MAX_TOKEN_BYTES: usize = 128;
const LICENSE_REQUIRED: &str = "license_required";

// ---------------------------------------------------------------------------
// Lock state
// ---------------------------------------------------------------------------

/// What the webview may be told about the licence. No email, key, ids or dates.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
#[allow(dead_code)] // `Revoked` is only produced by `clear` (S4 revalidation / deactivate)
pub enum LockState {
    /// Nothing verified yet (startup, or the Keychain could not be read yet).
    Checking,
    /// No receipt, or the receipt failed verification (signature, device key, v2 claims).
    Locked,
    /// A genuine, device-bound, unexpired receipt.
    Active,
    /// A genuine, device-bound receipt that is past its expiry.
    Expired,
    /// The licence was revoked or deactivated server-side (set by `clear`; the offline receipt
    /// alone cannot show this until online revalidation lands in S4).
    Revoked,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GateSummary {
    pub activation_id: String,
    pub features: Vec<String>,
    pub expires_at: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Evaluation {
    Active(GateSummary),
    Locked,
    Expired,
    /// The Keychain or device key could not be read this time; keep the previous state.
    Unavailable,
}

/// Verify the Keychain receipt exactly as activation does (signature against the pinned keyring,
/// device-key binding, v2 claims, expiry) and classify the outcome.
pub fn evaluate_receipt(
    now_epoch: u64,
    pinned_public_keys: &BTreeMap<String, String>,
    device_key: &impl DeviceKey,
    receipt_store: &impl ReceiptStore,
) -> Evaluation {
    let receipt = match receipt_store.load() {
        Ok(Some(receipt)) => receipt,
        Ok(None) => return Evaluation::Locked,
        Err(_) => return Evaluation::Unavailable,
    };
    if validate_slot_counts(receipt.device_slots_used, receipt.device_slots_allowed).is_err() {
        return Evaluation::Locked;
    }
    let public_key_der = match device_key.public_key_der() {
        Ok(der) => der,
        Err(_) => return Evaluation::Unavailable,
    };
    match verify_entitlement(
        &receipt.signed_entitlement,
        pinned_public_keys,
        &public_key_der,
        now_epoch,
    ) {
        Ok(verified) => Evaluation::Active(GateSummary {
            activation_id: verified.activation_id,
            features: verified.features,
            expires_at: verified.expires_at,
        }),
        Err(LicenseVerificationError::Expired) => Evaluation::Expired,
        Err(LicenseVerificationError::Invalid) => Evaluation::Locked,
    }
}

// ---------------------------------------------------------------------------
// Push to the sidecar
// ---------------------------------------------------------------------------

/// Body of `PUT /api/license/entitlement` (API-CONTRACT EN).
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct EntitlementPush {
    pub activation_id: String,
    pub edition: &'static str,
    pub features: Vec<String>,
    pub valid_for_seconds: u64,
}

/// `None` when the licence has less than the sidecar's minimum lifetime left: it is treated as
/// lapsed rather than pushing a value the sidecar would reject.
pub fn push_body(summary: &GateSummary, now_epoch: u64) -> Option<EntitlementPush> {
    let remaining = summary
        .expires_at
        .map_or(u64::MAX, |expires_at| expires_at.saturating_sub(now_epoch));
    let valid_for_seconds = remaining
        .min(ENTITLEMENT_LIFETIME_SECONDS)
        .min(MAX_VALID_FOR_SECONDS);
    if valid_for_seconds < MIN_VALID_FOR_SECONDS {
        return None;
    }
    let mut features = summary.features.clone();
    features.sort();
    features.dedup();
    Some(EntitlementPush {
        activation_id: summary.activation_id.clone(),
        edition: "paid",
        features,
        valid_for_seconds,
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PushError {
    /// Bad address or token shape; nothing was sent.
    Invalid,
    Unavailable,
    InvalidResponse,
    Rejected(u16),
}

impl PushError {
    /// A fixed label for logs: never carries a token, body or response text.
    pub fn label(self) -> String {
        match self {
            Self::Invalid => "invalid push configuration".into(),
            Self::Unavailable => "sidecar unavailable".into(),
            Self::InvalidResponse => "sidecar returned an invalid response".into(),
            Self::Rejected(status) => format!("sidecar rejected the request (HTTP {status})"),
        }
    }
}

pub trait EntitlementTransport {
    fn put(&self, body: &EntitlementPush) -> Result<(), PushError>;
    fn delete(&self) -> Result<(), PushError>;
}

/// Loopback HTTP client for the sidecar's entitlement route. Sends both the API bearer token
/// and the native grant header; the grant never leaves Rust.
pub struct LoopbackEntitlementClient {
    address: SocketAddr,
    api_token: String,
    native_grant: String,
}

impl std::fmt::Debug for LoopbackEntitlementClient {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("LoopbackEntitlementClient")
            .field("address", &self.address)
            .finish_non_exhaustive()
    }
}

fn is_header_safe_token(token: &str, min_bytes: usize) -> bool {
    (min_bytes..=MAX_TOKEN_BYTES).contains(&token.len())
        && token
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
}

impl LoopbackEntitlementClient {
    pub fn new(
        address: SocketAddr,
        api_token: &str,
        native_grant: &str,
    ) -> Result<Self, PushError> {
        if !address.ip().is_loopback()
            || !is_header_safe_token(api_token, 1)
            || !is_header_safe_token(native_grant, MIN_GRANT_TOKEN_BYTES)
        {
            return Err(PushError::Invalid);
        }
        Ok(Self {
            address,
            api_token: api_token.to_string(),
            native_grant: native_grant.to_string(),
        })
    }

    fn exchange(&self, method: &str, body: &[u8]) -> Result<u16, PushError> {
        let mut stream = TcpStream::connect_timeout(&self.address, PUSH_CONNECT_TIMEOUT)
            .map_err(|_| PushError::Unavailable)?;
        stream
            .set_read_timeout(Some(PUSH_IO_TIMEOUT))
            .and_then(|_| stream.set_write_timeout(Some(PUSH_IO_TIMEOUT)))
            .map_err(|_| PushError::Unavailable)?;
        write!(
            stream,
            "{method} /api/license/entitlement HTTP/1.0\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {}\r\nX-OfficeKit-Native-Grant: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            self.api_token,
            self.native_grant,
            body.len()
        )
        .and_then(|_| stream.write_all(body))
        .map_err(|_| PushError::Unavailable)?;
        // P-155: keep the socket open for writing and read the whole response. Half-closing
        // after the body made the packaged server treat the request as a disconnect.
        let mut response = Vec::with_capacity(512);
        stream
            .take((MAX_PUSH_RESPONSE_BYTES + 1) as u64)
            .read_to_end(&mut response)
            .map_err(|_| PushError::Unavailable)?;
        if response.len() > MAX_PUSH_RESPONSE_BYTES {
            return Err(PushError::InvalidResponse);
        }
        parse_status(&response)
    }

    fn expect_no_content(&self, method: &str, body: &[u8]) -> Result<(), PushError> {
        match self.exchange(method, body)? {
            204 => Ok(()),
            status => Err(PushError::Rejected(status)),
        }
    }
}

fn parse_status(response: &[u8]) -> Result<u16, PushError> {
    let boundary = response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or(PushError::InvalidResponse)?;
    let headers =
        std::str::from_utf8(&response[..boundary]).map_err(|_| PushError::InvalidResponse)?;
    let mut lines = headers.lines();
    let status_line = lines.next().ok_or(PushError::InvalidResponse)?;
    let mut parts = status_line.split_whitespace();
    if !parts
        .next()
        .is_some_and(|version| version == "HTTP/1.0" || version == "HTTP/1.1")
    {
        return Err(PushError::InvalidResponse);
    }
    let status = parts
        .next()
        .and_then(|code| code.parse::<u16>().ok())
        .filter(|code| (100..=599).contains(code))
        .ok_or(PushError::InvalidResponse)?;
    let body_length = response.len() - boundary - 4;
    let declared = lines.find_map(|line| {
        let (name, value) = line.split_once(':')?;
        name.eq_ignore_ascii_case("content-length")
            .then(|| value.trim().parse::<usize>().ok())
            .flatten()
    });
    if declared.is_some_and(|length| length != body_length) {
        return Err(PushError::InvalidResponse);
    }
    Ok(status)
}

impl EntitlementTransport for LoopbackEntitlementClient {
    fn put(&self, body: &EntitlementPush) -> Result<(), PushError> {
        let payload = serde_json::to_vec(body).map_err(|_| PushError::Invalid)?;
        self.expect_no_content("PUT", &payload)
    }

    fn delete(&self) -> Result<(), PushError> {
        self.expect_no_content("DELETE", &[])
    }
}

// ---------------------------------------------------------------------------
// Gate
// ---------------------------------------------------------------------------

struct GateInner {
    state: LockState,
    summary: Option<GateSummary>,
}

type StateObserver = Arc<dyn Fn(LockState) + Send + Sync>;

struct GateShared {
    inner: Mutex<GateInner>,
    /// Serialises whole refresh cycles, including the receipt evaluation (`refresh_with`), so a
    /// slow scheduled tick cannot overwrite the result of an activation that finished after it
    /// started: whichever cycle takes the lock second also reads the Keychain second.
    cycle: Mutex<()>,
    /// Told the new state whenever it changes (the app emits `STATE_CHANGED_EVENT`).
    observer: Mutex<Option<StateObserver>>,
}

/// What a refresh cycle asks of the sidecar.
enum PushAction {
    Put(EntitlementPush),
    Delete,
    Nothing,
}

/// `Some(seconds)` when the clock reads at or after the epoch; `None` otherwise.
pub fn epoch_seconds(at: std::time::SystemTime) -> Option<u64> {
    at.duration_since(std::time::UNIX_EPOCH)
        .ok()
        .map(|elapsed| elapsed.as_secs())
}

#[derive(Clone)]
pub struct LicenseGate {
    shared: Arc<GateShared>,
}

impl Default for LicenseGate {
    fn default() -> Self {
        Self::new()
    }
}

fn locked<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

impl LicenseGate {
    pub fn new() -> Self {
        Self {
            shared: Arc::new(GateShared {
                inner: Mutex::new(GateInner {
                    state: LockState::Checking,
                    summary: None,
                }),
                cycle: Mutex::new(()),
                observer: Mutex::new(None),
            }),
        }
    }

    /// Register the single state-change observer (replaces any previous one).
    pub fn on_change(&self, observer: impl Fn(LockState) + Send + Sync + 'static) {
        *locked(&self.shared.observer) = Some(Arc::new(observer));
    }

    /// The state at `now_epoch`; an Active licence whose expiry has passed since the last
    /// verification reads as Expired without waiting for the next tick. `None` means the system
    /// clock could not be read: an Active licence then reads Expired (fail closed), since its
    /// expiry cannot be checked.
    pub fn state(&self, now_epoch: impl Into<Option<u64>>) -> LockState {
        let now_epoch = now_epoch.into();
        let inner = locked(&self.shared.inner);
        match (inner.state, &inner.summary) {
            (LockState::Active, _) if now_epoch.is_none() => LockState::Expired,
            (LockState::Active, Some(summary))
                if summary
                    .expires_at
                    .is_some_and(|expires_at| now_epoch.is_some_and(|now| expires_at <= now)) =>
            {
                LockState::Expired
            }
            (LockState::Active, None) => LockState::Locked,
            (state, _) => state,
        }
    }

    fn set(&self, state: LockState, summary: Option<GateSummary>) {
        let previous = {
            let mut inner = locked(&self.shared.inner);
            let previous = inner.state;
            inner.state = state;
            inner.summary = summary;
            previous
        };
        if previous != state {
            let observer = locked(&self.shared.observer).clone();
            if let Some(observer) = observer {
                observer(state);
            }
        }
    }

    /// Decide and record the new state for one evaluation. Callers hold the cycle lock.
    fn apply(&self, now_epoch: u64, evaluation: Evaluation) -> PushAction {
        match evaluation {
            Evaluation::Active(summary) => match push_body(&summary, now_epoch) {
                Some(body) => {
                    self.set(LockState::Active, Some(summary));
                    PushAction::Put(body)
                }
                None => {
                    self.set(LockState::Expired, None);
                    PushAction::Delete
                }
            },
            Evaluation::Expired => {
                self.set(LockState::Expired, None);
                PushAction::Delete
            }
            Evaluation::Locked => {
                self.set(LockState::Locked, None);
                PushAction::Delete
            }
            Evaluation::Unavailable => {
                let (state, summary) = {
                    let inner = locked(&self.shared.inner);
                    (inner.state, inner.summary.clone())
                };
                match (state, summary) {
                    // Never leave the UI waiting forever on an unreadable Keychain.
                    (LockState::Checking, _) => {
                        self.set(LockState::Locked, None);
                        PushAction::Delete
                    }
                    // Keep the sidecar alive from the last verified summary, so an unreadable
                    // Keychain does not let it lapse while the native side still says Active.
                    (LockState::Active, Some(summary)) => match push_body(&summary, now_epoch) {
                        Some(body) => PushAction::Put(body),
                        None => {
                            self.set(LockState::Expired, None);
                            PushAction::Delete
                        }
                    },
                    _ => PushAction::Nothing,
                }
            }
        }
    }

    fn send(action: PushAction, transport: &impl EntitlementTransport) -> Result<(), PushError> {
        match action {
            PushAction::Put(body) => transport.put(&body),
            PushAction::Delete => transport.delete(),
            PushAction::Nothing => Ok(()),
        }
    }

    /// Apply a fresh evaluation, then tell the sidecar. The native state is updated first, so a
    /// failed push never leaves the native gate more permissive than the receipt; the caller
    /// retries (see `retry_failed_push` and `run_push_loop`).
    pub fn refresh(
        &self,
        now_epoch: u64,
        evaluation: Evaluation,
        transport: &impl EntitlementTransport,
    ) -> Result<(), PushError> {
        self.refresh_with(now_epoch, || evaluation, transport)
    }

    /// Like `refresh`, but the evaluation runs inside the cycle lock, so two cycles cannot read
    /// the Keychain in one order and apply in the other.
    pub fn refresh_with(
        &self,
        now_epoch: u64,
        evaluate: impl FnOnce() -> Evaluation,
        transport: &impl EntitlementTransport,
    ) -> Result<(), PushError> {
        let _cycle = locked(&self.shared.cycle);
        let action = self.apply(now_epoch, evaluate());
        Self::send(action, transport)
    }

    /// Record an evaluation without contacting the sidecar (startup: the sidecar is not up yet).
    pub fn evaluate_locally(&self, now_epoch: u64, evaluate: impl FnOnce() -> Evaluation) {
        let _cycle = locked(&self.shared.cycle);
        let _ = self.apply(now_epoch, evaluate());
    }

    /// Deactivation or revocation: lock now and clear the sidecar. Only `Locked` and `Revoked`
    /// are meaningful; anything else locks.
    pub fn clear(
        &self,
        state: LockState,
        transport: &impl EntitlementTransport,
    ) -> Result<(), PushError> {
        let _cycle = locked(&self.shared.cycle);
        let state = if state == LockState::Revoked {
            LockState::Revoked
        } else {
            LockState::Locked
        };
        self.set(state, None);
        transport.delete()
    }
}

/// `Err("license_required")` unless the licence is Active right now. `now_epoch` is `None` when
/// the system clock is unreadable, which denies (fail closed).
pub fn require_paid(
    gate: &LicenseGate,
    now_epoch: impl Into<Option<u64>>,
) -> Result<(), &'static str> {
    if gate.state(now_epoch) == LockState::Active {
        Ok(())
    } else {
        Err(LICENSE_REQUIRED)
    }
}

/// One verify-and-push cycle from the Keychain. Failures are logged by label only and retried by
/// the caller; this never panics. Returns whether the sidecar was brought in line. An unreadable
/// clock (`None`) locks: the receipt's expiry cannot be checked.
pub fn tick_from_store(
    gate: &LicenseGate,
    transport: &impl EntitlementTransport,
    now_epoch: impl Into<Option<u64>>,
    pinned_public_keys: &BTreeMap<String, String>,
    device_key: &impl DeviceKey,
    receipt_store: &impl ReceiptStore,
) -> bool {
    let result = match now_epoch.into() {
        Some(now_epoch) => gate.refresh_with(
            now_epoch,
            || evaluate_receipt(now_epoch, pinned_public_keys, device_key, receipt_store),
            transport,
        ),
        None => gate.refresh(0, Evaluation::Expired, transport),
    };
    match result {
        Ok(()) => true,
        Err(error) => {
            eprintln!("OfficeKit licence push failed: {}", error.label());
            false
        }
    }
}

/// Record the Keychain receipt in the native gate without contacting the sidecar. Run before the
/// webview starts so a licensed user is never `Checking` when its startup calls arrive.
pub fn check_from_store(
    gate: &LicenseGate,
    now_epoch: impl Into<Option<u64>>,
    pinned_public_keys: &BTreeMap<String, String>,
    device_key: &impl DeviceKey,
    receipt_store: &impl ReceiptStore,
) {
    match now_epoch.into() {
        Some(now_epoch) => gate.evaluate_locally(now_epoch, || {
            evaluate_receipt(now_epoch, pinned_public_keys, device_key, receipt_store)
        }),
        None => gate.evaluate_locally(0, || Evaluation::Expired),
    }
}

/// How long to wait before the next tick after `consecutive_failures` failed ones.
fn next_delay(consecutive_failures: usize) -> Duration {
    consecutive_failures
        .checked_sub(1)
        .and_then(|index| PUSH_RETRY_BACKOFF.get(index))
        .copied()
        .unwrap_or(PUSH_INTERVAL)
}

/// Run `tick` now and then after every `wait` that returns true. The wait is `PUSH_INTERVAL`
/// after a success and walks `PUSH_RETRY_BACKOFF` after failures (a panic counts as one), then
/// returns to `PUSH_INTERVAL` and re-arms. A panicking tick is contained and the loop carries on.
pub fn run_push_loop(mut wait: impl FnMut(Duration) -> bool, mut tick: impl FnMut() -> bool) {
    let mut failures = 0_usize;
    loop {
        let succeeded = catch_unwind(AssertUnwindSafe(&mut tick)).unwrap_or_else(|_| {
            eprintln!("OfficeKit licence push tick failed unexpectedly");
            false
        });
        failures = if succeeded { 0 } else { failures + 1 };
        let delay = next_delay(failures);
        if failures > PUSH_RETRY_BACKOFF.len() {
            failures = 0;
        }
        if !wait(delay) {
            break;
        }
    }
}

/// After a failed push (activation), retry on `PUSH_RETRY_BACKOFF` until one succeeds. Bounded:
/// gives up after the last backoff; the regular loop keeps its 15-minute cadence regardless.
pub fn retry_failed_push(mut wait: impl FnMut(Duration), mut tick: impl FnMut() -> bool) -> bool {
    for delay in PUSH_RETRY_BACKOFF {
        wait(delay);
        if tick() {
            return true;
        }
    }
    false
}

// ---------------------------------------------------------------------------
// Command classification
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandClass {
    /// Usable while locked.
    Exempt,
    /// Needs an Active licence.
    Paid,
}

use CommandClass::{Exempt, Paid};

/// Every `#[tauri::command]` in `src-tauri/src`, classified. A test fails if one is missing or
/// stale; `command_guard` denies any command that is not listed.
///
/// Free tools (owner decision 2026-10-21): the whole Calculators, Converters and Developer
/// categories, except Clipboard & Snippets Studio, which is a Pro studio and is locked (owner
/// decision 2026-10-22). Free tools call only the local API plus `result_copy_text` and
/// `result_save`, so those two stay Exempt even though paid tools use them too; the studio's
/// other native calls (`dictation_paste_text`, `media_clipboard_*`) are Paid. Ergonomics
/// reminders ship in every build as a paid feature (owner decision 2026-10-22), so the five
/// `ergonomics_*` commands are Paid. Updates has no native command (it is the sidecar's
/// `/api/release`); Settings is the agents panel, so `agent_*` are Paid.
pub const COMMAND_CLASSES: &[(&str, CommandClass)] = &[
    // Backend wiring the webview needs before it can show anything.
    ("check_backend_status", Exempt),
    ("officekit_api_token", Exempt),
    ("officekit_api_origin", Exempt),
    // Activation and lock state.
    ("license_status", Exempt),
    ("license_activate", Exempt),
    // Needs the purchase email and licence key typed again, so it is safe to leave open: a locked
    // or expired Mac must still be able to free its seat.
    ("license_deactivate", Exempt),
    // Hosted support reports: a locked or expired Mac must still be able to ask for help.
    ("support_ticket_submit", Exempt),
    ("support_ticket_updates", Exempt),
    // The "closed unexpectedly" notice offers that same report, so it is open to a locked Mac too.
    ("crash_notice_pending", Exempt),
    ("crash_notice_dismiss", Exempt),
    ("license_state", Exempt),
    // Shell.
    ("officekit_quit", Exempt),
    ("launcher_recent_tools", Exempt),
    // Network diagnostics are a paid tool (the sidecar's `/api/network/*` routes are paid), so the
    // native helpers that open the system settings pane and the speed-test page are paid too.
    ("open_network_settings", Paid),
    ("open_cloudflare_speed_test", Paid),
    // Added on main after the licence work was written; all belong to paid features.
    ("coach_workspace_clear", Paid),
    ("coach_workspace_open_apple_intelligence", Paid),
    ("crash_restart_status", Paid),
    ("crash_restart_set", Paid),
    ("global_panel_set_dictations", Paid),
    ("invoice_library_reconnect", Paid),
    // Shared by free (Developer, Converters) and paid tools: kept Exempt.
    ("result_copy_text", Exempt),
    ("result_save", Exempt),
    // Settings (agents panel).
    ("agent_helper_status", Paid),
    ("agent_settings_read", Paid),
    ("agent_settings_write", Paid),
    ("agent_choose_folders", Paid),
    ("agent_reveal_output", Paid),
    ("agent_skill_status", Paid),
    ("agent_skill_install", Paid),
    // Ergonomics reminders: a paid feature in every build (owner decision 2026-10-22).
    ("ergonomics_get_state", Paid),
    ("ergonomics_update_settings", Paid),
    ("ergonomics_reminder_action", Paid),
    ("ergonomics_preview", Paid),
    ("ergonomics_motion_action", Paid),
    ("ergonomics_calendar_action", Paid),
    ("app_settings_status", Paid),
    ("app_settings_save", Paid),
    ("calendar_permission_status", Paid),
    ("calendar_permission_request", Paid),
    ("coach_workspace_snapshot", Paid),
    ("coach_workspace_dismiss", Paid),
    ("coach_workspace_corrected_text", Paid),
    ("coach_workspace_done", Paid),
    ("file_intake_pending", Paid),
    ("file_intake_ack", Paid),
    ("finder_open_in_status", Paid),
    ("finder_open_in_set", Paid),
    ("menu_stats_status", Paid),
    ("menu_stats_adopt_legacy", Paid),
    ("system_sensor_metrics", Paid),
    ("system_hardware_metrics", Paid),
    ("trash_restore_confirm", Paid),
    ("trash_restore_apply", Paid),
    ("trash_record_forget", Paid),
    ("trash_restore_reveal", Paid),
    ("ergonomics_quick_controls_status", Paid),
    ("ergonomics_quick_controls_set_enabled", Paid),
    ("quick_controls_status", Paid),
    ("quick_controls_set_tool", Paid),
    ("quick_controls_set_hud_position", Paid),
    ("quick_controls_disable_all", Paid),
    ("speech_coach_status", Paid),
    ("speech_coach_configure", Paid),
    ("speech_coach_set_enabled", Paid),
    ("speech_coach_set_paused", Paid),
    ("speech_coach_notes", Paid),
    ("speech_coach_rules", Paid),
    ("speech_coach_record_session", Paid),
    ("speech_coach_clear_notes", Paid),
    ("speech_coach_dismiss_pattern", Paid),
    ("speech_coach_set_pattern_dismissed", Paid),
    ("speech_coach_set_pattern_useful", Paid),
    // Files, media, PDF, storage.
    ("file_selection_open", Paid),
    ("file_output_choose", Paid),
    ("file_job_reveal", Paid),
    ("media_toolkit_drop_set_enabled", Paid),
    ("media_clipboard_hotkey_set_enabled", Paid),
    ("media_clipboard_revision", Paid),
    ("media_finder_action_status", Paid),
    ("media_finder_action_install", Paid),
    ("media_finder_action_remove", Paid),
    ("media_folder_watch_open", Paid),
    ("media_handoff_capabilities", Paid),
    ("media_handoff_open", Paid),
    ("pdf_signing_provider_open", Paid),
    ("storage_scan_start", Paid),
    ("storage_cleanup_apply", Paid),
    ("storage_permissions_open", Paid),
    // Desktop: window snap, tray, drawers, global shortcuts, launcher apps.
    ("window_snap", Paid),
    ("window_snap_set_edge_enabled", Paid),
    ("quick_access_recording", Paid),
    ("tray_stats_update", Paid),
    ("menu_drawers_update", Paid),
    ("menu_drawers_remove", Paid),
    ("list_installed_apps", Paid),
    ("global_desktop_status", Paid),
    ("global_desktop_configure", Paid),
    ("global_desktop_refresh", Paid),
    ("global_desktop_default_shortcuts", Paid),
    ("screenshot_shortcut_configure", Paid),
    ("screenshot_capture", Paid),
    // Dictation and meetings.
    ("dictation_model_status", Paid),
    ("dictation_model_inventory", Paid),
    ("dictation_model_delete", Paid),
    ("dictation_model_select", Paid),
    ("dictation_set_translation_mode", Paid),
    ("dictation_set_spoken_language", Paid),
    ("dictation_set_vocabulary", Paid),
    ("dictation_set_context_options", Paid),
    ("dictation_set_streaming_commit", Paid),
    ("dictation_set_raw_audio", Paid),
    ("raw_audio_status", Paid),
    ("raw_audio_clear", Paid),
    ("raw_audio_show", Paid),
    ("dictation_set_llm_polish", Paid),
    ("dictation_polish_available", Paid),
    ("dictation_prepare_model", Paid),
    ("dictation_microphone_permission", Paid),
    ("dictation_request_microphone_permission", Paid),
    ("dictation_open_permission_settings", Paid),
    ("dictation_accessibility_permission", Paid),
    ("dictation_request_accessibility_permission", Paid),
    ("dictation_capture_start", Paid),
    ("dictation_capture_stop", Paid),
    ("dictation_transcribe_audio_file", Paid),
    ("quick_access_transcribe", Paid),
    ("dictation_hotkey_status", Paid),
    ("dictation_hotkey_configure", Paid),
    ("dictation_hotkey_configure_custom", Paid),
    ("dictation_hotkey_enable", Paid),
    ("dictation_hotkey_disable", Paid),
    ("dictation_paste_text", Paid),
    ("dictation_cleanup_and_paste", Paid),
    ("dictation_meeting_record_start", Paid),
    ("dictation_meeting_record_stop", Paid),
    ("dictation_meeting_status", Paid),
    ("dictation_screen_recording_permission", Paid),
    ("dictation_request_screen_recording_permission", Paid),
];

pub fn class_of(command: &str) -> Option<CommandClass> {
    COMMAND_CLASSES
        .iter()
        .find(|(name, _)| *name == command)
        .map(|(_, class)| *class)
}

/// Decision for one webview invoke: exempt commands pass, paid commands need an Active licence,
/// and an unclassified command is denied (fail closed).
pub fn command_guard(
    gate: &LicenseGate,
    command: &str,
    now_epoch: impl Into<Option<u64>>,
) -> Result<(), &'static str> {
    match class_of(command) {
        Some(Exempt) => Ok(()),
        Some(Paid) | None => require_paid(gate, now_epoch),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::license_client::{LicenseClientError, StoredLicenseReceipt};
    use std::cell::RefCell;
    use std::collections::BTreeSet;
    use std::net::TcpListener;

    const NOW: u64 = 1_800_000_000;
    const API_TOKEN: &str = "0b5e7d7e-1111-4222-8333-444455556666";
    const GRANT: &str = "9f1c2d3e-aaaa-4bbb-8ccc-ddddeeeeffff";
    const ACTIVATION_ID: &str = "CQkJCQkJCQkJCQkJCQkJCQ";

    fn summary(expires_at: Option<u64>) -> GateSummary {
        GateSummary {
            activation_id: ACTIVATION_ID.into(),
            features: vec!["image.convert".into(), "pdf.merge".into()],
            expires_at,
        }
    }

    // ----- push body -------------------------------------------------------

    #[test]
    fn push_lifetime_is_thirty_minutes_capped_by_expiry_and_never_below_the_sidecar_minimum() {
        let perpetual = push_body(&summary(None), NOW).unwrap();
        assert_eq!(perpetual.valid_for_seconds, 1800);
        assert_eq!(perpetual.edition, "paid");
        assert_eq!(
            push_body(&summary(Some(NOW + 10_000)), NOW)
                .unwrap()
                .valid_for_seconds,
            1800
        );
        assert_eq!(
            push_body(&summary(Some(NOW + 300)), NOW)
                .unwrap()
                .valid_for_seconds,
            300
        );
        assert_eq!(
            push_body(&summary(Some(NOW + 60)), NOW)
                .unwrap()
                .valid_for_seconds,
            60
        );
        assert!(push_body(&summary(Some(NOW + 59)), NOW).is_none());
        assert!(push_body(&summary(Some(NOW)), NOW).is_none());
        assert!(push_body(&summary(Some(NOW - 5)), NOW).is_none());
        assert!(ENTITLEMENT_LIFETIME_SECONDS * 1000 == PUSH_INTERVAL.as_millis() as u64 * 2);
    }

    #[test]
    fn push_features_are_sorted_unique_slugs() {
        let mut shuffled = summary(None);
        shuffled.features = vec![
            "pdf.merge".into(),
            "image.convert".into(),
            "pdf.merge".into(),
        ];
        let body = push_body(&shuffled, NOW).unwrap();
        assert_eq!(body.features, ["image.convert", "pdf.merge"]);
    }

    #[test]
    fn push_json_matches_the_contract_fields_exactly() {
        let body = push_body(&summary(None), NOW).unwrap();
        let json: serde_json::Value = serde_json::to_value(&body).unwrap();
        let mut keys: Vec<_> = json.as_object().unwrap().keys().cloned().collect();
        keys.sort();
        assert_eq!(
            keys,
            ["activation_id", "edition", "features", "valid_for_seconds"]
        );
        assert_eq!(json["edition"], "paid");
    }

    // ----- loopback client -------------------------------------------------

    struct Captured {
        head: String,
        body: Vec<u8>,
        client_stayed_open: bool,
    }

    /// One-shot loopback server on an ephemeral port (P-096). Reads headers and the declared
    /// body, checks the client has not half-closed, then sends `response` and closes.
    fn serve_once(response: Vec<u8>) -> (SocketAddr, std::thread::JoinHandle<Captured>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let handle = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let mut received = Vec::new();
            let mut chunk = [0_u8; 1024];
            let (head, body) = loop {
                let read = stream.read(&mut chunk).unwrap();
                assert!(read > 0, "client closed before finishing the request");
                received.extend_from_slice(&chunk[..read]);
                if let Some(boundary) = received.windows(4).position(|w| w == b"\r\n\r\n") {
                    let head = String::from_utf8(received[..boundary].to_vec()).unwrap();
                    let length = head
                        .lines()
                        .find_map(|line| line.strip_prefix("Content-Length: "))
                        .map(|value| value.parse::<usize>().unwrap())
                        .unwrap();
                    if received.len() >= boundary + 4 + length {
                        break (head, received[boundary + 4..boundary + 4 + length].to_vec());
                    }
                }
            };
            // P-155: a client that half-closes after the body reads as EOF (Ok(0)) here.
            stream
                .set_read_timeout(Some(Duration::from_millis(150)))
                .unwrap();
            let client_stayed_open = matches!(
                stream.read(&mut chunk),
                Err(ref error) if matches!(
                    error.kind(),
                    std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut
                )
            );
            stream.write_all(&response).unwrap();
            Captured {
                head,
                body,
                client_stayed_open,
            }
        });
        (address, handle)
    }

    fn client(address: SocketAddr) -> LoopbackEntitlementClient {
        LoopbackEntitlementClient::new(address, API_TOKEN, GRANT).unwrap()
    }

    const NO_CONTENT: &[u8] = b"HTTP/1.1 204 No Content\r\nserver: uvicorn\r\n\r\n";

    #[test]
    fn put_sends_both_tokens_and_the_contract_body_and_keeps_the_socket_open() {
        let (address, server) = serve_once(NO_CONTENT.to_vec());
        let body = push_body(&summary(None), NOW).unwrap();
        client(address).put(&body).unwrap();
        let captured = server.join().unwrap();
        assert!(captured
            .head
            .starts_with("PUT /api/license/entitlement HTTP/1.0\r\n"));
        assert!(captured
            .head
            .contains(&format!("Authorization: Bearer {API_TOKEN}")));
        assert!(captured
            .head
            .contains(&format!("X-OfficeKit-Native-Grant: {GRANT}")));
        assert!(captured.head.contains("Content-Type: application/json"));
        assert!(captured.client_stayed_open, "client half-closed (P-155)");
        let sent: serde_json::Value = serde_json::from_slice(&captured.body).unwrap();
        assert_eq!(sent["activation_id"], ACTIVATION_ID);
        assert_eq!(sent["edition"], "paid");
        assert_eq!(sent["valid_for_seconds"], 1800);
        assert_eq!(
            sent["features"],
            serde_json::json!(["image.convert", "pdf.merge"])
        );
    }

    #[test]
    fn delete_sends_the_grant_with_no_body() {
        let (address, server) = serve_once(NO_CONTENT.to_vec());
        client(address).delete().unwrap();
        let captured = server.join().unwrap();
        assert!(captured
            .head
            .starts_with("DELETE /api/license/entitlement HTTP/1.0\r\n"));
        assert!(captured
            .head
            .contains(&format!("X-OfficeKit-Native-Grant: {GRANT}")));
        assert!(captured.body.is_empty());
        assert!(captured.client_stayed_open);
    }

    #[test]
    fn only_204_is_success_and_other_statuses_are_typed_rejections() {
        for (raw, expected) in [
            (
                "HTTP/1.1 401 Unauthorized\r\ncontent-length: 2\r\n\r\n{}",
                PushError::Rejected(401),
            ),
            (
                "HTTP/1.1 422 Unprocessable Entity\r\ncontent-length: 2\r\n\r\n{}",
                PushError::Rejected(422),
            ),
            (
                "HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\n{}",
                PushError::Rejected(200),
            ),
            (
                "HTTP/1.1 403 Forbidden\r\ncontent-length: 2\r\n\r\n{}",
                PushError::Rejected(403),
            ),
        ] {
            let (address, server) = serve_once(raw.as_bytes().to_vec());
            assert_eq!(client(address).delete(), Err(expected), "{raw}");
            server.join().unwrap();
        }
    }

    #[test]
    fn empty_malformed_truncated_and_oversized_responses_are_invalid() {
        let oversized = format!(
            "HTTP/1.1 204 No Content\r\n\r\n{}",
            "x".repeat(MAX_PUSH_RESPONSE_BYTES + 10)
        );
        for raw in [
            Vec::new(),
            b"garbage".to_vec(),
            b"HTTP/1.1 abc OK\r\n\r\n".to_vec(),
            b"HTTP/2 204 OK\r\n\r\n".to_vec(),
            b"HTTP/1.1 204 No Content\r\ncontent-length: 10\r\n\r\nabc".to_vec(),
            oversized.into_bytes(),
        ] {
            let (address, server) = serve_once(raw.clone());
            assert_eq!(
                client(address).delete(),
                Err(PushError::InvalidResponse),
                "{:?}",
                String::from_utf8_lossy(&raw[..raw.len().min(40)])
            );
            server.join().unwrap();
        }
    }

    #[test]
    fn a_closed_port_is_unavailable_not_a_panic() {
        let address = {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            listener.local_addr().unwrap()
        };
        assert_eq!(client(address).delete(), Err(PushError::Unavailable));
    }

    #[test]
    fn client_refuses_non_loopback_addresses_and_unsafe_tokens() {
        let loopback: SocketAddr = "127.0.0.1:9".parse().unwrap();
        let remote: SocketAddr = "10.0.0.5:9".parse().unwrap();
        assert!(LoopbackEntitlementClient::new(remote, API_TOKEN, GRANT).is_err());
        assert!(LoopbackEntitlementClient::new(loopback, "", GRANT).is_err());
        assert!(LoopbackEntitlementClient::new(loopback, "bad\r\nX: y", GRANT).is_err());
        assert!(LoopbackEntitlementClient::new(loopback, API_TOKEN, "short").is_err());
        assert!(LoopbackEntitlementClient::new(loopback, API_TOKEN, &"g".repeat(129)).is_err());
        assert!(
            LoopbackEntitlementClient::new(loopback, API_TOKEN, "a b".repeat(20).as_str()).is_err()
        );
    }

    #[test]
    fn debug_and_error_labels_never_expose_tokens() {
        let loopback: SocketAddr = "127.0.0.1:9".parse().unwrap();
        let rendered = format!("{:?}", client(loopback));
        assert!(!rendered.contains(API_TOKEN) && !rendered.contains(GRANT));
        for error in [
            PushError::Invalid,
            PushError::Unavailable,
            PushError::InvalidResponse,
            PushError::Rejected(401),
        ] {
            let label = error.label();
            assert!(!label.contains(API_TOKEN) && !label.contains(GRANT));
        }
    }

    // ----- gate ------------------------------------------------------------

    #[derive(Default)]
    struct Recorder {
        calls: RefCell<Vec<String>>,
        fail: RefCell<Option<PushError>>,
    }

    impl EntitlementTransport for Recorder {
        fn put(&self, body: &EntitlementPush) -> Result<(), PushError> {
            self.calls
                .borrow_mut()
                .push(format!("PUT {}", body.valid_for_seconds));
            self.fail.borrow().map_or(Ok(()), Err)
        }
        fn delete(&self) -> Result<(), PushError> {
            self.calls.borrow_mut().push("DELETE".into());
            self.fail.borrow().map_or(Ok(()), Err)
        }
    }

    #[test]
    fn a_new_gate_is_checking_and_denies_paid_work() {
        let gate = LicenseGate::new();
        assert_eq!(gate.state(NOW), LockState::Checking);
        assert_eq!(require_paid(&gate, NOW), Err("license_required"));
    }

    #[test]
    fn active_evaluation_unlocks_and_pushes_thirty_minutes() {
        let gate = LicenseGate::new();
        let transport = Recorder::default();
        gate.refresh(NOW, Evaluation::Active(summary(None)), &transport)
            .unwrap();
        assert_eq!(gate.state(NOW), LockState::Active);
        assert_eq!(require_paid(&gate, NOW), Ok(()));
        assert_eq!(*transport.calls.borrow(), ["PUT 1800"]);
    }

    #[test]
    fn locked_expired_and_near_expiry_clear_the_sidecar() {
        for (evaluation, state) in [
            (Evaluation::Locked, LockState::Locked),
            (Evaluation::Expired, LockState::Expired),
            (
                Evaluation::Active(summary(Some(NOW + 30))),
                LockState::Expired,
            ),
        ] {
            let gate = LicenseGate::new();
            let transport = Recorder::default();
            gate.refresh(NOW, Evaluation::Active(summary(None)), &transport)
                .unwrap();
            gate.refresh(NOW, evaluation, &transport).unwrap();
            assert_eq!(gate.state(NOW), state);
            assert_eq!(require_paid(&gate, NOW), Err("license_required"));
            assert_eq!(transport.calls.borrow().last().unwrap(), "DELETE");
        }
    }

    #[test]
    fn a_failed_push_is_reported_but_the_native_state_still_follows_the_receipt() {
        let gate = LicenseGate::new();
        let transport = Recorder::default();
        *transport.fail.borrow_mut() = Some(PushError::Unavailable);
        assert_eq!(
            gate.refresh(NOW, Evaluation::Active(summary(None)), &transport),
            Err(PushError::Unavailable)
        );
        assert_eq!(gate.state(NOW), LockState::Active);
        // A failed DELETE still locks the native side immediately.
        assert_eq!(
            gate.refresh(NOW, Evaluation::Locked, &transport),
            Err(PushError::Unavailable)
        );
        assert_eq!(gate.state(NOW), LockState::Locked);
        // The next tick retries and recovers.
        *transport.fail.borrow_mut() = None;
        gate.refresh(NOW + 900, Evaluation::Active(summary(None)), &transport)
            .unwrap();
        assert_eq!(gate.state(NOW + 900), LockState::Active);
    }

    #[test]
    fn unavailable_keeps_the_previous_state_but_never_leaves_checking_forever() {
        let gate = LicenseGate::new();
        let transport = Recorder::default();
        gate.refresh(NOW, Evaluation::Active(summary(None)), &transport)
            .unwrap();
        gate.refresh(NOW + 900, Evaluation::Unavailable, &transport)
            .unwrap();
        assert_eq!(gate.state(NOW + 900), LockState::Active);
        // The cached, still-unexpired summary is re-pushed so the sidecar does not lapse.
        assert_eq!(*transport.calls.borrow(), ["PUT 1800", "PUT 1800"]);

        let fresh = LicenseGate::new();
        let transport = Recorder::default();
        fresh
            .refresh(NOW, Evaluation::Unavailable, &transport)
            .unwrap();
        assert_eq!(fresh.state(NOW), LockState::Locked);
        assert_eq!(*transport.calls.borrow(), ["DELETE"]);
    }

    #[test]
    fn an_active_licence_reads_expired_once_its_expiry_passes_between_ticks() {
        let gate = LicenseGate::new();
        gate.refresh(
            NOW,
            Evaluation::Active(summary(Some(NOW + 600))),
            &Recorder::default(),
        )
        .unwrap();
        assert_eq!(gate.state(NOW + 599), LockState::Active);
        assert_eq!(gate.state(NOW + 600), LockState::Expired);
        assert_eq!(require_paid(&gate, NOW + 600), Err("license_required"));
    }

    struct SlowTransport(Mutex<Vec<&'static str>>);
    impl EntitlementTransport for SlowTransport {
        fn put(&self, _body: &EntitlementPush) -> Result<(), PushError> {
            self.0.lock().unwrap().push("put start");
            std::thread::sleep(Duration::from_millis(300));
            self.0.lock().unwrap().push("put end");
            Ok(())
        }
        fn delete(&self) -> Result<(), PushError> {
            self.0.lock().unwrap().push("delete start");
            Ok(())
        }
    }

    #[test]
    fn refresh_cycles_are_serialised_so_a_stale_tick_cannot_overwrite_a_newer_result() {
        let gate = LicenseGate::new();
        let transport = Arc::new(SlowTransport(Mutex::new(Vec::new())));
        let (slow_gate, slow_transport) = (gate.clone(), transport.clone());
        let slow = std::thread::spawn(move || {
            slow_gate
                .refresh(NOW, Evaluation::Active(summary(None)), &*slow_transport)
                .unwrap();
        });
        std::thread::sleep(Duration::from_millis(80));
        gate.refresh(NOW, Evaluation::Locked, &*transport).unwrap();
        slow.join().unwrap();
        assert_eq!(
            *transport.0.lock().unwrap(),
            ["put start", "put end", "delete start"]
        );
        assert_eq!(gate.state(NOW), LockState::Locked);
    }

    #[test]
    fn clear_locks_or_revokes_and_deletes() {
        for (requested, expected) in [
            (LockState::Revoked, LockState::Revoked),
            (LockState::Locked, LockState::Locked),
            (LockState::Active, LockState::Locked),
        ] {
            let gate = LicenseGate::new();
            let transport = Recorder::default();
            gate.refresh(NOW, Evaluation::Active(summary(None)), &transport)
                .unwrap();
            gate.clear(requested, &transport).unwrap();
            assert_eq!(gate.state(NOW), expected);
            assert_eq!(transport.calls.borrow().last().unwrap(), "DELETE");
        }
    }

    #[test]
    fn lock_state_serialises_to_lowercase_words_only() {
        for (state, word) in [
            (LockState::Checking, "checking"),
            (LockState::Locked, "locked"),
            (LockState::Active, "active"),
            (LockState::Expired, "expired"),
            (LockState::Revoked, "revoked"),
        ] {
            assert_eq!(serde_json::to_value(state).unwrap(), word);
        }
    }

    #[test]
    fn a_poisoned_lock_does_not_panic_the_gate() {
        let gate = LicenseGate::new();
        let clone = gate.clone();
        let _ = std::thread::spawn(move || {
            let _held = clone.shared.inner.lock().unwrap();
            panic!("poison");
        })
        .join();
        assert_eq!(gate.state(NOW), LockState::Checking);
        assert!(gate
            .refresh(NOW, Evaluation::Locked, &Recorder::default())
            .is_ok());
    }

    // ----- receipt evaluation ---------------------------------------------

    struct FakeKey(Result<Vec<u8>, LicenseClientError>);
    impl DeviceKey for FakeKey {
        fn public_key_der(&self) -> Result<Vec<u8>, LicenseClientError> {
            self.0.clone()
        }
        fn sign_challenge(&self, _nonce: &[u8]) -> Result<Vec<u8>, LicenseClientError> {
            Err(LicenseClientError::SecureStorage)
        }
    }

    struct FakeStore(Result<Option<StoredLicenseReceipt>, LicenseClientError>);
    impl ReceiptStore for FakeStore {
        fn load(&self) -> Result<Option<StoredLicenseReceipt>, LicenseClientError> {
            self.0.clone()
        }
        fn save(&mut self, _receipt: StoredLicenseReceipt) -> Result<(), LicenseClientError> {
            Ok(())
        }
    }

    fn receipt(token: &str, used: u32, allowed: u32) -> StoredLicenseReceipt {
        StoredLicenseReceipt {
            signed_entitlement: token.into(),
            device_slots_used: used,
            device_slots_allowed: allowed,
            last_checked_epoch: NOW,
        }
    }

    mod signed {
        use super::*;
        use base64::engine::general_purpose::URL_SAFE_NO_PAD;
        use base64::Engine;
        use jsonwebtoken::{encode, Algorithm, EncodingKey, Header};
        use serde_json::json;
        use sha2::Digest;

        pub const DEVICE_DER: &[u8] = b"test-only device SubjectPublicKeyInfo";
        use crate::test_keys::{PRIVATE_KEY, PUBLIC_KEY};

        pub fn keyring() -> BTreeMap<String, String> {
            BTreeMap::from([("officekit-test-2026".to_string(), PUBLIC_KEY.to_string())])
        }

        pub fn token(exp: Option<u64>, device: &[u8]) -> String {
            let provider = &jsonwebtoken::crypto::rust_crypto::DEFAULT_PROVIDER;
            let _ = provider.install_default();
            let mut claims = json!({
                "iss": "https://api.officekit.app",
                "aud": "officekit.desktop",
                "product": "officekit",
                "schema": "officekit.entitlement.v2",
                "license_id": URL_SAFE_NO_PAD.encode([7_u8; 16]),
                "activation_id": URL_SAFE_NO_PAD.encode([9_u8; 16]),
                "email_sha256": "b4c9a289323b21a01c3e940f150eb9b8c542587f1abfd8f0e1cc1ffc5e475514",
                "edition": "paid",
                "features": ["image.convert", "pdf.merge"],
                "device_key_sha256": URL_SAFE_NO_PAD.encode(sha2::Sha256::digest(device)),
                "iat": NOW - 100,
            });
            if let Some(exp) = exp {
                claims["exp"] = json!(exp);
            }
            let mut header = Header::new(Algorithm::RS256);
            header.typ = Some("JWT".into());
            header.kid = Some("officekit-test-2026".into());
            encode(
                &header,
                &claims,
                &EncodingKey::from_rsa_pem(PRIVATE_KEY.as_bytes()).unwrap(),
            )
            .unwrap()
        }
    }

    fn evaluate(store: Result<Option<StoredLicenseReceipt>, LicenseClientError>) -> Evaluation {
        evaluate_receipt(
            NOW,
            &signed::keyring(),
            &FakeKey(Ok(signed::DEVICE_DER.to_vec())),
            &FakeStore(store),
        )
    }

    #[test]
    fn a_genuine_receipt_is_active_with_its_features_and_expiry() {
        let token = signed::token(Some(NOW + 5000), signed::DEVICE_DER);
        match evaluate(Ok(Some(receipt(&token, 1, 3)))) {
            Evaluation::Active(summary) => {
                assert_eq!(summary.features, ["image.convert", "pdf.merge"]);
                assert_eq!(summary.expires_at, Some(NOW + 5000));
            }
            other => panic!("expected active, got {other:?}"),
        }
        assert!(matches!(
            evaluate(Ok(Some(receipt(
                &signed::token(None, signed::DEVICE_DER),
                1,
                3
            )))),
            Evaluation::Active(_)
        ));
    }

    #[test]
    fn expired_receipt_is_expired_and_other_failures_are_locked() {
        let expired = signed::token(Some(NOW), signed::DEVICE_DER);
        assert_eq!(
            evaluate(Ok(Some(receipt(&expired, 1, 3)))),
            Evaluation::Expired
        );
        let other_device = signed::token(Some(NOW + 5000), b"another device");
        assert_eq!(
            evaluate(Ok(Some(receipt(&other_device, 1, 3)))),
            Evaluation::Locked
        );
        assert_eq!(
            evaluate(Ok(Some(receipt("not.a.jwt", 1, 3)))),
            Evaluation::Locked
        );
        let good = signed::token(Some(NOW + 5000), signed::DEVICE_DER);
        assert_eq!(evaluate(Ok(Some(receipt(&good, 4, 3)))), Evaluation::Locked);
        assert_eq!(evaluate(Ok(None)), Evaluation::Locked);
        assert_eq!(
            evaluate_receipt(
                NOW,
                &BTreeMap::new(),
                &FakeKey(Ok(signed::DEVICE_DER.to_vec())),
                &FakeStore(Ok(Some(receipt(&good, 1, 3))))
            ),
            Evaluation::Locked
        );
    }

    #[test]
    fn unreadable_keychain_or_device_key_is_unavailable_not_locked() {
        assert_eq!(
            evaluate(Err(LicenseClientError::SecureStorage)),
            Evaluation::Unavailable
        );
        let good = signed::token(Some(NOW + 5000), signed::DEVICE_DER);
        assert_eq!(
            evaluate_receipt(
                NOW,
                &signed::keyring(),
                &FakeKey(Err(LicenseClientError::SecureStorage)),
                &FakeStore(Ok(Some(receipt(&good, 1, 3))))
            ),
            Evaluation::Unavailable
        );
    }

    #[test]
    fn tick_from_store_pushes_a_genuine_receipt_to_a_real_loopback_server() {
        let (address, server) = serve_once(NO_CONTENT.to_vec());
        let gate = LicenseGate::new();
        let token = signed::token(Some(NOW + 5000), signed::DEVICE_DER);
        tick_from_store(
            &gate,
            &client(address),
            NOW,
            &signed::keyring(),
            &FakeKey(Ok(signed::DEVICE_DER.to_vec())),
            &FakeStore(Ok(Some(receipt(&token, 1, 3)))),
        );
        let captured = server.join().unwrap();
        assert_eq!(gate.state(NOW), LockState::Active);
        let sent: serde_json::Value = serde_json::from_slice(&captured.body).unwrap();
        assert_eq!(sent["valid_for_seconds"], 1800);
        assert!(!String::from_utf8_lossy(&captured.body).contains("email"));
    }

    /// Manual check against a running sidecar:
    /// `OFFICEKIT_LIVE_ADDR=127.0.0.1:PORT OFFICEKIT_LIVE_API_TOKEN=.. OFFICEKIT_LIVE_GRANT=..
    /// cargo test --lib live_sidecar -- --ignored`
    #[test]
    #[ignore = "needs a running sidecar with ephemeral port and tokens"]
    fn live_sidecar_accepts_put_and_delete() {
        let address: SocketAddr = std::env::var("OFFICEKIT_LIVE_ADDR")
            .unwrap()
            .parse()
            .unwrap();
        let client = LoopbackEntitlementClient::new(
            address,
            &std::env::var("OFFICEKIT_LIVE_API_TOKEN").unwrap(),
            &std::env::var("OFFICEKIT_LIVE_GRANT").unwrap(),
        )
        .unwrap();
        client
            .put(&push_body(&summary(None), NOW).unwrap())
            .unwrap();
        // The pause lets the operator query /api/license/status between the two calls.
        std::thread::sleep(Duration::from_secs(
            std::env::var("OFFICEKIT_LIVE_HOLD_SECONDS")
                .ok()
                .and_then(|value| value.parse().ok())
                .unwrap_or(0),
        ));
        client.delete().unwrap();
    }

    #[test]
    fn tick_from_store_swallows_an_unreachable_sidecar() {
        let address = {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            listener.local_addr().unwrap()
        };
        let gate = LicenseGate::new();
        tick_from_store(
            &gate,
            &client(address),
            NOW,
            &signed::keyring(),
            &FakeKey(Ok(signed::DEVICE_DER.to_vec())),
            &FakeStore(Ok(None)),
        );
        assert_eq!(gate.state(NOW), LockState::Locked);
    }

    // ----- scheduler -------------------------------------------------------

    #[test]
    fn push_loop_ticks_immediately_then_after_each_wait_and_survives_a_panic() {
        let mut ticks = 0;
        let mut waits = 0;
        run_push_loop(
            |_| {
                waits += 1;
                waits < 3
            },
            || {
                ticks += 1;
                if ticks == 2 {
                    panic!("tick failure");
                }
                true
            },
        );
        assert_eq!(ticks, 3);
        assert_eq!(waits, 3);
    }

    #[test]
    fn a_failed_push_is_retried_on_a_short_bounded_backoff_then_the_normal_cadence_rearms() {
        let mut delays = Vec::new();
        let mut outcomes = vec![false, false, false, false, false, true, true].into_iter();
        run_push_loop(
            |delay| {
                delays.push(delay);
                delays.len() < 7
            },
            || outcomes.next().unwrap(),
        );
        let seconds: Vec<u64> = delays.iter().map(Duration::as_secs).collect();
        // failures: 15s, 30s, 60s, then the full interval and the sequence re-arms (15s), then
        // two successes wait the full interval.
        assert_eq!(seconds, [15, 30, 60, 900, 15, 900, 900]);
        assert_eq!(PUSH_RETRY_BACKOFF.last().unwrap() < &PUSH_INTERVAL, true);
    }

    #[test]
    fn a_panicking_tick_counts_as_a_failure_for_the_backoff() {
        let mut delays = Vec::new();
        run_push_loop(
            |delay| {
                delays.push(delay);
                delays.len() < 2
            },
            || panic!("tick failure"),
        );
        assert_eq!(delays, [PUSH_RETRY_BACKOFF[0], PUSH_RETRY_BACKOFF[1]]);
    }

    #[test]
    fn retry_failed_push_stops_at_the_first_success_and_is_bounded() {
        let mut waits = Vec::new();
        let mut attempts = 0;
        assert!(retry_failed_push(
            |delay| waits.push(delay),
            || {
                attempts += 1;
                attempts == 2
            }
        ));
        assert_eq!(waits, [PUSH_RETRY_BACKOFF[0], PUSH_RETRY_BACKOFF[1]]);

        let mut waits = Vec::new();
        assert!(!retry_failed_push(|delay| waits.push(delay), || false));
        assert_eq!(waits, PUSH_RETRY_BACKOFF);
    }

    // ----- clock failure fails closed (CR-4, ARCH-4, QA-3) ------------------

    #[test]
    fn a_clock_before_the_epoch_reads_as_unavailable() {
        let before = std::time::UNIX_EPOCH - Duration::from_secs(5);
        assert_eq!(epoch_seconds(before), None);
        assert_eq!(
            epoch_seconds(std::time::UNIX_EPOCH + Duration::from_secs(42)),
            Some(42)
        );
    }

    #[test]
    fn an_unreadable_clock_denies_paid_work_for_every_active_licence() {
        for expires_at in [None, Some(NOW + 100_000)] {
            let gate = LicenseGate::new();
            gate.refresh(
                NOW,
                Evaluation::Active(summary(expires_at)),
                &Recorder::default(),
            )
            .unwrap();
            assert_eq!(gate.state(NOW), LockState::Active);
            assert_eq!(gate.state(None), LockState::Expired, "{expires_at:?}");
            assert_eq!(require_paid(&gate, None), Err("license_required"));
            assert_eq!(
                command_guard(&gate, "agent_settings_read", None),
                Err("license_required")
            );
            // Exempt commands (activation, lock state) still work so the UI can explain.
            assert_eq!(command_guard(&gate, "license_state", None), Ok(()));
            assert_eq!(command_guard(&gate, "result_copy_text", None), Ok(()));
        }
    }

    #[test]
    fn a_tick_with_an_unreadable_clock_locks_and_clears_the_sidecar() {
        let gate = LicenseGate::new();
        let transport = Recorder::default();
        gate.refresh(NOW, Evaluation::Active(summary(None)), &transport)
            .unwrap();
        let token = signed::token(Some(NOW + 5000), signed::DEVICE_DER);
        let ok = tick_from_store(
            &gate,
            &transport,
            None,
            &signed::keyring(),
            &FakeKey(Ok(signed::DEVICE_DER.to_vec())),
            &FakeStore(Ok(Some(receipt(&token, 1, 3)))),
        );
        assert!(ok);
        assert_eq!(gate.state(NOW), LockState::Expired);
        assert_eq!(transport.calls.borrow().last().unwrap(), "DELETE");
    }

    #[test]
    fn a_startup_check_with_an_unreadable_clock_does_not_unlock() {
        let gate = LicenseGate::new();
        let token = signed::token(None, signed::DEVICE_DER);
        check_from_store(
            &gate,
            None,
            &signed::keyring(),
            &FakeKey(Ok(signed::DEVICE_DER.to_vec())),
            &FakeStore(Ok(Some(receipt(&token, 1, 3)))),
        );
        assert_eq!(gate.state(NOW), LockState::Expired);
    }

    // ----- startup check (CR-2) --------------------------------------------

    #[test]
    fn a_startup_check_activates_a_genuine_receipt_before_any_push_and_never_stays_checking() {
        let token = signed::token(Some(NOW + 5000), signed::DEVICE_DER);
        let gate = LicenseGate::new();
        check_from_store(
            &gate,
            NOW,
            &signed::keyring(),
            &FakeKey(Ok(signed::DEVICE_DER.to_vec())),
            &FakeStore(Ok(Some(receipt(&token, 1, 3)))),
        );
        assert_eq!(gate.state(NOW), LockState::Active);
        assert_eq!(
            command_guard(&gate, "window_snap_set_edge_enabled", NOW),
            Ok(())
        );
        assert_eq!(
            command_guard(&gate, "screenshot_shortcut_configure", NOW),
            Ok(())
        );
        assert_eq!(
            command_guard(&gate, "media_toolkit_drop_set_enabled", NOW),
            Ok(())
        );

        let unreadable = LicenseGate::new();
        check_from_store(
            &unreadable,
            NOW,
            &signed::keyring(),
            &FakeKey(Ok(signed::DEVICE_DER.to_vec())),
            &FakeStore(Err(LicenseClientError::SecureStorage)),
        );
        assert_eq!(unreadable.state(NOW), LockState::Locked);
    }

    // ----- state-change event source (CR-2) ---------------------------------

    #[test]
    fn the_observer_hears_each_real_state_change_once_and_only_the_lowercase_word() {
        let gate = LicenseGate::new();
        let heard = Arc::new(Mutex::new(Vec::new()));
        let sink = heard.clone();
        gate.on_change(move |state| {
            sink.lock()
                .unwrap()
                .push(serde_json::to_string(&state).unwrap())
        });
        let transport = Recorder::default();
        gate.refresh(NOW, Evaluation::Locked, &transport).unwrap();
        gate.refresh(NOW, Evaluation::Locked, &transport).unwrap();
        gate.refresh(NOW, Evaluation::Active(summary(None)), &transport)
            .unwrap();
        gate.refresh(NOW, Evaluation::Active(summary(None)), &transport)
            .unwrap();
        gate.refresh(NOW, Evaluation::Expired, &transport).unwrap();
        assert_eq!(
            *heard.lock().unwrap(),
            ["\"locked\"", "\"active\"", "\"expired\""]
        );
        assert_eq!(STATE_CHANGED_EVENT, "license-state-changed");
    }

    // ----- unreadable Keychain keeps the sidecar alive (CR-5) ----------------

    #[test]
    fn an_unreadable_keychain_with_a_nearly_expired_cached_licence_expires_and_clears() {
        let gate = LicenseGate::new();
        let transport = Recorder::default();
        gate.refresh(
            NOW,
            Evaluation::Active(summary(Some(NOW + 100))),
            &transport,
        )
        .unwrap();
        gate.refresh(NOW + 50, Evaluation::Unavailable, &transport)
            .unwrap();
        assert_eq!(gate.state(NOW + 50), LockState::Expired);
        assert_eq!(transport.calls.borrow().last().unwrap(), "DELETE");
    }

    // ----- tamper evidence at the gate (QA-4) --------------------------------

    #[test]
    fn a_well_formed_token_with_a_flipped_signature_or_edited_payload_is_locked() {
        let good = signed::token(Some(NOW + 5000), signed::DEVICE_DER);
        let parts: Vec<&str> = good.split('.').collect();
        assert_eq!(parts.len(), 3);
        let flip = |segment: &str| {
            let mut bytes = segment.as_bytes().to_vec();
            let middle = bytes.len() / 2;
            bytes[middle] = if bytes[middle] == b'A' { b'B' } else { b'A' };
            String::from_utf8(bytes).unwrap()
        };
        let bad_signature = format!("{}.{}.{}", parts[0], parts[1], flip(parts[2]));
        let bad_payload = format!("{}.{}.{}", parts[0], flip(parts[1]), parts[2]);
        assert_ne!(bad_signature, good);
        assert_eq!(
            evaluate(Ok(Some(receipt(&bad_signature, 1, 3)))),
            Evaluation::Locked
        );
        assert_eq!(
            evaluate(Ok(Some(receipt(&bad_payload, 1, 3)))),
            Evaluation::Locked
        );
        // Control: the untouched token is Active.
        assert!(matches!(
            evaluate(Ok(Some(receipt(&good, 1, 3)))),
            Evaluation::Active(_)
        ));
    }

    // ----- cycle lock covers the Keychain read (CR-3) -------------------------

    /// Returns the receipt as it was when `load` was called, then dawdles: a stale reader.
    struct SlowStore {
        receipt: Arc<Mutex<Option<StoredLicenseReceipt>>>,
        delay: Duration,
    }
    impl ReceiptStore for SlowStore {
        fn load(&self) -> Result<Option<StoredLicenseReceipt>, LicenseClientError> {
            let snapshot = self.receipt.lock().unwrap().clone();
            std::thread::sleep(self.delay);
            Ok(snapshot)
        }
        fn save(&mut self, _receipt: StoredLicenseReceipt) -> Result<(), LicenseClientError> {
            Ok(())
        }
    }

    struct SyncRecorder(Mutex<Vec<String>>);
    impl EntitlementTransport for SyncRecorder {
        fn put(&self, body: &EntitlementPush) -> Result<(), PushError> {
            self.0
                .lock()
                .unwrap()
                .push(format!("PUT {}", body.valid_for_seconds));
            Ok(())
        }
        fn delete(&self) -> Result<(), PushError> {
            self.0.lock().unwrap().push("DELETE".into());
            Ok(())
        }
    }

    #[test]
    fn a_stale_tick_that_read_the_keychain_before_activation_cannot_overwrite_the_activation() {
        let gate = LicenseGate::new();
        let receipt_cell = Arc::new(Mutex::new(None));
        let transport = Arc::new(SyncRecorder(Mutex::new(Vec::new())));
        let token = signed::token(Some(NOW + 5000), signed::DEVICE_DER);

        let (tick_gate, tick_transport, tick_cell) =
            (gate.clone(), transport.clone(), receipt_cell.clone());
        let stale = std::thread::spawn(move || {
            tick_from_store(
                &tick_gate,
                &*tick_transport,
                NOW,
                &signed::keyring(),
                &FakeKey(Ok(signed::DEVICE_DER.to_vec())),
                &SlowStore {
                    receipt: tick_cell,
                    delay: Duration::from_millis(300),
                },
            );
        });
        // Activation lands while the stale tick is still reading, then runs its own tick.
        std::thread::sleep(Duration::from_millis(80));
        *receipt_cell.lock().unwrap() = Some(receipt(&token, 1, 3));
        tick_from_store(
            &gate,
            &*transport,
            NOW,
            &signed::keyring(),
            &FakeKey(Ok(signed::DEVICE_DER.to_vec())),
            &SlowStore {
                receipt: receipt_cell,
                delay: Duration::ZERO,
            },
        );
        stale.join().unwrap();
        assert_eq!(gate.state(NOW), LockState::Active);
        assert_eq!(transport.0.lock().unwrap().last().unwrap(), "PUT 1800");
    }

    // ----- the wrapper is registered (QA-2) ------------------------------------

    #[test]
    fn the_single_invoke_handler_is_wrapped_by_the_licence_guard_outside_the_companion_check() {
        let lib = source_files()
            .into_iter()
            .find(|(name, _)| name == "lib.rs")
            .unwrap()
            .1;
        let registrations = lib.matches(".invoke_handler(").count();
        // One list for the full profile and one for the companion profile; both are guarded.
        assert_eq!(
            registrations, 2,
            "expected the two invoke_handler registrations"
        );
        assert_eq!(
            lib.matches(".invoke_handler(restrict_companion_invoke(license_guarded(")
                .count(),
            2,
            "every invoke handler must be wrapped by license_guarded"
        );
        assert!(
            lib.contains("fn license_guarded_with_clock")
                && lib.contains("license_gate::command_guard("),
            "license_guarded must call command_guard"
        );
    }

    // ----- Clipboard & Snippets Studio is locked (owner decision 2026-10-22) ----

    #[test]
    fn clipboard_studio_native_calls_are_paid_or_the_shared_free_copy_helper() {
        for command in [
            "dictation_paste_text",
            "media_clipboard_hotkey_set_enabled",
            "media_clipboard_revision",
        ] {
            assert_eq!(class_of(command), Some(Paid), "{command}");
        }
        assert_eq!(class_of("result_copy_text"), Some(Exempt));
        for command in [
            "ergonomics_get_state",
            "ergonomics_update_settings",
            "ergonomics_reminder_action",
            "ergonomics_preview",
            "ergonomics_motion_action",
            "ergonomics_calendar_action",
        ] {
            assert_eq!(class_of(command), Some(Paid), "{command}");
        }
    }

    // ----- command classification -----------------------------------------

    fn source_files() -> Vec<(String, String)> {
        let directory = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
        let mut files = Vec::new();
        for entry in std::fs::read_dir(directory).unwrap() {
            let path = entry.unwrap().path();
            if path.extension().is_some_and(|ext| ext == "rs") {
                files.push((
                    path.file_name().unwrap().to_string_lossy().into_owned(),
                    std::fs::read_to_string(&path).unwrap(),
                ));
            }
        }
        files
    }

    fn command_names(source: &str) -> BTreeSet<String> {
        let marker = ["#[tauri", "::command]"].concat();
        let lines: Vec<&str> = source.lines().collect();
        let mut names = BTreeSet::new();
        for (index, line) in lines.iter().enumerate() {
            if line.trim() != marker {
                continue;
            }
            let declaration = lines[index + 1..]
                .iter()
                .map(|line| line.trim())
                .find(|line| !line.starts_with("#["))
                .unwrap();
            let after_fn = declaration.split("fn ").nth(1).unwrap();
            let name: String = after_fn
                .chars()
                .take_while(|c| c.is_ascii_alphanumeric() || *c == '_')
                .collect();
            names.insert(name);
        }
        names
    }

    fn handler_lists(source: &str) -> Vec<BTreeSet<String>> {
        let opener = ["generate_handler!", "["].concat();
        source
            .split(&opener)
            .skip(1)
            .map(|rest| {
                rest.split(']')
                    .next()
                    .unwrap()
                    .split(',')
                    .map(|entry| entry.trim().rsplit("::").next().unwrap().to_string())
                    .filter(|name| !name.is_empty())
                    .collect()
            })
            .collect()
    }

    #[test]
    fn every_tauri_command_is_classified_exactly_once() {
        let mut found = BTreeSet::new();
        for (_, source) in source_files() {
            found.extend(command_names(&source));
        }
        assert!(
            found.len() > 60,
            "command scan found {} commands",
            found.len()
        );
        let table: Vec<&str> = COMMAND_CLASSES.iter().map(|(name, _)| *name).collect();
        let classified: BTreeSet<String> = table.iter().map(|name| name.to_string()).collect();
        assert_eq!(
            table.len(),
            classified.len(),
            "a command is classified twice"
        );
        let unclassified: Vec<_> = found.difference(&classified).collect();
        let stale: Vec<_> = classified.difference(&found).collect();
        assert!(
            unclassified.is_empty(),
            "classify these commands in COMMAND_CLASSES: {unclassified:?}"
        );
        assert!(stale.is_empty(), "stale COMMAND_CLASSES entries: {stale:?}");
    }

    #[test]
    fn both_invoke_handler_lists_register_the_lock_surface_and_only_classified_commands() {
        let lib = source_files()
            .into_iter()
            .find(|(name, _)| name == "lib.rs")
            .unwrap()
            .1;
        let lists = handler_lists(&lib);
        assert_eq!(lists.len(), 2, "expected the two invoke_handler lists");
        let classified: BTreeSet<String> = COMMAND_CLASSES
            .iter()
            .map(|(name, _)| name.to_string())
            .collect();
        for list in &lists {
            for required in [
                "license_status",
                "license_activate",
                "license_deactivate",
                "support_ticket_submit",
                "support_ticket_updates",
                "license_state",
                "check_backend_status",
                "officekit_api_token",
                "officekit_api_origin",
                "result_copy_text",
                "result_save",
            ] {
                assert!(
                    list.contains(required),
                    "{required} missing from a handler list"
                );
            }
            let unknown: Vec<_> = list.difference(&classified).collect();
            assert!(unknown.is_empty(), "unclassified handlers: {unknown:?}");
        }
        let registered: BTreeSet<String> = lists.iter().flatten().cloned().collect();
        assert_eq!(
            registered, classified,
            "every classified command is registered in at least one list"
        );
    }

    #[test]
    fn the_free_tool_commands_stay_exempt_and_settings_commands_are_paid() {
        for command in [
            "result_copy_text",
            "result_save",
            "officekit_api_token",
            "officekit_api_origin",
            "check_backend_status",
            "license_activate",
            "license_deactivate",
            "support_ticket_submit",
            "support_ticket_updates",
            "license_status",
            "license_state",
            "launcher_recent_tools",
            "officekit_quit",
        ] {
            assert_eq!(class_of(command), Some(Exempt), "{command}");
        }
        for command in [
            "agent_settings_read",
            "agent_settings_write",
            "agent_skill_install",
            "file_selection_open",
            "dictation_capture_start",
            "screenshot_capture",
        ] {
            assert_eq!(class_of(command), Some(Paid), "{command}");
        }
    }

    #[test]
    fn command_guard_lets_exempt_through_denies_paid_and_unknown_while_locked() {
        let locked_gate = LicenseGate::new();
        assert_eq!(command_guard(&locked_gate, "result_copy_text", NOW), Ok(()));
        assert_eq!(command_guard(&locked_gate, "license_activate", NOW), Ok(()));
        assert_eq!(
            command_guard(&locked_gate, "agent_settings_read", NOW),
            Err("license_required")
        );
        assert_eq!(
            command_guard(&locked_gate, "a_future_unclassified_command", NOW),
            Err("license_required")
        );
        let active = LicenseGate::new();
        active
            .refresh(NOW, Evaluation::Active(summary(None)), &Recorder::default())
            .unwrap();
        assert_eq!(command_guard(&active, "agent_settings_read", NOW), Ok(()));
        // Even an Active gate lets an unclassified command through only because it is paid-gated,
        // never because it is exempt.
        assert_eq!(
            command_guard(&active, "a_future_unclassified_command", NOW),
            Ok(())
        );
        let expired = LicenseGate::new();
        expired
            .refresh(NOW, Evaluation::Expired, &Recorder::default())
            .unwrap();
        assert_eq!(
            command_guard(&expired, "agent_settings_read", NOW),
            Err("license_required")
        );
    }
}
