#!/usr/bin/env bash
# Run the end-to-end suites. From the repo root:  e2e/run_e2e.sh [pytest args]
#
# Boots a real signer-server, runs the server/host/extension/demo e2e matrix,
# verifying every signed output through /api/validate plus structural checks.
#
# Config comes from e2e/.env.e2e (copy e2e/.env.e2e.example if missing).
# Gated paths (off by default), enable per run:
#   OPENSIGNER_E2E_REAL_TOKEN=1  real DSC over the host (token plugged in + driver)
#   OPENSIGNER_E2E_BROWSER=1     Chrome + playwright extension run
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f e2e/.env.e2e ]; then
  echo "e2e/.env.e2e missing; copying from example (edit the PIN/PII before real runs)"
  cp e2e/.env.e2e.example e2e/.env.e2e
fi

# Deps: the Python packages plus the dev/test extras.
pip install -e ./core -e ./server -r requirements-dev.txt -q

# The host is a Rust binary; the host e2e skips itself if it is not built.
if command -v cargo >/dev/null 2>&1; then
  cargo build --release --manifest-path host-rs/Cargo.toml -q
fi

exec python -m pytest e2e/ -ra "$@"
