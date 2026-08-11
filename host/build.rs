//! Embeds the DocSigner logo and version metadata in the Windows .exe, so the
//! host is recognisable in Explorer, Task Manager and the Details tab rather
//! than showing the blank generic-executable icon.
//!
//! No-op on macOS and Linux, where an executable carries no icon resource.
//! The Windows release build runs natively on windows-latest with MSVC (see
//! .github/workflows/release.yml), so the resource compiler is always present.

fn main() {
    #[cfg(windows)]
    {
        println!("cargo:rerun-if-changed=packaging/icon.ico");
        winresource::WindowsResource::new()
            .set_icon("packaging/icon.ico")
            .compile()
            .expect("embedding the Windows icon resource failed");
    }
}
