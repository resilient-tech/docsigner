# opensigner-host (Rust)

The native messaging host, in Rust. Reads DSC token certificates over PKCS#11 and the OS certificate stores, and signs 32-byte digests with the token's private key. It never touches a PDF: the signing engine stays in Python (`core/`), and this binary only does the part that has to reach hardware.

Speaks the protocol frozen in [`CONTRACTS.md`](../CONTRACTS.md) section 2, unchanged. It is a drop-in replacement for `host/` (Python), verified against a real token.

## Why Rust here and nowhere else

`host/signer_host/` imports no pyHanko. Its whole dependency surface is `asn1crypto`, `python-pkcs11`, and the standard library, and every one of those has a mature Rust crate. The signing engine has no such equivalent: replacing pyHanko would mean hand-writing PAdES, RFC 5280 path validation, OCSP/CRL and RFC 3161, which is the wrong risk for a product whose value is that the signature holds up.

So this is the one component that moves, and the payoff is the component every browser-extension user installs:

|  | Python (PyInstaller) | Rust |
|---|---|---|
| Binary | ~45-50 MB | **942 KB** (macOS arm64, release) |
| Runtime needed | none (bundled CPython) | none (static) |
| tkinter for the PIN dialog | required | gone |
| Windows notifications | no-op | working |
| Cross-compiles | no | yes, with `cross` |

The size comes from `opt-level = "z"` with LTO and a stripped binary, plus
`native-tls`, which uses the TLS stack already on the machine rather than
bundling rustls for the sake of one JSON fetch in the update check.

## Build

```bash
cargo build --release
```

The binary lands at `target/release/opensigner-host`. No Python, no venv, no PyInstaller spec.

## Use it

```bash
opensigner-host                  # native messaging host on stdio (what the browser runs)
opensigner-host version
opensigner-host list
opensigner-host sign --thumbprint <hex> --hash <base64> --alg sha256
```

`list` and `sign` print one JSON object on stdout, which is also how the desktop app calls it. In host mode stdout carries protocol frames only; everything else goes to the log file that `getVersion` reports.

### Environment

| Variable | Effect |
|---|---|
| `OPENSIGNER_PKCS11_MODULES` | extra module paths, `:`-separated (`;` on Windows) |
| `OPENSIGNER_PIN` | skip the PIN dialog |
| `OPENSIGNER_NO_NOTIFY` | suppress signing notifications |
| `OPENSIGNER_UPDATE_URL` | JSON feed for the update check |

Module paths also come from `~/.config/opensigner/modules.json` (`%APPDATA%\opensigner\modules.json` on Windows), then a built-in list of well-known driver locations for OpenSC, ePass2003, ProxKey, SafeNet, eMudhra, Bit4id, InnaITKey and YubiKey.

## Layout

| File | What it does | Ported from |
|---|---|---|
| `main.rs` | stdio loop, CLI entry | `main.py` |
| `cli.rs` | `version` / `list` / `sign` | `cli.py` |
| `framing.rs` | 4-byte LE + UTF-8 JSON | `framing.py` |
| `protocol.rs` | dispatch, diagnostics, fallback order | `protocol.py` |
| `error.rs` | the eight wire codes | `errors.py` |
| `certs.rs` | DER to contract JSON, DigestInfo, ECDSA DER | `certs.py` |
| `modules.rs` | driver path discovery | `modules.py` |
| `pkcs11.rs` | scan, find, login, sign | `pkcs11_ops.py` |
| `os_store/` | Keychain, Windows MY, Linux stub | `os_store.py` |
| `pcsc_readers.rs` | reader identification | `pcsc.py` |
| `procs.rs` | competing token holders | `procs.py` |
| `pin.rs` | PIN dialogs | `pin.py` |
| `notify.rs` | desktop notifications | `notify.py` |
| `update.rs` | version check | `update.py` |
| `logging.rs` | file log under the config dir | (was inline in `main.py`) |

## Three behaviours that must not be refactored away

Each came out of live testing against real Indian DSC tokens, and each is marked at its call site.

**Fresh `C_Initialize` per scan.** WatchData ProxKey enumerates the token only at `C_Initialize`. After a replug or a USB sleep, a cached handle reports the token gone and every listing returns empty until the process dies. A new `Pkcs11` per scan gives this for free, since `Drop` calls `C_Finalize`. The Python host needed an explicit `reinitialize()` because python-pkcs11 cached the module process-wide.

**Per-slot iteration.** ProxKey exposes several reader slots and returns `CKR_DEVICE_REMOVED` for the empty ones. A bulk `get_slots_with_token()` aborts the whole scan on the first such slot, hiding a real token sitting in another. Every slot is walked individually and the failures are skipped.

**The 20-second per-module watchdog.** A hung driver must not spend the browser's 120-second native messaging timeout. Same ceiling as the Python version: the abandoned thread stays alive holding the module, because neither language can kill a thread stuck in a C call. The process-level fix is the wedged-scan restart in `protocol.rs`.

## Testing

```bash
cargo test
```

69 tests, no hardware required. They cover the framing edge cases, the RFC 8017 DigestInfo bytes, ECDSA INTEGER padding, error-code mapping, dispatch and parameter validation, and they assert invariants that hold whether or not a token is plugged in.

### What tests cannot cover

**Signing against a real token.** It needs the token holder's PIN, so it is a manual step:

```bash
opensigner-host list
OPENSIGNER_PIN=<your-pin> opensigner-host sign --thumbprint <hex> --hash $(printf 'x' | shasum -a 256 | cut -d' ' -f1 | xxd -r -p | base64)
```

Do not script a PIN guess. These tokens lock after a small number of wrong attempts and only the vendor tool can unlock them.

**The Windows store path.** `os_store/windows.rs` compiles only on Windows and has not been run. Treat it as unverified until it is built and exercised on a real Windows box with a token.

## Verified against the Python host

On a WatchData ProxKey with three Capricorn DSCs, `listCertificates` returns a payload byte-identical to the Python host's: 10886 bytes from each, zero field-level differences across all three certificates, matching `readers` and `diagnostics`. Driven over real Chrome framing it multiplexes request ids, returns `UNSUPPORTED` for unknown commands, and exits cleanly at EOF.

Reproduce it with `scripts/compare_hosts.py`.
