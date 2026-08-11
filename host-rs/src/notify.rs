//! Best-effort desktop notification. Never raises, never blocks the caller.
//!
//! A notification on every token signature makes a silent signing attempt
//! visible to the user, whose only other UI is the PIN dialog (and the PIN
//! cache means some signatures happen with no prompt at all). Set
//! `OPENSIGNER_NO_NOTIFY` to turn it off.
//!
//! notify-rust covers all three platforms, so unlike notify.py this is no
//! longer a no-op on Windows.

pub const ENV_DISABLE: &str = "OPENSIGNER_NO_NOTIFY";

pub fn notify(title: &str, body: &str) {
    if std::env::var_os(ENV_DISABLE).is_some() {
        return;
    }
    if let Err(e) = show(title, body) {
        log::debug!("notification suppressed: {e}");
    }
}

fn show(title: &str, body: &str) -> Result<(), notify_rust::error::Error> {
    let mut notification = notify_rust::Notification::new();
    notification.summary(title).body(body);
    // Windows toasts need an AppUserModelID; without one the OS drops them
    // silently. PowerShell is present on every supported Windows and is the
    // ID Microsoft's own samples use for unregistered senders.
    #[cfg(target_os = "windows")]
    notification
        .app_id("{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe");
    notification.show().map(|_| ())
}

/// The message signHash sends: how many hashes, and which certificate.
pub fn signed_message(count: usize, thumbprint: &str, origin: Option<&str>) -> String {
    let plural = if count == 1 { "" } else { "es" };
    let short: String = thumbprint.chars().take(12).collect();
    // The origin matters most here: with a cached PIN no dialog appears, so
    // this notification is the only thing naming who asked.
    match origin {
        Some(origin) => {
            format!("Signed {count} hash{plural} for {origin} with certificate {short}…")
        }
        None => format!("Signed {count} hash{plural} with certificate {short}…"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn message_matches_the_python_wording() {
        assert_eq!(
            signed_message(1, "937a32bb607f8c1a7705fbf4026d8dcf51cad839", None),
            "Signed 1 hash with certificate 937a32bb607f…"
        );
        assert_eq!(
            signed_message(4, "937a32bb607f8c1a7705fbf4026d8dcf51cad839", None),
            "Signed 4 hashes with certificate 937a32bb607f…"
        );
    }

    #[test]
    fn a_short_thumbprint_does_not_panic() {
        assert_eq!(
            signed_message(1, "ab", None),
            "Signed 1 hash with certificate ab…"
        );
        assert_eq!(
            signed_message(1, "", None),
            "Signed 1 hash with certificate …"
        );
    }

    #[test]
    fn the_disable_switch_is_honoured() {
        let _guard = crate::testenv::EnvGuard::new().set(ENV_DISABLE, "1");
        // No assertion available on "nothing appeared"; what this pins is that
        // the disabled path returns rather than reaching the OS notifier, which
        // in CI has no session bus and would otherwise log on every call.
        notify("OpenSigner", "should not appear");
    }

    /// Notifying with the switch unset must still not fail the signature: CI
    /// and headless boxes have no notification daemon at all.
    #[test]
    fn notifying_without_a_daemon_is_harmless() {
        let _guard = crate::testenv::EnvGuard::new().unset(ENV_DISABLE);
        notify("OpenSigner", "best effort only");
    }
}
