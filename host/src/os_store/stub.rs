//! Linux and everything else: no OS certificate store to ask.
//!
//! The driver is the only way in here, so this finds nothing and says so. That
//! is what lets the token's own error be the one the user sees.

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
