//! DocSigner native messaging host.
//!
//! With no arguments it runs the stdio loop the browser drives. With arguments
//! it runs the terminal CLI, which is also how the desktop app calls it.

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

use std::io;
use std::process::ExitCode;

use protocol::State;

pub const VERSION: &str = env!("CARGO_PKG_VERSION");

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    logging::init();

    if args.is_empty() {
        serve()
    } else {
        cli::run(&args)
    }
}

/// Read framed requests from stdin, write framed responses to stdout, until EOF.
///
/// stdout carries protocol frames only. Everything else goes to the log file,
/// which is why nothing outside `cli` ever prints.
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
