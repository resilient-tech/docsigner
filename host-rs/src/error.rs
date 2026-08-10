//! The eight error codes CONTRACTS.md section 2 allows on the wire, and nothing else.
//!
//! Dispatch never propagates an error out of the process: `protocol::handle`
//! turns every `HostError` into an `{id, error: {code, message}}` response.

use std::fmt;

use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum Code {
    #[serde(rename = "USER_CANCELLED")]
    UserCancelled,
    #[serde(rename = "PIN_INCORRECT")]
    PinIncorrect,
    #[serde(rename = "PIN_LOCKED")]
    PinLocked,
    #[serde(rename = "TOKEN_NOT_FOUND")]
    TokenNotFound,
    #[serde(rename = "CERT_NOT_FOUND")]
    CertNotFound,
    #[serde(rename = "MODULE_ERROR")]
    ModuleError,
    #[serde(rename = "UNSUPPORTED")]
    Unsupported,
    #[serde(rename = "INTERNAL")]
    Internal,
}

impl Code {
    pub fn as_str(self) -> &'static str {
        match self {
            Code::UserCancelled => "USER_CANCELLED",
            Code::PinIncorrect => "PIN_INCORRECT",
            Code::PinLocked => "PIN_LOCKED",
            Code::TokenNotFound => "TOKEN_NOT_FOUND",
            Code::CertNotFound => "CERT_NOT_FOUND",
            Code::ModuleError => "MODULE_ERROR",
            Code::Unsupported => "UNSUPPORTED",
            Code::Internal => "INTERNAL",
        }
    }
}

#[derive(Debug, Clone)]
pub struct HostError {
    pub code: Code,
    pub message: String,
}

impl HostError {
    pub fn new(code: Code, message: impl Into<String>) -> Self {
        HostError { code, message: message.into() }
    }

    pub fn internal(message: impl Into<String>) -> Self {
        HostError::new(Code::Internal, message)
    }

    pub fn unsupported(message: impl Into<String>) -> Self {
        HostError::new(Code::Unsupported, message)
    }

    pub fn cert_not_found(message: impl Into<String>) -> Self {
        HostError::new(Code::CertNotFound, message)
    }

    pub fn cancelled(message: impl Into<String>) -> Self {
        HostError::new(Code::UserCancelled, message)
    }

    /// Whether a PKCS#11 failure should let the OS store have a try.
    ///
    /// Mirrors protocol.py `_sign_with_fallback`: only not-found outcomes fall
    /// through. A wrong or locked PIN, or a cancelled dialog, is the user's
    /// answer and must surface as-is.
    pub fn allows_os_store_fallback(&self) -> bool {
        matches!(self.code, Code::TokenNotFound | Code::CertNotFound | Code::ModuleError)
    }
}

impl fmt::Display for HostError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for HostError {}

pub type Result<T> = std::result::Result<T, HostError>;
