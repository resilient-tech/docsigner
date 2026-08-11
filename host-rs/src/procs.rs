//! Programs that can hold a token's single PKCS#11 session.
//!
//! ePass/ProxKey-class drivers allow one process on the token at a time; a
//! vendor utility, another browser's host, or a third-party signing host
//! silently makes every scan come back empty. Naming the culprit beats
//! "replug and retry".
//! Tolerant like `pcsc_readers`: any failure means "nothing found", never an error.
//!
//! ponytail: shells out to ps/tasklist rather than pulling sysinfo, which is
//! ~500 KB of crate for one process list on a path that only runs when a scan
//! already came back empty.

use std::process::Command;

/// Lowercase needle in the process name -> what to tell the user to close.
const KNOWN: &[(&str, &str)] = &[
    ("docsigner-host", "another DocSigner host"),
    ("webpki", "a Web PKI signing host"),
    ("epass", "the ePass token manager"),
    ("proxkey", "the ProxKey token tool"),
    ("wdtoken", "the WatchData token tool"),
    ("etoken", "SafeNet Authentication Client"),
    ("safenet", "SafeNet Authentication Client"),
    ("cryptoida", "the mToken CryptoID tool"),
    ("trustkey", "the TrustKey tool"),
];

/// Display names of running programs likely holding the token, deduplicated.
///
/// Our own process is excluded. ponytail: self = this pid only; Rust has no
/// PyInstaller parent/child pair to filter, unlike the Python host.
pub fn competing() -> Vec<String> {
    let own = std::process::id();
    let mut found: Vec<String> = Vec::new();
    for (pid, name) in process_list() {
        if pid == own {
            continue;
        }
        for (needle, label) in KNOWN {
            if name.contains(needle) && !found.iter().any(|f| f == label) {
                found.push((*label).to_string());
            }
        }
    }
    found
}

/// (pid, lowercased process name) for every visible process; empty on failure.
fn process_list() -> Vec<(u32, String)> {
    #[cfg(target_os = "windows")]
    let output = Command::new("tasklist")
        .args(["/fo", "csv", "/nh"])
        .output();
    #[cfg(not(target_os = "windows"))]
    let output = Command::new("ps").args(["-A", "-o", "pid=,comm="]).output();

    let Ok(output) = output else {
        return Vec::new();
    };
    let text = String::from_utf8_lossy(&output.stdout);

    #[cfg(target_os = "windows")]
    {
        parse_tasklist(&text)
    }
    #[cfg(not(target_os = "windows"))]
    {
        parse_ps(&text)
    }
}

#[cfg(not(target_os = "windows"))]
fn parse_ps(text: &str) -> Vec<(u32, String)> {
    let mut rows = Vec::new();
    for line in text.lines() {
        let line = line.trim();
        let Some((pid, name)) = line.split_once(' ') else {
            continue;
        };
        let Ok(pid) = pid.trim().parse::<u32>() else {
            continue;
        };
        let name = name.trim();
        if name.is_empty() {
            continue;
        }
        let base = name.rsplit('/').next().unwrap_or(name);
        rows.push((pid, base.to_lowercase()));
    }
    rows
}

#[cfg(target_os = "windows")]
fn parse_tasklist(text: &str) -> Vec<(u32, String)> {
    let mut rows = Vec::new();
    for line in text.lines() {
        // "name.exe","1234","Console","1","10,000 K"
        let parts: Vec<&str> = line.split("\",\"").collect();
        if parts.len() < 2 {
            continue;
        }
        let name = parts[0].trim_matches('"');
        let Ok(pid) = parts[1].trim_matches('"').parse::<u32>() else {
            continue;
        };
        rows.push((pid, name.to_lowercase()));
    }
    rows
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn competing_never_panics() {
        let _ = competing();
    }

    /// Runs the real ps/tasklist and checks the parse, since the format is the
    /// only thing likely to drift.
    ///
    /// Deliberately no assertion that every pid is non-zero: Windows lists the
    /// System Idle Process as pid 0, which is a real row, not a parse failure.
    #[test]
    fn the_real_process_list_parses() {
        let list = process_list();
        assert!(!list.is_empty(), "expected at least one visible process");
        assert!(
            list.iter().all(|(_, name)| !name.is_empty()),
            "a parsed row must carry a name, or the needle match below is dead"
        );
        assert!(
            list.iter().all(|(_, name)| name == &name.to_lowercase()),
            "names are lowercased so the KNOWN needles can match"
        );
        // Our own process must be in there, which is what `competing` filters on.
        let own = std::process::id();
        assert!(
            list.iter().any(|(pid, _)| *pid == own),
            "the running test process should appear in its own process list"
        );
    }

    #[cfg(not(target_os = "windows"))]
    #[test]
    fn parses_ps_output() {
        let sample = "  501 /usr/sbin/cfprefsd\n  777 WatchData-ProxKey\n bad line\n";
        let rows = parse_ps(sample);
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0], (501, "cfprefsd".to_string()));
        assert_eq!(rows[1], (777, "watchdata-proxkey".to_string()));
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn parses_tasklist_output() {
        let sample = "\"eToken.exe\",\"1234\",\"Console\",\"1\",\"10,000 K\"\n";
        let rows = parse_tasklist(sample);
        assert_eq!(rows, vec![(1234, "etoken.exe".to_string())]);
    }

    #[test]
    fn known_needles_are_lowercase() {
        for (needle, label) in KNOWN {
            assert_eq!(*needle, needle.to_lowercase());
            assert!(!label.is_empty());
        }
    }
}
