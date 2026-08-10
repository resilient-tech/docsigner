//! Terminal tool speaking the same dispatch layer as the browser host.
//!
//! Also the interface the desktop app uses: it runs this binary as a fresh
//! subprocess per call and reads one JSON object from stdout.
//!
//!     opensigner-host version
//!     opensigner-host list
//!     opensigner-host sign --thumbprint ab12cd… --hash <b64> --alg sha256
//!
//! Set `OPENSIGNER_PIN` to skip the PIN dialog.
//!
//! ponytail: hand-rolled argument parsing rather than clap, for three
//! subcommands and three flags on a binary whose size is the point.

use std::process::ExitCode;

use serde_json::{json, Value};

use crate::protocol::{self, State};

const USAGE: &str = "\
opensigner-host — DSC token access for OpenSigner

USAGE:
    opensigner-host                     native messaging host on stdio (browser)
    opensigner-host version             show host and protocol version
    opensigner-host list                list certificates on all connected tokens
    opensigner-host sign --thumbprint <hex> --hash <b64> [--hash <b64>…] [--alg sha256]

ENVIRONMENT:
    OPENSIGNER_PIN               skip the PIN dialog
    OPENSIGNER_PKCS11_MODULES    extra PKCS#11 module paths
    OPENSIGNER_NO_NOTIFY         suppress signing notifications
    OPENSIGNER_UPDATE_URL        JSON feed for the update check
";

pub fn run(args: &[String]) -> ExitCode {
    let message = match build_request(args) {
        Ok(message) => message,
        Err(problem) => {
            eprintln!("{problem}\n\n{USAGE}");
            return ExitCode::FAILURE;
        }
    };

    let state = State::default();
    let response = protocol::handle_message(&message, &state);

    // Pretty-printed like the Python CLI: a human reads this, and the desktop
    // app parses it either way.
    match serde_json::to_string_pretty(&response) {
        Ok(text) => println!("{text}"),
        Err(e) => {
            eprintln!("could not encode the response: {e}");
            return ExitCode::FAILURE;
        }
    }

    for reader in response["result"]["readers"].as_array().unwrap_or(&vec![]) {
        if reader["driverFound"] == json!(false) {
            let name = reader["token"]
                .as_str()
                .or_else(|| reader["name"].as_str())
                .unwrap_or("a reader");
            eprintln!("note: {name} detected but no matching driver is installed");
        }
    }

    if response.get("result").is_some() {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn build_request(args: &[String]) -> Result<Value, String> {
    let command = args[0].as_str();
    let rest = &args[1..];

    match command {
        "version" | "--version" | "-V" => Ok(request("getVersion", json!({}))),
        "list" => Ok(request("listCertificates", json!({}))),
        "checkUpdate" | "check-update" => Ok(request("checkUpdate", json!({}))),
        "sign" => build_sign(rest),
        "help" | "--help" | "-h" => Err("".to_string()),
        other => Err(format!("unknown command: {other}")),
    }
}

fn request(command: &str, params: Value) -> Value {
    json!({ "id": "cli", "command": command, "params": params })
}

fn build_sign(args: &[String]) -> Result<Value, String> {
    let mut thumbprint: Option<String> = None;
    let mut hashes: Vec<String> = Vec::new();
    let mut alg = "sha256".to_string();

    let mut index = 0;
    while index < args.len() {
        let flag = args[index].as_str();
        let value = || {
            args.get(index + 1)
                .cloned()
                .ok_or_else(|| format!("{flag} needs a value"))
        };
        match flag {
            "--thumbprint" => {
                thumbprint = Some(value()?);
                index += 2;
            }
            "--hash" => {
                hashes.push(value()?);
                index += 2;
            }
            "--alg" | "--digest" => {
                alg = value()?;
                index += 2;
            }
            other => return Err(format!("unknown option for sign: {other}")),
        }
    }

    let thumbprint = thumbprint.ok_or("sign needs --thumbprint")?;
    if hashes.is_empty() {
        return Err("sign needs at least one --hash".to_string());
    }
    Ok(request(
        "signHash",
        json!({ "thumbprint": thumbprint, "hashes": hashes, "digestAlgorithm": alg }),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(list: &[&str]) -> Vec<String> {
        list.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn maps_subcommands_to_protocol_commands() {
        assert_eq!(build_request(&args(&["version"])).unwrap()["command"], "getVersion");
        assert_eq!(build_request(&args(&["list"])).unwrap()["command"], "listCertificates");
        assert_eq!(
            build_request(&args(&["check-update"])).unwrap()["command"],
            "checkUpdate"
        );
    }

    #[test]
    fn sign_collects_repeated_hashes_in_order() {
        let request = build_request(&args(&[
            "sign",
            "--thumbprint",
            "abc123",
            "--hash",
            "AAAA",
            "--hash",
            "BBBB",
            "--alg",
            "sha384",
        ]))
        .unwrap();
        assert_eq!(request["command"], "signHash");
        assert_eq!(request["params"]["thumbprint"], "abc123");
        assert_eq!(request["params"]["hashes"], json!(["AAAA", "BBBB"]));
        assert_eq!(request["params"]["digestAlgorithm"], "sha384");
    }

    #[test]
    fn sign_defaults_to_sha256() {
        let request =
            build_request(&args(&["sign", "--thumbprint", "ab", "--hash", "AA"])).unwrap();
        assert_eq!(request["params"]["digestAlgorithm"], "sha256");
    }

    #[test]
    fn sign_rejects_incomplete_invocations() {
        for bad in [
            vec!["sign"],
            vec!["sign", "--thumbprint", "ab"],
            vec!["sign", "--hash", "AA"],
            vec!["sign", "--thumbprint"],
            vec!["sign", "--thumbprint", "ab", "--hash", "AA", "--bogus", "x"],
        ] {
            assert!(build_request(&args(&bad)).is_err(), "{bad:?} should fail");
        }
    }

    #[test]
    fn unknown_commands_are_rejected() {
        assert!(build_request(&args(&["frobnicate"])).is_err());
    }

    #[test]
    fn the_cli_id_is_stable() {
        assert_eq!(build_request(&args(&["list"])).unwrap()["id"], "cli");
    }
}
