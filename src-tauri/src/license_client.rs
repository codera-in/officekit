use crate::licensing::{verify_entitlement, LicenseVerificationError, VerifiedEntitlement};
use base64::engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD};
use base64::Engine;
use p256::ecdsa::SigningKey;
#[cfg(target_os = "macos")]
use p256::elliptic_curve::Generate;
use p256::pkcs8::{DecodePrivateKey, EncodePrivateKey, EncodePublicKey};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use std::collections::BTreeMap;
use std::io::Read;
use std::time::Duration;

const MAX_LICENSE_KEY_BYTES: usize = 512;
// The 3-byte server minimum is implied by the structure checks below (the shortest
// accepted address is `a@b.c`), so only the upper bound needs a constant.
const MAX_EMAIL_BYTES: usize = 254;
const MAX_DEVICE_PUBLIC_KEY_DER_BYTES: usize = 2048;
const MAX_ECDSA_SIGNATURE_DER_BYTES: usize = 1024;
const MAX_LICENSE_RESPONSE_BYTES: usize = 8192;
const MAX_LICENSE_PUBLIC_KEYRING_BYTES: usize = 32 * 1024;
const MAX_LICENSE_PUBLIC_KEYS: usize = 8;
const MAX_CHALLENGE_SECONDS: u64 = 300;
// `now_epoch` is read before the challenge request, and the server stamps the expiry from its own clock
// when it answers, so a slow round trip or a small clock offset puts the expiry a little past
// now + MAX_CHALLENGE_SECONDS. Without this allowance a 1 s request is rejected as an invalid response.
const CHALLENGE_CLOCK_SKEW_SECONDS: u64 = 60;
const LICENSE_KEYCHAIN_SERVICE: &str = "app.officekit.desktop.license.v1";
const DEVICE_KEYCHAIN_ACCOUNT: &str = "device-private-key-pkcs8";
const RECEIPT_KEYCHAIN_ACCOUNT: &str = "signed-entitlement-v1";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LicenseClientError {
    InvalidInput,
    InvalidResponse,
    InvalidCredential,
    DeviceLimit,
    Unavailable,
    NoPinnedKeys,
    SecureStorage,
    #[cfg(not(target_os = "macos"))]
    UnsupportedPlatform,
}

impl LicenseClientError {
    pub fn public_message(self) -> &'static str {
        match self {
            Self::InvalidInput => "Enter a valid purchase email and license key and try again.",
            Self::InvalidResponse => "The licensing service returned an invalid response. No license was saved.",
            Self::InvalidCredential => "The email or license key is not valid. Check both and try again.",
            Self::DeviceLimit => "All device slots for this license are in use. Deactivate another device or contact support.",
            Self::Unavailable => "The licensing service is unavailable. Try again when you are online.",
            Self::NoPinnedKeys => "License verification is not configured in this build.",
            Self::SecureStorage => "macOS Keychain could not store or read the device license safely.",
            #[cfg(not(target_os = "macos"))]
            Self::UnsupportedPlatform => "Device-bound license activation is not available on this platform yet.",
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActivationChallengeRequest {
    pub email: String,
    pub license_key: String,
    pub device_public_key: String,
    pub platform: String,
    pub app_version: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ActivationChallengeResponse {
    pub challenge_id: String,
    pub nonce: String,
    pub expires_at_epoch: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActivationSignature {
    pub email: String,
    pub license_key: String,
    pub challenge_id: String,
    pub signature: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ActivationResponse {
    pub activation_id: String,
    pub signed_entitlement: String,
    pub device_slots_used: u32,
    pub device_slots_allowed: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StoredLicenseReceipt {
    pub signed_entitlement: String,
    pub device_slots_used: u32,
    pub device_slots_allowed: u32,
    pub last_checked_epoch: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ActiveLicenseStatus {
    pub activation_id: String,
    pub edition: String,
    pub features: Vec<String>,
    pub device_slots_used: u32,
    pub device_slots_allowed: u32,
    pub last_checked_epoch: u64,
    pub offline_capable: bool,
}

pub trait ActivationApi {
    fn create_challenge(
        &mut self,
        request: ActivationChallengeRequest,
    ) -> Result<ActivationChallengeResponse, LicenseClientError>;

    fn activate(
        &mut self,
        signature: ActivationSignature,
    ) -> Result<ActivationResponse, LicenseClientError>;
}

pub trait DeviceKey {
    fn public_key_der(&self) -> Result<Vec<u8>, LicenseClientError>;
    fn sign_challenge(&self, nonce: &[u8]) -> Result<Vec<u8>, LicenseClientError>;
}

pub trait ReceiptStore {
    fn load(&self) -> Result<Option<StoredLicenseReceipt>, LicenseClientError>;
    fn save(&mut self, receipt: StoredLicenseReceipt) -> Result<(), LicenseClientError>;
}

/// Frees this Mac's seat on the server. Authenticated by the purchase email and licence key, which
/// the app never stores, so the user types them again.
pub trait DeactivationApi {
    fn deactivate(
        &mut self,
        email: &str,
        license_key: &str,
        activation_id: &str,
    ) -> Result<(), LicenseClientError>;
}

/// Removes the saved receipt. The device key stays: re-activating with the same key reuses it.
pub trait ReceiptClear {
    fn clear(&mut self) -> Result<(), LicenseClientError>;
}

/// Server first, then local: the receipt is removed only after the server confirmed (or already
/// knew nothing about) this activation, so a failed call never leaves the Mac locked with its seat
/// still taken. Returns `Ok(false)` when there was nothing to deactivate.
pub fn deactivate_license(
    email: &str,
    license_key: &str,
    now_epoch: u64,
    pinned_public_keys: &BTreeMap<String, String>,
    api: &mut impl DeactivationApi,
    device_key: &impl DeviceKey,
    receipt_store: &mut (impl ReceiptStore + ReceiptClear),
) -> Result<bool, LicenseClientError> {
    validate_activation_input(email, license_key, "macos", "1.0.0")?;
    let Some(status) =
        current_license_status(now_epoch, pinned_public_keys, device_key, receipt_store)?
    else {
        return Ok(false);
    };
    api.deactivate(email, license_key, &status.activation_id)?;
    receipt_store.clear()?;
    Ok(true)
}

pub fn activate_license(
    email: &str,
    license_key: &str,
    platform: &str,
    app_version: &str,
    now_epoch: u64,
    pinned_public_keys: &BTreeMap<String, String>,
    api: &mut impl ActivationApi,
    device_key: &impl DeviceKey,
    receipt_store: &mut impl ReceiptStore,
) -> Result<ActiveLicenseStatus, LicenseClientError> {
    validate_activation_input(email, license_key, platform, app_version)?;
    if pinned_public_keys.is_empty() {
        return Err(LicenseClientError::NoPinnedKeys);
    }

    let public_key_der = device_key.public_key_der()?;
    if public_key_der.is_empty() || public_key_der.len() > MAX_DEVICE_PUBLIC_KEY_DER_BYTES {
        return Err(LicenseClientError::SecureStorage);
    }
    let challenge = api.create_challenge(ActivationChallengeRequest {
        email: email.to_string(),
        license_key: license_key.to_string(),
        device_public_key: STANDARD.encode(&public_key_der),
        platform: platform.to_string(),
        app_version: app_version.to_string(),
    })?;
    let nonce = validate_challenge(challenge.clone(), now_epoch)?;
    let signature_der = device_key.sign_challenge(&nonce)?;
    if signature_der.is_empty() || signature_der.len() > MAX_ECDSA_SIGNATURE_DER_BYTES {
        return Err(LicenseClientError::SecureStorage);
    }
    let activation = api.activate(ActivationSignature {
        email: email.to_string(),
        license_key: license_key.to_string(),
        challenge_id: challenge.challenge_id,
        signature: URL_SAFE_NO_PAD.encode(signature_der),
    })?;
    validate_activation_response(activation.clone())?;
    let verified = verify_entitlement(
        &activation.signed_entitlement,
        pinned_public_keys,
        &public_key_der,
        now_epoch,
    )
    .map_err(map_verification_error)?;
    if verified.activation_id != activation.activation_id {
        return Err(LicenseClientError::InvalidResponse);
    }

    let status = status_from_verified(
        verified,
        activation.device_slots_used,
        activation.device_slots_allowed,
        now_epoch,
    );
    receipt_store.save(StoredLicenseReceipt {
        signed_entitlement: activation.signed_entitlement,
        device_slots_used: activation.device_slots_used,
        device_slots_allowed: activation.device_slots_allowed,
        last_checked_epoch: now_epoch,
    })?;
    Ok(status)
}

pub fn current_license_status(
    now_epoch: u64,
    pinned_public_keys: &BTreeMap<String, String>,
    device_key: &impl DeviceKey,
    receipt_store: &impl ReceiptStore,
) -> Result<Option<ActiveLicenseStatus>, LicenseClientError> {
    let Some(receipt) = receipt_store.load()? else {
        return Ok(None);
    };
    validate_slot_counts(receipt.device_slots_used, receipt.device_slots_allowed)?;
    let public_key_der = device_key.public_key_der()?;
    let verified = verify_entitlement(
        &receipt.signed_entitlement,
        pinned_public_keys,
        &public_key_der,
        now_epoch,
    )
    .map_err(map_verification_error)?;
    Ok(Some(status_from_verified(
        verified,
        receipt.device_slots_used,
        receipt.device_slots_allowed,
        receipt.last_checked_epoch,
    )))
}

fn status_from_verified(
    verified: VerifiedEntitlement,
    device_slots_used: u32,
    device_slots_allowed: u32,
    last_checked_epoch: u64,
) -> ActiveLicenseStatus {
    ActiveLicenseStatus {
        activation_id: verified.activation_id,
        edition: verified.edition,
        features: verified.features,
        device_slots_used,
        device_slots_allowed,
        last_checked_epoch,
        offline_capable: true,
    }
}

// A cheap client-side prefilter only: the server is authoritative and also rejects a local
// part over 64 characters and Unicode whitespace or control characters (services/licensing/email.mjs).
// Such addresses reach the server, return 422 and show the same generic credential message.
fn is_plausible_email(email: &str) -> bool {
    if email.trim() != email
        || email.len() > MAX_EMAIL_BYTES
        || email.bytes().any(|byte| byte.is_ascii_control())
    {
        return false;
    }
    let mut parts = email.split('@');
    match (parts.next(), parts.next(), parts.next()) {
        (Some(local), Some(domain), None) => {
            !local.is_empty() && !domain.is_empty() && domain.contains('.')
        }
        _ => false,
    }
}

fn validate_activation_input(
    email: &str,
    license_key: &str,
    platform: &str,
    app_version: &str,
) -> Result<(), LicenseClientError> {
    if !is_plausible_email(email)
        || license_key.is_empty()
        || license_key.len() > MAX_LICENSE_KEY_BYTES
        || license_key.trim() != license_key
        || !license_key.bytes().all(|byte| !byte.is_ascii_control())
        || !matches!(platform, "macos" | "windows" | "linux")
        || app_version.is_empty()
        || app_version.len() > 64
        || !app_version.is_ascii()
        || !app_version
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || ".+-".contains(byte as char))
    {
        return Err(LicenseClientError::InvalidInput);
    }
    Ok(())
}

fn validate_challenge(
    challenge: ActivationChallengeResponse,
    now_epoch: u64,
) -> Result<Vec<u8>, LicenseClientError> {
    if decode_canonical_base64url(&challenge.challenge_id, 16).is_none()
        || challenge.expires_at_epoch <= now_epoch
        || challenge.expires_at_epoch
            > now_epoch.saturating_add(MAX_CHALLENGE_SECONDS + CHALLENGE_CLOCK_SKEW_SECONDS)
    {
        return Err(LicenseClientError::InvalidResponse);
    }
    let nonce = decode_canonical_base64url(&challenge.nonce, 32)
        .ok_or(LicenseClientError::InvalidResponse)?;
    Ok(nonce)
}

fn validate_activation_response(response: ActivationResponse) -> Result<(), LicenseClientError> {
    if decode_canonical_base64url(&response.activation_id, 16).is_none()
        || response.signed_entitlement.is_empty()
        || response.signed_entitlement.len() > 8192
    {
        return Err(LicenseClientError::InvalidResponse);
    }
    validate_slot_counts(response.device_slots_used, response.device_slots_allowed)
}

pub(crate) fn validate_slot_counts(used: u32, allowed: u32) -> Result<(), LicenseClientError> {
    if used == 0 || allowed == 0 || used > allowed || allowed > 10_000 {
        return Err(LicenseClientError::InvalidResponse);
    }
    Ok(())
}

fn decode_canonical_base64url(value: &str, expected_bytes: usize) -> Option<Vec<u8>> {
    if value.is_empty()
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
    {
        return None;
    }
    let decoded = URL_SAFE_NO_PAD.decode(value).ok()?;
    (decoded.len() == expected_bytes && URL_SAFE_NO_PAD.encode(&decoded) == value)
        .then_some(decoded)
}

fn map_verification_error(_error: LicenseVerificationError) -> LicenseClientError {
    LicenseClientError::InvalidResponse
}

pub fn parse_pinned_keyring(raw: &str) -> Result<BTreeMap<String, String>, LicenseClientError> {
    if raw.is_empty() || raw == "{}" {
        return Ok(BTreeMap::new());
    }
    if raw.len() > MAX_LICENSE_PUBLIC_KEYRING_BYTES {
        return Err(LicenseClientError::InvalidResponse);
    }
    let keys: BTreeMap<String, String> =
        serde_json::from_str(raw).map_err(|_| LicenseClientError::InvalidResponse)?;
    if keys.is_empty()
        || keys.len() > MAX_LICENSE_PUBLIC_KEYS
        || keys.iter().any(|(kid, pem)| {
            kid.is_empty()
                || kid.len() > 64
                || !kid.is_ascii()
                || pem.is_empty()
                || pem.len() > 4096
                || !pem.contains("-----BEGIN PUBLIC KEY-----")
        })
    {
        return Err(LicenseClientError::InvalidResponse);
    }
    Ok(keys)
}

pub fn configured_license_api_base_url() -> Result<&'static str, LicenseClientError> {
    let base_url =
        option_env!("OFFICEKIT_LICENSE_API_BASE_URL").unwrap_or("https://api.officekit.app");
    let production_url = base_url == "https://api.officekit.app";
    let dev_loopback = cfg!(debug_assertions)
        && base_url
            .strip_prefix("http://127.0.0.1:")
            .is_some_and(|port| !port.is_empty() && port.bytes().all(|byte| byte.is_ascii_digit()));
    if production_url || dev_loopback {
        Ok(base_url)
    } else {
        Err(LicenseClientError::Unavailable)
    }
}

pub struct HttpActivationApi {
    base_url: String,
    agent: ureq::Agent,
}

impl HttpActivationApi {
    pub fn new(base_url: &str) -> Result<Self, LicenseClientError> {
        let configured = configured_license_api_base_url()?;
        if base_url != configured {
            return Err(LicenseClientError::Unavailable);
        }
        let agent = ureq::Agent::config_builder()
            .timeout_global(Some(Duration::from_secs(12)))
            .build()
            .into();
        Ok(Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            agent,
        })
    }

    fn post_json<Request, Response>(
        &self,
        path: &'static str,
        request: &Request,
    ) -> Result<Response, LicenseClientError>
    where
        Request: Serialize,
        Response: DeserializeOwned,
    {
        let url = format!("{}{path}", self.base_url);
        let response = self
            .agent
            .post(&url)
            .send_json(request)
            .map_err(map_http_error)?;
        if response
            .headers()
            .get("content-length")
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<usize>().ok())
            .is_some_and(|length| length > MAX_LICENSE_RESPONSE_BYTES)
        {
            return Err(LicenseClientError::InvalidResponse);
        }
        let mut bytes = Vec::with_capacity(1024);
        response
            .into_body()
            .into_reader()
            .take((MAX_LICENSE_RESPONSE_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|_| LicenseClientError::Unavailable)?;
        if bytes.is_empty() || bytes.len() > MAX_LICENSE_RESPONSE_BYTES {
            return Err(LicenseClientError::InvalidResponse);
        }
        serde_json::from_slice(&bytes).map_err(|_| LicenseClientError::InvalidResponse)
    }
}

impl ActivationApi for HttpActivationApi {
    fn create_challenge(
        &mut self,
        request: ActivationChallengeRequest,
    ) -> Result<ActivationChallengeResponse, LicenseClientError> {
        self.post_json("/v1/license-activation-challenges", &request)
    }

    fn activate(
        &mut self,
        signature: ActivationSignature,
    ) -> Result<ActivationResponse, LicenseClientError> {
        self.post_json("/v1/license-activations", &signature)
    }
}

impl DeactivationApi for HttpActivationApi {
    fn deactivate(
        &mut self,
        email: &str,
        license_key: &str,
        activation_id: &str,
    ) -> Result<(), LicenseClientError> {
        // The id is a 22-character base64url value from a verified receipt; refuse anything else
        // rather than build a path from it.
        if activation_id.len() != 22
            || !activation_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
        {
            return Err(LicenseClientError::InvalidResponse);
        }
        let url = format!("{}/v1/license-activations/{activation_id}", self.base_url);
        match self
            .agent
            .delete(&url)
            .header("Authorization", format!("Bearer {license_key}"))
            .header("X-OfficeKit-Email", email)
            .call()
        {
            Ok(_) => Ok(()),
            // The server no longer knows this activation: the seat is already free.
            Err(ureq::Error::StatusCode(404)) => Ok(()),
            Err(error) => Err(map_http_error(error)),
        }
    }
}

fn map_http_error(error: ureq::Error) -> LicenseClientError {
    match error {
        ureq::Error::StatusCode(409) => LicenseClientError::DeviceLimit,
        ureq::Error::StatusCode(400 | 422) => LicenseClientError::InvalidCredential,
        _ => LicenseClientError::Unavailable,
    }
}

#[cfg(target_os = "macos")]
pub struct MacKeychainLicenseStore;

#[cfg(target_os = "macos")]
impl MacKeychainLicenseStore {
    pub fn new() -> Self {
        Self
    }

    fn keychain_options(
        account: &str,
    ) -> Result<security_framework::passwords::PasswordOptions, LicenseClientError> {
        use security_framework::passwords::PasswordOptions;
        // A SecAccessControl object forces the data-protection keychain, which needs the restricted
        // keychain-access-groups entitlement (a provisioning profile). Without it every write fails with
        // errSecMissingEntitlement (-34018), so activation could never store the device key or receipt in
        // an ad-hoc or Developer ID build. A plain generic password in the login keychain needs no
        // entitlement, is only readable by this app without a user prompt, and is never synchronised.
        let mut options = PasswordOptions::new_generic_password(LICENSE_KEYCHAIN_SERVICE, account);
        options.set_access_synchronized(Some(false));
        Ok(options)
    }

    fn read_item(account: &str) -> Result<Option<Vec<u8>>, LicenseClientError> {
        use security_framework::passwords::{generic_password, PasswordOptions};
        let mut options = PasswordOptions::new_generic_password(LICENSE_KEYCHAIN_SERVICE, account);
        options.set_access_synchronized(Some(false));
        match generic_password(options) {
            Ok(value) => Ok(Some(value)),
            Err(error) if error.code() == -25300 => Ok(None),
            Err(_) => Err(LicenseClientError::SecureStorage),
        }
    }

    fn write_item(account: &str, value: &[u8]) -> Result<(), LicenseClientError> {
        security_framework::passwords::set_generic_password_options(
            value,
            Self::keychain_options(account)?,
        )
        .map_err(|_| LicenseClientError::SecureStorage)
    }

    fn load_or_create_private_key(&self) -> Result<SigningKey, LicenseClientError> {
        if let Some(bytes) = Self::read_item(DEVICE_KEYCHAIN_ACCOUNT)? {
            return SigningKey::from_pkcs8_der(&bytes)
                .map_err(|_| LicenseClientError::SecureStorage);
        }
        let key = SigningKey::generate();
        let document = key
            .to_pkcs8_der()
            .map_err(|_| LicenseClientError::SecureStorage)?;
        Self::write_item(DEVICE_KEYCHAIN_ACCOUNT, document.as_bytes())?;
        Ok(key)
    }
}

#[cfg(target_os = "macos")]
impl DeviceKey for MacKeychainLicenseStore {
    fn public_key_der(&self) -> Result<Vec<u8>, LicenseClientError> {
        let key = self.load_or_create_private_key()?;
        key.verifying_key()
            .to_public_key_der()
            .map(|der| der.as_bytes().to_vec())
            .map_err(|_| LicenseClientError::SecureStorage)
    }

    fn sign_challenge(&self, nonce: &[u8]) -> Result<Vec<u8>, LicenseClientError> {
        use p256::ecdsa::signature::Signer;
        if nonce.len() != 32 {
            return Err(LicenseClientError::InvalidInput);
        }
        let key = self.load_or_create_private_key()?;
        let signature: p256::ecdsa::Signature = key.sign(nonce);
        Ok(signature.to_der().as_bytes().to_vec())
    }
}

#[cfg(target_os = "macos")]
impl ReceiptStore for MacKeychainLicenseStore {
    fn load(&self) -> Result<Option<StoredLicenseReceipt>, LicenseClientError> {
        let Some(bytes) = Self::read_item(RECEIPT_KEYCHAIN_ACCOUNT)? else {
            return Ok(None);
        };
        if bytes.len() > MAX_LICENSE_RESPONSE_BYTES {
            return Err(LicenseClientError::SecureStorage);
        }
        serde_json::from_slice(&bytes)
            .map(Some)
            .map_err(|_| LicenseClientError::SecureStorage)
    }

    fn save(&mut self, receipt: StoredLicenseReceipt) -> Result<(), LicenseClientError> {
        let bytes = serde_json::to_vec(&receipt).map_err(|_| LicenseClientError::SecureStorage)?;
        if bytes.len() > MAX_LICENSE_RESPONSE_BYTES {
            return Err(LicenseClientError::InvalidResponse);
        }
        Self::write_item(RECEIPT_KEYCHAIN_ACCOUNT, &bytes)
    }
}

#[cfg(target_os = "macos")]
impl ReceiptClear for MacKeychainLicenseStore {
    fn clear(&mut self) -> Result<(), LicenseClientError> {
        use security_framework::passwords::{delete_generic_password_options, PasswordOptions};
        let mut options = PasswordOptions::new_generic_password(
            LICENSE_KEYCHAIN_SERVICE,
            RECEIPT_KEYCHAIN_ACCOUNT,
        );
        options.set_access_synchronized(Some(false));
        match delete_generic_password_options(options) {
            Ok(()) => Ok(()),
            // Already gone is the state the caller wanted.
            Err(error) if error.code() == -25300 => Ok(()),
            Err(_) => Err(LicenseClientError::SecureStorage),
        }
    }
}

#[cfg(not(target_os = "macos"))]
pub struct MacKeychainLicenseStore;

#[cfg(not(target_os = "macos"))]
impl MacKeychainLicenseStore {
    pub fn new() -> Self {
        Self
    }
}

#[cfg(not(target_os = "macos"))]
impl DeviceKey for MacKeychainLicenseStore {
    fn public_key_der(&self) -> Result<Vec<u8>, LicenseClientError> {
        Err(LicenseClientError::UnsupportedPlatform)
    }

    fn sign_challenge(&self, _nonce: &[u8]) -> Result<Vec<u8>, LicenseClientError> {
        Err(LicenseClientError::UnsupportedPlatform)
    }
}

#[cfg(not(target_os = "macos"))]
impl ReceiptStore for MacKeychainLicenseStore {
    fn load(&self) -> Result<Option<StoredLicenseReceipt>, LicenseClientError> {
        Err(LicenseClientError::UnsupportedPlatform)
    }

    fn save(&mut self, _receipt: StoredLicenseReceipt) -> Result<(), LicenseClientError> {
        Err(LicenseClientError::UnsupportedPlatform)
    }
}

#[cfg(not(target_os = "macos"))]
impl ReceiptClear for MacKeychainLicenseStore {
    fn clear(&mut self) -> Result<(), LicenseClientError> {
        Err(LicenseClientError::UnsupportedPlatform)
    }
}

#[cfg(test)]
mod tests {
    use super::{
        activate_license, ActivationApi, ActivationChallengeRequest, ActivationChallengeResponse,
        ActivationResponse, ActivationSignature, DeviceKey, LicenseClientError, ReceiptStore,
        StoredLicenseReceipt,
    };
    use base64::engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD};
    use base64::Engine;
    use jsonwebtoken::{encode, Algorithm, EncodingKey, Header};
    use serde_json::{json, Value};
    use sha2::Digest;
    use std::collections::BTreeMap;

    const NOW: u64 = 1_800_000_000;
    const LICENSE_KEY: &str = "OK1.reference.secret";
    const EMAIL: &str = "buyer@example.com";
    const EMAIL_SHA256: &str = "b4c9a289323b21a01c3e940f150eb9b8c542587f1abfd8f0e1cc1ffc5e475514";
    const DEVICE_PUBLIC_KEY_DER: &[u8] = b"test-only device SubjectPublicKeyInfo";
    use crate::test_keys::{PRIVATE_KEY, PUBLIC_KEY};
    const ACTIVATION_ID: &str = "CQkJCQkJCQkJCQkJCQkJCQ";
    const CHALLENGE_ID: &str = "CgoKCgoKCgoKCgoKCgoKCg";

    #[derive(Default)]
    struct FakeApi {
        challenge_request: Option<ActivationChallengeRequest>,
        signature: Option<ActivationSignature>,
        challenge_calls: usize,
        activation_calls: usize,
        response: Option<ActivationResponse>,
        challenge_error: Option<LicenseClientError>,
    }

    impl ActivationApi for FakeApi {
        fn create_challenge(
            &mut self,
            request: ActivationChallengeRequest,
        ) -> Result<ActivationChallengeResponse, LicenseClientError> {
            self.challenge_calls += 1;
            self.challenge_request = Some(request);
            if let Some(error) = self.challenge_error {
                return Err(error);
            }
            Ok(ActivationChallengeResponse {
                challenge_id: CHALLENGE_ID.to_string(),
                nonce: URL_SAFE_NO_PAD.encode([4_u8; 32]),
                expires_at_epoch: NOW + 300,
            })
        }

        fn activate(
            &mut self,
            signature: ActivationSignature,
        ) -> Result<ActivationResponse, LicenseClientError> {
            self.activation_calls += 1;
            self.signature = Some(signature);
            self.response.clone().ok_or(LicenseClientError::Unavailable)
        }
    }

    struct FakeDeviceKey;

    impl DeviceKey for FakeDeviceKey {
        fn public_key_der(&self) -> Result<Vec<u8>, LicenseClientError> {
            Ok(DEVICE_PUBLIC_KEY_DER.to_vec())
        }

        fn sign_challenge(&self, nonce: &[u8]) -> Result<Vec<u8>, LicenseClientError> {
            if nonce == [4_u8; 32] {
                Ok(b"test-only DER ECDSA signature".to_vec())
            } else {
                Err(LicenseClientError::InvalidResponse)
            }
        }
    }

    #[derive(Default)]
    struct FakeReceiptStore(Vec<StoredLicenseReceipt>);

    impl ReceiptStore for FakeReceiptStore {
        fn load(&self) -> Result<Option<StoredLicenseReceipt>, LicenseClientError> {
            Ok(self.0.last().cloned())
        }

        fn save(&mut self, receipt: StoredLicenseReceipt) -> Result<(), LicenseClientError> {
            self.0.push(receipt);
            Ok(())
        }
    }

    fn keyring() -> BTreeMap<String, String> {
        BTreeMap::from([("officekit-test-2026".to_string(), PUBLIC_KEY.to_string())])
    }

    fn valid_entitlement() -> String {
        let digest = sha2::Sha256::digest(DEVICE_PUBLIC_KEY_DER);
        let claims: Value = json!({
            "iss": "https://api.officekit.app",
            "aud": "officekit.desktop",
            "product": "officekit",
            "schema": "officekit.entitlement.v2",
            "license_id": URL_SAFE_NO_PAD.encode([7_u8; 16]),
            "activation_id": ACTIVATION_ID,
            "email_sha256": EMAIL_SHA256,
            "edition": "paid",
            "features": ["image.convert", "pdf.merge"],
            "device_key_sha256": URL_SAFE_NO_PAD.encode(digest),
            "iat": NOW - 60,
        });
        let key = EncodingKey::from_rsa_pem(PRIVATE_KEY.as_bytes()).expect("test key");
        let mut header = Header::new(Algorithm::RS256);
        header.kid = Some("officekit-test-2026".to_string());
        header.typ = Some("JWT".to_string());
        encode(&header, &claims, &key).expect("sign test receipt")
    }

    fn api_with_receipt(token: String) -> FakeApi {
        FakeApi {
            response: Some(ActivationResponse {
                activation_id: ACTIVATION_ID.to_string(),
                signed_entitlement: token,
                device_slots_used: 2,
                device_slots_allowed: 5,
            }),
            ..FakeApi::default()
        }
    }

    #[derive(Default)]
    struct FakeDeactivationApi {
        calls: Vec<(String, String, String)>,
        error: Option<LicenseClientError>,
    }

    impl super::DeactivationApi for FakeDeactivationApi {
        fn deactivate(
            &mut self,
            email: &str,
            license_key: &str,
            activation_id: &str,
        ) -> Result<(), LicenseClientError> {
            self.calls.push((
                email.to_string(),
                license_key.to_string(),
                activation_id.to_string(),
            ));
            self.error.map_or(Ok(()), Err)
        }
    }

    impl super::ReceiptClear for FakeReceiptStore {
        fn clear(&mut self) -> Result<(), LicenseClientError> {
            self.0.clear();
            Ok(())
        }
    }

    fn activated_store() -> FakeReceiptStore {
        let mut api = api_with_receipt(valid_entitlement());
        let mut storage = FakeReceiptStore::default();
        activate_license(
            EMAIL,
            LICENSE_KEY,
            "macos",
            "1.0.0",
            NOW,
            &keyring(),
            &mut api,
            &FakeDeviceKey,
            &mut storage,
        )
        .expect("activation should complete");
        storage
    }

    #[test]
    fn deactivation_tells_the_server_first_then_removes_the_receipt() {
        let mut storage = activated_store();
        let mut api = FakeDeactivationApi::default();
        let done = super::deactivate_license(
            EMAIL,
            LICENSE_KEY,
            NOW,
            &keyring(),
            &mut api,
            &FakeDeviceKey,
            &mut storage,
        );
        assert_eq!(done, Ok(true));
        assert_eq!(
            api.calls,
            vec![(
                EMAIL.to_string(),
                LICENSE_KEY.to_string(),
                ACTIVATION_ID.to_string()
            )],
            "the id comes from the verified receipt, not from the caller"
        );
        assert!(storage.load().unwrap().is_none());
    }

    #[test]
    fn a_failed_server_call_leaves_the_receipt_so_the_seat_and_the_unlock_stay_in_step() {
        for error in [
            LicenseClientError::Unavailable,
            LicenseClientError::InvalidCredential,
        ] {
            let mut storage = activated_store();
            let mut api = FakeDeactivationApi {
                error: Some(error),
                ..FakeDeactivationApi::default()
            };
            let done = super::deactivate_license(
                EMAIL,
                LICENSE_KEY,
                NOW,
                &keyring(),
                &mut api,
                &FakeDeviceKey,
                &mut storage,
            );
            assert_eq!(done, Err(error));
            assert!(storage.load().unwrap().is_some(), "{error:?}");
        }
    }

    #[test]
    fn deactivation_with_no_receipt_or_bad_input_does_not_call_the_server() {
        let mut api = FakeDeactivationApi::default();
        let mut empty = FakeReceiptStore::default();
        assert_eq!(
            super::deactivate_license(
                EMAIL,
                LICENSE_KEY,
                NOW,
                &keyring(),
                &mut api,
                &FakeDeviceKey,
                &mut empty
            ),
            Ok(false)
        );
        let mut storage = activated_store();
        for (email, key) in [
            ("not-an-email", LICENSE_KEY),
            (EMAIL, ""),
            (EMAIL, " padded "),
        ] {
            assert_eq!(
                super::deactivate_license(
                    email,
                    key,
                    NOW,
                    &keyring(),
                    &mut api,
                    &FakeDeviceKey,
                    &mut storage
                ),
                Err(LicenseClientError::InvalidInput)
            );
        }
        assert!(api.calls.is_empty());
        assert!(storage.load().unwrap().is_some());
    }

    #[test]
    fn the_http_deactivation_refuses_a_malformed_activation_id() {
        use super::DeactivationApi;
        let mut api = super::HttpActivationApi {
            base_url: "https://api.officekit.app".to_string(),
            agent: ureq::Agent::new_with_defaults(),
        };
        for id in [
            "",
            "short",
            "has/slash/in/it/xxxxxx",
            "../../../etc/passwd/xx",
        ] {
            assert_eq!(
                api.deactivate(EMAIL, LICENSE_KEY, id),
                Err(LicenseClientError::InvalidResponse),
                "{id}"
            );
        }
    }

    #[test]
    fn challenge_expiry_tolerates_request_latency_but_not_a_long_lifetime_or_expiry() {
        let challenge = |expires_at_epoch: u64| ActivationChallengeResponse {
            challenge_id: URL_SAFE_NO_PAD.encode([1_u8; 16]),
            nonce: URL_SAFE_NO_PAD.encode([4_u8; 32]),
            expires_at_epoch,
        };
        // The exact lifetime, and a lifetime a second or a minute past it (slow request, small skew).
        for expires in [NOW + 300, NOW + 301, NOW + 360] {
            assert!(
                super::validate_challenge(challenge(expires), NOW).is_ok(),
                "{expires}"
            );
        }
        // Beyond the allowance, already expired, and expiring right now are all rejected.
        for expires in [NOW + 361, NOW, NOW - 1] {
            assert!(
                matches!(
                    super::validate_challenge(challenge(expires), NOW),
                    Err(LicenseClientError::InvalidResponse)
                ),
                "{expires}"
            );
        }
    }

    #[test]
    fn activation_proves_device_then_verifies_and_persists_signed_receipt() {
        let mut api = api_with_receipt(valid_entitlement());
        let mut storage = FakeReceiptStore::default();
        let status = activate_license(
            EMAIL,
            LICENSE_KEY,
            "macos",
            "1.0.0",
            NOW,
            &keyring(),
            &mut api,
            &FakeDeviceKey,
            &mut storage,
        )
        .expect("activation should complete");

        assert_eq!(api.challenge_calls, 1);
        assert_eq!(api.activation_calls, 1);
        let request = api.challenge_request.expect("challenge request");
        assert_eq!(request.email, EMAIL);
        assert_eq!(request.license_key, LICENSE_KEY);
        assert_eq!(
            request.device_public_key,
            STANDARD.encode(DEVICE_PUBLIC_KEY_DER)
        );
        assert_eq!(request.platform, "macos");
        assert_eq!(request.app_version, "1.0.0");
        let proof = api.signature.expect("proof");
        assert_eq!(proof.email, EMAIL);
        assert_eq!(proof.license_key, LICENSE_KEY);
        assert_eq!(proof.challenge_id, CHALLENGE_ID);
        assert_eq!(
            proof.signature,
            URL_SAFE_NO_PAD.encode(b"test-only DER ECDSA signature")
        );
        assert_eq!(status.activation_id, ACTIVATION_ID);
        assert_eq!(status.device_slots_used, 2);
        assert_eq!(status.device_slots_allowed, 5);
        assert_eq!(storage.0.len(), 1);
        assert_eq!(storage.0[0].signed_entitlement, valid_entitlement());
    }

    #[test]
    fn payloads_serialize_the_email_field_and_receipt_never_contains_it() {
        let mut api = api_with_receipt(valid_entitlement());
        let mut storage = FakeReceiptStore::default();
        activate_license(
            EMAIL,
            LICENSE_KEY,
            "macos",
            "1.0.0",
            NOW,
            &keyring(),
            &mut api,
            &FakeDeviceKey,
            &mut storage,
        )
        .expect("activation should complete");

        let challenge = serde_json::to_value(api.challenge_request.as_ref().unwrap()).unwrap();
        let proof = serde_json::to_value(api.signature.as_ref().unwrap()).unwrap();
        assert_eq!(challenge["email"], EMAIL);
        assert_eq!(proof["email"], EMAIL);
        let stored = serde_json::to_string(&storage.0[0]).unwrap();
        assert!(!stored.contains(EMAIL));
        assert!(!stored.contains("email\""));
    }

    #[test]
    fn malformed_email_fails_before_network_without_echoing_it() {
        let long_email = format!("{}@example.com", "a".repeat(250));
        let invalid = [
            "",
            "a@b",
            " buyer@example.com",
            "buyer@example.com ",
            "buyer@@example.com",
            "buyer@example@com",
            "buyerexample.com",
            "@example.com",
            "buyer@",
            "buyer@examplecom",
            "bu\nyer@example.com",
            "buyer@exam\u{7f}ple.com",
            "buyer@example\u{0}.com",
            long_email.as_str(),
        ];
        for email in invalid {
            let mut api = FakeApi::default();
            let mut storage = FakeReceiptStore::default();
            let error = activate_license(
                email,
                LICENSE_KEY,
                "macos",
                "1.0.0",
                NOW,
                &keyring(),
                &mut api,
                &FakeDeviceKey,
                &mut storage,
            )
            .expect_err("invalid email");
            assert_eq!(
                error,
                LicenseClientError::InvalidInput,
                "accepted {email:?}"
            );
            assert!(!error.public_message().contains("example"));
            assert_eq!(api.challenge_calls, 0);
            assert!(storage.0.is_empty());
        }
    }

    #[test]
    fn email_length_boundaries_accept_254_and_reject_255_bytes() {
        let local = "a".repeat(254 - "@b.co".len());
        let longest = format!("{local}@b.co");
        assert_eq!(longest.len(), 254);
        let too_long = format!("a{longest}");
        assert_eq!(too_long.len(), 255);
        for (email, ok) in [
            (longest.as_str(), true),
            (too_long.as_str(), false),
            ("a@b.c", true),
        ] {
            let mut api = api_with_receipt(valid_entitlement());
            let mut storage = FakeReceiptStore::default();
            let result = activate_license(
                email,
                LICENSE_KEY,
                "macos",
                "1.0.0",
                NOW,
                &keyring(),
                &mut api,
                &FakeDeviceKey,
                &mut storage,
            );
            assert_eq!(result.is_ok(), ok, "{email}");
        }
    }

    #[test]
    fn invalid_credential_message_is_one_exact_sentence_and_http_400_422_map_to_it() {
        assert_eq!(
            LicenseClientError::InvalidCredential.public_message(),
            "The email or license key is not valid. Check both and try again."
        );
        for status in [400_u16, 422] {
            assert_eq!(
                super::map_http_error(ureq::Error::StatusCode(status)),
                LicenseClientError::InvalidCredential,
                "status {status}"
            );
        }
        assert_eq!(
            super::map_http_error(ureq::Error::StatusCode(409)),
            LicenseClientError::DeviceLimit
        );
        assert_eq!(
            super::map_http_error(ureq::Error::StatusCode(500)),
            LicenseClientError::Unavailable
        );
    }

    #[test]
    fn rejected_credentials_never_surface_the_email_or_key() {
        let email = "buyer.secret@example.com";
        let mut api = FakeApi::default();
        let mut storage = FakeReceiptStore::default();
        api.challenge_error = Some(LicenseClientError::InvalidCredential);
        let error = activate_license(
            email,
            LICENSE_KEY,
            "macos",
            "1.0.0",
            NOW,
            &keyring(),
            &mut api,
            &FakeDeviceKey,
            &mut storage,
        )
        .expect_err("credential rejected");
        assert_eq!(error, LicenseClientError::InvalidCredential);
        for text in [error.public_message().to_string(), format!("{error:?}")] {
            assert!(!text.contains(email) && !text.contains("buyer.secret"));
            assert!(!text.contains(LICENSE_KEY));
        }
        assert!(storage.0.is_empty());
    }

    #[test]
    fn v1_entitlements_are_never_persisted() {
        let digest = sha2::Sha256::digest(DEVICE_PUBLIC_KEY_DER);
        let claims: Value = json!({
            "iss": "https://api.officekit.app", "aud": "officekit.desktop",
            "product": "officekit", "schema": "officekit.entitlement.v1",
            "license_id": URL_SAFE_NO_PAD.encode([7_u8; 16]),
            "activation_id": ACTIVATION_ID, "edition": "paid",
            "features": ["pdf.merge"],
            "device_key_sha256": URL_SAFE_NO_PAD.encode(digest), "iat": NOW - 60
        });
        let key = EncodingKey::from_rsa_pem(PRIVATE_KEY.as_bytes()).expect("test key");
        let mut header = Header::new(Algorithm::RS256);
        header.kid = Some("officekit-test-2026".to_string());
        header.typ = Some("JWT".to_string());
        let token = encode(&header, &claims, &key).expect("sign v1 receipt");
        let mut api = api_with_receipt(token);
        let mut storage = FakeReceiptStore::default();
        assert_eq!(
            activate_license(
                EMAIL,
                LICENSE_KEY,
                "macos",
                "1.0.0",
                NOW,
                &keyring(),
                &mut api,
                &FakeDeviceKey,
                &mut storage,
            ),
            Err(LicenseClientError::InvalidResponse)
        );
        assert!(storage.0.is_empty());
    }

    #[test]
    fn invalid_challenge_or_slot_metadata_never_saves_a_receipt() {
        let mut api = api_with_receipt(valid_entitlement());
        let storage = FakeReceiptStore::default();
        let mut challenge = api
            .create_challenge(ActivationChallengeRequest {
                email: EMAIL.to_string(),
                license_key: LICENSE_KEY.to_string(),
                device_public_key: STANDARD.encode(DEVICE_PUBLIC_KEY_DER),
                platform: "macos".to_string(),
                app_version: "1.0.0".to_string(),
            })
            .expect("fixture challenge");
        challenge.challenge_id = "not-a-canonical-id".to_string();
        assert_eq!(
            super::validate_challenge(challenge, NOW),
            Err(LicenseClientError::InvalidResponse)
        );
        assert!(storage.0.is_empty());

        for (used, allowed) in [(0, 5), (6, 5), (1, 0), (1, 10_001)] {
            let response = ActivationResponse {
                activation_id: ACTIVATION_ID.to_string(),
                signed_entitlement: valid_entitlement(),
                device_slots_used: used,
                device_slots_allowed: allowed,
            };
            assert_eq!(
                super::validate_activation_response(response),
                Err(LicenseClientError::InvalidResponse)
            );
        }
    }

    #[test]
    fn tampered_or_wrong_device_entitlement_is_never_persisted() {
        for token in [format!("{}.x", valid_entitlement()), {
            let digest = sha2::Sha256::digest(b"different device");
            let claims: Value = json!({
                "iss": "https://api.officekit.app", "aud": "officekit.desktop",
                "product": "officekit", "schema": "officekit.entitlement.v2",
                "license_id": URL_SAFE_NO_PAD.encode([7_u8; 16]),
                "activation_id": ACTIVATION_ID, "email_sha256": EMAIL_SHA256,
                "edition": "paid",
                "features": ["pdf.merge"],
                "device_key_sha256": URL_SAFE_NO_PAD.encode(digest), "iat": NOW - 60
            });
            let key = EncodingKey::from_rsa_pem(PRIVATE_KEY.as_bytes()).expect("test key");
            let mut header = Header::new(Algorithm::RS256);
            header.kid = Some("officekit-test-2026".to_string());
            header.typ = Some("JWT".to_string());
            encode(&header, &claims, &key).expect("sign wrong-device receipt")
        }] {
            let mut api = api_with_receipt(token);
            let mut storage = FakeReceiptStore::default();
            assert_eq!(
                activate_license(
                    EMAIL,
                    LICENSE_KEY,
                    "macos",
                    "1.0.0",
                    NOW,
                    &keyring(),
                    &mut api,
                    &FakeDeviceKey,
                    &mut storage,
                ),
                Err(LicenseClientError::InvalidResponse)
            );
            assert!(storage.0.is_empty());
        }
    }

    #[test]
    fn malformed_credentials_and_platform_metadata_fail_before_network() {
        let long_key = "x".repeat(513);
        for key in ["", " bad-key", "bad-key ", long_key.as_str()] {
            let mut api = FakeApi::default();
            let mut storage = FakeReceiptStore::default();
            assert_eq!(
                activate_license(
                    EMAIL,
                    key,
                    "macos",
                    "1.0.0",
                    NOW,
                    &keyring(),
                    &mut api,
                    &FakeDeviceKey,
                    &mut storage,
                ),
                Err(LicenseClientError::InvalidInput)
            );
            assert_eq!(api.challenge_calls, 0);
            assert!(storage.0.is_empty());
        }
    }

    #[test]
    fn activation_id_must_be_the_service_opaque_16_byte_identifier() {
        for activation_id in ["not-a-uuid", "550e8400-e29b-41d4-a716-446655440000", "AQ"] {
            let mut response = api_with_receipt(valid_entitlement()).response.unwrap();
            response.activation_id = activation_id.to_string();
            assert_eq!(
                super::validate_activation_response(response),
                Err(LicenseClientError::InvalidResponse)
            );
        }
    }

    #[test]
    fn absent_pinned_keys_fail_closed_before_network_access() {
        let mut api = FakeApi::default();
        let mut storage = FakeReceiptStore::default();
        assert_eq!(
            activate_license(
                EMAIL,
                LICENSE_KEY,
                "macos",
                "1.0.0",
                NOW,
                &BTreeMap::new(),
                &mut api,
                &FakeDeviceKey,
                &mut storage,
            ),
            Err(LicenseClientError::NoPinnedKeys)
        );
        assert_eq!(api.challenge_calls, 0);
        assert_eq!(api.activation_calls, 0);
        assert!(storage.0.is_empty());
    }

    #[test]
    fn pinned_keyring_is_bounded_and_rejects_invalid_entries() {
        assert!(super::parse_pinned_keyring("{}").unwrap().is_empty());
        let valid = format!(
            "{{\"release-2026\":{}}}",
            serde_json::to_string(&*PUBLIC_KEY).unwrap()
        );
        assert_eq!(super::parse_pinned_keyring(&valid).unwrap().len(), 1);
        for raw in [
            "not-json",
            "{\"\":\"-----BEGIN PUBLIC KEY-----\"}",
            "{\"release\":\"private key\"}",
            &" ".repeat(32 * 1024 + 1),
        ] {
            assert_eq!(
                super::parse_pinned_keyring(raw),
                Err(LicenseClientError::InvalidResponse)
            );
        }
    }

    #[test]
    fn cached_entitlement_is_verified_offline_against_the_current_device_key() {
        let mut storage = FakeReceiptStore(vec![StoredLicenseReceipt {
            signed_entitlement: valid_entitlement(),
            device_slots_used: 2,
            device_slots_allowed: 5,
            last_checked_epoch: NOW - 15,
        }]);
        let status = super::current_license_status(NOW, &keyring(), &FakeDeviceKey, &storage)
            .expect("valid local receipt")
            .expect("active offline license");
        assert!(status.offline_capable);
        assert_eq!(status.last_checked_epoch, NOW - 15);
        assert_eq!(status.activation_id, ACTIVATION_ID);

        storage.0[0].device_slots_used = 0;
        assert_eq!(
            super::current_license_status(NOW, &keyring(), &FakeDeviceKey, &storage),
            Err(LicenseClientError::InvalidResponse)
        );
    }
}
