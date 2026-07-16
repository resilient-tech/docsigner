# signer-host (opensigner-host)

The native app that reaches a USB token or smartcard. The browser extension
speaks to it over native messaging; it reads certificates and signs hashes over
PKCS#11 (or the OS certificate store on macOS and Windows). The PIN prompt
happens here, in a native dialog, so the PIN never touches the browser or the
network. The desktop app uses the same host.

New here? Read [`../docs/host.md`](../docs/host.md) first — plain words and a
flow chart of how a request flows.

Two executables, one package:

- `opensigner-host` (`main.py`) speaks the native messaging protocol on
  stdin/stdout. Browsers launch this one.
- `opensigner-host-cli` (`cli.py`) runs the same commands from a terminal, for
  testing and scripting.

## Install (development)

```bash
pip install -e ./host
opensigner-host-cli list         # prints the certificates on your token
```

Your token's driver must be installed first; it ships the PKCS#11 module the
host loads.

CLI commands: `version`, `list`, `sign` (signs one or more base64 digests). Run
`opensigner-host-cli <command> -h` for options.

## Pack it (single-file binary)

Users should not need Python. Build a standalone binary for the OS you are on
(PyInstaller does not cross-compile):

```bash
pip install pyinstaller
pyinstaller host/packaging/opensigner-host.spec
```

Then register it with the installed browsers, passing the extension ID that
`chrome://extensions` showed when you loaded the extension:

```bash
host/packaging/install.sh <chrome-extension-id>     # macOS / Linux
host\packaging\install.bat <chrome-extension-id>    # Windows
```

The installer copies the binary and writes the native messaging manifests for
Chrome, Chromium, Edge, Brave, and Firefox (templates in `packaging/manifests/`).
For distribution, sign the binary: Authenticode on Windows, notarization on
macOS.

## Token configuration

Known PKCS#11 module paths ship for OpenSC, ePass2003, WatchData ProxKey,
SafeNet eToken, and eMudhra. For anything else, point the host at the module:

```bash
export OPENSIGNER_PKCS11_MODULES=/path/to/your/pkcs11.so
```

or add it to `~/.config/opensigner/modules.json`
(`%APPDATA%\opensigner\modules.json` on Windows). On macOS and Windows the host
also reads tokens registered with the OS certificate store, and reports readers
seen over PC/SC even when the driver is missing, so `list` can say "token
detected, driver not installed" instead of showing nothing.

## Tests

```bash
pip install -e "./host[test]"
pytest host/tests
```

No hardware needed: a fake PKCS#11 layer stands in for the token. A real-token
run (`opensigner-host-cli list`, then sign through the demo) is a manual step
before releases.
