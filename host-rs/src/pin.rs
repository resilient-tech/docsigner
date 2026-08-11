//! PIN acquisition chain: env var (CLI and tests), then a local dialog.
//!
//! PINs never cross the native messaging protocol; the host prompts locally.
//! Every platform shells out to a dialog the OS already ships, which is how the
//! Python host worked on macOS. Doing the same on Windows and Linux is what
//! lets this binary drop tkinter, worth 7.7 MB in the packaged desktop app and
//! absent entirely on a minimal Linux install.

use std::process::Command;

use crate::error::{HostError, Result};

pub const ENV_VAR: &str = "OPENSIGNER_PIN";

/// Long enough for someone to find the token and read the label off it.
const DIALOG_TIMEOUT_SECONDS: u64 = 300;

/// Return the token PIN. `USER_CANCELLED` when none is available.
///
/// `origin` is the website the browser says asked for this signature, already
/// validated by `protocol::clean_origin`. It goes in the dialog so the one
/// moment a human authorises a signature names who is asking. `None` for the
/// CLI and the desktop app, where the person at the keyboard is the caller.
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

/// The dialog's message. Built once here so all three platforms say the same
/// thing and only have to escape it for their own shell.
fn prompt_text(token_label: &str, origin: Option<&str>) -> String {
    let label = label_or_default(token_label);
    match origin {
        Some(origin) => format!("{origin} is asking you to sign.\n\nPIN for {label}:"),
        None => format!("PIN for {label}:"),
    }
}

#[cfg(target_os = "macos")]
fn prompt(text: &str) -> Option<String> {
    // AppleScript error -128 is the user pressing Cancel, which the handler
    // turns into an empty string so the caller sees a cancellation, not a crash.
    let text = text
        .replace('\\', r"\\")
        .replace('"', "\\\"")
        .replace('\n', r"\n");
    let script = format!(
        "try\n  \
           text returned of (display dialog \"{text}\" default answer \"\" \
           with hidden answer with title \"OpenSigner\")\n\
         on error number -128\n  \
           \"\"\n\
         end try"
    );
    run_dialog(Command::new("osascript").arg("-e").arg(script))
}

#[cfg(target_os = "windows")]
fn prompt(text: &str) -> Option<String> {
    // A WinForms masked box through PowerShell. The host is spawned by the
    // browser with no console, so Read-Host is not an option.
    //
    // A single-quoted PowerShell string cannot carry a newline or a quote, so
    // the text is escaped for quotes and rebuilt as a concatenation with
    // [char]10 wherever a line break belongs.
    let label = text
        .split('\n')
        .map(|line| line.replace('\'', "''"))
        .collect::<Vec<_>>()
        .join("' + [char]10 + '");
    let script = format!(
        r#"Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$f = New-Object Windows.Forms.Form
$f.Text = 'OpenSigner'; $f.Width = 340; $f.Height = 210
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
    // zenity on GNOME, kdialog on KDE, pinentry as the GPG-era fallback that is
    // present on most headful Linux boxes. First one that answers wins.
    if let Some(pin) = run_dialog(
        Command::new("zenity")
            .arg("--password")
            .arg("--title=OpenSigner")
            .arg(format!("--text={text}")),
    ) {
        return Some(pin);
    }
    if let Some(pin) = run_dialog(
        Command::new("kdialog")
            .arg("--password")
            .arg(text)
            .arg("--title")
            .arg("OpenSigner"),
    ) {
        return Some(pin);
    }
    pinentry(text)
}

/// pinentry speaks Assuan on stdio: `SETDESC`, `GETPIN`, and the answer comes
/// back on a `D ` line.
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
        // Assuan is line-based, so a literal newline would end the command.
        // Percent-encoding is how the protocol carries one (and %, in turn).
        let desc = text.replace('%', "%25").replace('\n', "%0A");
        let _ = writeln!(stdin, "SETTITLE OpenSigner");
        let _ = writeln!(stdin, "SETDESC {desc}");
        let _ = writeln!(stdin, "GETPIN");
        let _ = writeln!(stdin, "BYE");
    }
    let output = child.wait_with_output().ok()?;
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .find_map(|line| line.strip_prefix("D ").map(str::to_string))
}

/// Run a dialog command and take its stdout as the PIN.
///
/// `None` means the tool is absent, failed, or the user cancelled; the caller
/// treats all three the same way.
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

    /// The env var is the path the CLI, the desktop app and the tests use, and
    /// the only one that can be exercised without a human at the screen.
    #[test]
    fn env_var_short_circuits_the_dialog() {
        let previous = std::env::var_os(ENV_VAR);
        std::env::set_var(ENV_VAR, "123456");
        let pin = get_pin("WD PROXKey", None);
        match previous {
            Some(v) => std::env::set_var(ENV_VAR, v),
            None => std::env::remove_var(ENV_VAR),
        }
        assert_eq!(pin.unwrap(), "123456");
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
