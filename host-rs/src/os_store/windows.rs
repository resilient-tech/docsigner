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
use windows::Win32::Foundation::{HANDLE, NTE_USER_CANCELLED};
use windows::Win32::Security::Cryptography::{
    CertCloseStore, CertEnumCertificatesInStore, CertFreeCertificateContext,
    CertGetCertificateContextProperty, CertOpenSystemStoreW, CryptAcquireCertificatePrivateKey,
    NCryptFreeObject, NCryptSignHash, BCRYPT_PKCS1_PADDING_INFO, BCRYPT_SHA256_ALGORITHM,
    BCRYPT_SHA384_ALGORITHM, BCRYPT_SHA512_ALGORITHM, CERT_CONTEXT, CERT_KEY_PROV_INFO_PROP_ID,
    CRYPT_ACQUIRE_ONLY_NCRYPT_KEY_FLAG, NCRYPT_FLAGS, NCRYPT_KEY_HANDLE, NCRYPT_PAD_PKCS1_FLAG,
    NCRYPT_SILENT_FLAG,
};

use crate::certs::{self, DigestAlg, KeyType, Source};
use crate::error::{HostError, Result};

pub const STORE_LABEL: &str = "MY";

/// RAII wrapper so every early return still closes the store.
struct Store(HANDLE);

impl Store {
    fn open() -> Result<Self> {
        // SAFETY: a null provider with a store name opens the current user's store.
        let handle = unsafe { CertOpenSystemStoreW(HANDLE::default(), w_my()) }.map_err(|e| {
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

fn w_my() -> PCWSTR {
    // "MY\0" as UTF-16, kept alive for the duration of the call below.
    const MY: &[u16] = &[b'M' as u16, b'Y' as u16, 0];
    PCWSTR(MY.as_ptr())
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

/// Walk the store, handing each context to `visit`. Stops early when `visit`
/// returns `Some`.
fn for_each_certificate<T>(
    mut visit: impl FnMut(*const CERT_CONTEXT, &[u8]) -> Option<T>,
) -> Result<Option<T>> {
    let store = Store::open()?;
    let mut context: *mut CERT_CONTEXT = std::ptr::null_mut();
    loop {
        // SAFETY: passing the previous context advances the enumeration and
        // frees it; a null return ends the walk.
        context = unsafe { CertEnumCertificatesInStore(store.0, Some(context)) } as *mut _;
        if context.is_null() {
            return Ok(None);
        }
        let der = unsafe { context_der(context) };
        if let Some(found) = visit(context, &der) {
            // The enumeration owns the context; duplicate nothing, just stop.
            // SAFETY: freeing the context we stopped on, which the loop would
            // otherwise have freed on the next call.
            unsafe {
                let _ = CertFreeCertificateContext(Some(context));
            }
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

fn map_ncrypt_error(error: windows::core::Error, doing: &str) -> HostError {
    if error.code() == NTE_USER_CANCELLED {
        HostError::cancelled("signing was cancelled")
    } else {
        HostError::internal(format!("{doing} failed ({:#010x})", error.code().0))
    }
}

pub fn sign(thumbprint: &str, digests: &[Vec<u8>], alg: DigestAlg) -> Result<Vec<Vec<u8>>> {
    let der = for_each_certificate(|_context, der| {
        (certs::thumbprint(der) == thumbprint).then(|| der.to_vec())
    })?
    .ok_or_else(|| {
        HostError::cert_not_found(format!(
            "no certificate with thumbprint {thumbprint} in the Windows store"
        ))
    })?;

    let key_type = certs::cert_info(&der, "", "", Source::OsStore)?.key_type;

    // Re-walk to get a live context for the match: the enumeration above freed
    // the one it stopped on, and CNG needs a context to acquire the key from.
    let mut key = NCRYPT_KEY_HANDLE::default();
    let mut caller_frees = false;
    let acquired = for_each_certificate(|context, candidate| {
        if certs::thumbprint(candidate) != thumbprint {
            return None;
        }
        let mut handle = NCRYPT_KEY_HANDLE::default();
        let mut key_spec = 0u32;
        let mut free = windows::Win32::Foundation::BOOL::default();
        // SAFETY: context is live here; ONLY_NCRYPT_KEY guarantees the handle
        // is an NCRYPT_KEY_HANDLE rather than a legacy CryptoAPI handle.
        let ok = unsafe {
            CryptAcquireCertificatePrivateKey(
                context,
                CRYPT_ACQUIRE_ONLY_NCRYPT_KEY_FLAG,
                None,
                &mut handle.0 as *mut _ as *mut _,
                &mut key_spec,
                Some(&mut free),
            )
        }
        .is_ok();
        ok.then(|| (handle, free.as_bool()))
    })?;

    match acquired {
        Some((handle, free)) => {
            key = handle;
            caller_frees = free;
        }
        None => {
            return Err(HostError::cert_not_found(
                "certificate found but its private key is not accessible",
            ))
        }
    }

    let result = (|| -> Result<Vec<Vec<u8>>> {
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
                            key,
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
                    let raw = ncrypt_sign(key, None, NCRYPT_SILENT_FLAG, digest)?;
                    certs::ecdsa_raw_to_der(&raw)
                })
                .collect(),
        }
    })();

    if caller_frees {
        // SAFETY: the handle came from CryptAcquireCertificatePrivateKey with
        // caller_frees set, so we own it.
        unsafe {
            let _ = NCryptFreeObject(key.into());
        }
    }
    result
}
