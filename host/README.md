# docsigner-host (Rust)

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

The binary lands at `target/release/docsigner-host`. No Python, no venv, no PyInstaller spec.

## Releasing

Merge into `master`. `.github/workflows/release.yml` builds every platform, publishes the archives with a `SHA256SUMS`, and writes the `latest.json` the `checkUpdate` command reads.

Work lands on `develop`. When a batch of it is ready, bump the version and merge:

```bash
python scripts/bump_version.py     # 0.2.0 -> 0.2.1, in three files
git commit -am "chore(release): v0.2.1"
```

The version in `Cargo.toml` is the host's own, bumped only when `host/` changes (`python scripts/bump_version.py host`). The release tag comes from `VERSION` at the repo root. A merge that forgot either bump fails in the first job, before anything builds. Run the workflow from the Actions tab (`workflow_dispatch`) to build without publishing.

**One download per OS, and the architecture is not the user's problem.** Each choice is deliberate and the reasoning is written into the workflow so nobody removes it:

| OS | Built for | Why not the other one |
|---|---|---|
| macOS | x86_64 | Runs on every Mac through Rosetta. An x86_64 process can load an x86_64-only PKCS#11 driver; an arm64 process cannot, and some Indian CA middleware still ships x86_64 only. |
| Windows | x64 | The token middleware is x64. An ARM64-native build could not load it, while the x64 build runs emulated on ARM and loads the driver normally. |
| Linux | oldest supported Ubuntu | glibc is backward but not forward compatible, so building on the newest runner would refuse to start on older distros. |

Measured rather than assumed: the x86_64 build, cross-compiled on an arm64 Mac, lists all three certificates off a real ProxKey under Rosetta. That token's own dylib happens to be universal, so this is insurance against the vendors that have not caught up rather than a fix for that one.

### macOS, without a signing certificate

`packaging/homebrew/docsigner-host.rb` installs the released archive as a Homebrew formula:

```bash
brew install resilient-tech/tap/docsigner-host
```

Homebrew stamps `com.apple.quarantine` on casks only, never on formulae, so a formula-installed binary runs with no Gatekeeper prompt and no Apple Developer ID. Copy the file into the tap repo and update `sha256` from the release's `SHA256SUMS` when tagging. A direct download of the same `.tar.gz` is quarantined and needs one `xattr -dr com.apple.quarantine` before it runs.

## Use it

```bash
docsigner-host                  # native messaging host on stdio (what the browser runs)
docsigner-host version
docsigner-host list
docsigner-host sign --thumbprint <hex> --hash <base64> --alg sha256
```

`list` and `sign` print one JSON object on stdout, which is also how the desktop app calls it. In host mode stdout carries protocol frames only; everything else goes to the log file that `getVersion` reports.

### Environment

| Variable | Effect |
|---|---|
| `DOCSIGNER_PKCS11_MODULES` | extra module paths, `:`-separated (`;` on Windows) |
| `DOCSIGNER_PIN` | skip the PIN dialog |
| `DOCSIGNER_NO_NOTIFY` | suppress signing notifications |
| `DOCSIGNER_UPDATE_URL` | JSON feed for the update check; defaults to this repo's `latest.json` |

Module paths also come from `~/.config/docsigner/modules.json` (`%APPDATA%\docsigner\modules.json` on Windows), then a built-in list of well-known driver locations for OpenSC, ePass2003, ProxKey, SafeNet, eMudhra, Bit4id, InnaITKey and YubiKey.

## Layout

Every file, one line each: [`../docs/host.md`](../docs/host.md#module-map-where-things-live).

## Three behaviours that must not be refactored away

Each came out of live testing against real Indian DSC tokens, and each is marked at its call site.

**Fresh `C_Initialize` per scan.** WatchData ProxKey enumerates the token only at `C_Initialize`. After a replug or a USB sleep, a cached handle reports the token gone and every listing returns empty until the process dies. A new `Pkcs11` per scan gives this for free, since `Drop` calls `C_Finalize`. The Python host needed an explicit `reinitialize()` because python-pkcs11 cached the module process-wide.

**Per-slot iteration.** ProxKey exposes several reader slots and returns `CKR_DEVICE_REMOVED` for the empty ones. A bulk `get_slots_with_token()` aborts the whole scan on the first such slot, hiding a real token sitting in another. Every slot is walked individually and the failures are skipped.

**The 20-second per-module watchdog.** A hung driver must not spend the browser's 120-second native messaging timeout. Same ceiling as the Python version: the abandoned thread stays alive holding the module, because neither language can kill a thread stuck in a C call. The process-level fix is the wedged-scan restart in `protocol.rs`.

## Testing

```bash
cargo test
```

No hardware required. They cover the framing edge cases, the RFC 8017 DigestInfo bytes, ECDSA INTEGER padding, error-code mapping, dispatch and parameter validation, and they assert invariants that hold whether or not a token is plugged in.

### What tests cannot cover

**Signing against a real token.** It needs the token holder's PIN, so it stays a manual step:

```bash
docsigner-host list
DOCSIGNER_PIN=<your-pin> docsigner-host sign --thumbprint <hex> --hash $(printf 'x' | shasum -a 256 | cut -d' ' -f1 | xxd -r -p | base64)
```

Never script a PIN guess. These tokens lock after a small number of wrong attempts and only the vendor tool can unlock them, so test the failure paths against SoftHSM, not hardware.

**The Windows store path.** `os_store/windows.rs` compiles only on Windows and has not been run. Treat it as unverified until it is built and exercised on a real Windows box with a token. It is the riskiest file in the crate: raw CNG calls, and `sign` walks the store twice because the enumeration frees the context it stops on.

## Verified against real hardware

On a WatchData ProxKey carrying three Capricorn DSCs (2026-08-11, macOS arm64):

**Listing.** `listCertificates` returned a payload byte-identical to the Python host's: 10886 bytes from each, zero field-level differences across all three certificates, matching `readers` and `diagnostics`.

That comparison ran against `host/`, the Python host this replaced, which was removed once the Rust one became the default. To reproduce it, check the Python host and the harness out of history:

```bash
git checkout 4c45006 -- host scripts/compare_hosts.py
pip install -e ./host && python scripts/compare_hosts.py
```

The harness drives the Rust host over real native messaging framing and diffs every command's JSON against the Python host's, comparing certificates order-independently.

**Signing.** Every signature was checked three ways: it verifies against the certificate's public key, it is byte-identical to the Python host's (PKCS#1 v1.5 is deterministic, so it has to be), and a batch keeps its order.

| Check | Result |
|---|---|
| sha256 / sha384 / sha512 | 256-byte signatures, all verify, all identical to Python |
| Batch of 3 in one login | all verify, signature *i* belongs to digest *i* |
| Second certificate on the same token | verifies against its own certificate and correctly fails against the other, so `find_private_key` matched by CKA_ID rather than defaulting to the only key |
| Unknown thumbprint | `CERT_NOT_FOUND` |
| PIN cache | one supplied PIN served a later request with no PIN and no dialog available |
| Wrong PIN | reported `PIN_INCORRECT` only after the fix below |

### The wrong-PIN finding

One deliberate wrong-PIN attempt exposed a defect **both hosts shared**: a WatchData ProxKey rejects a wrong PIN with `CKR_GENERAL_ERROR`, not `CKR_PIN_INCORRECT`. Matching the return value alone therefore reported `INTERNAL`, with two consequences:

- the page could not tell the user their PIN was wrong, only that something failed;
- the stale-cached-PIN retry never fired, because it keyed off `PIN_INCORRECT`. A PIN changed on the token would fail every call for the full ten-minute cache TTL.

`map_login_rv` now reads the vague return values (`CKR_GENERAL_ERROR`, `CKR_FUNCTION_FAILED`) as a rejected PIN when they come from `C_Login` specifically, where the module has already loaded and the certificate has already been found. `map_login_error` consults the token's own `user_pin_locked` flag first, since that is authoritative and a locked PIN must never be retried.

Any future backend has the same trap waiting: a token that rejects a PIN with a generic error code, and a retry path keyed on `PIN_INCORRECT` that then never fires.

**End to end.** A PDF signed through `docsigner-core` with the token via this host validates as `valid: true, intact: true, modifications_ok: true`, and `trusted: true` against the repo's `trust/` anchors up the Capricorn chain to CCA India.

**Through the desktop app.** With `DOCSIGNER_HOST_BIN` pointed at this binary, the desktop backend lists all three certificates and bulk-signs four files on one PIN, every signature verifying.

Not verified: wrong-PIN and locked-PIN handling, which cannot be exercised on hardware without risking a lockout.
