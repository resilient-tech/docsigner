//! OS certificate store backend: macOS Keychain and Windows MY store.
//!
//! another vendor's host reads the OS store first (docs/host.md): token
//! drivers usually register the token's certificate there on install, so the
//! certificate is found with no driver-path configuration, and the private-key
//! operation routes back through the same OS API, which forwards it to the
//! token. This module mirrors that. Linux has no universal OS store; there it
//! lists nothing and PKCS#11 stays the only path.
//!
//! Same contract shape as `pkcs11`: entries carry `source = "os-store"`,
//! `moduleName = "os-store"`, `tokenLabel` = store name. The OS shows its own
//! unlock/PIN dialog during signing, so `pin.rs` is never involved here.

use crate::certs::{self, CertInfo, DigestAlg, Source};
use crate::error::{HostError, Result};

#[cfg_attr(target_os = "macos", path = "macos.rs")]
#[cfg_attr(target_os = "windows", path = "windows.rs")]
#[cfg_attr(not(any(target_os = "macos", target_os = "windows")), path = "stub.rs")]
mod platform;

/// The store name reported as `tokenLabel`.
pub const STORE_LABEL: &str = platform::STORE_LABEL;

fn entry(der: &[u8], token_label: &str) -> Result<CertInfo> {
    certs::cert_info(der, token_label, "os-store", Source::OsStore)
}

/// Contract-shaped entries from the OS store; empty where none exists.
///
/// Tolerant like the PKCS#11 scan: a broken store read is logged and yields
/// nothing rather than hiding certificates found on tokens.
pub fn list_certificates() -> Vec<CertInfo> {
    let ders = match platform::list_der() {
        Ok(ders) => ders,
        Err(e) => {
            log::warn!("OS store listing failed: {e}");
            return Vec::new();
        }
    };
    ders.into_iter()
        .filter(|der| certs::signing_capable(der))
        .filter_map(|der| match entry(&der, STORE_LABEL) {
            Ok(info) => Some(info),
            Err(e) => {
                log::warn!("skipping unparseable {STORE_LABEL} certificate: {e}");
                None
            }
        })
        .collect()
}

/// Sign raw digests with the OS-store key matching the thumbprint.
///
/// Raises `CERT_NOT_FOUND` when the platform has no OS store or the certificate
/// is not in it, so callers can fall back or report cleanly.
pub fn sign_hashes(thumbprint: &str, digests: &[Vec<u8>], alg: DigestAlg) -> Result<Vec<Vec<u8>>> {
    if digests.is_empty() {
        return Err(HostError::internal("hashes must be a non-empty list"));
    }
    platform::sign(&thumbprint.trim().to_lowercase(), digests, alg)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Runs against whatever this machine's store holds. On Linux it must be
    /// empty; elsewhere every entry must be contract-shaped and signing-capable.
    #[test]
    fn listing_is_contract_shaped_on_every_platform() {
        let found = list_certificates();
        if cfg!(not(any(target_os = "macos", target_os = "windows"))) {
            assert!(found.is_empty(), "Linux has no universal OS store");
        }
        for info in &found {
            assert_eq!(info.thumbprint.len(), 40);
            assert_eq!(info.module_name, "os-store");
            assert_eq!(info.token_label, STORE_LABEL);
            assert!(
                info.key_usage.digital_signature || info.key_usage.non_repudiation,
                "the listing must filter to signing-capable certificates"
            );
        }
    }

    #[test]
    fn signing_an_unknown_thumbprint_reports_cert_not_found() {
        let error = sign_hashes("00".repeat(20).as_str(), &[vec![0u8; 32]], DigestAlg::Sha256)
            .expect_err("an all-zero thumbprint is not in any store");
        assert_eq!(error.code, crate::error::Code::CertNotFound);
        assert!(error.allows_os_store_fallback());
    }

    #[test]
    fn signing_an_empty_batch_is_rejected() {
        let error = sign_hashes("abcd", &[], DigestAlg::Sha256).unwrap_err();
        assert_eq!(error.code, crate::error::Code::Internal);
    }
}
