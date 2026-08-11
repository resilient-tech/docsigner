# End-to-end tests

Live e2e for DocSigner. Unlike the unit suites (which mock the token and use
FastAPI's in-memory `TestClient`), these boot a **real** signer-server over a
socket and drive the server, host, extension, and demo the way a browser and
token would — then verify every signed output through the server's own
`/api/validate` plus structural checks on the bytes (DSS for LTV, RFC 3161
timestamp for the `-T` profiles, `pdfRevocationInfoArchival` for CCA).

## Run

```bash
e2e/run_e2e.sh                 # boots a server, runs everything runnable
e2e/run_e2e.sh -k server       # just the server matrix
python -m pytest e2e/ -ra      # same, without the dep install step
```

Config is read from `e2e/.env.e2e` (secrets, gitignored). Copy the template and
edit it — the token PIN is `admin@123` by default:

```bash
cp e2e/.env.e2e.example e2e/.env.e2e
```

`.env.e2e` holds the token PIN (`DOCSIGNER_PIN`), the signer PII the test certs
carry (`E2E_SIGNER_CN/ORG/COUNTRY/EMAIL`, reason, location), the server-held
`.p12` passphrase, ports, `TSA_URL`, `TRUST_DIR`, and the two gate flags.

## What runs where

The suite is honest about its environment: cases it cannot exercise **skip with
a reason** rather than pass hollowly or fail.

| Suite | Runs in CI / offline sandbox | Needs your machine |
|---|---|---|
| `test_server_e2e.py` | B-B (all digests, RSA + EC, PDF + CAdES, token + server-side), batch, XAdES, appearance variants, error paths | B-T (reachable TSA); B-LT/B-LTA/CCA-LTV/CCA-LTA (CA-issued cert + reachable OCSP → real DSC) |
| `test_host_e2e.py` | real host process `getVersion`; list/sign over the wire vs a fake token, PIN `admin@123`, signatures verified against the cert | real DSC: `DOCSIGNER_E2E_REAL_TOKEN=1` + `DOCSIGNER_PKCS11_MODULES` |
| `test_extension_e2e.py` | manifest / script / icon checks (via the JS suite); bridge event-name contract | browser: `DOCSIGNER_E2E_BROWSER=1` (Chrome + `pip install playwright`, `playwright install chromium`) |
| `test_demo_e2e.py` | demo page served, asset graph resolves, demo's server-side PDF/XAdES/CAdES flows validate | — |

Why the LTV/CCA profiles skip offline: they embed revocation data fetched from
the signer certificate's CA over OCSP/CRL. A self-signed test cert has no CA to
ask, and the sandbox blocks the CA endpoints anyway. On your machine with the
DSC token plugged in and its CA reachable, they run — flip the gate:

```bash
DOCSIGNER_E2E_REAL_TOKEN=1 DOCSIGNER_PKCS11_MODULES=/path/to/pkcs11.so \
  python -m pytest e2e/test_host_e2e.py -k real_token -s
```

## The matrix

Profiles `B-B · B-T · B-LT · B-LTA · CCA-LTV · CCA-LTA` × flows
`token-session · server-side · batch` × digests `sha256/384/512` × key types
`RSA · EC` × formats `PDF · CAdES(.p7s) · XAdES(.xml)`, plus visible/invisible/
positioned appearances and the seven error codes from `CONTRACTS.md`.
