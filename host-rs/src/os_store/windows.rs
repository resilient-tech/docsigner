//! The Windows certificate store.
//!
//! Walk the user's store, keep only certificates that have a key behind them.
//! Signing hands the work to Windows, which passes it to the token and shows
//! its own PIN dialog.
//!
//! Windows wants the bare hash for RSA, so no envelope is built here. For EC it
//! returns the two halves loose, repackaged the same way the token path does.

use std::ffi::c_void;

use windows::core::PCWSTR;
use windows::Win32::Foundation::{BOOL, NTE_USER_CANCELLED};
use windows::Win32::Security::Cryptography::{
    CertCloseStore, CertEnumCertificatesInStore, CertGetCertificateContextProperty,
    CertOpenSystemStoreW, CryptAcquireCertificatePrivateKey, NCryptFreeObject, NCryptSignHash,
    BCRYPT_PKCS1_PADDING_INFO, BCRYPT_SHA256_ALGORITHM, BCRYPT_SHA384_ALGORITHM,
    BCRYPT_SHA512_ALGORITHM, CERT_CONTEXT, CERT_KEY_SPEC, CRYPT_ACQUIRE_ONLY_NCRYPT_KEY_FLAG,
    HCERTSTORE, HCRYPTPROV_LEGACY, HCRYPTPROV_OR_NCRYPT_KEY_HANDLE, NCRYPT_FLAGS, NCRYPT_HANDLE,
    NCRYPT_KEY_HANDLE, NCRYPT_PAD_PKCS1_FLAG, NCRYPT_SILENT_FLAG,
};

use crate::certs::{self, DigestAlg, KeyType, Source};
use crate::error::{HostError, Result};

pub const STORE_LABEL: &str = "MY";

/// The flag Windows sets when a certificate has a usable key behind it.
const CERT_KEY_PROV_INFO_PROP_ID: u32 = 2;

/// "MY\0" as UTF-16, the store name.
const MY: &[u16] = &[b'M' as u16, b'Y' as u16, 0];

/// Closes the store on the way out, whichever way we leave.
struct Store(HCERTSTORE);

impl Store {
    fn open() -> Result<Self> {
        // SAFETY: no provider plus a store name opens the current user's store.
        let handle =
            unsafe { CertOpenSystemStoreW(HCRYPTPROV_LEGACY::default(), PCWSTR(MY.as_ptr())) }
                .map_err(|e| {
                    HostError::internal(format!("cannot open the Windows certificate store: {e}"))
                })?;
        Ok(Store(handle))
    }
}

impl Drop for Store {
    fn drop(&mut self) {
        // SAFETY: opened by us, closed exactly once.
        unsafe {
            let _ = CertCloseStore(self.0, 0);
        }
    }
}

/// The raw bytes of one certificate.
///
/// SAFETY: `context` must still be alive.
unsafe fn context_der(context: *const CERT_CONTEXT) -> Vec<u8> {
    let context = &*context;
    std::slice::from_raw_parts(context.pbCertEncoded, context.cbCertEncoded as usize).to_vec()
}

/// Does this one have a key behind it?
///
/// SAFETY: `context` must still be alive.
unsafe fn has_private_key(context: *const CERT_CONTEXT) -> bool {
    let mut size = 0u32;
    CertGetCertificateContextProperty(context, CERT_KEY_PROV_INFO_PROP_ID, None, &mut size).is_ok()
}

/// Walk the store, showing each certificate to `visit`. Stops at the first hit.
///
/// Each one is only alive inside the callback; the next step frees it. Anything
/// you want to keep must be copied out. That is why `sign` does its whole job
/// in there rather than carrying one away.
fn for_each_certificate<T>(
    mut visit: impl FnMut(*const CERT_CONTEXT, &[u8]) -> Option<T>,
) -> Result<Option<T>> {
    let store = Store::open()?;
    let mut context: *const CERT_CONTEXT = std::ptr::null();
    loop {
        // SAFETY: handing back the last one moves on and frees it. Null ends
        // the walk with nothing left to free.
        context = unsafe { CertEnumCertificatesInStore(store.0, Some(context)) };
        if context.is_null() {
            return Ok(None);
        }
        let der = unsafe { context_der(context) };
        if let Some(found) = visit(context, &der) {
            return Ok(Some(found));
        }
    }
}

pub fn list_der() -> Result<Vec<Vec<u8>>> {
    let mut found = Vec::new();
    for_each_certificate(|context, der| {
        // SAFETY: alive for as long as this callback runs.
        if unsafe { has_private_key(context) } {
            found.push(der.to_vec());
        }
        None::<()>
    })?;
    Ok(found)
}

fn digest_algorithm_name(alg: DigestAlg) -> PCWSTR {
    match alg {
        DigestAlg::Sha256 => BCRYPT_SHA256_ALGORITHM,
        DigestAlg::Sha384 => BCRYPT_SHA384_ALGORITHM,
        DigestAlg::Sha512 => BCRYPT_SHA512_ALGORITHM,
    }
}

fn map_ncrypt_error(error: windows::core::Error, doing: &str) -> HostError {
    if error.code() == NTE_USER_CANCELLED {
        HostError::cancelled("signing was cancelled")
    } else {
        HostError::internal(format!("{doing} failed ({:#010x})", error.code().0))
    }
}

/// Sign once: ask how big the answer is, then ask for it.
fn ncrypt_sign(
    key: NCRYPT_KEY_HANDLE,
    padding: Option<*const c_void>,
    flags: NCRYPT_FLAGS,
    digest: &[u8],
) -> Result<Vec<u8>> {
    let mut needed = 0u32;
    // SAFETY: a null buffer is how you ask for the size.
    unsafe { NCryptSignHash(key, padding, digest, None, &mut needed, flags) }
        .map_err(|e| map_ncrypt_error(e, "NCryptSignHash (size)"))?;

    let mut buffer = vec![0u8; needed as usize];
    // SAFETY: the buffer is exactly the size just reported.
    unsafe { NCryptSignHash(key, padding, digest, Some(&mut buffer), &mut needed, flags) }
        .map_err(|e| map_ncrypt_error(e, "NCryptSignHash"))?;
    buffer.truncate(needed as usize);
    Ok(buffer)
}

/// A key handle that cleans itself up, when the OS said it is ours to clean.
struct AcquiredKey {
    handle: NCRYPT_KEY_HANDLE,
    caller_frees: bool,
}

impl Drop for AcquiredKey {
    fn drop(&mut self) {
        if self.caller_frees {
            // SAFETY: the OS told us we own this handle, so we free it.
            unsafe {
                let _ = NCryptFreeObject(NCRYPT_HANDLE(self.handle.0));
            }
        }
    }
}

/// Get hold of the key behind a certificate.
///
/// SAFETY: `context` must still be alive.
unsafe fn acquire_key(context: *const CERT_CONTEXT) -> Option<AcquiredKey> {
    let mut handle = HCRYPTPROV_OR_NCRYPT_KEY_HANDLE::default();
    let mut key_spec = CERT_KEY_SPEC::default();
    let mut caller_frees = BOOL::default();
    CryptAcquireCertificatePrivateKey(
        context,
        // This flag guarantees we get a modern key handle and never a legacy
        // one, which is what makes the cast below safe.
        CRYPT_ACQUIRE_ONLY_NCRYPT_KEY_FLAG,
        None,
        &mut handle,
        Some(&mut key_spec),
        Some(&mut caller_frees),
    )
    .ok()?;
    Some(AcquiredKey {
        handle: NCRYPT_KEY_HANDLE(handle.0),
        caller_frees: caller_frees.as_bool(),
    })
}

pub fn sign(thumbprint: &str, digests: &[Vec<u8>], alg: DigestAlg) -> Result<Vec<Vec<u8>>> {
    // Everything happens inside the callback, because the walk frees each
    // certificate as it moves on and the key only works while its own is alive.
    let outcome = for_each_certificate(|context, der| {
        if certs::thumbprint(der) != thumbprint {
            return None;
        }
        // SAFETY: alive for as long as this callback runs.
        let Some(key) = (unsafe { acquire_key(context) }) else {
            return Some(Err(HostError::cert_not_found(
                "certificate found but its private key is not accessible",
            )));
        };
        Some(sign_with_key(&key, der, digests, alg))
    })?;

    outcome.unwrap_or_else(|| {
        Err(HostError::cert_not_found(format!(
            "no certificate with thumbprint {thumbprint} in the Windows store"
        )))
    })
}

fn sign_with_key(
    key: &AcquiredKey,
    der: &[u8],
    digests: &[Vec<u8>],
    alg: DigestAlg,
) -> Result<Vec<Vec<u8>>> {
    let key_type = certs::cert_info(der, "", "", Source::OsStore)?.key_type;
    match key_type {
        KeyType::Rsa => {
            let padding = BCRYPT_PKCS1_PADDING_INFO {
                pszAlgId: digest_algorithm_name(alg),
            };
            let padding_ptr = &padding as *const _ as *const c_void;
            digests
                .iter()
                .map(|digest| {
                    ncrypt_sign(
                        key.handle,
                        Some(padding_ptr),
                        NCRYPT_PAD_PKCS1_FLAG | NCRYPT_SILENT_FLAG,
                        digest,
                    )
                })
                .collect()
        }
        // Windows hands back the two halves loose. Repackage them.
        KeyType::Ec => digests
            .iter()
            .map(|digest| {
                let raw = ncrypt_sign(key.handle, None, NCRYPT_SILENT_FLAG, digest)?;
                certs::ecdsa_raw_to_der(&raw)
            })
            .collect(),
    }
}
