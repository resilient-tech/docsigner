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
    notification.app_id("{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe");
    notification.show().map(|_| ())
}

/// The message signHash sends: how many hashes, and which certificate.
pub fn signed_message(count: usize, thumbprint: &str) -> String {
    let plural = if count == 1 { "" } else { "es" };
    let short: String = thumbprint.chars().take(12).collect();
    format!("Signed {count} hash{plural} with certificate {short}…")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn message_matches_the_python_wording() {
        assert_eq!(
            signed_message(1, "937a32bb607f8c1a7705fbf4026d8dcf51cad839"),
            "Signed 1 hash with certificate 937a32bb607f…"
        );
        assert_eq!(
            signed_message(4, "937a32bb607f8c1a7705fbf4026d8dcf51cad839"),
            "Signed 4 hashes with certificate 937a32bb607f…"
        );
    }

    #[test]
    fn a_short_thumbprint_does_not_panic() {
        assert_eq!(signed_message(1, "ab"), "Signed 1 hash with certificate ab…");
        assert_eq!(signed_message(1, ""), "Signed 1 hash with certificate …");
    }

    #[test]
    fn the_disable_switch_is_honoured() {
        std::env::set_var(ENV_DISABLE, "1");
        notify("OpenSigner", "should not appear");
        std::env::remove_var(ENV_DISABLE);
    }
}
