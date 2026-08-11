//! PKCS#11 operations: certificate listing and hash signing via cryptoki.
//!
//! Three behaviours here came out of live testing against real Indian DSC
//! tokens and must survive any refactor. Each is marked at its call site:
//! fresh `C_Initialize` per scan, per-slot iteration that skips bad slots, and
//! the per-module watchdog.

use std::collections::HashMap;
use std::path::Path;
use std::sync::mpsc;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use cryptoki::context::{CInitializeArgs, Pkcs11};
use cryptoki::error::{Error as P11Error, RvError};
use cryptoki::mechanism::Mechanism;
use cryptoki::object::{Attribute, AttributeType, ObjectClass, ObjectHandle};
use cryptoki::session::{Session, UserType};
use cryptoki::slot::Slot;
use cryptoki::types::AuthPin;

use crate::certs::{self, CertInfo, DigestAlg, KeyType, Source};
use crate::error::{Code, HostError, Result};
use crate::modules;

/// A hung driver call (stuck C_Initialize, dead USB state) must not cost the
/// browser its 120 s native timeout.
///
/// ponytail: flat per-module budget; the abandoned thread stays alive holding
/// the module. The process-level fix is the user replugging or the host
/// restarting on reconnect (see `protocol::State::restart_requested`).
const SCAN_TIMEOUT: Duration = Duration::from_secs(20);

/// Successful PINs, cached per token label so a batch of separate signHash
/// calls costs one prompt. Memory-only: the cache lives exactly as long as the
/// host process, i.e. as long as the extension keeps its native messaging port
/// open.
///
/// ponytail: flat 10-minute TTL, make it configurable if anyone asks.
const PIN_CACHE_TTL: Duration = Duration::from_secs(600);

fn pin_cache() -> &'static Mutex<HashMap<String, (String, Instant)>> {
    static CACHE: OnceLock<Mutex<HashMap<String, (String, Instant)>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

fn cached_pin(label: &str) -> Option<String> {
    let mut cache = pin_cache().lock().ok()?;
    match cache.get(label) {
        Some((pin, expiry)) if *expiry > Instant::now() => Some(pin.clone()),
        Some(_) => {
            cache.remove(label);
            None
        }
        None => None,
    }
}

fn remember_pin(label: &str, pin: &str) {
    if let Ok(mut cache) = pin_cache().lock() {
        cache.insert(
            label.to_string(),
            (pin.to_string(), Instant::now() + PIN_CACHE_TTL),
        );
    }
}

fn forget_pin(label: &str) {
    if let Ok(mut cache) = pin_cache().lock() {
        cache.remove(label);
    }
}

/// Counters that let a caller report WHY a certificate list came back empty.
#[derive(Debug, Default, Clone)]
pub struct ScanStats {
    pub configured: usize,
    pub loaded: usize,
    pub tokens: usize,
    /// Module basenames abandoned after `SCAN_TIMEOUT`.
    pub stuck: Vec<String>,
}

/// What one module's scan produced, sent back from the watchdog thread.
/// Only plain data crosses the channel: `Session` is deliberately `!Send`.
struct ModuleScan {
    certificates: Vec<CertInfo>,
    loaded: bool,
    tokens: usize,
}

/// Load a PKCS#11 module and run `C_Initialize`.
///
/// A fresh `Pkcs11` per scan is the fix for WatchData ProxKey, which
/// enumerates the token only at `C_Initialize`: after a replug or a USB sleep a
/// cached handle reports the token gone forever. Dropping the context calls
/// `C_Finalize`, so each scan starts clean. The Python host needed an explicit
/// `reinitialize()` here because python-pkcs11 cached the module process-wide.
fn load_module(path: &Path) -> std::result::Result<Pkcs11, P11Error> {
    let context = Pkcs11::new(path)?;
    context.initialize(CInitializeArgs::OsThreads)?;
    Ok(context)
}

/// Slots that report a token, one at a time, skipping the ones that raise.
///
/// Some drivers (WatchData ProxKey) expose several reader slots and return
/// `CKR_DEVICE_REMOVED` for the empty ones. A bulk `get_slots_with_token()`
/// aborts the whole scan on the first such slot, which hides a real token
/// sitting in another slot. Walk every slot individually instead.
fn tokens_on(context: &Pkcs11, path: &Path) -> Vec<(Slot, String)> {
    let slots = match context.get_all_slots() {
        Ok(slots) => slots,
        Err(e) => {
            log::warn!("cannot list slots for {}: {e}", path.display());
            return Vec::new();
        }
    };
    let mut found = Vec::new();
    for slot in slots {
        match context.get_token_info(slot) {
            Ok(info) => found.push((slot, info.label().trim().to_string())),
            Err(e) => {
                log::warn!("skipping slot {slot} on {}: {e}", path.display());
            }
        }
    }
    found
}

/// Every certificate on an open session, as (handle, DER).
fn certs_on_session(session: &Session) -> Vec<(ObjectHandle, Vec<u8>)> {
    let handles = match session.find_objects(&[Attribute::Class(ObjectClass::CERTIFICATE)]) {
        Ok(handles) => handles,
        Err(e) => {
            log::warn!("cannot enumerate certificates: {e}");
            return Vec::new();
        }
    };
    let mut found = Vec::new();
    for handle in handles {
        match session.get_attributes(handle, &[AttributeType::Value]) {
            Ok(attributes) => {
                for attribute in attributes {
                    if let Attribute::Value(der) = attribute {
                        found.push((handle, der));
                    }
                }
            }
            Err(e) => log::warn!("cannot read a certificate value: {e}"),
        }
    }
    found
}

/// Contract entries for every certificate on one module's tokens.
fn scan_module(path: &Path) -> ModuleScan {
    let context = match load_module(path) {
        Ok(context) => context,
        Err(e) => {
            log::warn!("cannot load PKCS#11 module {}: {e}", path.display());
            return ModuleScan {
                certificates: Vec::new(),
                loaded: false,
                tokens: 0,
            };
        }
    };
    let module_name = modules::basename(path);
    let tokens = tokens_on(&context, path);
    let mut certificates = Vec::new();

    for (slot, label) in &tokens {
        let session = match context.open_ro_session(*slot) {
            Ok(session) => session,
            Err(e) => {
                log::warn!(
                    "cannot read certificates from token on {}: {e}",
                    path.display()
                );
                continue;
            }
        };
        for (_handle, der) in certs_on_session(&session) {
            match certs::cert_info(&der, label, &module_name, Source::Pkcs11) {
                Ok(info) => certificates.push(info),
                Err(e) => log::warn!(
                    "skipping unparseable certificate on {}: {e}",
                    path.display()
                ),
            }
        }
    }
    ModuleScan {
        certificates,
        loaded: true,
        tokens: tokens.len(),
    }
}

/// Scan all configured modules and return contract-shaped certificate entries.
///
/// Broken modules and unreadable tokens are logged and skipped so one bad
/// driver does not hide certificates on a healthy token. Each module scan runs
/// under `SCAN_TIMEOUT`; a stuck driver is abandoned and named in
/// `stats.stuck`.
pub fn list_certificates(stats: &mut ScanStats) -> Vec<CertInfo> {
    let mut found: Vec<CertInfo> = Vec::new();
    let mut seen = std::collections::HashSet::new();

    for path in modules::discover_modules() {
        stats.configured += 1;
        let started = Instant::now();

        let (sender, receiver) = mpsc::channel();
        let worker_path = path.clone();
        // The worker owns the whole PKCS#11 lifetime: Session is !Send, so
        // nothing but finished data may cross back.
        std::thread::spawn(move || {
            let _ = sender.send(scan_module(&worker_path));
        });

        let scan = match receiver.recv_timeout(SCAN_TIMEOUT) {
            Ok(scan) => scan,
            Err(_) => {
                stats.stuck.push(modules::basename(&path));
                log::warn!(
                    "PKCS#11 module {} still scanning after {}s; abandoned",
                    path.display(),
                    SCAN_TIMEOUT.as_secs()
                );
                continue;
            }
        };
        if scan.loaded {
            stats.loaded += 1;
        }
        stats.tokens += scan.tokens;

        let elapsed = started.elapsed();
        if elapsed > Duration::from_secs(2) {
            log::info!(
                "slow PKCS#11 module {}: {:.1}s",
                path.display(),
                elapsed.as_secs_f32()
            );
        }
        for info in scan.certificates {
            if seen.insert(info.thumbprint.clone()) {
                found.push(info);
            }
        }
    }
    found
}

/// Map a PKCS#11 return value to a contract code.
///
/// Split out from `map_error` because cryptoki keeps the `Function` half of
/// `Error::Pkcs11` private, so a test cannot build the full error but can call
/// this.
fn map_rv(rv: RvError) -> HostError {
    match rv {
        RvError::PinIncorrect => HostError::new(Code::PinIncorrect, "the PIN is incorrect"),
        RvError::PinLocked => HostError::new(
            Code::PinLocked,
            "the PIN is locked; unlock it with the token vendor tool",
        ),
        RvError::TokenNotPresent | RvError::TokenNotRecognized | RvError::DeviceRemoved => {
            HostError::new(Code::TokenNotFound, "the token is not present")
        }
        other => HostError::internal(format!("PKCS#11 error: {other:?}")),
    }
}

/// Translate a PKCS#11 error into a `HostError` with a contract code.
fn map_error(error: &P11Error) -> HostError {
    match error {
        P11Error::Pkcs11(rv, _) => map_rv(*rv),
        other => HostError::internal(format!("PKCS#11 error: {other}")),
    }
}

/// Map a return value seen specifically while logging in.
///
/// Not every driver uses the PIN-specific return values. WatchData ProxKey
/// answers a wrong PIN with `CKR_GENERAL_ERROR` (live-tested against a
/// Capricorn DSC), and matching the return value alone then reports INTERNAL:
/// the page cannot tell the user their PIN was wrong, and the stale-cache retry
/// in `login` never fires. The Python host has the same gap.
///
/// By this point the module loaded, the token answered and the certificate was
/// found by thumbprint, so a `C_Login` failure means the PIN was not accepted.
/// Only the vague failures are reinterpreted; anything that names a real
/// condition still maps through `map_rv`.
fn map_login_rv(rv: RvError) -> HostError {
    match rv {
        RvError::GeneralError | RvError::FunctionFailed => {
            HostError::new(Code::PinIncorrect, "the PIN is incorrect")
        }
        other => map_rv(other),
    }
}

/// Translate a login failure, consulting the token before the return value.
///
/// The token's own flags are authoritative for a locked PIN, and a locked PIN
/// must never be retried: that is what burns the last attempt.
fn map_login_error(context: &Pkcs11, slot: Slot, error: &P11Error) -> HostError {
    if context
        .get_token_info(slot)
        .map(|info| info.user_pin_locked())
        .unwrap_or(false)
    {
        return HostError::new(
            Code::PinLocked,
            "the PIN is locked; unlock it with the token vendor tool",
        );
    }
    match error {
        P11Error::Pkcs11(rv, _) => map_login_rv(*rv),
        other => HostError::internal(format!("PKCS#11 error: {other}")),
    }
}

/// A located certificate, with its module context held open so the caller can
/// log in and sign on the same slot.
struct Located {
    context: Pkcs11,
    slot: Slot,
    label: String,
    der: Vec<u8>,
    cka_id: Option<Vec<u8>>,
    cka_label: Option<Vec<u8>>,
}

/// Locate a certificate by thumbprint across every module and token.
fn find_certificate(thumbprint: &str) -> Result<Located> {
    let mut configured = 0usize;
    let mut loaded = 0usize;
    let mut tokens = 0usize;

    for path in modules::discover_modules() {
        configured += 1;
        let context = match load_module(&path) {
            Ok(context) => context,
            Err(e) => {
                log::warn!("cannot load PKCS#11 module {}: {e}", path.display());
                continue;
            }
        };
        loaded += 1;
        for (slot, label) in tokens_on(&context, &path) {
            tokens += 1;
            let session = match context.open_ro_session(slot) {
                Ok(session) => session,
                Err(e) => {
                    log::warn!("cannot scan token on {}: {e}", path.display());
                    continue;
                }
            };
            for (handle, der) in certs_on_session(&session) {
                if certs::thumbprint(&der) != thumbprint {
                    continue;
                }
                let (cka_id, cka_label) = key_hints(&session, handle);
                drop(session);
                return Ok(Located {
                    context,
                    slot,
                    label,
                    der,
                    cka_id,
                    cka_label,
                });
            }
        }
    }

    if configured > 0 && loaded == 0 {
        return Err(HostError::new(
            Code::ModuleError,
            "no PKCS#11 module could be loaded",
        ));
    }
    if tokens == 0 {
        return Err(HostError::new(
            Code::TokenNotFound,
            "no token is present; plug in the device and retry",
        ));
    }
    Err(HostError::cert_not_found(format!(
        "no certificate with thumbprint {thumbprint} on any present token"
    )))
}

/// CKA_ID and CKA_LABEL of a certificate object, used to match its private key.
fn key_hints(session: &Session, handle: ObjectHandle) -> (Option<Vec<u8>>, Option<Vec<u8>>) {
    let Ok(attributes) = session.get_attributes(handle, &[AttributeType::Id, AttributeType::Label])
    else {
        return (None, None);
    };
    let mut id = None;
    let mut label = None;
    for attribute in attributes {
        match attribute {
            Attribute::Id(value) if !value.is_empty() => id = Some(value),
            Attribute::Label(value) if !value.is_empty() => label = Some(value),
            _ => {}
        }
    }
    (id, label)
}

/// Match the private key to the certificate: by CKA_ID, then label, then the
/// only key on the token.
fn find_private_key(
    session: &Session,
    cka_id: Option<&Vec<u8>>,
    cka_label: Option<&Vec<u8>>,
) -> Option<ObjectHandle> {
    if let Some(id) = cka_id {
        let template = [
            Attribute::Class(ObjectClass::PRIVATE_KEY),
            Attribute::Id(id.clone()),
        ];
        if let Ok(handles) = session.find_objects(&template) {
            if let Some(handle) = handles.first() {
                return Some(*handle);
            }
        }
    }
    if let Some(label) = cka_label {
        let template = [
            Attribute::Class(ObjectClass::PRIVATE_KEY),
            Attribute::Label(label.clone()),
        ];
        if let Ok(handles) = session.find_objects(&template) {
            if let Some(handle) = handles.first() {
                return Some(*handle);
            }
        }
    }
    // ponytail: last resort grabs the only private key; fine for single-cert
    // DSC tokens, revisit if multi-key tokens misbehave.
    let handles = session
        .find_objects(&[Attribute::Class(ObjectClass::PRIVATE_KEY)])
        .ok()?;
    match handles.as_slice() {
        [only] => Some(*only),
        _ => None,
    }
}

/// How the host obtains a PIN. `protocol` passes either a page-supplied value
/// or the native dialog.
pub type PinProvider<'a> = &'a dyn Fn(&str) -> Result<String>;

/// Sign raw digests with the private key matching a certificate thumbprint.
///
/// All digests are signed inside one login session: one PIN prompt per batch.
/// Returns raw signature bytes per digest, in order.
pub fn sign_hashes(
    thumbprint: &str,
    digests: &[Vec<u8>],
    alg: DigestAlg,
    pin_provider: PinProvider<'_>,
) -> Result<Vec<Vec<u8>>> {
    if digests.is_empty() {
        return Err(HostError::internal("hashes must be a non-empty list"));
    }
    let thumbprint = thumbprint.trim().to_lowercase();
    let located = find_certificate(&thumbprint)?;

    // Key type decides the mechanism; an unsupported one fails before we ask
    // for a PIN.
    let key_type = certs::cert_info(&located.der, "", "", Source::Pkcs11)?.key_type;

    let session = login(&located, pin_provider)?;

    let key = find_private_key(
        &session,
        located.cka_id.as_ref(),
        located.cka_label.as_ref(),
    )
    .ok_or_else(|| {
        HostError::cert_not_found("certificate found but its private key is not on the token")
    })?;

    digests
        .iter()
        .map(|digest| sign_one(&session, key, digest, key_type, alg))
        .collect()
}

/// Open a session and log in, with the cached-PIN retry.
///
/// A cached PIN that has gone stale (changed on the token) earns exactly one
/// fresh prompt, never a blind retry that would burn a PIN attempt.
fn login(located: &Located, pin_provider: PinProvider<'_>) -> Result<Session> {
    let cached = cached_pin(&located.label);
    let pin = match &cached {
        Some(pin) => pin.clone(),
        None => pin_provider(&located.label)?,
    };
    if pin.is_empty() {
        return Err(HostError::cancelled("PIN entry was cancelled"));
    }

    let failure = match open_and_login(located, &pin) {
        Ok(session) => {
            remember_pin(&located.label, &pin);
            return Ok(session);
        }
        Err(e) => map_login_error(&located.context, located.slot, &e),
    };

    // Anything other than a rejected PIN (locked, token pulled mid-login) is
    // the answer, not something to retry.
    if failure.code != Code::PinIncorrect {
        return Err(failure);
    }
    forget_pin(&located.label);
    if cached.is_none() {
        return Err(failure);
    }

    // The cached PIN went stale (changed on the token): one proper retry.
    let fresh = pin_provider(&located.label)?;
    if fresh.is_empty() {
        return Err(HostError::cancelled("PIN entry was cancelled"));
    }
    let session = open_and_login(located, &fresh)
        .map_err(|e| map_login_error(&located.context, located.slot, &e))?;
    remember_pin(&located.label, &fresh);
    Ok(session)
}

fn open_and_login(located: &Located, pin: &str) -> std::result::Result<Session, P11Error> {
    let session = located.context.open_ro_session(located.slot)?;
    session.login(UserType::User, Some(&AuthPin::new(pin.to_string())))?;
    Ok(session)
}

fn sign_one(
    session: &Session,
    key: ObjectHandle,
    digest: &[u8],
    key_type: KeyType,
    alg: DigestAlg,
) -> Result<Vec<u8>> {
    match key_type {
        // PKCS#1 v1.5: wrap the digest in a DigestInfo, sign with CKM_RSA_PKCS.
        KeyType::Rsa => {
            let info = certs::digest_info(digest, alg)?;
            session
                .sign(&Mechanism::RsaPkcs, key, &info)
                .map_err(|e| map_error(&e))
        }
        // CKM_ECDSA over the raw digest, then raw r||s converted to DER.
        KeyType::Ec => {
            let raw = session
                .sign(&Mechanism::Ecdsa, key, digest)
                .map_err(|e| map_error(&e))?;
            certs::ecdsa_raw_to_der(&raw)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pin_cache_round_trips_and_expires_on_forget() {
        // Labels are unique per test: the cache is process-global and cargo
        // runs these on parallel threads, so a shared key (or a clear) makes
        // them race. CI caught exactly that.
        assert_eq!(cached_pin("round-trip-token"), None);
        remember_pin("round-trip-token", "1234");
        assert_eq!(cached_pin("round-trip-token").as_deref(), Some("1234"));
        forget_pin("round-trip-token");
        assert_eq!(cached_pin("round-trip-token"), None);
    }

    #[test]
    fn pin_cache_is_keyed_per_token_label() {
        remember_pin("keyed-token-a", "1111");
        remember_pin("keyed-token-b", "2222");
        assert_eq!(cached_pin("keyed-token-a").as_deref(), Some("1111"));
        assert_eq!(cached_pin("keyed-token-b").as_deref(), Some("2222"));
        forget_pin("keyed-token-a");
        assert_eq!(cached_pin("keyed-token-a"), None);
        assert_eq!(
            cached_pin("keyed-token-b").as_deref(),
            Some("2222"),
            "forgetting one label must not disturb another"
        );
        forget_pin("keyed-token-b");
    }

    #[test]
    fn scan_stats_start_empty() {
        let stats = ScanStats::default();
        assert_eq!((stats.configured, stats.loaded, stats.tokens), (0, 0, 0));
        assert!(stats.stuck.is_empty());
    }

    #[test]
    fn error_mapping_follows_the_contract() {
        let cases = [
            (RvError::PinIncorrect, Code::PinIncorrect),
            (RvError::PinLocked, Code::PinLocked),
            (RvError::TokenNotPresent, Code::TokenNotFound),
            (RvError::TokenNotRecognized, Code::TokenNotFound),
            (RvError::DeviceRemoved, Code::TokenNotFound),
            (RvError::DeviceError, Code::Internal),
            (RvError::GeneralError, Code::Internal),
        ];
        for (rv, expected) in cases {
            assert_eq!(map_rv(rv).code, expected, "{rv:?}");
        }
    }

    /// The distinction protocol.rs relies on: a wrong or locked PIN is the
    /// user's answer and must surface, while a missing token or module lets the
    /// OS store have a try.
    #[test]
    fn only_not_found_errors_allow_the_os_store_fallback() {
        assert!(!map_rv(RvError::PinIncorrect).allows_os_store_fallback());
        assert!(!map_rv(RvError::PinLocked).allows_os_store_fallback());
        assert!(map_rv(RvError::TokenNotPresent).allows_os_store_fallback());
        assert!(map_rv(RvError::DeviceRemoved).allows_os_store_fallback());
    }

    /// Live-tested regression: a WatchData ProxKey rejects a wrong PIN with
    /// CKR_GENERAL_ERROR, not CKR_PIN_INCORRECT. Reading that as INTERNAL tells
    /// the user nothing and stops the stale-cache retry from ever firing.
    #[test]
    fn vague_login_failures_are_read_as_a_rejected_pin() {
        for rv in [RvError::GeneralError, RvError::FunctionFailed] {
            assert_eq!(
                map_login_rv(rv).code,
                Code::PinIncorrect,
                "{rv:?} at login time means the PIN was not accepted"
            );
        }
        // Away from login the same return value is still just an internal error.
        assert_eq!(map_rv(RvError::GeneralError).code, Code::Internal);
    }

    /// Reinterpreting the vague codes must not swallow the specific ones.
    #[test]
    fn login_mapping_keeps_the_specific_return_values() {
        assert_eq!(map_login_rv(RvError::PinIncorrect).code, Code::PinIncorrect);
        assert_eq!(map_login_rv(RvError::PinLocked).code, Code::PinLocked);
        assert_eq!(
            map_login_rv(RvError::TokenNotPresent).code,
            Code::TokenNotFound
        );
        assert_eq!(
            map_login_rv(RvError::DeviceRemoved).code,
            Code::TokenNotFound
        );
    }

    /// A locked PIN must never be retried: the retry is what burns the last
    /// attempt. Only PinIncorrect reaches the second prompt in `login`.
    #[test]
    fn a_locked_pin_is_not_a_retryable_outcome() {
        assert_ne!(map_login_rv(RvError::PinLocked).code, Code::PinIncorrect);
        assert_ne!(
            map_login_rv(RvError::TokenNotPresent).code,
            Code::PinIncorrect
        );
    }

    /// Runs against whatever the machine has: no driver, a driver with no
    /// token, or a real token. The invariants hold in all three cases, so this
    /// is meaningful in CI and on a developer's desk with a DSC plugged in.
    #[test]
    fn a_scan_always_reports_self_consistent_stats() {
        let mut stats = ScanStats::default();
        let found = list_certificates(&mut stats);

        assert!(
            stats.loaded <= stats.configured,
            "cannot load more than configured"
        );
        if stats.configured == 0 {
            assert_eq!(found.len(), 0, "no driver on disk means no certificates");
        }
        if !found.is_empty() {
            assert!(stats.tokens > 0, "certificates imply a token answered");
        }

        let mut thumbprints: Vec<&str> = found.iter().map(|c| c.thumbprint.as_str()).collect();
        let before = thumbprints.len();
        thumbprints.sort_unstable();
        thumbprints.dedup();
        assert_eq!(
            before,
            thumbprints.len(),
            "the scan must deduplicate by thumbprint"
        );

        for info in &found {
            assert_eq!(info.thumbprint.len(), 40, "SHA-1 hex is 40 characters");
            assert!(!info.certificate.is_empty());
            assert!(info.subject.contains('='), "subject should render as RDNs");
            assert!(info.valid_to.ends_with('Z'));
        }
    }

    #[test]
    fn signing_with_no_token_reports_a_contract_code() {
        let provider = |_: &str| Ok("0000".to_string());
        let error = sign_hashes("deadbeef", &[vec![0u8; 32]], DigestAlg::Sha256, &provider)
            .expect_err("no token is present in CI");
        assert!(
            matches!(
                error.code,
                Code::TokenNotFound | Code::CertNotFound | Code::ModuleError
            ),
            "got {:?}",
            error.code
        );
        assert!(error.allows_os_store_fallback());
    }

    #[test]
    fn signing_an_empty_batch_is_rejected() {
        let provider = |_: &str| Ok("0000".to_string());
        let error = sign_hashes("deadbeef", &[], DigestAlg::Sha256, &provider).unwrap_err();
        assert_eq!(error.code, Code::Internal);
    }
}
