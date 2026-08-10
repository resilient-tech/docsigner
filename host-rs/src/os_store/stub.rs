//! Linux and everything else: no universal OS certificate store.
//!
//! PKCS#11 is the only path here, so listing yields nothing and signing reports
//! `CERT_NOT_FOUND`, which is what lets `protocol` keep the PKCS#11 error as the
//! one it surfaces.

use crate::certs::DigestAlg;
use crate::error::{HostError, Result};

pub const STORE_LABEL: &str = "none";

pub fn list_der() -> Result<Vec<Vec<u8>>> {
    Ok(Vec::new())
}

pub fn sign(_thumbprint: &str, _digests: &[Vec<u8>], _alg: DigestAlg) -> Result<Vec<Vec<u8>>> {
    Err(HostError::cert_not_found(
        "this platform has no OS certificate store",
    ))
}
