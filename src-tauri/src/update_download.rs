//! In-app download of a new OfficeKit installer.
//!
//! The update dialog shows the progress and, when the download finishes, offers to open the DMG. Nothing
//! here replaces the running app. The download is trusted only if its SHA-256 matches the checksum in the
//! update manifest (which the local API read from officekit.app over HTTPS), so a file from a redirect
//! target that does not match is deleted, never opened.

use serde::Serialize;
use sha2::{Digest, Sha256};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

/// Hosts the download may start at or be redirected through: the update link on officekit.app and the
/// GitHub release assets it redirects to.
const ALLOWED_HOSTS: [&str; 4] = [
    "officekit.app",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
];
/// Largest installer the app will download (the shipped DMG is about 250 MB).
pub const MAX_INSTALLER_BYTES: u64 = 1_500_000_000;
const MAX_REDIRECTS: usize = 5;
const CHUNK_BYTES: usize = 64 * 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UpdateError {
    InvalidRequest(&'static str),
    Busy,
    Cancelled,
    Network,
    SizeMismatch,
    ChecksumMismatch,
    Disk,
}

impl UpdateError {
    /// A short, user-facing reason. Never contains a path or a URL.
    pub fn message(&self) -> &'static str {
        match self {
            UpdateError::InvalidRequest(reason) => reason,
            UpdateError::Busy => "A download is already running.",
            UpdateError::Cancelled => "The download was cancelled.",
            UpdateError::Network => "The connection dropped before the download finished.",
            UpdateError::SizeMismatch => "The downloaded file was not the expected size.",
            UpdateError::ChecksumMismatch => "The downloaded file did not match its checksum.",
            UpdateError::Disk => "OfficeKit could not save the installer to the Downloads folder.",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpdateRequest {
    pub version: String,
    pub url: String,
    pub sha256: String,
    pub size: u64,
}

/// `vMAJOR.MINOR.PATCH` without the `v`, each part at most nine digits.
fn valid_version(version: &str) -> bool {
    let parts: Vec<&str> = version.split('.').collect();
    parts.len() == 3
        && parts.iter().all(|part| {
            !part.is_empty()
                && part.len() <= 9
                && part.bytes().all(|byte| byte.is_ascii_digit())
                && (part.len() == 1 || !part.starts_with('0'))
        })
}

/// An `https` URL, no credentials or fragment, default port, on an allowed host.
pub fn is_allowed_https_url(url: &str) -> bool {
    let Some(rest) = url.strip_prefix("https://") else {
        return false;
    };
    if url.len() > 2048 || url.contains('#') || url.bytes().any(|byte| byte.is_ascii_control()) {
        return false;
    }
    let authority = rest.split(['/', '?']).next().unwrap_or("");
    if authority.is_empty() || authority.contains('@') || authority.contains(':') {
        return false;
    }
    ALLOWED_HOSTS.contains(&authority)
}

pub fn validate_request(
    version: &str,
    url: &str,
    sha256: &str,
    size: u64,
) -> Result<UpdateRequest, UpdateError> {
    if !valid_version(version) {
        return Err(UpdateError::InvalidRequest(
            "The update version is invalid.",
        ));
    }
    if !is_allowed_https_url(url) {
        return Err(UpdateError::InvalidRequest(
            "The update link is not allowed.",
        ));
    }
    if sha256.len() != 64 || !sha256.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(UpdateError::InvalidRequest(
            "The update checksum is invalid.",
        ));
    }
    if size == 0 || size > MAX_INSTALLER_BYTES {
        return Err(UpdateError::InvalidRequest("The update size is invalid."));
    }
    Ok(UpdateRequest {
        version: version.to_string(),
        url: url.to_string(),
        sha256: sha256.to_ascii_lowercase(),
        size,
    })
}

pub fn installer_file_name(version: &str) -> String {
    format!("OfficeKit_{version}_aarch64.dmg")
}

/// Resolve a `Location` header against the current URL. Only absolute https URLs and root-relative paths
/// are followed, and the result must be on an allowed host.
pub fn next_hop(current: &str, location: &str) -> Result<String, UpdateError> {
    let target = if location.starts_with("https://") {
        location.to_string()
    } else if location.starts_with('/') && !location.starts_with("//") {
        let rest = current.strip_prefix("https://").unwrap_or("");
        let authority = rest.split('/').next().unwrap_or("");
        format!("https://{authority}{location}")
    } else {
        return Err(UpdateError::Network);
    };
    if is_allowed_https_url(&target) {
        Ok(target)
    } else {
        Err(UpdateError::Network)
    }
}

/// Copy `reader` to `writer`, hashing as it goes. Fails on a size other than `expected_size`, on a
/// checksum other than `expected_sha256` and when `cancelled` is set. `progress` gets the bytes so far.
pub fn stream_and_verify<R: Read, W: Write>(
    reader: &mut R,
    writer: &mut W,
    expected_size: u64,
    expected_sha256: &str,
    cancelled: &AtomicBool,
    mut progress: impl FnMut(u64),
) -> Result<(), UpdateError> {
    let mut hasher = Sha256::new();
    let mut received: u64 = 0;
    let mut buffer = vec![0u8; CHUNK_BYTES];
    loop {
        if cancelled.load(Ordering::SeqCst) {
            return Err(UpdateError::Cancelled);
        }
        let read = reader.read(&mut buffer).map_err(|_| UpdateError::Network)?;
        if read == 0 {
            break;
        }
        received += read as u64;
        if received > expected_size {
            return Err(UpdateError::SizeMismatch);
        }
        hasher.update(&buffer[..read]);
        writer
            .write_all(&buffer[..read])
            .map_err(|_| UpdateError::Disk)?;
        progress(received);
    }
    if received != expected_size {
        return Err(UpdateError::SizeMismatch);
    }
    writer.flush().map_err(|_| UpdateError::Disk)?;
    let digest = hasher.finalize();
    let mut actual = String::with_capacity(64);
    for byte in digest {
        actual.push_str(&format!("{byte:02x}"));
    }
    if actual.eq_ignore_ascii_case(expected_sha256) {
        Ok(())
    } else {
        Err(UpdateError::ChecksumMismatch)
    }
}

/// Fetch `url`, following at most [`MAX_REDIRECTS`] redirects that stay on allowed hosts, and return the
/// final response. `allowed` decides each hop (the app passes the host allow-list; tests pass a local one).
fn open_following_redirects(
    agent: &ureq::Agent,
    url: &str,
    allowed: &dyn Fn(&str) -> bool,
) -> Result<ureq::http::Response<ureq::Body>, UpdateError> {
    let mut current = url.to_string();
    for _ in 0..=MAX_REDIRECTS {
        if !allowed(&current) {
            return Err(UpdateError::Network);
        }
        let response = agent
            .get(&current)
            .call()
            .map_err(|_| UpdateError::Network)?;
        let status = response.status().as_u16();
        if (300..400).contains(&status) {
            let location = response
                .headers()
                .get("location")
                .and_then(|value| value.to_str().ok())
                .ok_or(UpdateError::Network)?
                .to_string();
            current = next_hop(&current, &location)?;
            continue;
        }
        if status == 200 {
            return Ok(response);
        }
        return Err(UpdateError::Network);
    }
    Err(UpdateError::Network)
}

fn build_agent() -> ureq::Agent {
    ureq::Agent::config_builder()
        .max_redirects(0)
        .max_redirects_will_error(false)
        .http_status_as_error(false)
        .timeout_connect(Some(Duration::from_secs(15)))
        .timeout_global(Some(Duration::from_secs(3600)))
        .build()
        .into()
}

/// Download, verify and move the installer into `directory`. The partial file is removed on any failure.
pub fn download_installer(
    request: &UpdateRequest,
    directory: &Path,
    cancelled: &AtomicBool,
    progress: impl FnMut(u64),
) -> Result<PathBuf, UpdateError> {
    download_with(
        &build_agent(),
        request,
        directory,
        cancelled,
        &is_allowed_https_url,
        progress,
    )
}

fn download_with(
    agent: &ureq::Agent,
    request: &UpdateRequest,
    directory: &Path,
    cancelled: &AtomicBool,
    allowed: &dyn Fn(&str) -> bool,
    progress: impl FnMut(u64),
) -> Result<PathBuf, UpdateError> {
    let final_path = directory.join(installer_file_name(&request.version));
    let partial_path = directory.join(format!("{}.part", installer_file_name(&request.version)));
    let response = open_following_redirects(agent, &request.url, allowed)?;
    let mut reader = response
        .into_body()
        .into_with_config()
        .limit(MAX_INSTALLER_BYTES + 1)
        .reader();
    let mut file = std::fs::File::create(&partial_path).map_err(|_| UpdateError::Disk)?;
    let outcome = stream_and_verify(
        &mut reader,
        &mut file,
        request.size,
        &request.sha256,
        cancelled,
        progress,
    );
    drop(file);
    match outcome {
        Ok(()) => std::fs::rename(&partial_path, &final_path)
            .map(|()| final_path)
            .map_err(|_| {
                let _ = std::fs::remove_file(&partial_path);
                UpdateError::Disk
            }),
        Err(error) => {
            let _ = std::fs::remove_file(&partial_path);
            Err(error)
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum UpdateStatus {
    Idle,
    Downloading {
        version: String,
        received: u64,
        total: u64,
    },
    Ready {
        version: String,
        file_name: String,
    },
    Failed {
        version: String,
        message: String,
    },
}

/// Download state shared between the worker thread and the commands. The installer path stays on the
/// Rust side; the webview only ever sees a file name.
pub struct UpdateDownloadState {
    status: Mutex<UpdateStatus>,
    path: Mutex<Option<PathBuf>>,
    cancelled: AtomicBool,
}

impl UpdateDownloadState {
    pub fn new() -> Self {
        Self {
            status: Mutex::new(UpdateStatus::Idle),
            path: Mutex::new(None),
            cancelled: AtomicBool::new(false),
        }
    }

    pub fn status(&self) -> UpdateStatus {
        self.status
            .lock()
            .map(|s| s.clone())
            .unwrap_or(UpdateStatus::Idle)
    }

    pub fn cancel_flag(&self) -> &AtomicBool {
        &self.cancelled
    }

    /// Reserve the single download slot. A finished or failed download may be replaced; a running one may not.
    pub fn begin(&self, request: &UpdateRequest) -> Result<(), UpdateError> {
        let mut status = self.status.lock().map_err(|_| UpdateError::Busy)?;
        if matches!(*status, UpdateStatus::Downloading { .. }) {
            return Err(UpdateError::Busy);
        }
        self.cancelled.store(false, Ordering::SeqCst);
        *status = UpdateStatus::Downloading {
            version: request.version.clone(),
            received: 0,
            total: request.size,
        };
        if let Ok(mut path) = self.path.lock() {
            *path = None;
        }
        Ok(())
    }

    pub fn progress(&self, version: &str, received: u64, total: u64) {
        if let Ok(mut status) = self.status.lock() {
            *status = UpdateStatus::Downloading {
                version: version.to_string(),
                received,
                total,
            };
        }
    }

    pub fn finish(&self, version: &str, result: Result<PathBuf, UpdateError>) {
        let (status, path) = match result {
            Ok(path) => (
                UpdateStatus::Ready {
                    version: version.to_string(),
                    file_name: path
                        .file_name()
                        .map(|name| name.to_string_lossy().into_owned())
                        .unwrap_or_default(),
                },
                Some(path),
            ),
            Err(UpdateError::Cancelled) => (UpdateStatus::Idle, None),
            Err(error) => (
                UpdateStatus::Failed {
                    version: version.to_string(),
                    message: error.message().to_string(),
                },
                None,
            ),
        };
        if let Ok(mut slot) = self.path.lock() {
            *slot = path;
        }
        if let Ok(mut current) = self.status.lock() {
            *current = status;
        }
    }

    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::SeqCst);
    }

    /// The finished installer, only while the state says it is ready.
    pub fn ready_path(&self) -> Option<PathBuf> {
        if !matches!(self.status(), UpdateStatus::Ready { .. }) {
            return None;
        }
        self.path.lock().ok().and_then(|path| path.clone())
    }
}

impl Default for UpdateDownloadState {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    const GOOD_SHA: &str = "827f4a0365e4656ab9997b3cf917195379ea43455767437dc20fea82d7374920";
    const GOOD_URL: &str = "https://officekit.app/get";

    fn sha256_hex(bytes: &[u8]) -> String {
        let mut text = String::new();
        for byte in Sha256::digest(bytes) {
            text.push_str(&format!("{byte:02x}"));
        }
        text
    }

    #[test]
    fn a_valid_request_is_accepted_and_the_checksum_is_lowercased() {
        let request = validate_request(
            "1.0.124",
            GOOD_URL,
            &GOOD_SHA.to_ascii_uppercase(),
            247_904_819,
        )
        .unwrap();
        assert_eq!(request.sha256, GOOD_SHA);
        assert_eq!(
            installer_file_name(&request.version),
            "OfficeKit_1.0.124_aarch64.dmg"
        );
    }

    #[test]
    fn bad_versions_are_rejected() {
        for version in [
            "",
            "1.0",
            "1.0.0.1",
            "v1.0.1",
            "1.0.01",
            "1.0.x",
            "../1.0.1",
            "1.0.1234567890",
        ] {
            assert!(
                validate_request(version, GOOD_URL, GOOD_SHA, 10).is_err(),
                "{version:?}"
            );
        }
    }

    #[test]
    fn only_https_urls_on_allowed_hosts_are_accepted() {
        for url in [
            "https://officekit.app/get",
            "https://github.com/codera-in/officekit/releases/download/v1.0.124/OfficeKit_1.0.124_aarch64.dmg",
            "https://objects.githubusercontent.com/x",
            "https://release-assets.githubusercontent.com/x?y=1",
        ] {
            assert!(is_allowed_https_url(url), "{url}");
        }
        for url in [
            "http://officekit.app/get",
            "https://evil.example/get",
            "https://officekit.app.evil.example/get",
            "https://evil.example/officekit.app",
            "https://user@officekit.app/get",
            "https://officekit.app:8443/get",
            "https://officekit.app/get#frag",
            "https://officekit.app\\@evil.example/",
            "ftp://officekit.app/get",
            "file:///etc/passwd",
            "https://",
            "",
        ] {
            assert!(!is_allowed_https_url(url), "{url}");
        }
    }

    #[test]
    fn checksums_and_sizes_are_validated() {
        for sha in ["", "abc", &"g".repeat(64), &"a".repeat(63), &"a".repeat(65)] {
            assert!(
                validate_request("1.0.1", GOOD_URL, sha, 10).is_err(),
                "{sha}"
            );
        }
        assert!(validate_request("1.0.1", GOOD_URL, GOOD_SHA, 0).is_err());
        assert!(validate_request("1.0.1", GOOD_URL, GOOD_SHA, MAX_INSTALLER_BYTES + 1).is_err());
        assert!(validate_request("1.0.1", GOOD_URL, GOOD_SHA, MAX_INSTALLER_BYTES).is_ok());
    }

    #[test]
    fn redirects_follow_only_allowed_https_targets() {
        assert_eq!(
            next_hop(GOOD_URL, "https://github.com/a/b").unwrap(),
            "https://github.com/a/b"
        );
        assert_eq!(
            next_hop(GOOD_URL, "/releases/x").unwrap(),
            "https://officekit.app/releases/x"
        );
        for location in [
            "http://github.com/a",
            "https://evil.example/a",
            "//evil.example/a",
            "relative/path",
            "",
            "https://github.com@evil.example/",
        ] {
            assert_eq!(
                next_hop(GOOD_URL, location),
                Err(UpdateError::Network),
                "{location}"
            );
        }
    }

    #[test]
    fn a_matching_stream_is_accepted_and_reports_progress() {
        let data = vec![7u8; 200_000];
        let mut seen = Vec::new();
        let mut output = Vec::new();
        stream_and_verify(
            &mut Cursor::new(&data),
            &mut output,
            data.len() as u64,
            &sha256_hex(&data),
            &AtomicBool::new(false),
            |received| seen.push(received),
        )
        .unwrap();
        assert_eq!(output, data);
        assert_eq!(*seen.last().unwrap(), data.len() as u64);
        assert!(seen.windows(2).all(|pair| pair[0] < pair[1]));
    }

    #[test]
    fn a_wrong_checksum_a_short_stream_and_a_long_stream_are_refused() {
        let data = vec![1u8; 1000];
        let run = |size: u64, sha: &str| {
            stream_and_verify(
                &mut Cursor::new(&data),
                &mut Vec::new(),
                size,
                sha,
                &AtomicBool::new(false),
                |_| {},
            )
        };
        assert_eq!(
            run(1000, &"0".repeat(64)),
            Err(UpdateError::ChecksumMismatch)
        );
        assert_eq!(
            run(1001, &sha256_hex(&data)),
            Err(UpdateError::SizeMismatch)
        );
        assert_eq!(run(999, &sha256_hex(&data)), Err(UpdateError::SizeMismatch));
    }

    #[test]
    fn cancelling_stops_the_stream() {
        let data = vec![1u8; 1000];
        let cancelled = AtomicBool::new(true);
        assert_eq!(
            stream_and_verify(
                &mut Cursor::new(&data),
                &mut Vec::new(),
                1000,
                &sha256_hex(&data),
                &cancelled,
                |_| {}
            ),
            Err(UpdateError::Cancelled)
        );
    }

    #[test]
    fn a_failing_reader_and_a_failing_writer_map_to_network_and_disk_errors() {
        struct BrokenReader;
        impl Read for BrokenReader {
            fn read(&mut self, _: &mut [u8]) -> std::io::Result<usize> {
                Err(std::io::Error::other("reset"))
            }
        }
        struct BrokenWriter;
        impl Write for BrokenWriter {
            fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
                Err(std::io::Error::other("full"))
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        let flag = AtomicBool::new(false);
        assert_eq!(
            stream_and_verify(
                &mut BrokenReader,
                &mut Vec::new(),
                10,
                GOOD_SHA,
                &flag,
                |_| {}
            ),
            Err(UpdateError::Network)
        );
        assert_eq!(
            stream_and_verify(
                &mut Cursor::new(vec![1u8; 10]),
                &mut BrokenWriter,
                10,
                GOOD_SHA,
                &flag,
                |_| {}
            ),
            Err(UpdateError::Disk)
        );
    }

    #[test]
    fn the_state_allows_one_download_at_a_time_and_hides_the_path() {
        let state = UpdateDownloadState::new();
        let request = validate_request("1.0.124", GOOD_URL, GOOD_SHA, 100).unwrap();
        assert_eq!(state.status(), UpdateStatus::Idle);
        state.begin(&request).unwrap();
        assert_eq!(state.begin(&request), Err(UpdateError::Busy));
        state.progress("1.0.124", 40, 100);
        assert_eq!(
            state.status(),
            UpdateStatus::Downloading {
                version: "1.0.124".into(),
                received: 40,
                total: 100
            }
        );
        assert!(state.ready_path().is_none());

        state.finish(
            "1.0.124",
            Ok(PathBuf::from(
                "/Users/x/Downloads/OfficeKit_1.0.124_aarch64.dmg",
            )),
        );
        assert_eq!(
            state.status(),
            UpdateStatus::Ready {
                version: "1.0.124".into(),
                file_name: "OfficeKit_1.0.124_aarch64.dmg".into()
            }
        );
        assert!(state.ready_path().is_some());
        let json = serde_json::to_string(&state.status()).unwrap();
        assert!(!json.contains("/Users/"), "{json}");

        // A finished download can be replaced by a new one.
        state.begin(&request).unwrap();
        assert!(state.ready_path().is_none());
    }

    #[test]
    fn a_failed_download_reports_a_plain_message_and_cancel_returns_to_idle() {
        let state = UpdateDownloadState::new();
        let request = validate_request("1.0.124", GOOD_URL, GOOD_SHA, 100).unwrap();
        state.begin(&request).unwrap();
        state.finish("1.0.124", Err(UpdateError::ChecksumMismatch));
        assert_eq!(
            state.status(),
            UpdateStatus::Failed {
                version: "1.0.124".into(),
                message: "The downloaded file did not match its checksum.".into()
            }
        );
        state.begin(&request).unwrap();
        state.cancel();
        assert!(state.cancel_flag().load(Ordering::SeqCst));
        state.finish("1.0.124", Err(UpdateError::Cancelled));
        assert_eq!(state.status(), UpdateStatus::Idle);
    }

    /// A one-shot local server for the redirect and download path.
    fn serve(responses: Vec<(String, Vec<u8>)>) -> (String, std::thread::JoinHandle<()>) {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let handle = std::thread::spawn(move || {
            for (head, body) in responses {
                let (mut stream, _) = listener.accept().unwrap();
                let mut request = [0u8; 2048];
                let _ = stream.read(&mut request);
                let _ = stream.write_all(head.as_bytes());
                let _ = stream.write_all(&body);
            }
        });
        (base, handle)
    }

    fn temp_directory(name: &str) -> PathBuf {
        let directory =
            std::env::temp_dir().join(format!("officekit-update-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&directory);
        std::fs::create_dir_all(&directory).unwrap();
        directory
    }

    #[test]
    fn a_download_over_a_local_server_is_saved_only_when_it_matches() {
        let data = vec![5u8; 120_000];
        let directory = temp_directory("local");
        for (checksum, expect_ok) in [(sha256_hex(&data), true), ("0".repeat(64), false)] {
            let (base, server) = serve(vec![(
                format!(
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    data.len()
                ),
                data.clone(),
            )]);
            let request = UpdateRequest {
                version: "1.0.124".into(),
                url: format!("{base}/file.dmg"),
                sha256: checksum,
                size: data.len() as u64,
            };
            let result = download_with(
                &build_agent(),
                &request,
                &directory,
                &AtomicBool::new(false),
                &|url: &str| url.starts_with("http://127.0.0.1"),
                |_| {},
            );
            server.join().ok();
            let final_path = directory.join(installer_file_name("1.0.124"));
            let partial = directory.join(format!("{}.part", installer_file_name("1.0.124")));
            assert!(!partial.exists(), "the partial file never survives");
            if expect_ok {
                assert_eq!(result.unwrap(), final_path);
                assert_eq!(std::fs::read(&final_path).unwrap(), data);
                std::fs::remove_file(&final_path).unwrap();
            } else {
                assert_eq!(result, Err(UpdateError::ChecksumMismatch));
                assert!(
                    !final_path.exists(),
                    "a file that fails its checksum is deleted"
                );
            }
        }
        std::fs::remove_dir_all(&directory).ok();
    }

    #[test]
    fn a_hop_to_a_host_that_is_not_allowed_is_refused_before_any_request() {
        let agent = build_agent();
        let result =
            open_following_redirects(&agent, "https://evil.example/x", &is_allowed_https_url);
        assert!(matches!(result, Err(UpdateError::Network)));
    }
}
