//! Talking to the token through its driver: read certificates, sign hashes.
//!
//! Three things here were learned the hard way against real Indian tokens and
//! must survive any refactor. Each is explained where it happens: a fresh start
//! per scan, walking slots one at a time, and the watchdog.

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

/// A wedged driver must not burn the browser's whole 2-minute patience.
///
/// ponytail: flat per-module budget; the abandoned thread stays alive holding
/// the module. The process-level fix is the user replugging or the host
/// restarting on reconnect (see `protocol::State::restart_requested`).
const SCAN_TIMEOUT: Duration = Duration::from_secs(20);

/// PINs that worked, remembered per token, so several signs cost one prompt.
/// In memory only. Dies with the process, and nothing writes it anywhere.
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

/// Numbers that explain why a list came back empty.
#[derive(Debug, Default, Clone)]
pub struct ScanStats {
    pub configured: usize,
    pub loaded: usize,
    pub tokens: usize,
    /// Drivers we gave up waiting on.
    pub stuck: Vec<String>,
}

/// What one driver's scan found. Only plain data comes back from the worker.
struct ModuleScan {
    certificates: Vec<CertInfo>,
    loaded: bool,
    tokens: usize,
}

/// Open a driver so its own libraries win over ours. Linux only.
///
/// glibc resolves a dlopen'd object's symbols against the process-wide scope
/// first. This binary links libpcsclite for reader detection, so a driver that
/// carries its *own* forked copy binds to ours instead. WatchData's ProxKey is
/// exactly that: it ships libpcsclite_wd talking to its own pcscd_wd daemon,
/// gets handed stock libpcsclite looking for a pcscd that is not running, and
/// answers C_Initialize with CKR_DEVICE_ERROR. Every certificate list comes back
/// empty. RTLD_DEEPBIND puts the driver's own dependencies first.
///
/// Only a pre-open: the dlopen inside `Pkcs11::new` finds this same object
/// already relocated, and dropping the guard leaves cryptoki holding the last
/// reference, so the unload-per-scan below still happens.
///
/// Windows binds imports per module and macOS uses two-level namespaces, so
/// neither has the clash.
#[cfg(target_os = "linux")]
fn preload(path: &Path) -> Option<libloading::os::unix::Library> {
    use libloading::os::unix::{Library, RTLD_LOCAL, RTLD_NOW};
    // Not in libloading's re-exports. Stable in glibc's bits/dlfcn.h.
    const RTLD_DEEPBIND: std::os::raw::c_int = 0x8;
    // RTLD_NOW so every relocation is resolved here, under DEEPBIND.
    unsafe { Library::open(Some(path), RTLD_NOW | RTLD_LOCAL | RTLD_DEEPBIND) }.ok()
}

#[cfg(not(target_os = "linux"))]
fn preload(_path: &Path) -> Option<()> {
    None
}

/// Load a driver and start it up.
///
/// Fresh every scan, on purpose. A ProxKey only looks for the token at startup,
/// so a reused handle keeps saying "no token" forever after a replug or a sleep.
/// Dropping this shuts the driver down, so the next scan starts clean.
fn load_module(path: &Path) -> std::result::Result<Pkcs11, P11Error> {
    let _deepbind = preload(path);
    let context = Pkcs11::new(path)?;
    context.initialize(CInitializeArgs::OsThreads)?;
    Ok(context)
}

/// Every slot holding a token, checked one at a time, bad ones skipped.
///
/// A ProxKey shows several slots and errors on the empty ones. Asking for them
/// all at once dies on the first empty slot and hides a real token sitting in
/// the next one. So walk them individually.
fn tokens_on(context: &Pkcs11, path: &Path) -> Vec<(Slot, String, bool)> {
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
            Ok(info) => found.push((
                slot,
                info.label().trim().to_string(),
                info.protected_authentication_path(),
            )),
            Err(e) => {
                log::warn!("skipping slot {slot} on {}: {e}", path.display());
            }
        }
    }
    found
}

/// Every certificate the open session can see.
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

/// Everything on the tokens behind one driver, in the shape the caller wants.
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

    for (slot, label, protected) in &tokens {
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
                Ok(mut info) => {
                    info.protected_auth_path = *protected;
                    certificates.push(info);
                }
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

/// Look at every driver we know about and collect what they see.
///
/// A broken driver is logged and skipped, so one bad one cannot hide a healthy
/// token. A driver that hangs gets abandoned and named in `stats.stuck`.
pub fn list_certificates(stats: &mut ScanStats) -> Vec<CertInfo> {
    let mut found: Vec<CertInfo> = Vec::new();
    let mut seen = std::collections::HashSet::new();

    for path in modules::discover_modules() {
        stats.configured += 1;
        let started = Instant::now();

        let (sender, receiver) = mpsc::channel();
        let worker_path = path.clone();
        // The worker owns the driver from start to finish. Only finished data
        // comes back across; the session itself cannot leave this thread.
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

/// Driver failure to one of our error codes.
///
/// Split out from `map_error` so tests can call it: the full error type cannot
/// be built by hand.
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

/// Driver error to one of ours.
fn map_error(error: &P11Error) -> HostError {
    match error {
        P11Error::Pkcs11(rv, _) => map_rv(*rv),
        other => HostError::internal(format!("PKCS#11 error: {other}")),
    }
}

/// Same, but for a failure that happened while logging in.
///
/// Not every driver bothers with the "wrong PIN" code. A ProxKey answers a bad
/// PIN with a generic error, which read literally means we tell the user
/// nothing and the retry never fires. Live-tested against a Capricorn DSC.
///
/// By this point the driver loaded, the token answered and we found the
/// certificate. So a login failure means the PIN was refused. Only the vague
/// codes get reread this way; a code that names a real problem is believed.
fn map_login_rv(rv: RvError) -> HostError {
    match rv {
        RvError::GeneralError | RvError::FunctionFailed => {
            HostError::new(Code::PinIncorrect, "the PIN is incorrect")
        }
        other => map_rv(other),
    }
}

/// Ask the token itself before believing the error code.
///
/// The token knows whether it is locked, and a locked PIN must never be
/// retried. The retry is what burns the last attempt.
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

/// A certificate we found, with its driver still open so we can sign right here.
struct Located {
    context: Pkcs11,
    slot: Slot,
    label: String,
    der: Vec<u8>,
    cka_id: Option<Vec<u8>>,
    cka_label: Option<Vec<u8>>,
}

/// Hunt for one certificate across every driver and every token.
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
        for (slot, label, _protected) in tokens_on(&context, &path) {
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

/// A certificate's ID and label, which is how we find its key.
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

/// Find the key that belongs to this certificate. Try the ID, then the label,
/// then give up and take the only key there is.
fn find_private_key(
    session: &Session,
    cka_id: Option<&Vec<u8>>,
    cka_label: Option<&Vec<u8>>,
) -> Option<ObjectHandle> {
    // CKA_ID first, then CKA_LABEL. Order matters: ID is the attribute PKCS#11
    // means for pairing a certificate with its key, and a label can be shared.
    let by = [
        cka_id.map(|id| Attribute::Id(id.clone())),
        cka_label.map(|label| Attribute::Label(label.clone())),
    ];
    for attribute in by.into_iter().flatten() {
        let template = [Attribute::Class(ObjectClass::PRIVATE_KEY), attribute];
        if let Ok(handles) = session.find_objects(&template) {
            if let Some(handle) = handles.first() {
                return Some(*handle);
            }
        }
    }
    // ponytail: last resort takes the only key on the token. Fine for the
    // usual single-key DSC, revisit if a multi-key token misbehaves.
    let handles = session
        .find_objects(&[Attribute::Class(ObjectClass::PRIVATE_KEY)])
        .ok()?;
    match handles.as_slice() {
        [only] => Some(*only),
        _ => None,
    }
}

/// Where the PIN comes from: handed to us, or asked for in a dialog.
pub type PinProvider<'a> = &'a dyn Fn(&str) -> Result<String>;

/// Sign hashes with the key behind a certificate.
///
/// All of them on one login, so the user types the PIN once. Answers come back
/// in the order the hashes went in.
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

    // Work out how to sign first, so an unsupported key fails before we make
    // someone type a PIN for nothing.
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

/// Open a session and log in.
///
/// Does this token collect the PIN itself?
///
/// A pinpad reader is the classic case, and a driver with its own dialog is the
/// same thing: WatchData's ProxKey on Linux sets this. PKCS#11 is explicit that
/// C_Login then takes no PIN and the application must not ask for one. Ignoring
/// it is what made the desktop app prompt and the driver prompt again — two
/// dialogs for one signature, with the PIN travelling through our process for
/// nothing.
fn protected_auth_path(located: &Located) -> bool {
    located
        .context
        .get_token_info(located.slot)
        .map(|info| info.protected_authentication_path())
        .unwrap_or(false)
}

/// Log in and let the token ask for the PIN. No prompt, no cache: we never see
/// it, which is the point of the flag.
fn login_protected(located: &Located) -> std::result::Result<Session, P11Error> {
    let session = located.context.open_ro_session(located.slot)?;
    session.login(UserType::User, None)?;
    Ok(session)
}

/// A remembered PIN that has since been changed earns exactly one fresh
/// prompt. Never a blind retry, which would eat an attempt.
fn login(located: &Located, pin_provider: PinProvider<'_>) -> Result<Session> {
    if protected_auth_path(located) {
        return login_protected(located)
            .map_err(|e| map_login_error(&located.context, located.slot, &e));
    }
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

    // Anything but a refused PIN is the final answer. Do not retry it.
    if failure.code != Code::PinIncorrect {
        return Err(failure);
    }
    forget_pin(&located.label);
    if cached.is_none() {
        return Err(failure);
    }

    // The PIN changed on the token since we remembered it. One proper retry.
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
        // RSA: wrap the hash in its standard envelope first.
        KeyType::Rsa => {
            let info = certs::digest_info(digest, alg)?;
            session
                .sign(&Mechanism::RsaPkcs, key, &info)
                .map_err(|e| map_error(&e))
        }
        // EC: sign the bare hash, then repackage the answer.
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
        // One label per test. The cache is shared and these run in parallel, so
        // a reused label makes them race. CI caught exactly that.
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

    /// The split protocol.rs leans on: a PIN problem is the user's answer and
    /// must be shown, while a missing token lets the OS store have a go.
    #[test]
    fn only_not_found_errors_allow_the_os_store_fallback() {
        assert!(!map_rv(RvError::PinIncorrect).allows_os_store_fallback());
        assert!(!map_rv(RvError::PinLocked).allows_os_store_fallback());
        assert!(map_rv(RvError::TokenNotPresent).allows_os_store_fallback());
        assert!(map_rv(RvError::DeviceRemoved).allows_os_store_fallback());
    }

    /// Found on real hardware: a ProxKey refuses a wrong PIN with a generic
    /// error. Believing it literally tells the user nothing and kills the retry.
    #[test]
    fn vague_login_failures_are_read_as_a_rejected_pin() {
        for rv in [RvError::GeneralError, RvError::FunctionFailed] {
            assert_eq!(
                map_login_rv(rv).code,
                Code::PinIncorrect,
                "{rv:?} at login time means the PIN was not accepted"
            );
        }
        // Outside login, the same code still means what it says.
        assert_eq!(map_rv(RvError::GeneralError).code, Code::Internal);
    }

    /// Rereading the vague codes must not swallow the clear ones.
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

    /// Never retry a locked PIN. The retry is what burns the last attempt.
    #[test]
    fn a_locked_pin_is_not_a_retryable_outcome() {
        assert_ne!(map_login_rv(RvError::PinLocked).code, Code::PinIncorrect);
        assert_ne!(
            map_login_rv(RvError::TokenNotPresent).code,
            Code::PinIncorrect
        );
    }

    /// Runs against whatever the machine has: nothing, a driver with no token,
    /// or a real token. Holds in all three, so it means something in CI and at
    /// a desk with a DSC plugged in.
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

    /// Guards the dlopen flags. A wrong one makes dlopen fail outright, `preload`
    /// return None, and every Linux driver quietly go back to binding our
    /// libpcsclite instead of its own — the CKR_DEVICE_ERROR this fixed.
    #[cfg(target_os = "linux")]
    #[test]
    fn deepbind_preload_opens_a_real_library() {
        assert!(
            preload(Path::new("libpcsclite.so.1")).is_some(),
            "the flags must be a mode dlopen accepts"
        );
        assert!(preload(Path::new("/nonexistent/driver.so")).is_none());
    }
}
