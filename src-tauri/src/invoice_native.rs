//! Native-only reconnection to a remembered, identity-bound invoice folder.

use crate::workspace_native::NativeGrantToken;
use crate::{BackendApiAddress, BackendApiToken};
use serde_json::{json, Value};
use tauri::State;

/// Paths and the native credential remain outside the webview. The backend
/// revalidates its remembered directory identity before authorizing this binding.
#[tauri::command]
pub fn invoice_library_reconnect(
    binding_id: String,
    token: State<'_, NativeGrantToken>,
    api_token: State<'_, BackendApiToken>,
    backend_address: State<'_, BackendApiAddress>,
) -> Result<Value, String> {
    let id = uuid::Uuid::parse_str(&binding_id)
        .map_err(|_| "Choose a valid invoice library.".to_string())?;
    if id.to_string() != binding_id {
        return Err("Choose a valid invoice library.".into());
    }
    let agent = ureq::Agent::new_with_config(
        ureq::config::Config::builder()
            .max_redirects(0)
            .timeout_global(Some(std::time::Duration::from_secs(15)))
            .build(),
    );
    let response = agent
        .post(format!(
            "http://{}/api/invoice-libraries/{id}/reconnections",
            backend_address.0
        ))
        .header("Authorization", &format!("Bearer {}", api_token.0))
        .header("X-OfficeKit-Native-Grant", &token.0)
        .send_json(json!({}))
        .map_err(|_| {
            "The invoice folder could not be reconnected. Choose the folder again.".to_string()
        })?;
    response
        .into_body()
        .with_config()
        .limit(1024 * 1024)
        .read_json::<Value>()
        .map_err(|_| "The invoice folder returned invalid metadata.".into())
}

#[cfg(test)]
#[path = "invoice_native_tests.rs"]
mod tests;
