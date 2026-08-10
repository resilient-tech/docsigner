//! macOS Keychain backend.
//!
//! Identities (certificate + private key) are read with `SecItemCopyMatching`
//! and signed with `SecKeyCreateSignature`. The `…Digest…` algorithms take the
//! digest bytes directly: Security wraps the DigestInfo for RSA and returns a
//! DER `ECDSA-Sig-Value` for EC, which is exactly the shape the contract wants,
//! so unlike the PKCS#11 and CNG paths nothing needs converting afterwards.

use security_framework::identity::SecIdentity;
use security_framework::item::{ItemClass, ItemSearchOptions, Limit, Reference, SearchResult};
use security_framework::key::Algorithm;

use crate::certs::{self, DigestAlg, KeyType, Source};
use crate::error::{HostError, Result};

pub const STORE_LABEL: &str = "keychain";

/// `errSecItemNotFound`. An empty keychain is not a failure, and Security
/// reports it as an error status rather than an empty result.
const ERR_SEC_ITEM_NOT_FOUND: i32 = -25300;

/// `errSecUserCanceled`, the user dismissing the Keychain access prompt.
const ERR_SEC_USER_CANCELED: i32 = -128;

/// (identity, DER) for every identity in the user's keychains.
fn identities() -> Result<Vec<(SecIdentity, Vec<u8>)>> {
    let results = match ItemSearchOptions::new()
        .class(ItemClass::identity())
        .load_refs(true)
        .limit(Limit::All)
        .search()
    {
        Ok(results) => results,
        Err(e) if e.code() == ERR_SEC_ITEM_NOT_FOUND => return Ok(Vec::new()),
        Err(e) => return Err(HostError::internal(format!("Keychain query failed: {e}"))),
    };

    let mut found = Vec::new();
    for result in results {
        let SearchResult::Ref(Reference::Identity(identity)) = result else {
            continue;
        };
        match identity.certificate() {
            Ok(certificate) => {
                let der = certificate.to_der();
                found.push((identity, der));
            }
            Err(e) => log::warn!("skipping a Keychain identity with no certificate: {e}"),
        }
    }
    Ok(found)
}

pub fn list_der() -> Result<Vec<Vec<u8>>> {
    Ok(identities()?.into_iter().map(|(_, der)| der).collect())
}

fn algorithm(key_type: KeyType, alg: DigestAlg) -> Algorithm {
    match (key_type, alg) {
        (KeyType::Rsa, DigestAlg::Sha256) => Algorithm::RSASignatureDigestPKCS1v15SHA256,
        (KeyType::Rsa, DigestAlg::Sha384) => Algorithm::RSASignatureDigestPKCS1v15SHA384,
        (KeyType::Rsa, DigestAlg::Sha512) => Algorithm::RSASignatureDigestPKCS1v15SHA512,
        (KeyType::Ec, DigestAlg::Sha256) => Algorithm::ECDSASignatureDigestX962SHA256,
        (KeyType::Ec, DigestAlg::Sha384) => Algorithm::ECDSASignatureDigestX962SHA384,
        (KeyType::Ec, DigestAlg::Sha512) => Algorithm::ECDSASignatureDigestX962SHA512,
    }
}

pub fn sign(thumbprint: &str, digests: &[Vec<u8>], alg: DigestAlg) -> Result<Vec<Vec<u8>>> {
    let (identity, der) = identities()?
        .into_iter()
        .find(|(_, der)| certs::thumbprint(der) == thumbprint)
        .ok_or_else(|| {
            HostError::cert_not_found(format!(
                "no certificate with thumbprint {thumbprint} in the Keychain"
            ))
        })?;

    let key_type = certs::cert_info(&der, "", "", Source::OsStore)?.key_type;
    let key = identity.private_key().map_err(|e| {
        log::warn!("Keychain private key unavailable: {e}");
        HostError::cert_not_found("certificate found but its private key is not accessible")
    })?;

    let algorithm = algorithm(key_type, alg);
    digests
        .iter()
        .map(|digest| {
            key.create_signature(algorithm, digest).map_err(|e| {
                // The user dismissing the Keychain prompt is a cancellation,
                // not a failure.
                if e.code() == ERR_SEC_USER_CANCELED as isize {
                    HostError::cancelled("Keychain access was cancelled")
                } else {
                    HostError::internal(format!("Keychain signing failed: {e}"))
                }
            })
        })
        .collect()
}
