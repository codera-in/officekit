//! RSA key pair for the licence tests. It is generated once per test run, so no private key is committed.
use rsa::pkcs8::{EncodePrivateKey, EncodePublicKey, LineEnding};
use rsa::{Generate, PrivateKey};
use std::sync::LazyLock;

static KEY: LazyLock<PrivateKey> = LazyLock::new(PrivateKey::generate);

/// PKCS#8 PEM, the format the tests hand to `EncodingKey::from_rsa_pem`.
pub static PRIVATE_KEY: LazyLock<String> = LazyLock::new(|| {
    KEY.to_pkcs8_pem(LineEnding::LF)
        .expect("encode the test private key")
        .to_string()
});

/// SPKI PEM, the format the licence keyring stores.
pub static PUBLIC_KEY: LazyLock<String> = LazyLock::new(|| {
    KEY.to_public_key()
        .to_public_key_pem(LineEnding::LF)
        .expect("encode the test public key")
});
