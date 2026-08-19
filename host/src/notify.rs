//! A popup after every signature. Never fails, never holds anyone up.
//!
//! The PIN dialog is the user's only other sign that anything happened, and a
//! remembered PIN means some signatures show no dialog at all. This is what
//! stops a signature being invisible. `DOCSIGNER_NO_NOTIFY` turns it off.

pub const ENV_DISABLE: &str = "DOCSIGNER_NO_NOTIFY";

/// The identity the desktop app already claims for its taskbar button.
#[cfg(target_os = "windows")]
const APP_ID: &str = "tech.resilient.docsigner";

/// What Microsoft's own samples borrow when an app has no identity of its own.
#[cfg(target_os = "windows")]
const POWERSHELL_APP_ID: &str =
    "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe";

/// Announce something, as `app`, in the words of `message`.
///
/// Two arguments because the platforms differ in where the name goes: Windows
/// puts it in a header of its own, the others have no header and need it inside
/// the popup or nothing identifies the sender.
pub fn notify(app: &str, message: &str) {
    if std::env::var_os(ENV_DISABLE).is_some() {
        return;
    }
    if let Err(e) = show(app, message) {
        // warn, not debug: the logger is capped at Info, so a debug line here was
        // discarded and a notification that never appeared left no trace at all —
        // no popup, no error, nothing in host.log to explain it.
        log::warn!("could not show the notification: {e}");
    }
}

#[cfg(not(target_os = "windows"))]
fn show(app: &str, message: &str) -> Result<(), notify_rust::error::Error> {
    notify_rust::Notification::new()
        .summary(app)
        .body(message)
        .show()
        .map(|_| ())
}

/// Windows credits a popup to a *registered* identity, never to the process that
/// sent it, and drops popups from a sender it does not know. Borrowing
/// PowerShell's identity is the usual way round that, and it is why every
/// signature used to be announced by "Windows PowerShell".
///
/// An unpackaged app gets one registration: a key under HKCU naming itself. With
/// that in place the popup is ours; without it we still fall back to PowerShell,
/// because a popup under the wrong name beats a signature nobody is told about.
#[cfg(target_os = "windows")]
fn show(app: &str, message: &str) -> Result<(), notify_rust::error::Error> {
    let mut notification = notify_rust::Notification::new();
    match register_identity() {
        // The header says who we are now, so the message goes where the name used
        // to, rather than the popup saying "DocSigner" twice.
        Ok(()) => {
            if notification.summary(message).app_id(APP_ID).show().is_ok() {
                return Ok(());
            }
        }
        Err(e) => log::debug!("could not register the popup identity: {e}"),
    }
    // Credited to PowerShell instead: nothing in that header is ours, so the name
    // goes back inside. The wrong name beats a signature nobody is told about.
    notification
        .summary(app)
        .body(message)
        .app_id(POWERSHELL_APP_ID)
        .show()
        .map(|_| ())
}

/// Tell Windows our name, so it has one to show. Writes a single string under
/// `HKCU\Software\Classes\AppUserModelId`, the documented registration for an app
/// with no installer. No icon: a packaged build keeps its .ico inside the .exe,
/// and there is no image file on disk to point at.
#[cfg(target_os = "windows")]
fn register_identity() -> windows::core::Result<()> {
    use windows::core::w;
    use windows::Win32::System::Registry::{
        RegCloseKey, RegCreateKeyExW, RegSetValueExW, HKEY, HKEY_CURRENT_USER, KEY_SET_VALUE,
        REG_OPTION_NON_VOLATILE, REG_SZ,
    };

    let mut key = HKEY::default();
    unsafe {
        RegCreateKeyExW(
            HKEY_CURRENT_USER,
            w!("Software\\Classes\\AppUserModelId\\tech.resilient.docsigner"),
            0,
            None,
            REG_OPTION_NON_VOLATILE,
            KEY_SET_VALUE,
            None,
            &mut key,
            None,
        )
        .ok()?;
        // Wide, and NUL-terminated: REG_SZ counts bytes, terminator included.
        let name: Vec<u16> = "DocSigner\0".encode_utf16().collect();
        let bytes = std::slice::from_raw_parts(
            name.as_ptr().cast::<u8>(),
            std::mem::size_of_val(&name[..]),
        );
        let set = RegSetValueExW(key, w!("DisplayName"), 0, REG_SZ, Some(bytes));
        let _ = RegCloseKey(key);
        set.ok()?;
    }
    Ok(())
}

/// The message signHash sends: what happened, and who asked for it.
///
/// "Signed 1 hash with certificate 60d7e9402d70…" was the old wording, which read
/// as a debug line: a hash and a thumbprint mean nothing to whoever is signing.
/// One hash is one document, so say that. The thumbprint went to the log.
pub fn signed_message(count: usize, origin: Option<&str>) -> String {
    let documents = if count == 1 { "document" } else { "documents" };
    // The site name matters most. With a remembered PIN there is no dialog, so
    // this popup is the only thing that says who asked.
    match origin {
        Some(origin) => format!("Signed {count} {documents} for {origin}."),
        None => format!("Signed {count} {documents}."),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_message_reads_as_a_sentence() {
        assert_eq!(signed_message(1, None), "Signed 1 document.");
        assert_eq!(signed_message(4, None), "Signed 4 documents.");
        assert_eq!(
            signed_message(2, Some("example.com")),
            "Signed 2 documents for example.com."
        );
    }

    /// Nothing a thumbprint or a hash count would leak into the popup.
    #[test]
    fn the_message_holds_no_jargon() {
        let message = signed_message(3, Some("example.com"));
        for jargon in ["hash", "certificate", "thumbprint"] {
            assert!(
                !message.contains(jargon),
                "{message:?} still says {jargon:?}"
            );
        }
    }

    #[test]
    fn the_disable_switch_is_honoured() {
        let _guard = crate::testenv::EnvGuard::new().set(ENV_DISABLE, "1");
        // Cannot assert that nothing appeared. What this pins is that the
        // switched-off path returns without bothering the OS at all.
        notify("DocSigner", "should not appear");
    }

    /// Notifying with the switch unset must still not fail the signature: CI
    /// and headless boxes have no notification daemon at all.
    #[test]
    fn notifying_without_a_daemon_is_harmless() {
        let _guard = crate::testenv::EnvGuard::new().unset(ENV_DISABLE);
        notify("DocSigner", "best effort only");
    }
}
