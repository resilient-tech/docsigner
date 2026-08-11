//! "Is there a newer version?" Nothing more: we never download anything.
//!
//! Installed by hand means nobody can push an update, so a host quietly goes
//! stale forever. This lets a page say so and point at the installer.
//!
//! Reads a JSON file at `DOCSIGNER_UPDATE_URL` holding at least:
//!
//!     {"version": "0.2.0", "url": "https://…/download"}
//!
//! Anything that goes wrong comes back as "no update", never as an error, so a
//! check can never break the page.

use std::time::Duration;

use serde::Serialize;
use serde_json::Value;

pub const ENV_URL: &str = "DOCSIGNER_UPDATE_URL";
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

/// Pull the numbers out of a version, ignoring anything else. So `1.2.3-rc1`
/// and `1.2.3` come out the same.
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

/// The feed to check: the env var, else the compiled-in default.
fn configured_url() -> String {
    std::env::var(ENV_URL)
        .ok()
        .filter(|u| !u.is_empty())
        .unwrap_or_else(|| DEFAULT_UPDATE_URL.to_string())
}

/// Return the current/latest versions and whether an update is available.
pub fn check_update() -> UpdateStatus {
    check_update_at(&configured_url())
}

/// The check itself, against a URL you pass in.
///
/// Split out so tests can drive every branch without touching environment
/// variables, which every test thread shares.
pub fn check_update_at(url: &str) -> UpdateStatus {
    if url.is_empty() {
        return UpdateStatus::unavailable("no update source configured");
    }

    let response = ureq::AgentBuilder::new()
        .timeout_connect(TIMEOUT)
        .timeout_read(TIMEOUT)
        .build()
        .get(url)
        .call();

    // Every failure here is soft. Flattened to a string straight away, because
    // only the message is wanted and the error type is big enough to complain
    // about carrying around.
    let data: Value = match response
        .map_err(|e| e.to_string())
        .and_then(|r| r.into_json::<Value>().map_err(|e| e.to_string()))
    {
        Ok(data) => data,
        Err(e) => return UpdateStatus::unavailable(format!("could not check for updates: {e}")),
    };

    let latest = data.get("version").and_then(Value::as_str).unwrap_or("");
    let download_url = data.get("url").and_then(Value::as_str).map(str::to_string);

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
        let status = check_update_at("");
        assert!(!status.update_available);
        assert_eq!(status.message, "no update source configured");
        assert_eq!(status.latest_version, None);
        assert_eq!(status.download_url, None);
        assert_eq!(status.current_version, crate::VERSION);
    }

    #[test]
    fn an_unreachable_source_is_soft() {
        // Reserved TEST-NET-1 address: never routes, fails fast.
        let status = check_update_at("http://192.0.2.1:9/latest.json");
        assert!(!status.update_available);
        assert!(
            status.message.starts_with("could not check for updates"),
            "{}",
            status.message
        );
        assert_eq!(status.latest_version, None);
    }

    #[test]
    fn a_malformed_url_is_soft_too() {
        let status = check_update_at("not-a-url");
        assert!(!status.update_available);
        assert!(status.message.starts_with("could not check for updates"));
    }

    /// The env plumbing, which is the only part that needs process state.
    ///
    /// Each guard gets its own scope: EnvGuard holds a non-reentrant lock, so
    /// two live at once in one scope would deadlock rather than fail.
    #[test]
    fn the_env_var_selects_the_feed() {
        use crate::testenv::EnvGuard;

        {
            let _guard = EnvGuard::new().unset(ENV_URL);
            assert_eq!(configured_url(), DEFAULT_UPDATE_URL);
        }
        {
            let _guard = EnvGuard::new().set(ENV_URL, "https://example.invalid/latest.json");
            assert_eq!(configured_url(), "https://example.invalid/latest.json");
        }
    }

    /// An empty variable means "unset", not "fetch the empty URL".
    #[test]
    fn an_empty_env_var_falls_back_to_the_default() {
        use crate::testenv::EnvGuard;

        let _guard = EnvGuard::new().set(ENV_URL, "");
        assert_eq!(configured_url(), DEFAULT_UPDATE_URL);
        assert_eq!(check_update().message, "no update source configured");
    }
}
