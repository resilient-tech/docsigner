//! Serialised, self-restoring environment variables for tests.
//!
//! cargo runs tests as threads inside one process, so `set_var` and
//! `remove_var` are global mutations that race. This is not theoretical: two
//! tests sharing `DOCSIGNER_UPDATE_URL` turned CI red on Windows while the
//! same commit passed on Linux and macOS, because one removed the variable
//! between the other's set and read.
//!
//! Every test that touches process environment takes this guard. Holding it
//! serialises them against each other, and dropping it puts back whatever was
//! there before, so a panicking test cannot leak state into the next one.

use std::ffi::OsString;
use std::sync::{Mutex, MutexGuard, OnceLock};

fn env_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}

pub struct EnvGuard {
    // (key, what was there before), restored in reverse on drop.
    saved: Vec<(&'static str, Option<OsString>)>,
    // Held for the guard's lifetime; the field is the point, not its value.
    _lock: MutexGuard<'static, ()>,
}

impl EnvGuard {
    /// Take the lock and start recording.
    ///
    /// The lock is not reentrant: two live guards in one scope deadlock rather
    /// than fail, and `let _guard = …` twice in a row shadows without dropping.
    /// Give each guard its own block when a test needs more than one.
    pub fn new() -> Self {
        EnvGuard {
            saved: Vec::new(),
            // A test that panicked while holding the lock poisons it. The env
            // is restored by Drop regardless, so the guard is still usable.
            _lock: env_lock().lock().unwrap_or_else(|e| e.into_inner()),
        }
    }

    pub fn set(mut self, key: &'static str, value: &str) -> Self {
        self.remember(key);
        std::env::set_var(key, value);
        self
    }

    pub fn unset(mut self, key: &'static str) -> Self {
        self.remember(key);
        std::env::remove_var(key);
        self
    }

    fn remember(&mut self, key: &'static str) {
        if !self.saved.iter().any(|(seen, _)| *seen == key) {
            self.saved.push((key, std::env::var_os(key)));
        }
    }
}

impl Drop for EnvGuard {
    fn drop(&mut self) {
        for (key, previous) in self.saved.drain(..).rev() {
            match previous {
                Some(value) => std::env::set_var(key, value),
                None => std::env::remove_var(key),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Each test below owns a distinct key, so the unguarded set_var/remove_var
    // calls used to arrange the "before" state cannot collide with anything.
    const KEY: &str = "DOCSIGNER_TESTENV_PROBE";

    #[test]
    fn restores_a_variable_that_was_absent() {
        std::env::remove_var(KEY);
        {
            let _guard = EnvGuard::new().set(KEY, "value");
            assert_eq!(std::env::var(KEY).as_deref(), Ok("value"));
        }
        assert!(std::env::var_os(KEY).is_none(), "must be removed again");
    }

    #[test]
    fn restores_a_variable_that_was_present() {
        const OWN: &str = "DOCSIGNER_TESTENV_PROBE_PRESENT";
        std::env::set_var(OWN, "original");
        {
            let _guard = EnvGuard::new().set(OWN, "overridden");
            assert_eq!(std::env::var(OWN).as_deref(), Ok("overridden"));
        }
        assert_eq!(std::env::var(OWN).as_deref(), Ok("original"));
        std::env::remove_var(OWN);
    }

    #[test]
    fn handles_several_variables_and_a_repeated_key() {
        const A: &str = "DOCSIGNER_TESTENV_PROBE_A";
        const B: &str = "DOCSIGNER_TESTENV_PROBE_B";
        std::env::remove_var(A);
        std::env::remove_var(B);
        {
            // Setting A twice must still restore to "absent", not to the
            // intermediate value.
            let _guard = EnvGuard::new().set(A, "one").set(B, "two").set(A, "three");
            assert_eq!(std::env::var(A).as_deref(), Ok("three"));
            assert_eq!(std::env::var(B).as_deref(), Ok("two"));
        }
        assert!(std::env::var_os(A).is_none());
        assert!(std::env::var_os(B).is_none());
    }

    #[test]
    fn restores_on_panic() {
        const OWN: &str = "DOCSIGNER_TESTENV_PROBE_PANIC";
        std::env::remove_var(OWN);
        let result = std::panic::catch_unwind(|| {
            let _guard = EnvGuard::new().set(OWN, "set");
            panic!("boom");
        });
        assert!(result.is_err());
        assert!(
            std::env::var_os(OWN).is_none(),
            "a panicking test must not leak its environment"
        );
    }
}
