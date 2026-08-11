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

/// Longest origin worth showing: 253 for a DNS name, plus scheme and port.
const MAX_ORIGIN_LEN: usize = 300;

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

    let origin = clean_origin(params.get("origin"))?;

    let digests: Vec<Vec<u8>> = hashes
        .iter()
        .map(|h| certs::base64_decode(h.as_str().unwrap_or("")))
        .collect::<Result<_>>()?;

    let signatures =
        sign_with_fallback(thumbprint, &digests, alg, pin.as_deref(), origin.as_deref())?;

    notify::notify(
        "DocSigner",
        &notify::signed_message(signatures.len(), thumbprint, origin.as_deref()),
    );
    Ok(json!({
        "signatures": signatures.iter().map(|s| certs::base64_encode(s)).collect::<Vec<_>>()
    }))
}

/// Validate the origin the browser attached to a signHash request.
///
/// The extension fills this from `sender.origin`, so a page cannot forge it,
/// and the host checks the shape anyway: this string goes in front of a human
/// in the PIN dialog, and one carrying a path, a newline or userinfo could
/// dress itself up as a site it is not. a European project enforces the same rule.
///
/// An origin is a scheme, a host and an optional port. Anything else is
/// refused. https always, http only for loopback, which is the secure-context
/// carve-out browsers themselves make and where the demo server runs.
///
/// ponytail: hand-rolled rather than pulling a URL crate in for a shape check.
fn clean_origin(value: Option<&Value>) -> Result<Option<String>> {
    let origin = match value {
        None | Some(Value::Null) => return Ok(None),
        Some(Value::String(text)) if text.is_empty() => return Ok(None),
        Some(Value::String(text)) => text.as_str(),
        Some(_) => return Err(HostError::internal("origin must be a string when present")),
    };

    let reject = || HostError::internal(format!("{origin:?} is not a bare web origin"));

    // A DNS name maxes out at 253 characters, plus "https://" and ":65535".
    // Anything longer is not a real origin and would only run off the edge of
    // the dialog, pushing the part that matters out of sight.
    if origin.len() > MAX_ORIGIN_LEN {
        return Err(reject());
    }

    // ASCII only. Browsers hand `sender.origin` over as punycode, so a
    // non-ASCII origin did not come from one. Refusing it closes two ways of
    // dressing up as another site in the dialog that the checks below cannot
    // see: homograph letters (Cyrillic "е" for "e") and bidi overrides like
    // U+202E, which reverse how everything after them renders. Neither counts
    // as a control character, so `is_control` alone lets both through.
    if !origin.is_ascii() {
        return Err(reject());
    }

    let (scheme, rest) = origin.split_once("://").ok_or_else(&reject)?;
    if rest.is_empty()
        || rest.contains(['/', '?', '#', '@', '\\', ' '])
        || rest.chars().any(char::is_control)
    {
        return Err(reject());
    }

    // Split a trailing :port off, leaving IPv6 brackets and bare hosts alone.
    let host = rest.rsplit_once(':').map_or(rest, |(host, port)| {
        if !port.is_empty() && port.bytes().all(|b| b.is_ascii_digit()) {
            host
        } else {
            rest
        }
    });
    let loopback = matches!(host, "localhost" | "127.0.0.1" | "[::1]");

    match scheme {
        "https" => Ok(Some(origin.to_string())),
        "http" if loopback => Ok(Some(origin.to_string())),
        _ => Err(reject()),
    }
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
    origin: Option<&str>,
) -> Result<Vec<Vec<u8>>> {
    let supplied = pin.map(str::to_string);
    let asking = origin.map(str::to_string);
    let provider = move |label: &str| -> Result<String> {
        match &supplied {
            Some(pin) => Ok(pin.clone()),
            None => pin::get_pin(label, asking.as_deref()),
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
    fn an_origin_must_be_a_bare_web_origin() {
        for good in [
            "https://portal.example.com",
            "https://portal.example.com:8443",
            "http://localhost:8080",
            "http://127.0.0.1",
            "http://[::1]:8080",
        ] {
            assert_eq!(
                clean_origin(Some(&json!(good))).unwrap(),
                Some(good.to_string()),
                "{good} should be accepted"
            );
        }

        // Absent, null and empty all mean "the caller is not a browser".
        for absent in [None, Some(json!(null)), Some(json!(""))] {
            assert_eq!(clean_origin(absent.as_ref()).unwrap(), None);
        }

        for bad in [
            json!("https://evil.example.com/path"),
            json!("https://evil.example.com/"),
            json!("https://user:pw@evil.example.com"),
            json!("https://evil.example.com?q=1"),
            json!("https://evil.example.com#f"),
            json!("https://bank.example.com\nreally: evil.example.com"),
            json!("http://not-loopback.example.com"),
            json!("file:///etc/passwd"),
            json!("javascript:alert(1)"),
            json!("portal.example.com"),
            json!("https://"),
            json!(42),
        ] {
            assert!(clean_origin(Some(&bad)).is_err(), "{bad} should be refused");
        }
    }

    /// The origin is the only text in the PIN dialog that names who is asking,
    /// so it has to be text that cannot pretend to be a different site.
    /// `is_control` does not catch either of these: both are ordinary
    /// printable characters as far as Rust is concerned.
    #[test]
    fn an_origin_cannot_disguise_itself_in_the_dialog() {
        // U+202E reverses how everything after it renders.
        let bidi = "https://example.com\u{202E}liave.knab-evil";
        assert!(
            clean_origin(Some(&json!(bidi))).is_err(),
            "a bidi override must not reach the dialog"
        );

        // Cyrillic "е" for Latin "e": identical on screen, different domain.
        let homograph = "https://\u{0435}xample.com";
        assert!(
            clean_origin(Some(&json!(homograph))).is_err(),
            "a homograph must not reach the dialog"
        );

        // Browsers hand sender.origin over already punycoded, so the real
        // article still passes.
        assert_eq!(
            clean_origin(Some(&json!("https://xn--xample-9uf.com"))).unwrap(),
            Some("https://xn--xample-9uf.com".to_string())
        );
    }

    #[test]
    fn an_absurdly_long_origin_is_refused() {
        let long = format!("https://{}.com", "a".repeat(MAX_ORIGIN_LEN));
        assert!(clean_origin(Some(&json!(long))).is_err());

        // A long-but-plausible one still passes, so the cap is not in the way.
        let plausible = format!("https://{}.example.com", "a".repeat(60));
        assert_eq!(
            clean_origin(Some(&json!(plausible))).unwrap(),
            Some(plausible)
        );
    }

    /// Browsers lowercase the scheme in sender.origin, so an uppercase one did
    /// not come from a browser. Pinned because it is easy to "fix" by accident.
    #[test]
    fn the_scheme_is_matched_exactly() {
        for bad in ["HTTPS://example.com", "Https://example.com"] {
            assert!(clean_origin(Some(&json!(bad))).is_err(), "{bad}");
        }
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
        let _guard = crate::testenv::EnvGuard::new().unset(update::ENV_URL);
        let response = dispatch(json!({"id": "1", "command": "checkUpdate"}));
        assert!(response.get("error").is_none(), "a check must never error");
        assert_eq!(response["result"]["updateAvailable"], false);
        // The contract says every field is present even when nothing is set.
        for key in ["currentVersion", "latestVersion", "downloadUrl", "message"] {
            assert!(
                response["result"].get(key).is_some(),
                "checkUpdate must always carry {key}"
            );
        }
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
