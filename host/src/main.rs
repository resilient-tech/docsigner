//! The little program that reaches the USB token.
//!
//! No arguments: sit and talk to the browser. With arguments: run as a terminal
//! tool, which is also how the desktop app calls it.

mod certs;
mod cli;
mod error;
mod framing;
mod logging;
mod modules;
mod notify;
mod os_store;
mod pcsc_readers;
mod pin;
mod pkcs11;
mod procs;
mod protocol;
#[cfg(test)]
mod testenv;
mod update;

use std::io::{self, IsTerminal};
use std::process::ExitCode;

use protocol::State;

pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Every verb `cli::build_request` accepts. Kept in step with it by the test at
/// the bottom of this file.
const CLI_COMMANDS: [&str; 10] = [
    "version",
    "--version",
    "-V",
    "list",
    "checkUpdate",
    "check-update",
    "sign",
    "help",
    "--help",
    "-h",
];

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    logging::init();

    if wants_cli(args.first().map(String::as_str), io::stdin().is_terminal()) {
        cli::run(&args)
    } else {
        serve()
    }
}

/// Terminal tool, or native messaging host?
///
/// Not "any argument means terminal tool". Browsers pass one: Chrome the
/// calling extension's origin, Firefox the path to the host manifest, Windows
/// additionally `--parent-window=<handle>`. Reading either as a command exits
/// with usage text before a single frame is read, and the browser reports that
/// as "Native host has exited" with nothing in the log to explain it.
///
/// So a known verb means terminal tool. Anything else does too if a person is
/// watching, which keeps typos printing usage instead of hanging on a pipe that
/// will never deliver a frame. A browser's stdin is a pipe, so it always serves,
/// whatever it put on the command line.
fn wants_cli(first: Option<&str>, stdin_is_terminal: bool) -> bool {
    match first {
        None => false,
        Some(arg) => CLI_COMMANDS.contains(&arg) || stdin_is_terminal,
    }
}

/// Answer requests until the browser goes away.
///
/// Only replies go out. Everything else goes to the log file, which is why
/// nothing outside `cli` ever prints.
fn serve() -> ExitCode {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut input = stdin.lock();
    let mut output = stdout.lock();
    let state = State::default();

    log::info!("host started");
    loop {
        let payload = match framing::read_frame(&mut input) {
            Ok(Some(payload)) => payload,
            Ok(None) => break,
            Err(e) => {
                log::warn!("stream ended mid-frame: {e}");
                break;
            }
        };

        let response = protocol::handle_raw(&payload, &state);
        if let Err(e) = framing::write_message(&mut output, &response) {
            log::warn!("browser closed the pipe: {e}");
            break;
        }

        if state.restart_requested.get() {
            log::info!("exiting after a wedged scan; the extension reconnects on demand");
            break;
        }
    }
    log::info!("host stopped");
    ExitCode::SUCCESS
}

#[cfg(test)]
mod tests {
    use super::{wants_cli, CLI_COMMANDS};

    // Chrome hands over the extension origin, Firefox the manifest path, and
    // Windows adds a window handle. Every one of them must still be served.
    #[test]
    fn a_browsers_argument_is_never_read_as_a_command() {
        for arg in [
            "chrome-extension://mbfpejilpjacnimpgbolffkmmfllnlhl/",
            "moz-extension://8b0e4c0f-0000-0000-0000-000000000000/",
            "/Library/Application Support/Mozilla/NativeMessagingHosts/com.docsigner.host.json",
            "--parent-window=132408",
        ] {
            assert!(
                !wants_cli(Some(arg), false),
                "{arg} came from a browser and must be served, not parsed"
            );
        }
    }

    #[test]
    fn the_terminal_still_gets_the_terminal_tool() {
        for command in CLI_COMMANDS {
            assert!(
                wants_cli(Some(command), false),
                "{command} is a CLI command"
            );
        }
        // A typo prints usage rather than hanging on stdin, but only for a human.
        assert!(wants_cli(Some("lst"), true));
        assert!(!wants_cli(Some("lst"), false));
        assert!(!wants_cli(None, true), "no arguments means host mode");
    }
}
