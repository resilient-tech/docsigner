//! Terminal tool speaking the same dispatch layer as the browser host.
//!
//! Also the interface the desktop app uses: it runs this binary as a fresh
//! subprocess per call and reads one JSON object from stdout.
//!
//!     opensigner-host version
//!     opensigner-host list
//!     opensigner-host sign --thumbprint ab12cd… --hash <b64> --alg sha256

use std::process::ExitCode;

pub fn run(_args: &[String]) -> ExitCode {
    ExitCode::SUCCESS
}
