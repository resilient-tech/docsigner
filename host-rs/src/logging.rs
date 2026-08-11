//! File logging to the per-user config directory, with stderr as the fallback.
//!
//! A dependency-free `log` sink: the alternatives (simplelog, fern, env_logger)
//! all pull a formatter stack for what is one timestamped line appended to one
//! file. `getVersion` reports the path so support can ask for one file by name.

use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use log::{Level, LevelFilter, Metadata, Record};

/// Per-user config directory: `~/.config/opensigner` on POSIX,
/// `%APPDATA%\opensigner` on Windows. Matches modules.py `config_dir()`.
pub fn config_dir() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        std::env::var_os("APPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|| dirs::home_dir().unwrap_or_default())
            .join("opensigner")
    }
    #[cfg(not(target_os = "windows"))]
    {
        dirs::home_dir()
            .unwrap_or_default()
            .join(".config")
            .join("opensigner")
    }
}

pub fn log_path() -> PathBuf {
    config_dir().join("host.log")
}

enum Sink {
    File(Mutex<File>),
    Stderr,
}

struct HostLogger {
    sink: Sink,
}

impl log::Log for HostLogger {
    fn enabled(&self, metadata: &Metadata) -> bool {
        metadata.level() <= Level::Info
    }

    fn log(&self, record: &Record) {
        if !self.enabled(record.metadata()) {
            return;
        }
        let line = format!(
            "{} {} {}: {}\n",
            timestamp(),
            record.level(),
            record.target(),
            record.args()
        );
        match &self.sink {
            Sink::File(file) => {
                if let Ok(mut file) = file.lock() {
                    let _ = file.write_all(line.as_bytes());
                    let _ = file.flush();
                }
            }
            Sink::Stderr => {
                let _ = std::io::stderr().write_all(line.as_bytes());
            }
        }
    }

    fn flush(&self) {
        if let Sink::File(file) = &self.sink {
            if let Ok(mut file) = file.lock() {
                let _ = file.flush();
            }
        }
    }
}

/// Seconds since the epoch as `YYYY-MM-DDTHH:MM:SSZ`.
///
/// ponytail: civil-from-days rather than a date crate, since this is the only
/// place the host formats a wall clock it did not get from a certificate.
fn timestamp() -> String {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let (days, secs) = ((now / 86_400) as i64, now % 86_400);
    let (year, month, day) = civil_from_days(days);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        secs / 3600,
        (secs % 3600) / 60,
        secs % 60
    )
}

/// Howard Hinnant's civil_from_days, the standard days-since-epoch to Y/M/D.
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// Install the logger. Never fails: a directory we cannot create means stderr.
pub fn init() {
    let sink = build_sink();
    let logger = Box::new(HostLogger { sink });
    // set_boxed_logger only fails if a logger is already installed, which in a
    // single-binary host means the CLI already called this.
    if log::set_boxed_logger(logger).is_ok() {
        log::set_max_level(LevelFilter::Info);
    }
}

fn build_sink() -> Sink {
    let directory = config_dir();
    if std::fs::create_dir_all(&directory).is_err() {
        return Sink::Stderr;
    }
    match OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path())
    {
        Ok(file) => Sink::File(Mutex::new(file)),
        Err(_) => Sink::Stderr,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn civil_from_days_hits_known_dates() {
        assert_eq!(civil_from_days(0), (1970, 1, 1));
        assert_eq!(civil_from_days(19_723), (2024, 1, 1));
        // 2024 is a leap year: day 60 of the year is 29 February.
        assert_eq!(civil_from_days(19_782), (2024, 2, 29));
        assert_eq!(civil_from_days(20_454), (2026, 1, 1));
    }

    #[test]
    fn timestamp_has_the_right_shape() {
        let stamp = timestamp();
        assert_eq!(stamp.len(), 20, "{stamp}");
        assert!(stamp.ends_with('Z'));
        assert_eq!(stamp.as_bytes()[10], b'T');
    }

    #[test]
    fn config_dir_is_under_the_home_directory() {
        let dir = config_dir();
        assert!(dir.ends_with("opensigner"), "{dir:?}");
    }
}
