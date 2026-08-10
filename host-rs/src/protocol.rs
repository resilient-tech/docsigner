//! Request dispatch per CONTRACTS.md section 2.
//!
//! `{id, command, params}` in, `{id, result}` or `{id, error: {code, message}}`
//! out. Dispatch never panics out: every failure becomes an error response.

use std::cell::Cell;
use std::time::Instant;

use serde::Serialize;
use serde_json::{json, Map, Value};

use crate::certs::{self, CertInfo, DigestAlg};
use crate::error::{Code, HostError, Result};
use crate::{notify, os_store, pcsc_readers, pin, pkcs11, procs, update};

pub const PROTOCOL_VERSION: u32 = 1;

#[derive(Debug, Default)]
pub struct State {
    /// Set when a scan looked wedged: module loaded, reader or token present,
    /// zero certificates. `main` exits after the reply so the extension's next
    /// request spawns a fresh process (full `C_Initialize`). WatchData's driver
    /// caches its slot state per process; neither re-initialising nor a replug
    /// clears it, only a fresh process does (live-tested: an extension reload
    /// fixed what a replug could not).
    pub restart_requested: Cell<bool>,
}

#[derive(Serialize)]
struct ErrorBody {
    code: Code,
    message: String,
}

/// Dispatch raw request bytes. Always returns a response, never fails.
pub fn handle_raw(payload: &[u8], state: &State) -> Value {
    let message: Value = match serde_json::from_slice(payload) {
        Ok(message) => message,
        Err(_) => return error_response(Value::Null, Code::Internal, "request is not valid JSON"),
    };
    handle_message(&message, state)
}

/// Dispatch a decoded request. Always returns a response, never fails.
pub fn handle_message(message: &Value, state: &State) -> Value {
    let id = message.get("id").cloned().unwrap_or(Value::Null);

    let Some(object) = message.as_object() else {
        return error_response(id, Code::Internal, "request must be a JSON object");
    };
    let command = object.get("command").and_then(Value::as_str).unwrap_or("");
    let params = match object.get("params") {
        None | Some(Value::Null) => Value::Object(Map::new()),
        Some(value) if value.is_object() => value.clone(),
        Some(_) => return error_response(id, Code::Internal, "params must be an object"),
    };

    let outcome = match command {
        "getVersion" => Ok(get_version()),
        "checkUpdate" => Ok(json!(update::check_update())),
        "listCertificates" => Ok(list_certificates(state)),
        "signHash" => sign_hash(&params),
        other => Err(HostError::unsupported(format!(
            "unknown command: {other:?}"
        ))),
    };

    match outcome {
        Ok(result) => json!({ "id": id, "result": result }),
        Err(e) => error_response(id, e.code, e.message),
    }
}

fn error_response(id: Value, code: Code, message: impl Into<String>) -> Value {
    json!({ "id": id, "error": ErrorBody { code, message: message.into() } })
}

fn get_version() -> Value {
    json!({
        "version": crate::VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "logPath": crate::logging::log_path().to_string_lossy(),
    })
}

/// PKCS#11 tokens plus the OS store, deduplicated by thumbprint.
///
/// A token certificate its driver also registered in the OS store shows up
/// once, as `pkcs11`, keeping the Python host's behaviour for existing users.
///
/// Each source is isolated: the Keychain and the PC/SC reader scan can behave
/// differently when the browser spawns the host (session and permission context
/// differ from a terminal), and a failure there must not hide the tokens
/// PKCS#11 found. The per-source counts are logged so a browser-side empty
/// result can be told apart from a host-side one.
fn list_certificates(state: &State) -> Value {
    let started = Instant::now();
    let mut stats = pkcs11::ScanStats::default();

    let mut certificates = pkcs11::list_certificates(&mut stats);
    let pkcs11_count = certificates.len();

    let seen: std::collections::HashSet<String> =
        certificates.iter().map(|c| c.thumbprint.clone()).collect();
    let os_certs: Vec<CertInfo> = os_store::list_certificates()
        .into_iter()
        .filter(|c| !seen.contains(&c.thumbprint))
        .collect();
    let os_count = os_certs.len();
    certificates.extend(os_certs);

    let readers = pcsc_readers::detect_readers();

    let mut diagnostics = Map::new();
    diagnostics.insert("modulesConfigured".into(), json!(stats.configured));
    diagnostics.insert("modulesLoaded".into(), json!(stats.loaded));
    diagnostics.insert("tokens".into(), json!(stats.tokens));
    diagnostics.insert("pkcs11Certificates".into(), json!(pkcs11_count));
    diagnostics.insert("osStoreCertificates".into(), json!(os_count));
    if !stats.stuck.is_empty() {
        diagnostics.insert("stuckModules".into(), json!(stats.stuck));
    }
    if pkcs11_count == 0 {
        // Only when the scan came back empty: the process listing is pointless
        // when the token answered, and this keeps the happy path fast.
        let competing = procs::competing();
        if !competing.is_empty() {
            diagnostics.insert("competingProcesses".into(), json!(competing));
        }
    }
    if pkcs11_count == 0 && stats.loaded > 0 && (!readers.is_empty() || stats.tokens > 0) {
        state.restart_requested.set(true);
        diagnostics.insert("hostWillRestart".into(), json!(true));
        log::warn!(
            "wedged scan (driver loaded, device present, 0 certificates); \
             exiting after this reply so the next request gets a fresh process"
        );
    }

    log::info!(
        "listCertificates -> {} certificates, {} readers, {:?} in {:.1}s",
        certificates.len(),
        readers.len(),
        diagnostics,
        started.elapsed().as_secs_f32()
    );

    let mut result = Map::new();
    result.insert("certificates".into(), json!(certificates));
    result.insert("diagnostics".into(), Value::Object(diagnostics));
    if !readers.is_empty() {
        result.insert("readers".into(), json!(readers));
    }
    Value::Object(result)
}

fn sign_hash(params: &Value) -> Result<Value> {
    let thumbprint = params
        .get("thumbprint")
        .and_then(Value::as_str)
        .filter(|t| !t.is_empty())
        .ok_or_else(|| HostError::internal("signHash needs a thumbprint string"))?;

    let hashes = params
        .get("hashes")
        .and_then(Value::as_array)
        .filter(|list| !list.is_empty() && list.iter().all(Value::is_string))
        .ok_or_else(|| HostError::internal("signHash needs a non-empty list of base64 hashes"))?;

    let alg = DigestAlg::parse(
        params
            .get("digestAlgorithm")
            .and_then(Value::as_str)
            .unwrap_or("sha256"),
    )?;

    let pin = match params.get("pin") {
        None | Some(Value::Null) => None,
        Some(Value::String(pin)) => Some(pin.clone()),
        Some(_) => return Err(HostError::internal("pin must be a string when present")),
    };

    let digests: Vec<Vec<u8>> = hashes
        .iter()
        .map(|h| certs::base64_decode(h.as_str().unwrap_or("")))
        .collect::<Result<_>>()?;

    let signatures = sign_with_fallback(thumbprint, &digests, alg, pin.as_deref())?;

    notify::notify(
        "OpenSigner",
        &notify::signed_message(signatures.len(), thumbprint),
    );
    Ok(json!({
        "signatures": signatures.iter().map(|s| certs::base64_encode(s)).collect::<Vec<_>>()
    }))
}

/// Tokens first, then the OS store.
///
/// Only not-found outcomes trigger the fallback; PIN and cancellation errors
/// surface as-is. When neither side has the certificate, the PKCS#11 error
/// wins: it distinguishes "no module", "no token" and "no certificate".
///
/// A page-supplied pin (CONTRACTS.md section 2) replaces the native dialog on
/// the PKCS#11 path; the os-store path always uses the OS's own dialog.
fn sign_with_fallback(
    thumbprint: &str,
    digests: &[Vec<u8>],
    alg: DigestAlg,
    pin: Option<&str>,
) -> Result<Vec<Vec<u8>>> {
    let supplied = pin.map(str::to_string);
    let provider = move |label: &str| -> Result<String> {
        match &supplied {
            Some(pin) => Ok(pin.clone()),
            None => pin::get_pin(label),
        }
    };

    let first = match pkcs11::sign_hashes(thumbprint, digests, alg, &provider) {
        Ok(signatures) => return Ok(signatures),
        Err(e) => e,
    };
    if !first.allows_os_store_fallback() {
        return Err(first);
    }
    match os_store::sign_hashes(thumbprint, digests, alg) {
        Ok(signatures) => Ok(signatures),
        Err(fallback) => Err(if fallback.code == Code::CertNotFound {
            first
        } else {
            fallback
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dispatch(message: Value) -> Value {
        handle_message(&message, &State::default())
    }

    #[test]
    fn get_version_reports_the_protocol_and_log_path() {
        let response = dispatch(json!({"id": "1", "command": "getVersion"}));
        let result = &response["result"];
        assert_eq!(response["id"], "1");
        assert_eq!(result["version"], crate::VERSION);
        assert_eq!(result["protocolVersion"], PROTOCOL_VERSION);
        assert!(result["logPath"].as_str().unwrap().ends_with("host.log"));
    }

    #[test]
    fn the_id_is_echoed_verbatim_including_odd_types() {
        assert_eq!(dispatch(json!({"id": 7, "command": "getVersion"}))["id"], 7);
        assert_eq!(
            dispatch(json!({"id": null, "command": "getVersion"}))["id"],
            Value::Null
        );
        // An id we never saw still comes back on the error path.
        assert_eq!(dispatch(json!({"id": "x", "command": "nope"}))["id"], "x");
    }

    #[test]
    fn an_unknown_command_is_unsupported() {
        let response = dispatch(json!({"id": "1", "command": "listPrinters"}));
        assert_eq!(response["error"]["code"], "UNSUPPORTED");
        assert!(response["error"]["message"]
            .as_str()
            .unwrap()
            .contains("listPrinters"));
    }

    #[test]
    fn a_missing_command_is_unsupported_not_a_panic() {
        let response = dispatch(json!({"id": "1"}));
        assert_eq!(response["error"]["code"], "UNSUPPORTED");
    }

    #[test]
    fn malformed_json_becomes_an_internal_error() {
        let response = handle_raw(b"{not json", &State::default());
        assert_eq!(response["error"]["code"], "INTERNAL");
        assert_eq!(response["id"], Value::Null);
    }

    #[test]
    fn a_non_object_request_is_rejected() {
        let response = handle_raw(b"[1, 2, 3]", &State::default());
        assert_eq!(response["error"]["code"], "INTERNAL");
    }

    #[test]
    fn non_object_params_are_rejected() {
        let response = dispatch(json!({"id": "1", "command": "signHash", "params": "nope"}));
        assert_eq!(response["error"]["code"], "INTERNAL");
    }

    #[test]
    fn sign_hash_validates_its_parameters() {
        let cases = [
            json!({}),
            json!({"hashes": ["AA=="]}),
            json!({"thumbprint": "", "hashes": ["AA=="]}),
            json!({"thumbprint": "ab", "hashes": []}),
            json!({"thumbprint": "ab", "hashes": [1, 2]}),
            json!({"thumbprint": "ab", "hashes": ["!!not base64!!"]}),
            json!({"thumbprint": "ab", "hashes": ["AA=="], "pin": 1234}),
        ];
        for params in cases {
            let response = dispatch(json!({"id": "1", "command": "signHash", "params": params}));
            assert_eq!(
                response["error"]["code"], "INTERNAL",
                "should have rejected {params}"
            );
        }
    }

    #[test]
    fn sign_hash_rejects_an_unsupported_digest() {
        let response = dispatch(json!({
            "id": "1", "command": "signHash",
            "params": {"thumbprint": "ab", "hashes": ["AA=="], "digestAlgorithm": "md5"}
        }));
        assert_eq!(response["error"]["code"], "UNSUPPORTED");
    }

    #[test]
    fn check_update_is_soft_with_no_source_configured() {
        let previous = std::env::var_os(update::ENV_URL);
        std::env::remove_var(update::ENV_URL);
        let response = dispatch(json!({"id": "1", "command": "checkUpdate"}));
        if let Some(v) = previous {
            std::env::set_var(update::ENV_URL, v);
        }
        assert!(response.get("error").is_none(), "a check must never error");
        assert_eq!(response["result"]["updateAvailable"], false);
    }

    /// Shape assertions that hold whether or not a token is plugged in.
    #[test]
    fn list_certificates_always_carries_diagnostics() {
        let state = State::default();
        let response = handle_message(&json!({"id": "1", "command": "listCertificates"}), &state);
        let result = &response["result"];

        assert!(result["certificates"].is_array());
        let diagnostics = &result["diagnostics"];
        for key in [
            "modulesConfigured",
            "modulesLoaded",
            "tokens",
            "pkcs11Certificates",
            "osStoreCertificates",
        ] {
            assert!(diagnostics[key].is_number(), "missing {key}");
        }
        // readers is absent, never null, when no smart-card service answers.
        if let Some(readers) = result.get("readers") {
            assert!(readers.is_array());
        }
    }

    #[test]
    fn a_healthy_scan_does_not_request_a_restart() {
        let state = State::default();
        let response = handle_message(&json!({"id": "1", "command": "listCertificates"}), &state);
        let found = response["result"]["certificates"].as_array().unwrap().len();
        if found > 0 {
            assert!(
                !state.restart_requested.get(),
                "a scan that returned certificates must not ask for a restart"
            );
        }
    }
}
