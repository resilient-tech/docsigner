//! Token identification via PC/SC smart-card reader names.
//!
//! The trick learned from a vendor host (docs/host.md):
//! every USB token is a CCID device, and the OS smart-card service reads its
//! reader name from the USB descriptor with no vendor driver installed. So we
//! can tell WHICH token is plugged in even when its PKCS#11 driver is missing,
//! and say "install driver X" instead of showing an empty list.
//!
//! Everything here is tolerant: any failure means "no readers", never an error.

use serde::Serialize;

use crate::modules;

/// (needles in the lowercased reader name, token model, module-basename hints).
/// Reader names harvested from a vendor host's maps plus vendor docs.
const KNOWN: &[(&[&str], &str, &[&str])] = &[
    (
        &["watchdata", "wdind", "proxkey"],
        "WatchData ProxKey",
        &["signaturep11", "wdpkcs", "proxkey"],
    ),
    (
        &["epass", "feitian", "hypersecu", "fs usb", "ft usb"],
        "Feitian ePass2003 / Hypersecu HYP2003",
        &["eps2003", "ep3003", "castle", "hyperpki", "es2003", "shuttle"],
    ),
    (
        &["aks ifdh", "safenet", "aladdin", "etoken"],
        "SafeNet eToken",
        &["etpkcs11", "etoken"],
    ),
    (&["longmai", "cryptoid"], "Longmai mToken CryptoID", &["cryptoid"]),
    (&["trustkey", "trust key"], "TrustKey", &["trustkey"]),
    (&["bit4id"], "Bit4id tokenME", &["bit4"]),
    (&["innait", "precision"], "Precision InnaITKey", &["innait"]),
    (&["yubico", "yubikey"], "YubiKey", &["ykcs11"]),
    (&["gemplus", "gemalto"], "Gemalto smartcard", &["opensc"]),
];

#[derive(Debug, Clone, Serialize)]
pub struct Reader {
    pub name: String,
    /// Model guessed from the reader name; null when unrecognised.
    pub token: Option<String>,
    #[serde(rename = "driverFound")]
    pub driver_found: bool,
}

/// (token model, driver basename hints) for a reader name.
pub fn identify(reader_name: &str) -> (Option<&'static str>, &'static [&'static str]) {
    let low = reader_name.to_lowercase();
    for (needles, token, hints) in KNOWN {
        if needles.iter().any(|needle| low.contains(needle)) {
            return (Some(token), hints);
        }
    }
    (None, &[])
}

/// Connected smart-card reader names; empty on any failure (no service, no lib).
pub fn reader_names() -> Vec<String> {
    let context = match pcsc::Context::establish(pcsc::Scope::System) {
        Ok(context) => context,
        Err(e) => {
            log::debug!("no PC/SC context: {e}");
            return Vec::new();
        }
    };
    let length = match context.list_readers_len() {
        Ok(length) if length > 0 => length,
        Ok(_) => return Vec::new(),
        Err(e) => {
            log::warn!("PC/SC reader listing failed: {e}");
            return Vec::new();
        }
    };
    let mut buffer = vec![0u8; length];
    match context.list_readers(&mut buffer) {
        Ok(readers) => readers
            .map(|name| name.to_string_lossy().into_owned())
            .filter(|name| !name.is_empty())
            .collect(),
        Err(e) => {
            log::warn!("PC/SC reader listing failed: {e}");
            Vec::new()
        }
    }
}

/// Contract-shaped reader entries: name, token model guess, driver status.
///
/// `driverFound` means a module matching the token's known driver basenames is
/// installed (per `modules::discover_modules`); false for unrecognised readers.
pub fn detect_readers() -> Vec<Reader> {
    let names = reader_names();
    if names.is_empty() {
        return Vec::new();
    }
    let installed = modules::installed_basenames();
    names
        .into_iter()
        .map(|name| {
            let (token, hints) = identify(&name);
            Reader {
                driver_found: hints.iter().any(|hint| installed.contains(hint)),
                token: token.map(str::to_string),
                name,
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identifies_known_readers_case_insensitively() {
        let (token, hints) = identify("Watchdata WDIND USB CCID Key 0");
        assert_eq!(token, Some("WatchData ProxKey"));
        assert!(hints.contains(&"wdpkcs"));

        let (token, _) = identify("FEITIAN ePass2003 00 00");
        assert_eq!(token, Some("Feitian ePass2003 / Hypersecu HYP2003"));

        let (token, _) = identify("Yubico YubiKey OTP+FIDO+CCID");
        assert_eq!(token, Some("YubiKey"));
    }

    #[test]
    fn unknown_readers_report_no_model_and_no_hints() {
        let (token, hints) = identify("Generic Smartcard Reader");
        assert_eq!(token, None);
        assert!(hints.is_empty());
    }

    #[test]
    fn reader_listing_never_panics_without_a_smartcard_service() {
        // CI has no PC/SC daemon; the contract is that this degrades to empty.
        let _ = reader_names();
        let _ = detect_readers();
    }

    #[test]
    fn every_known_entry_has_needles_and_hints() {
        for (needles, token, hints) in KNOWN {
            assert!(!needles.is_empty(), "{token} has no needles");
            assert!(!hints.is_empty(), "{token} has no driver hints");
            for needle in *needles {
                assert_eq!(*needle, needle.to_lowercase(), "needles must be lowercase");
            }
        }
    }
}
