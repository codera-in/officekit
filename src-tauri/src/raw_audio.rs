//! Opt-in troubleshooting copy of each dictation's untouched microphone audio.
//!
//! Off by default. Files stay on this Mac in a private folder, are deleted 24 hours after they
//! were written, are capped in total size, and are never read by support or crash reporting.
//! Only files this module wrote (`dictation-<unix seconds>-<n>.wav`) are ever listed or deleted.

use serde::Serialize;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

pub const RETENTION_SECONDS: u64 = 24 * 60 * 60;
pub const CAP_BYTES: u64 = 200 * 1024 * 1024;
const SAMPLE_RATE: u32 = 16_000;
const PREFIX: &str = "dictation-";

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Stats {
    pub count: usize,
    pub bytes: u64,
    /// When the oldest saved recording is deleted (unix seconds).
    pub oldest_expires_at: Option<u64>,
}

/// A 32-bit float, 16 kHz, mono WAV: the samples exactly as captured, playable anywhere.
pub fn wav_bytes(samples: &[f32]) -> Vec<u8> {
    let data_len = (samples.len() * 4) as u32;
    let mut bytes = Vec::with_capacity(44 + data_len as usize);
    bytes.extend_from_slice(b"RIFF");
    bytes.extend_from_slice(&(36 + data_len).to_le_bytes());
    bytes.extend_from_slice(b"WAVEfmt ");
    bytes.extend_from_slice(&16_u32.to_le_bytes());
    bytes.extend_from_slice(&3_u16.to_le_bytes()); // IEEE float
    bytes.extend_from_slice(&1_u16.to_le_bytes());
    bytes.extend_from_slice(&SAMPLE_RATE.to_le_bytes());
    bytes.extend_from_slice(&(SAMPLE_RATE * 4).to_le_bytes());
    bytes.extend_from_slice(&4_u16.to_le_bytes());
    bytes.extend_from_slice(&32_u16.to_le_bytes());
    bytes.extend_from_slice(b"data");
    bytes.extend_from_slice(&data_len.to_le_bytes());
    for sample in samples {
        bytes.extend_from_slice(&sample.to_le_bytes());
    }
    bytes
}

/// Save one recording and return when it will be deleted.
pub fn save(directory: &Path, samples: &[f32], now: u64) -> std::io::Result<u64> {
    create_private_directory(directory)?;
    let bytes = wav_bytes(samples);
    // Make room first: expired files go, then the oldest until this one fits under the cap.
    remove_until(directory, now, CAP_BYTES.saturating_sub(bytes.len() as u64));
    for counter in 0_u32.. {
        let path = directory.join(format!("{PREFIX}{now}-{counter}.wav"));
        match private_file_options().open(&path) {
            Ok(mut file) => {
                if let Err(error) = file.write_all(&bytes) {
                    drop(file);
                    let _ = fs::remove_file(&path);
                    return Err(error);
                }
                return Ok(now + RETENTION_SECONDS);
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error),
        }
    }
    unreachable!("the counter never runs out")
}

/// Delete expired recordings, then the oldest until the folder fits the cap.
pub fn sweep(directory: &Path, now: u64) -> usize {
    remove_until(directory, now, CAP_BYTES)
}

pub fn stats(directory: &Path) -> Stats {
    let files = recordings(directory);
    Stats {
        count: files.len(),
        bytes: files.iter().map(|file| file.size).sum(),
        oldest_expires_at: files
            .iter()
            .map(|file| file.written_at + RETENTION_SECONDS)
            .min(),
    }
}

/// Delete every recording this module wrote.
pub fn clear(directory: &Path) -> usize {
    recordings(directory)
        .into_iter()
        .filter(|file| fs::remove_file(&file.path).is_ok())
        .count()
}

struct Recording {
    written_at: u64,
    path: PathBuf,
    size: u64,
}

/// Recordings this module wrote, oldest first. Any other file in the folder is not listed.
fn recordings(directory: &Path) -> Vec<Recording> {
    let Ok(entries) = fs::read_dir(directory) else {
        return Vec::new();
    };
    let mut files: Vec<Recording> = entries
        .flatten()
        .filter_map(|entry| {
            let name = entry.file_name().into_string().ok()?;
            let stem = name.strip_prefix(PREFIX)?.strip_suffix(".wav")?;
            let (seconds, counter) = stem.split_once('-')?;
            counter.parse::<u32>().ok()?;
            let metadata = entry
                .metadata()
                .ok()
                .filter(|metadata| metadata.is_file())?;
            Some(Recording {
                written_at: seconds.parse().ok()?,
                path: entry.path(),
                size: metadata.len(),
            })
        })
        .collect();
    files
        .sort_by(|left, right| (left.written_at, &left.path).cmp(&(right.written_at, &right.path)));
    files
}

/// Delete recordings that are 24 hours old, then the oldest until the total is within `budget`.
fn remove_until(directory: &Path, now: u64, budget: u64) -> usize {
    let mut files = recordings(directory);
    let mut removed = 0;
    let mut total: u64 = files.iter().map(|file| file.size).sum();
    files.retain(|file| {
        if now.saturating_sub(file.written_at) >= RETENTION_SECONDS
            && fs::remove_file(&file.path).is_ok()
        {
            total -= file.size;
            removed += 1;
            return false;
        }
        true
    });
    for file in files {
        if total <= budget {
            break;
        }
        if fs::remove_file(&file.path).is_ok() {
            total -= file.size;
            removed += 1;
        }
    }
    removed
}

fn private_file_options() -> fs::OpenOptions {
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options
}

fn create_private_directory(directory: &Path) -> std::io::Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(directory)?;
        fs::set_permissions(directory, fs::Permissions::from_mode(0o700))
    }
    #[cfg(not(unix))]
    {
        fs::create_dir_all(directory)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn folder(name: &str) -> PathBuf {
        let path =
            std::env::temp_dir().join(format!("officekit-raw-audio-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&path);
        path
    }

    const NOW: u64 = 1_800_000_000;

    #[test]
    fn a_saved_recording_is_a_playable_wav_with_the_samples_unchanged() {
        let directory = folder("wav");
        let samples = [0.0_f32, 0.5, -0.25, 1.0];
        let expires = save(&directory, &samples, NOW).expect("saved");
        assert_eq!(expires, NOW + RETENTION_SECONDS);
        let file = recordings(&directory).pop().expect("one file").path;
        let bytes = fs::read(file).unwrap();
        assert_eq!(&bytes[0..4], b"RIFF");
        assert_eq!(&bytes[8..16], b"WAVEfmt ");
        assert_eq!(
            u16::from_le_bytes([bytes[20], bytes[21]]),
            3,
            "float format"
        );
        assert_eq!(
            u32::from_le_bytes([bytes[24], bytes[25], bytes[26], bytes[27]]),
            16_000
        );
        assert_eq!(bytes.len(), 44 + samples.len() * 4);
        assert_eq!(&bytes[44..48], &0.0_f32.to_le_bytes());
        assert_eq!(&bytes[48..52], &0.5_f32.to_le_bytes());
        assert_eq!(bytes, wav_bytes(&samples));
        let _ = fs::remove_dir_all(directory);
    }

    #[cfg(unix)]
    #[test]
    fn the_folder_and_files_are_private_to_the_owner() {
        use std::os::unix::fs::PermissionsExt;
        let directory = folder("perms");
        save(&directory, &[0.1; 8], NOW).unwrap();
        let mode = |path: &Path| fs::metadata(path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode(&directory), 0o700);
        assert_eq!(mode(&recordings(&directory)[0].path), 0o600);
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn two_recordings_in_the_same_second_both_survive() {
        let directory = folder("same-second");
        save(&directory, &[0.1; 8], NOW).unwrap();
        save(&directory, &[0.2; 8], NOW).unwrap();
        assert_eq!(stats(&directory).count, 2);
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn recordings_older_than_24_hours_are_swept_and_newer_ones_stay() {
        let directory = folder("expiry");
        save(&directory, &[0.1; 8], NOW).unwrap();
        save(&directory, &[0.1; 8], NOW + 3_600).unwrap();
        assert_eq!(
            sweep(&directory, NOW + RETENTION_SECONDS - 1),
            0,
            "not yet 24 hours"
        );
        assert_eq!(
            sweep(&directory, NOW + RETENTION_SECONDS),
            1,
            "exactly 24 hours is expired"
        );
        assert_eq!(stats(&directory).count, 1);
        assert_eq!(
            stats(&directory).oldest_expires_at,
            Some(NOW + 3_600 + RETENTION_SECONDS)
        );
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn saving_sweeps_first_so_an_old_recording_never_outlives_the_next_dictation() {
        let directory = folder("save-sweeps");
        save(&directory, &[0.1; 8], NOW).unwrap();
        save(&directory, &[0.1; 8], NOW + RETENTION_SECONDS + 5).unwrap();
        assert_eq!(stats(&directory).count, 1);
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn the_size_cap_removes_the_oldest_recording_first() {
        let directory = folder("cap");
        let big = vec![0.1_f32; (CAP_BYTES / 4 / 2 + 1000) as usize];
        save(&directory, &big, NOW).unwrap();
        save(&directory, &big, NOW + 10).unwrap();
        let after = stats(&directory);
        assert_eq!(after.count, 1, "the second would not fit beside the first");
        assert_eq!(after.oldest_expires_at, Some(NOW + 10 + RETENTION_SECONDS));
        assert!(after.bytes <= CAP_BYTES);
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn clear_deletes_only_files_this_module_wrote() {
        let directory = folder("clear");
        save(&directory, &[0.1; 8], NOW).unwrap();
        save(&directory, &[0.1; 8], NOW + 1).unwrap();
        fs::write(directory.join("notes.txt"), b"mine").unwrap();
        fs::write(directory.join("dictation-abc.wav"), b"not ours").unwrap();
        assert_eq!(clear(&directory), 2);
        assert_eq!(stats(&directory), Stats::default());
        assert!(directory.join("notes.txt").exists());
        assert!(
            directory.join("dictation-abc.wav").exists(),
            "an unparseable name is left alone"
        );
        assert_eq!(sweep(&directory, NOW + 10 * RETENTION_SECONDS), 0);
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn a_missing_folder_is_empty_not_an_error() {
        let directory = folder("missing");
        assert_eq!(stats(&directory), Stats::default());
        assert_eq!(clear(&directory), 0);
        assert_eq!(sweep(&directory, NOW), 0);
    }

    #[test]
    fn stats_serialise_with_the_names_the_settings_page_reads() {
        let json = serde_json::to_value(Stats {
            count: 3,
            bytes: 4_100_000,
            oldest_expires_at: Some(9),
        })
        .unwrap();
        assert_eq!(json["count"], 3);
        assert_eq!(json["bytes"], 4_100_000);
        assert_eq!(json["oldestExpiresAt"], 9);
    }
}
