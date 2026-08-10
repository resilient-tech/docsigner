//! Discovery of PKCS#11 module paths.
//!
//! Priority order: the `OPENSIGNER_PKCS11_MODULES` env var, the user config
//! file, then a built-in list of well-known install paths for common tokens.
//! Only paths that exist on disk are returned.

use std::path::{Path, PathBuf};

use serde_json::Value;

pub const ENV_VAR: &str = "OPENSIGNER_PKCS11_MODULES";

pub use crate::logging::config_dir;

/// Paths harvested from a reference project (config.go) and a vendor host
/// (sdscript.js) in addition to our own research; see
/// docs/host.md.
#[cfg(target_os = "windows")]
fn well_known() -> Vec<PathBuf> {
    let system_root = std::env::var("SystemRoot").unwrap_or_else(|_| r"C:\Windows".into());
    let system32 = Path::new(&system_root).join("System32");
    let syswow64 = Path::new(&system_root).join("SysWOW64");

    let mut paths: Vec<PathBuf> = [
        // OpenSC
        "opensc-pkcs11.dll",
        // Feitian ePass2003 / ePass3003 (eMudhra, Capricorn, Sify, (n)Code, Pantasign)
        "eps2003csp11.dll",
        "eps2003csp11_v2.dll",
        "eps2003csp11v2.dll",
        "ShuttleCsp11_3000.dll",
        "ep3003csp11.dll",
        // Feitian generic / Hypersecu HyperPKI (Castle)
        "castle_v3.dll",
        "castle.dll",
        "HyperPKICsp11_2003.dll",
        // SafeNet / Aladdin / Thales eToken
        "eTPKCS11.dll",
        // WatchData ProxKey
        "SignatureP11.dll",
        "wdpkcs.dll",
        "WDPKCS11.dll",
        // eMudhra variants (Trust Key, Longmai mToken CryptoID)
        "TRUSTKEYP11.dll",
        "CryptoIDA_pkcs11.dll",
        "mToken CryptoID PKCS11.dll",
        // Bit4id tokenME
        "bit4ipki.dll",
        // Precision InnaITKey
        "InnaITPKCS11Driver.dll",
        // A.E.T. SafeSign / Athena IDProtect / YubiKey
        "aetpkcs11.dll",
        "asepkcs.dll",
        "ykcs11.dll",
    ]
    .iter()
    .map(|name| system32.join(name))
    .collect();

    for name in ["eps2003csp11v2.dll", "HyperPKICsp11_2003.dll"] {
        paths.push(syswow64.join(name));
    }

    for var in ["ProgramFiles", "ProgramFiles(x86)"] {
        let Ok(base) = std::env::var(var) else { continue };
        let base = Path::new(&base);
        paths.push(base.join(r"OpenSC Project\OpenSC\pkcs11\opensc-pkcs11.dll"));
        paths.push(base.join(r"HYP\HYP PKI Manager\pkcs11hw.dll"));
        paths.push(base.join(r"Hypersecu\HyperPKI\castle_v3.dll"));
        paths.push(base.join(r"Yubico\Yubico PIV Tool\bin\libykcs11.dll"));
    }
    paths
}

#[cfg(target_os = "macos")]
fn well_known() -> Vec<PathBuf> {
    [
        // OpenSC
        "/Library/OpenSC/lib/opensc-pkcs11.so",
        "/usr/local/lib/opensc-pkcs11.so",
        "/opt/homebrew/lib/opensc-pkcs11.so",
        "/usr/local/lib/pkcs11/opensc-pkcs11.so",
        // Feitian ePass2003 / Hypersecu HYP2003 (castle)
        "/usr/local/lib/libcastle.dylib",
        "/usr/local/lib/libcastle.1.0.0.dylib",
        "/usr/local/lib/libcastle_v2.1.0.0.dylib",
        // SafeNet eToken (libeTPkcs11 is the real basename; libeToken kept for old installs)
        "/usr/local/lib/libeTPkcs11.dylib",
        "/Library/Frameworks/eToken.framework/Versions/A/libeTPkcs11.dylib",
        "/usr/local/lib/libeToken.dylib",
        "/Library/Frameworks/eToken.framework/Versions/A/libeToken.dylib",
        // WatchData ProxKey
        "/usr/local/lib/wdProxKeyUsbKeyTool/libwdpkcs_Proxkey.dylib",
        "/usr/local/lib/libwdpkcs_SignatureP11.dylib",
        "/Library/WatchData/ProxKey/lib/libwdpkcs_SignatureP11.dylib",
        // Longmai mToken CryptoID (eMudhra)
        "/Applications/CryptoIDATools.app/Contents/MacOS/libcryptoid_pkcs11.dylib",
        // Precision InnaITKey
        "/opt/Precision_Biometric/InnaITDSC/libraries/libInnaITPKCS11Driver.dylib",
        // YubiKey
        "/usr/local/lib/libykcs11.dylib",
        "/opt/homebrew/lib/libykcs11.dylib",
    ]
    .iter()
    .map(PathBuf::from)
    .collect()
}

#[cfg(not(any(target_os = "windows", target_os = "macos")))]
fn well_known() -> Vec<PathBuf> {
    [
        // OpenSC (most EU smartcards)
        "/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so",
        "/usr/lib/opensc-pkcs11.so",
        "/usr/lib64/opensc-pkcs11.so",
        "/usr/lib/pkcs11/opensc-pkcs11.so",
        "/usr/local/lib/opensc-pkcs11.so",
        // Feitian ePass2003 (castle)
        "/usr/lib/libcastle.so",
        "/usr/lib/libcastle.so.1.0.0",
        "/usr/lib/libcastle_v2.so.1.0.0",
        "/usr/lib64/libcastle.so",
        "/usr/lib64/libcastle.so.1.0.0",
        "/usr/lib/x86_64-linux-gnu/libcastle.so.1.0.0",
        "/usr/lib/libes2003.so",
        // WatchData ProxKey
        "/usr/lib/WatchData/ProxKey/lib/libwdpkcs_SignatureP11.so",
        "/usr/lib64/WatchData/ProxKey/lib/libwdpkcs_SignatureP11.so",
        "/usr/lib/libwdpkcs_SignatureP11.so",
        "/usr/lib/libwdpkcs.so",
        "/usr/lib/libProxKeyP11.so",
        // SafeNet eToken
        "/usr/lib/libeTPkcs11.so",
        "/usr/lib/x86_64-linux-gnu/libeTPkcs11.so",
        "/usr/lib64/libeTPkcs11.so",
        "/usr/lib/libeToken.so",
        "/usr/lib64/libeToken.so",
        "/usr/lib/pkcs11/libeToken.so",
        // eMudhra variants (Trust Key, Longmai mToken CryptoID)
        "/usr/lib/TRUSTKEY/libtrustkeyP11.so",
        "/usr/lib/libtrustkeyP11.so",
        "/usr/lib/libcryptoida_pkcs11.so",
        "/opt/CryptoIDATools/bin/lib/libcryptoid_pkcs11.so",
        // Precision InnaITKey
        "/opt/Precision_Biometric/InnaITDSC/libraries/libInnaITPKCS11Driver.so",
        // YubiKey
        "/usr/lib/x86_64-linux-gnu/libykcs11.so",
        "/usr/lib/libykcs11.so",
        "/usr/lib64/libykcs11.so",
    ]
    .iter()
    .map(PathBuf::from)
    .collect()
}

/// Module paths from the user config file. Accepts a bare list or
/// `{"modules": [...]}`.
fn config_modules() -> Vec<PathBuf> {
    let path = config_dir().join("modules.json");
    let Ok(raw) = std::fs::read_to_string(&path) else {
        return Vec::new();
    };
    let Ok(parsed) = serde_json::from_str::<Value>(&raw) else {
        log::warn!("ignoring invalid JSON in {}", path.display());
        return Vec::new();
    };
    let list = match &parsed {
        Value::Object(map) => map.get("modules"),
        other => Some(other),
    };
    match list {
        Some(Value::Array(items)) => items
            .iter()
            .filter_map(|item| item.as_str())
            .map(PathBuf::from)
            .collect(),
        _ => {
            log::warn!(
                "ignoring {}: expected a list or an object with a 'modules' list",
                path.display()
            );
            Vec::new()
        }
    }
}

/// Expand a leading `~` the way Python's `os.path.expanduser` does, so a
/// config file written for the Python host keeps working.
fn expand_user(path: PathBuf) -> PathBuf {
    let Some(text) = path.to_str() else { return path };
    let Some(rest) = text.strip_prefix('~') else {
        return path;
    };
    let Some(home) = dirs::home_dir() else { return path };
    let rest = rest.trim_start_matches(std::path::MAIN_SEPARATOR).trim_start_matches('/');
    if rest.is_empty() {
        home
    } else {
        home.join(rest)
    }
}

/// PKCS#11 module paths that exist on disk, deduplicated, in priority order.
pub fn discover_modules() -> Vec<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Some(raw) = std::env::var_os(ENV_VAR) {
        // std::env::split_paths handles the platform separator (':' / ';').
        candidates.extend(std::env::split_paths(&raw).filter(|p| !p.as_os_str().is_empty()));
    }
    candidates.extend(config_modules());
    candidates.extend(well_known());

    let mut seen = std::collections::HashSet::new();
    let mut found = Vec::new();
    for candidate in candidates {
        let candidate = expand_user(candidate);
        if !seen.insert(candidate.clone()) {
            continue;
        }
        if candidate.is_file() {
            found.push(candidate);
        }
    }
    found
}

/// Lowercased basenames of the modules currently installed, joined into one
/// string. `pcsc::detect_readers` substring-matches driver hints against it.
pub fn installed_basenames() -> String {
    discover_modules()
        .iter()
        .filter_map(|p| p.file_name())
        .map(|n| n.to_string_lossy().to_lowercase())
        .collect::<Vec<_>>()
        .join(" ")
}

pub fn basename(path: &Path) -> String {
    path.file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| path.to_string_lossy().into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn well_known_paths_are_absolute_and_nonempty() {
        let paths = well_known();
        assert!(paths.len() > 10, "expected a real driver list, got {}", paths.len());
        for path in &paths {
            assert!(path.is_absolute(), "{path:?} should be absolute");
        }
    }

    #[test]
    fn env_var_paths_come_first_and_only_if_they_exist() {
        let mut file = tempfile::NamedTempFile::new().unwrap();
        file.write_all(b"not really a module").unwrap();
        let real = file.path().to_path_buf();

        temp_env(ENV_VAR, Some(&format!("/nonexistent/a.so{}{}", path_sep(), real.display())), || {
            let found = discover_modules();
            assert_eq!(found.first(), Some(&real), "existing env path should lead");
            assert!(
                !found.iter().any(|p| p.ends_with("a.so")),
                "a path that is not on disk must be dropped"
            );
        });
    }

    #[test]
    fn missing_env_var_still_returns_the_well_known_scan() {
        temp_env(ENV_VAR, None, || {
            // No assertion on contents: a dev machine has no token driver. The
            // point is that discovery runs and never panics.
            let _ = discover_modules();
        });
    }

    #[test]
    fn expand_user_resolves_a_leading_tilde() {
        let home = dirs::home_dir().unwrap();
        assert_eq!(expand_user(PathBuf::from("~/x.so")), home.join("x.so"));
        assert_eq!(expand_user(PathBuf::from("/abs/x.so")), PathBuf::from("/abs/x.so"));
    }

    #[test]
    fn basename_matches_the_module_name_field() {
        assert_eq!(basename(Path::new("/usr/lib/libcastle.so")), "libcastle.so");
    }

    fn path_sep() -> char {
        if cfg!(windows) {
            ';'
        } else {
            ':'
        }
    }

    /// Set or clear an env var for the duration of a closure. Tests that touch
    /// process env run in the same process, so restore what was there.
    fn temp_env(key: &str, value: Option<&str>, body: impl FnOnce()) {
        let previous = std::env::var_os(key);
        match value {
            Some(v) => std::env::set_var(key, v),
            None => std::env::remove_var(key),
        }
        body();
        match previous {
            Some(v) => std::env::set_var(key, v),
            None => std::env::remove_var(key),
        }
    }
}
