//! Records why OfficeKit panicked. A panic inside a macOS launch callback cannot unwind, so the
//! system crash report only shows `abort()`; this keeps the message and location.
//! Only the panic text and source location are written, never user data.

use std::io::Write;
use std::path::PathBuf;

const MAX_LOG_BYTES: u64 = 256 * 1024;

pub fn log_path() -> Option<PathBuf> {
    let home = std::env::var_os("HOME")?;
    Some(PathBuf::from(home).join("Library/Logs/app.officekit.desktop/panic.log"))
}

pub fn format_line(
    timestamp_secs: u64,
    thread: &str,
    location: Option<(&str, u32)>,
    message: &str,
) -> String {
    let place = location
        .map(|(file, line)| format!("{file}:{line}"))
        .unwrap_or_else(|| "unknown location".into());
    let message: String = message.chars().take(500).collect();
    format!(
        "[{timestamp_secs}] thread '{thread}' panicked at {place}: {}\n",
        message.replace('\n', " ")
    )
}

pub fn append_line(path: &std::path::Path, line: &str) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    if std::fs::metadata(path)
        .map(|meta| meta.len() > MAX_LOG_BYTES)
        .unwrap_or(false)
    {
        std::fs::remove_file(path)?;
    }
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)?;
    file.write_all(line.as_bytes())
}

pub fn install() {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        if let Some(path) = log_path() {
            let message = info
                .payload()
                .downcast_ref::<&str>()
                .map(|text| (*text).to_string())
                .or_else(|| info.payload().downcast_ref::<String>().cloned())
                .unwrap_or_else(|| "non-text panic".into());
            let thread = std::thread::current();
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|elapsed| elapsed.as_secs())
                .unwrap_or(0);
            let line = format_line(
                now,
                thread.name().unwrap_or("unnamed"),
                info.location().map(|place| (place.file(), place.line())),
                &message,
            );
            let _ = append_line(&path, &line);
        }
        previous(info);
    }));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn line_names_thread_location_and_message() {
        let line = format_line(7, "main", Some(("src/lib.rs", 42)), "boom\nsecond");
        assert_eq!(
            line,
            "[7] thread 'main' panicked at src/lib.rs:42: boom second\n"
        );
    }

    #[test]
    fn line_handles_missing_location_and_bounds_long_messages() {
        let line = format_line(1, "t", None, &"x".repeat(2000));
        assert!(line.contains("unknown location"));
        assert!(line.len() < 600);
    }

    #[test]
    fn append_creates_the_folder_and_restarts_an_oversized_log() {
        let dir = std::env::temp_dir().join(format!("officekit-panic-log-{}", std::process::id()));
        let path = dir.join("nested/panic.log");
        append_line(&path, "one\n").unwrap();
        append_line(&path, "two\n").unwrap();
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "one\ntwo\n");
        std::fs::write(&path, vec![b'x'; (MAX_LOG_BYTES + 1) as usize]).unwrap();
        append_line(&path, "fresh\n").unwrap();
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "fresh\n");
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
