//! Getting the PIN: an environment variable first, then a dialog.
//!
//! The PIN never travels over the wire. We ask for it here, on the user's own
//! machine. Every platform borrows a dialog the OS already ships, which is why
//! this binary carries no UI toolkit of its own.

use std::process::Command;

use crate::error::{HostError, Result};

pub const ENV_VAR: &str = "DOCSIGNER_PIN";

/// Long enough for someone to find the token and read the label off it.
const DIALOG_TIMEOUT_SECONDS: u64 = 300;

/// Get the PIN. Reports a cancel when there is none.
///
/// `origin` is the site asking, checked already. It goes in the dialog, so the
/// one moment a human approves a signature says who it is for. None from the
/// CLI and the desktop app, where the person at the keyboard is the asker.
pub fn get_pin(token_label: &str, origin: Option<&str>) -> Result<String> {
    if let Ok(pin) = std::env::var(ENV_VAR) {
        if !pin.is_empty() {
            return Ok(pin);
        }
    }
    match prompt(&prompt_text(token_label, origin)) {
        Some(pin) if !pin.is_empty() => Ok(pin),
        _ => Err(HostError::cancelled("PIN entry was cancelled")),
    }
}

fn label_or_default(token_label: &str) -> &str {
    if token_label.trim().is_empty() {
        "token"
    } else {
        token_label
    }
}

/// What the dialog says. Written once, so all three platforms match.
fn prompt_text(token_label: &str, origin: Option<&str>) -> String {
    let label = label_or_default(token_label);
    match origin {
        Some(origin) => format!("{origin} is asking you to sign.\n\nPIN for {label}:"),
        None => format!("PIN for {label}:"),
    }
}

#[cfg(target_os = "macos")]
fn prompt(text: &str) -> Option<String> {
    // That error number is the user pressing Cancel. Turn it into an empty
    // answer so the caller sees a cancel, not a crash.
    let text = text
        .replace('\\', r"\\")
        .replace('"', "\\\"")
        .replace('\n', r"\n");
    let script = format!(
        "try\n  \
           text returned of (display dialog \"{text}\" default answer \"\" \
           with hidden answer with title \"DocSigner\")\n\
         on error number -128\n  \
           \"\"\n\
         end try"
    );
    run_dialog(Command::new("osascript").arg("-e").arg(script))
}

#[cfg(target_os = "windows")]
fn prompt(text: &str) -> Option<String> {
    // A password box drawn by PowerShell. The browser starts us with no console,
    // so asking on the command line is not an option.
    //
    // PowerShell strings cannot hold a newline or a quote, so the message is
    // escaped and glued back together around each line break.
    let label = text
        .split('\n')
        .map(|line| line.replace('\'', "''"))
        .collect::<Vec<_>>()
        .join("' + [char]10 + '");
    let script = format!(
        r#"Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$f = New-Object Windows.Forms.Form
$f.Text = 'DocSigner'; $f.Width = 340; $f.Height = 210
$f.StartPosition = 'CenterScreen'; $f.TopMost = $true
$f.FormBorderStyle = 'FixedDialog'; $f.MinimizeBox = $false; $f.MaximizeBox = $false
$l = New-Object Windows.Forms.Label
$l.Text = '{label}'; $l.Left = 12; $l.Top = 16; $l.Width = 300; $l.Height = 56
$t = New-Object Windows.Forms.TextBox
$t.UseSystemPasswordChar = $true; $t.Left = 12; $t.Top = 80; $t.Width = 300
$ok = New-Object Windows.Forms.Button
$ok.Text = 'OK'; $ok.Left = 144; $ok.Top = 120; $ok.DialogResult = 'OK'
$no = New-Object Windows.Forms.Button
$no.Text = 'Cancel'; $no.Left = 232; $no.Top = 120; $no.DialogResult = 'Cancel'
$f.Controls.AddRange(@($l, $t, $ok, $no))
$f.AcceptButton = $ok; $f.CancelButton = $no
$f.Add_Shown({{ $f.Activate(); $t.Focus() }})
if ($f.ShowDialog() -eq 'OK') {{ [Console]::Out.Write($t.Text) }}"#
    );
    run_dialog(
        Command::new("powershell")
            .args(["-NoProfile", "-NonInteractive", "-STA", "-Command"])
            .arg(script),
    )
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn prompt(text: &str) -> Option<String> {
    // Whichever of the three the desktop happens to have. First one wins.
    if let Some(pin) = run_dialog(
        Command::new("zenity")
            .arg("--password")
            .arg("--title=DocSigner")
            .arg(format!("--text={text}")),
    ) {
        return Some(pin);
    }
    if let Some(pin) = run_dialog(
        Command::new("kdialog")
            .arg("--password")
            .arg(text)
            .arg("--title")
            .arg("DocSigner"),
    ) {
        return Some(pin);
    }
    pinentry(text)
}

/// pinentry has its own little protocol: set the message, ask, read the reply.
#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn pinentry(text: &str) -> Option<String> {
    use std::io::Write;
    use std::process::Stdio;

    let mut child = Command::new("pinentry")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    {
        let stdin = child.stdin.as_mut()?;
        // One command per line, so a real newline would cut it short. The
        // protocol's own escaping carries one instead.
        let desc = text.replace('%', "%25").replace('\n', "%0A");
        let _ = writeln!(stdin, "SETTITLE DocSigner");
        let _ = writeln!(stdin, "SETDESC {desc}");
        let _ = writeln!(stdin, "GETPIN");
        let _ = writeln!(stdin, "BYE");
    }
    let output = child.wait_with_output().ok()?;
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .find_map(|line| line.strip_prefix("D ").map(str::to_string))
}

/// Run a dialog and take what it prints as the PIN.
///
/// None covers all three of: no such tool, it broke, the user said no. The
/// caller treats them the same.
fn run_dialog(command: &mut Command) -> Option<String> {
    let child = command
        .stdin(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .ok()?;
    let output = wait_with_timeout(child)?;
    if !output.status.success() {
        return None;
    }
    let pin = String::from_utf8_lossy(&output.stdout)
        .trim_end_matches(['\r', '\n'])
        .to_string();
    (!pin.is_empty()).then_some(pin)
}

/// Wait for a dialog, giving up after `DIALOG_TIMEOUT_SECONDS`.
///
/// ponytail: polls twice a second rather than pulling an async runtime or
/// wiring SIGCHLD, for a process that a human is standing in front of.
fn wait_with_timeout(mut child: std::process::Child) -> Option<std::process::Output> {
    let deadline =
        std::time::Instant::now() + std::time::Duration::from_secs(DIALOG_TIMEOUT_SECONDS);
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return child.wait_with_output().ok(),
            Ok(None) => {}
            Err(_) => return None,
        }
        if std::time::Instant::now() >= deadline {
            let _ = child.kill();
            return None;
        }
        std::thread::sleep(std::time::Duration::from_millis(500));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use crate::testenv::EnvGuard;

    /// The only path that works with nobody at the screen, so it is the one
    /// the CLI, the desktop app and the tests use.
    #[test]
    fn env_var_short_circuits_the_dialog() {
        let _guard = EnvGuard::new().set(ENV_VAR, "123456");
        assert_eq!(get_pin("WD PROXKey", None).unwrap(), "123456");
        // The origin makes no difference to the env path.
        assert_eq!(
            get_pin("WD PROXKey", Some("https://example.com")).unwrap(),
            "123456"
        );
    }

    /// An empty variable is not a PIN. Sending it to the token would burn an
    /// attempt for nothing.
    #[test]
    fn an_empty_env_var_does_not_count_as_a_pin() {
        let _guard = EnvGuard::new().set(ENV_VAR, "");
        // No dialog answers in a test, so this cancels instead of hanging. The
        // point is that "" never came back as a PIN.
        match get_pin("WD PROXKey", None) {
            Ok(pin) => assert!(!pin.is_empty(), "an empty PIN must never be returned"),
            Err(e) => assert_eq!(e.code, crate::error::Code::UserCancelled),
        }
    }

    #[test]
    fn label_falls_back_when_the_token_has_none() {
        assert_eq!(label_or_default(""), "token");
        assert_eq!(label_or_default("   "), "token");
        assert_eq!(label_or_default("WD PROXKey"), "WD PROXKey");
    }

    #[test]
    fn a_missing_dialog_tool_is_a_cancellation_not_a_panic() {
        assert!(run_dialog(&mut Command::new("definitely-not-a-real-dialog-tool")).is_none());
    }
}
