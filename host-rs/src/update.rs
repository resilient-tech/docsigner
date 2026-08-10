//! Update check: compare the running version against a published one.
//!
//! A version-check only, no self-download. Native hosts installed by hand go
//! stale silently and there is no store to push a new build; this lets a page
//! tell the user a newer host exists and point them at the installer.
//!
//! The source is a JSON URL, `OPENSIGNER_UPDATE_URL` (falls back to the module
//! default, empty until a release feed exists), returning at least:
//!
//!     {"version": "0.2.0", "url": "https://…/download"}
//!
//! Network and parse failures are soft: they come back as `updateAvailable:
//! false` with a message, never as a protocol error, so a check never breaks
//! the page.

use std::time::Duration;

use serde::Serialize;
use serde_json::Value;

pub const ENV_URL: &str = "OPENSIGNER_UPDATE_URL";
pub const DEFAULT_UPDATE_URL: &str = ""; // set when a release feed exists
const TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Debug, Clone, Serialize)]
pub struct UpdateStatus {
    #[serde(rename = "currentVersion")]
    pub current_version: String,
    #[serde(rename = "latestVersion")]
    pub latest_version: Option<String>,
    #[serde(rename = "updateAvailable")]
    pub update_available: bool,
    #[serde(rename = "downloadUrl")]
    pub download_url: Option<String>,
    pub message: String,
}

impl UpdateStatus {
    fn unavailable(message: impl Into<String>) -> Self {
        UpdateStatus {
            current_version: crate::VERSION.to_string(),
            latest_version: None,
            update_available: false,
            download_url: None,
            message: message.into(),
        }
    }
}

/// Split a version into its integer parts, ignoring any suffix. Mirrors the
/// Python's `re.findall(r"\d+")`, so `1.2.3-rc1` and `1.2.3` compare equal on
/// the parts that exist.
fn version_parts(text: &str) -> Vec<u64> {
    let mut parts = Vec::new();
    let mut current = String::new();
    for ch in text.chars() {
        if ch.is_ascii_digit() {
            current.push(ch);
        } else if !current.is_empty() {
            parts.push(current.parse().unwrap_or(0));
            current.clear();
        }
    }
    if !current.is_empty() {
        parts.push(current.parse().unwrap_or(0));
    }
    parts
}

/// Whether `latest` is newer than `current`, comparing zero-padded parts.
pub fn is_newer(latest: &str, current: &str) -> bool {
    let (mut a, mut b) = (version_parts(latest), version_parts(current));
    let width = a.len().max(b.len());
    a.resize(width, 0);
    b.resize(width, 0);
    a > b
}

/// Return the current/latest versions and whether an update is available.
pub fn check_update() -> UpdateStatus {
    let url = std::env::var(ENV_URL)
        .ok()
        .filter(|u| !u.is_empty())
        .unwrap_or_else(|| DEFAULT_UPDATE_URL.to_string());
    if url.is_empty() {
        return UpdateStatus::unavailable("no update source configured");
    }

    let response = ureq::AgentBuilder::new()
        .timeout_connect(TIMEOUT)
        .timeout_read(TIMEOUT)
        .build()
        .get(&url)
        .call();

    // Network, HTTP and JSON failures are all soft.
    let data: Value = match response.and_then(|r| r.into_json().map_err(Into::into)) {
        Ok(data) => data,
        Err(e) => return UpdateStatus::unavailable(format!("could not check for updates: {e}")),
    };

    let latest = data.get("version").and_then(Value::as_str).unwrap_or("");
    let download_url = data
        .get("url")
        .and_then(Value::as_str)
        .map(str::to_string);

    let mut status = UpdateStatus {
        current_version: crate::VERSION.to_string(),
        latest_version: (!latest.is_empty()).then(|| latest.to_string()),
        update_available: false,
        download_url,
        message: String::new(),
    };
    if !latest.is_empty() && is_newer(latest, crate::VERSION) {
        status.update_available = true;
        status.message = format!("version {latest} is available");
    } else {
        status.message = "up to date".to_string();
    }
    status
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_comparison_matches_the_python() {
        assert!(is_newer("0.2.0", "0.1.0"));
        assert!(is_newer("1.0.0", "0.9.9"));
        assert!(is_newer("0.1.1", "0.1"));
        assert!(!is_newer("0.1.0", "0.1.0"));
        assert!(!is_newer("0.1.0", "0.2.0"));
        // Uneven part counts pad with zeros, so 0.2 == 0.2.0.
        assert!(!is_newer("0.2", "0.2.0"));
        assert!(!is_newer("0.2.0", "0.2"));
    }

    #[test]
    fn version_parts_ignores_suffixes() {
        assert_eq!(version_parts("1.2.3"), vec![1, 2, 3]);
        assert_eq!(version_parts("v1.2.3-rc1"), vec![1, 2, 3, 1]);
        assert_eq!(version_parts(""), Vec::<u64>::new());
        assert_eq!(version_parts("none"), Vec::<u64>::new());
    }

    #[test]
    fn an_unset_source_is_reported_not_an_error() {
        let previous = std::env::var_os(ENV_URL);
        std::env::remove_var(ENV_URL);
        let status = check_update();
        if let Some(v) = previous {
            std::env::set_var(ENV_URL, v);
        }
        assert!(!status.update_available);
        assert_eq!(status.message, "no update source configured");
        assert_eq!(status.latest_version, None);
        assert_eq!(status.current_version, crate::VERSION);
    }

    #[test]
    fn an_unreachable_source_is_soft() {
        let previous = std::env::var_os(ENV_URL);
        // Reserved TEST-NET-1 address: never routes, fails fast.
        std::env::set_var(ENV_URL, "http://192.0.2.1:9/latest.json");
        let status = check_update();
        match previous {
            Some(v) => std::env::set_var(ENV_URL, v),
            None => std::env::remove_var(ENV_URL),
        }
        assert!(!status.update_available);
        assert!(
            status.message.starts_with("could not check for updates"),
            "{}",
            status.message
        );
    }
}
