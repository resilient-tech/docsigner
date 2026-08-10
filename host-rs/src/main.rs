//! OpenSigner native messaging host.
//!
//! Default mode is the stdio loop the browser drives. With arguments it runs
//! the terminal CLI instead, which is also how the desktop app calls it.

mod certs;
mod cli;
mod error;
mod framing;
mod logging;
mod modules;
mod pcsc_readers;
mod pkcs11;
mod procs;

use std::io::{self, Read, Write};
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    logging::init();

    if !args.is_empty() {
        return cli::run(&args);
    }
    serve()
}

/// Read framed requests from stdin, write framed responses to stdout, until EOF.
///
/// stdout carries protocol frames only. Everything else goes to the log file,
/// which is why nothing in this crate ever calls `println!`.
fn serve() -> ExitCode {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut input = stdin.lock();
    let mut output = stdout.lock();

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
        let response = dispatch(&payload);
        if let Err(e) = framing::write_message(&mut output, &response) {
            log::warn!("browser closed the pipe: {e}");
            break;
        }
    }
    log::info!("host stopped");
    ExitCode::SUCCESS
}

fn dispatch(_payload: &[u8]) -> serde_json::Value {
    serde_json::json!({ "id": null, "error": { "code": "INTERNAL", "message": "not wired yet" } })
}

// Silence unused warnings while the tree is being filled in.
#[allow(dead_code)]
fn _unused(_: &mut dyn Read, _: &mut dyn Write) {}
