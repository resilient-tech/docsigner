//! Windows `MY` certificate store backend.
//!
//! Certificates come from `CertOpenSystemStoreW`/`CertEnumCertificatesInStore`,
//! filtered to those that actually have a private key. Signing goes through CNG
//! (`NCryptSignHash`), which forwards to the token and lets the OS show its own
//! PIN dialog.
//!
//! CNG returns raw `r || s` for ECDSA, so that path converts to DER the same way
//! the PKCS#11 one does. RSA takes a bare digest plus a padding descriptor, so
//! no DigestInfo is built here.

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

/// `CERT_KEY_PROV_INFO_PROP_ID`. Its presence is how the store says a
/// certificate has a usable private key behind it.
const CERT_KEY_PROV_INFO_PROP_ID: u32 = 2;

/// "MY\0" as UTF-16, the store name.
const MY: &[u16] = &[b'M' as u16, b'Y' as u16, 0];

/// RAII wrapper so every early return still closes the store.
struct Store(HCERTSTORE);

impl Store {
    fn open() -> Result<Self> {
        // SAFETY: a default (null) legacy provider with a store name opens the
        // current user's store.
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
        // SAFETY: self.0 came from CertOpenSystemStoreW and is closed once.
        unsafe {
            let _ = CertCloseStore(self.0, 0);
        }
    }
}

/// DER bytes of a certificate context.
///
/// SAFETY: `context` must be a live CERT_CONTEXT from the enumeration.
unsafe fn context_der(context: *const CERT_CONTEXT) -> Vec<u8> {
    let context = &*context;
    std::slice::from_raw_parts(context.pbCertEncoded, context.cbCertEncoded as usize).to_vec()
}

/// Whether the certificate has an associated private key.
///
/// SAFETY: `context` must be a live CERT_CONTEXT from the enumeration.
unsafe fn has_private_key(context: *const CERT_CONTEXT) -> bool {
    let mut size = 0u32;
    CertGetCertificateContextProperty(context, CERT_KEY_PROV_INFO_PROP_ID, None, &mut size).is_ok()
}

/// Walk the store, handing each live context to `visit`. Stops at the first
/// `Some`, whose value is returned.
///
/// The context stays valid only for the duration of the callback: the next
/// enumeration step frees it. Anything needed afterwards must be copied out,
/// which is why `sign` does its whole job inside the callback rather than
/// carrying a context away.
fn for_each_certificate<T>(
    mut visit: impl FnMut(*const CERT_CONTEXT, &[u8]) -> Option<T>,
) -> Result<Option<T>> {
    let store = Store::open()?;
    let mut context: *const CERT_CONTEXT = std::ptr::null();
    loop {
        // SAFETY: passing the previous context advances the enumeration and
        // frees it; a null return ends the walk and frees nothing further.
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
        // SAFETY: context is live for the duration of this callback.
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

/// One `NCryptSignHash` call: ask for the length, then fill the buffer.
fn ncrypt_sign(
    key: NCRYPT_KEY_HANDLE,
    padding: Option<*const c_void>,
    flags: NCRYPT_FLAGS,
    digest: &[u8],
) -> Result<Vec<u8>> {
    let mut needed = 0u32;
    // SAFETY: a null output buffer asks CNG for the required size.
    unsafe { NCryptSignHash(key, padding, digest, None, &mut needed, flags) }
        .map_err(|e| map_ncrypt_error(e, "NCryptSignHash (size)"))?;

    let mut buffer = vec![0u8; needed as usize];
    // SAFETY: buffer is exactly `needed` bytes, as CNG just reported.
    unsafe { NCryptSignHash(key, padding, digest, Some(&mut buffer), &mut needed, flags) }
        .map_err(|e| map_ncrypt_error(e, "NCryptSignHash"))?;
    buffer.truncate(needed as usize);
    Ok(buffer)
}

/// A CNG key handle that frees itself when the OS said we own it.
struct AcquiredKey {
    handle: NCRYPT_KEY_HANDLE,
    caller_frees: bool,
}

impl Drop for AcquiredKey {
    fn drop(&mut self) {
        if self.caller_frees {
            // SAFETY: the handle came from CryptAcquireCertificatePrivateKey
            // with pfCallerFreeProvOrNCryptKey set, so we own it.
            unsafe {
                let _ = NCryptFreeObject(NCRYPT_HANDLE(self.handle.0));
            }
        }
    }
}

/// Acquire the CNG private key behind a certificate context.
///
/// SAFETY: `context` must be a live CERT_CONTEXT.
unsafe fn acquire_key(context: *const CERT_CONTEXT) -> Option<AcquiredKey> {
    let mut handle = HCRYPTPROV_OR_NCRYPT_KEY_HANDLE::default();
    let mut key_spec = CERT_KEY_SPEC::default();
    let mut caller_frees = BOOL::default();
    CryptAcquireCertificatePrivateKey(
        context,
        // ONLY_NCRYPT_KEY guarantees the handle is a CNG key rather than a
        // legacy CryptoAPI provider, so the transmute below is sound.
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
    // The whole job happens inside the callback: the enumeration frees each
    // context as it moves on, so the key must be acquired and used while the
    // matching context is still live.
    let outcome = for_each_certificate(|context, der| {
        if certs::thumbprint(der) != thumbprint {
            return None;
        }
        // SAFETY: context is live for the duration of this callback.
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
        // CNG returns raw r||s; convert like the PKCS#11 path.
        KeyType::Ec => digests
            .iter()
            .map(|digest| {
                let raw = ncrypt_sign(key.handle, None, NCRYPT_SILENT_FLAG, digest)?;
                certs::ecdsa_raw_to_der(&raw)
            })
            .collect(),
    }
}
