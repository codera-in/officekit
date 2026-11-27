use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::sync::OnceLock;

const MAX_ENTITLEMENT_BYTES: usize = 8192;
const MAX_PUBLIC_KEY_PEM_BYTES: usize = 4096;
const MAX_DEVICE_PUBLIC_KEY_DER_BYTES: usize = 2048;
const MAX_FUTURE_ISSUED_AT_SKEW_SECONDS: u64 = 300;
const ISSUER: &str = "https://api.officekit.app";
const AUDIENCE: &str = "officekit.desktop";
const PRODUCT: &str = "officekit";
const SCHEMA: &str = "officekit.entitlement.v2";
const EMAIL_SHA256_HEX_BYTES: usize = 64;
const ENTITLEMENT_KID_PATTERN: &str =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-";
const FEATURE_PATTERN: &str = "abcdefghijklmnopqrstuvwxyz0123456789_.-";

static RUST_CRYPTO_PROVIDER_READY: OnceLock<bool> = OnceLock::new();

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LicenseVerificationError {
    Invalid,
    /// Genuine, device-bound and well formed, but past its `exp`.
    Expired,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifiedEntitlement {
    pub license_id: String,
    pub activation_id: String,
    pub edition: String,
    pub features: Vec<String>,
    pub issued_at: u64,
    pub expires_at: Option<u64>,
    pub device_key_sha256: String,
    pub email_sha256: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct StrictJoseHeader {
    alg: String,
    kid: String,
    typ: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct EntitlementClaims {
    iss: String,
    aud: String,
    product: String,
    schema: String,
    license_id: String,
    activation_id: String,
    email_sha256: String,
    edition: String,
    features: Vec<String>,
    device_key_sha256: String,
    iat: u64,
    #[serde(default, deserialize_with = "deserialize_expiration")]
    exp: Option<u64>,
}

fn deserialize_expiration<'de, D>(deserializer: D) -> Result<Option<u64>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    u64::deserialize(deserializer).map(Some)
}

fn ensure_crypto_provider() -> bool {
    *RUST_CRYPTO_PROVIDER_READY.get_or_init(|| {
        let provider = &jsonwebtoken::crypto::rust_crypto::DEFAULT_PROVIDER;
        match provider.install_default() {
            Ok(()) => true,
            Err(installed) => std::ptr::eq(installed, provider),
        }
    })
}

fn is_ascii_slug(value: &str, allowed: &str, first_must_be_letter: bool, max_bytes: usize) -> bool {
    if value.is_empty() || value.len() > max_bytes || !value.is_ascii() {
        return false;
    }
    let mut bytes = value.bytes();
    let first = bytes.next().unwrap_or_default();
    let first_valid = if first_must_be_letter {
        first.is_ascii_lowercase()
    } else {
        allowed.contains(first as char)
    };
    first_valid && bytes.all(|byte| allowed.contains(byte as char))
}

fn is_lowercase_sha256_hex(value: &str) -> bool {
    value.len() == EMAIL_SHA256_HEX_BYTES
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
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

fn strict_header(token: &str) -> Result<StrictJoseHeader, LicenseVerificationError> {
    let mut parts = token.split('.');
    let header_segment = parts.next().ok_or(LicenseVerificationError::Invalid)?;
    let payload_segment = parts.next().ok_or(LicenseVerificationError::Invalid)?;
    let signature_segment = parts.next().ok_or(LicenseVerificationError::Invalid)?;
    if parts.next().is_some()
        || header_segment.is_empty()
        || payload_segment.is_empty()
        || signature_segment.is_empty()
    {
        return Err(LicenseVerificationError::Invalid);
    }
    let header_bytes = URL_SAFE_NO_PAD
        .decode(header_segment)
        .map_err(|_| LicenseVerificationError::Invalid)?;
    let header: StrictJoseHeader =
        serde_json::from_slice(&header_bytes).map_err(|_| LicenseVerificationError::Invalid)?;
    if header.alg != "RS256"
        || header.typ != "JWT"
        || !is_ascii_slug(&header.kid, ENTITLEMENT_KID_PATTERN, false, 64)
    {
        return Err(LicenseVerificationError::Invalid);
    }
    Ok(header)
}

/// Verify a server-signed OfficeKit entitlement and bind it to this device's public key.
/// The caller must supply a build-pinned key ring; a token cannot supply its own trust key.
pub fn verify_entitlement(
    token: &str,
    pinned_public_keys: &BTreeMap<String, String>,
    device_public_key_der: &[u8],
    now_epoch: u64,
) -> Result<VerifiedEntitlement, LicenseVerificationError> {
    if token.len() > MAX_ENTITLEMENT_BYTES
        || token.is_empty()
        || device_public_key_der.is_empty()
        || device_public_key_der.len() > MAX_DEVICE_PUBLIC_KEY_DER_BYTES
    {
        return Err(LicenseVerificationError::Invalid);
    }
    let header = strict_header(token)?;
    let public_key_pem = pinned_public_keys
        .get(&header.kid)
        .filter(|pem| !pem.is_empty() && pem.len() <= MAX_PUBLIC_KEY_PEM_BYTES)
        .ok_or(LicenseVerificationError::Invalid)?;
    if !ensure_crypto_provider() {
        return Err(LicenseVerificationError::Invalid);
    }

    let key = DecodingKey::from_rsa_pem(public_key_pem.as_bytes())
        .map_err(|_| LicenseVerificationError::Invalid)?;
    let mut validation = Validation::new(Algorithm::RS256);
    validation.validate_exp = false;
    validation.validate_nbf = false;
    validation.validate_aud = false;
    validation.required_spec_claims.clear();
    let claims = decode::<EntitlementClaims>(token, &key, &validation)
        .map_err(|_| LicenseVerificationError::Invalid)?
        .claims;

    if claims.iss != ISSUER
        || claims.aud != AUDIENCE
        || claims.product != PRODUCT
        || claims.schema != SCHEMA
        || claims.edition != "paid"
        || claims.iat > now_epoch.saturating_add(MAX_FUTURE_ISSUED_AT_SKEW_SECONDS)
        || decode_canonical_base64url(&claims.license_id, 16).is_none()
        || decode_canonical_base64url(&claims.activation_id, 16).is_none()
        || decode_canonical_base64url(&claims.device_key_sha256, 32).is_none()
        || !is_lowercase_sha256_hex(&claims.email_sha256)
        || claims
            .exp
            .is_some_and(|expires_at| expires_at <= claims.iat)
        || claims.features.len() > 128
    {
        return Err(LicenseVerificationError::Invalid);
    }

    if !claims
        .features
        .iter()
        .all(|feature| is_ascii_slug(feature, FEATURE_PATTERN, true, 64))
        || claims.features.windows(2).any(|pair| pair[0] >= pair[1])
    {
        return Err(LicenseVerificationError::Invalid);
    }

    let expected_device_digest = URL_SAFE_NO_PAD.encode(Sha256::digest(device_public_key_der));
    if claims.device_key_sha256 != expected_device_digest {
        return Err(LicenseVerificationError::Invalid);
    }
    // Checked last so `Expired` is only ever reported for a token that is otherwise genuine,
    // signed for this device and well formed; the locked UI can then say "expired" honestly.
    if claims.exp.is_some_and(|expires_at| expires_at <= now_epoch) {
        return Err(LicenseVerificationError::Expired);
    }

    Ok(VerifiedEntitlement {
        license_id: claims.license_id,
        activation_id: claims.activation_id,
        edition: claims.edition,
        features: claims.features,
        issued_at: claims.iat,
        expires_at: claims.exp,
        device_key_sha256: claims.device_key_sha256,
        email_sha256: claims.email_sha256,
    })
}

#[cfg(test)]
mod tests {
    use super::{verify_entitlement, LicenseVerificationError, MAX_FUTURE_ISSUED_AT_SKEW_SECONDS};
    use base64::engine::general_purpose::URL_SAFE_NO_PAD;
    use base64::Engine;
    use jsonwebtoken::{encode, Algorithm, EncodingKey, Header};
    use serde_json::{json, Value};
    use sha2::Digest;
    use std::collections::BTreeMap;
    use std::sync::Once;

    const NOW: u64 = 1_800_000_000;
    const DEVICE_PUBLIC_KEY: &[u8] = b"test-only SubjectPublicKeyInfo bytes";
    const EMAIL_SHA256: &str = "b4c9a289323b21a01c3e940f150eb9b8c542587f1abfd8f0e1cc1ffc5e475514";
    use crate::test_keys::{PRIVATE_KEY, PUBLIC_KEY};
    static INSTALL_CRYPTO: Once = Once::new();

    fn install_crypto_provider() {
        INSTALL_CRYPTO.call_once(|| {
            let provider = &jsonwebtoken::crypto::rust_crypto::DEFAULT_PROVIDER;
            match provider.install_default() {
                Ok(()) => {}
                Err(installed) => assert!(
                    std::ptr::eq(installed, provider),
                    "a different JWT crypto provider is already installed"
                ),
            }
        });
    }

    fn valid_claims() -> Value {
        let device_digest = sha2::Sha256::digest(DEVICE_PUBLIC_KEY);
        json!({
            "iss": "https://api.officekit.app",
            "aud": "officekit.desktop",
            "product": "officekit",
            "schema": "officekit.entitlement.v2",
            "license_id": URL_SAFE_NO_PAD.encode([7_u8; 16]),
            "activation_id": URL_SAFE_NO_PAD.encode([9_u8; 16]),
            "email_sha256": EMAIL_SHA256,
            "edition": "paid",
            "features": ["image.convert", "pdf.merge"],
            "device_key_sha256": URL_SAFE_NO_PAD.encode(device_digest),
            "iat": NOW - 60,
            "exp": NOW + 3600,
        })
    }

    fn keyring() -> BTreeMap<String, String> {
        BTreeMap::from([("officekit-test-2026".to_string(), PUBLIC_KEY.to_string())])
    }

    fn signed_token(claims: &Value) -> String {
        install_crypto_provider();
        let mut header = Header::new(Algorithm::RS256);
        header.typ = Some("JWT".to_string());
        header.kid = Some("officekit-test-2026".to_string());
        encode(
            &header,
            claims,
            &EncodingKey::from_rsa_pem(PRIVATE_KEY.as_bytes()).expect("test RSA key"),
        )
        .expect("sign test entitlement")
    }

    fn verify(token: &str) -> Result<super::VerifiedEntitlement, LicenseVerificationError> {
        verify_entitlement(token, &keyring(), DEVICE_PUBLIC_KEY, NOW)
    }

    #[test]
    fn valid_device_bound_entitlement_is_verified() {
        let verified = verify(&signed_token(&valid_claims())).expect("valid entitlement");
        assert_eq!(verified.edition, "paid");
        assert_eq!(verified.features, ["image.convert", "pdf.merge"]);
        assert_eq!(verified.license_id, URL_SAFE_NO_PAD.encode([7_u8; 16]));
        assert_eq!(verified.activation_id, URL_SAFE_NO_PAD.encode([9_u8; 16]));
        assert_eq!(verified.expires_at, Some(NOW + 3600));
        assert_eq!(verified.email_sha256, EMAIL_SHA256);
    }

    #[test]
    fn v1_tokens_without_email_digest_fail_closed() {
        let mut claims = valid_claims();
        claims["schema"] = json!("officekit.entitlement.v1");
        claims
            .as_object_mut()
            .expect("object")
            .remove("email_sha256");
        assert_eq!(
            verify(&signed_token(&claims)),
            Err(LicenseVerificationError::Invalid)
        );
    }

    #[test]
    fn missing_or_malformed_email_digest_is_rejected() {
        let mut missing = valid_claims();
        missing
            .as_object_mut()
            .expect("object")
            .remove("email_sha256");
        assert_eq!(
            verify(&signed_token(&missing)),
            Err(LicenseVerificationError::Invalid)
        );

        let upper = EMAIL_SHA256.to_uppercase();
        for value in [
            json!(&EMAIL_SHA256[..63]),
            json!(format!("{EMAIL_SHA256}0")),
            json!(upper),
            json!(format!("{}g", &EMAIL_SHA256[..63])),
            json!(""),
            json!(null),
            json!(5),
        ] {
            let mut claims = valid_claims();
            claims["email_sha256"] = value.clone();
            assert_eq!(
                verify(&signed_token(&claims)),
                Err(LicenseVerificationError::Invalid),
                "accepted email_sha256 {value}"
            );
        }
    }

    #[test]
    fn perpetual_entitlement_without_expiration_is_allowed() {
        let mut claims = valid_claims();
        claims.as_object_mut().expect("object").remove("exp");
        let verified = verify(&signed_token(&claims)).expect("perpetual entitlement");
        assert_eq!(verified.expires_at, None);
    }

    #[test]
    fn signature_and_device_binding_must_both_match() {
        let token = signed_token(&valid_claims());
        let mut segments: Vec<&str> = token.split('.').collect();
        let mut signature = segments[2].as_bytes().to_vec();
        signature[0] = if signature[0] == b'A' { b'B' } else { b'A' };
        segments[2] = std::str::from_utf8(&signature).expect("ASCII base64url");
        let changed_signature = segments.join(".");
        assert_eq!(
            verify(&changed_signature),
            Err(LicenseVerificationError::Invalid)
        );
        assert_eq!(
            verify_entitlement(&token, &keyring(), b"copied to another device", NOW),
            Err(LicenseVerificationError::Invalid)
        );
        assert_eq!(
            verify_entitlement(&token, &keyring(), &vec![0; 2049], NOW),
            Err(LicenseVerificationError::Invalid)
        );
    }

    #[test]
    fn unknown_key_id_and_wrong_algorithm_are_rejected() {
        let token = signed_token(&valid_claims());
        let empty_keys = BTreeMap::new();
        assert_eq!(
            verify_entitlement(&token, &empty_keys, DEVICE_PUBLIC_KEY, NOW),
            Err(LicenseVerificationError::Invalid)
        );

        install_crypto_provider();
        let mut header = Header::new(Algorithm::HS256);
        header.kid = Some("officekit-test-2026".to_string());
        let wrong_algorithm = encode(
            &header,
            &valid_claims(),
            &EncodingKey::from_secret(PRIVATE_KEY.as_bytes()).expect("test secret"),
        )
        .expect("create wrong-algorithm test token");
        assert_eq!(
            verify(&wrong_algorithm),
            Err(LicenseVerificationError::Invalid)
        );
    }

    #[test]
    fn expired_and_future_issued_entitlements_are_rejected() {
        let mut expired = valid_claims();
        expired["exp"] = json!(NOW);
        assert_eq!(
            verify(&signed_token(&expired)),
            Err(LicenseVerificationError::Expired)
        );

        // Expiry is reported only for an otherwise fully valid token: a wrong-device or
        // wrong-signature token that has also lapsed stays plain Invalid.
        assert_eq!(
            verify_entitlement(&signed_token(&expired), &keyring(), b"another device", NOW),
            Err(LicenseVerificationError::Invalid)
        );

        let mut future = valid_claims();
        future["iat"] = json!(NOW + MAX_FUTURE_ISSUED_AT_SKEW_SECONDS + 1);
        future["exp"] = json!(NOW + MAX_FUTURE_ISSUED_AT_SKEW_SECONDS + 3601);
        assert_eq!(
            verify(&signed_token(&future)),
            Err(LicenseVerificationError::Invalid)
        );

        let mut slight_clock_skew = valid_claims();
        slight_clock_skew["iat"] = json!(NOW + 30);
        slight_clock_skew["exp"] = json!(NOW + 3600);
        assert!(verify(&signed_token(&slight_clock_skew)).is_ok());
    }

    #[test]
    fn malformed_identity_policy_features_and_extra_claims_fail_closed() {
        for (name, value) in [
            ("iss", json!("https://attacker.example")),
            ("aud", json!("another.product")),
            ("product", json!("other")),
            ("schema", json!("officekit.entitlement.v1")),
            ("schema", json!("officekit.entitlement.v3")),
            ("edition", json!("free")),
            ("license_id", json!("short")),
            (
                "license_id",
                json!(format!("{}=", URL_SAFE_NO_PAD.encode([7_u8; 16]))),
            ),
            ("activation_id", json!("short")),
            ("device_key_sha256", json!("not-a-thumbprint")),
            ("features", json!(["pdf.merge", "pdf.merge"])),
            ("features", json!(["invalid feature"])),
            (
                "features",
                json!((0..129).map(|_| "tool").collect::<Vec<_>>()),
            ),
            ("iat", json!(-1)),
            ("exp", json!(NOW - 61)),
            ("exp", Value::Null),
        ] {
            let mut claims = valid_claims();
            claims[name] = value;
            assert_eq!(
                verify(&signed_token(&claims)),
                Err(LicenseVerificationError::Invalid),
                "accepted malformed {name}"
            );
        }

        let mut claims = valid_claims();
        claims["untrusted"] = json!(true);
        assert_eq!(
            verify(&signed_token(&claims)),
            Err(LicenseVerificationError::Invalid)
        );
    }

    #[test]
    fn noncanonical_feature_order_is_rejected() {
        let mut claims = valid_claims();
        claims["features"] = json!(["pdf.merge", "image.convert"]);
        assert_eq!(
            verify(&signed_token(&claims)),
            Err(LicenseVerificationError::Invalid)
        );
    }

    #[test]
    fn malformed_oversized_and_non_compact_tokens_are_rejected() {
        for token in ["", "a.b", "a.b.c.d", "not.a.jwt"] {
            assert_eq!(verify(token), Err(LicenseVerificationError::Invalid));
        }
        assert_eq!(
            verify(&"a".repeat(8193)),
            Err(LicenseVerificationError::Invalid)
        );

        let token = signed_token(&valid_claims());
        let parts: Vec<&str> = token.split('.').collect();
        let mut header: Value =
            serde_json::from_slice(&URL_SAFE_NO_PAD.decode(parts[0]).expect("header base64"))
                .expect("header JSON");
        header["unexpected"] = json!("field");
        let forged_header = format!(
            "{}.{}.{}",
            URL_SAFE_NO_PAD.encode(serde_json::to_vec(&header).expect("serialize header")),
            parts[1],
            parts[2]
        );
        assert_eq!(
            verify(&forged_header),
            Err(LicenseVerificationError::Invalid)
        );
    }
}
