#!/usr/bin/env python3
"""Diff the Rust host against the Python host, command by command.

Both speak CONTRACTS.md section 2, so a port is correct when their JSON
matches. Run it with a token plugged in for the interesting comparison; without
one it still checks that both agree on an empty result and on the diagnostics
that explain why.

    python scripts/compare_hosts.py

Signing is deliberately not compared: it needs the token holder's PIN, and these
tokens lock after a few wrong attempts.
"""

import json
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUST_BIN = REPO / "host-rs" / "target" / "release" / "opensigner-host"
RUST_BIN_DEBUG = REPO / "host-rs" / "target" / "debug" / "opensigner-host"
PYTHON_BIN = REPO / ".venv" / "bin" / "python"

# Ordering is not part of the contract; both hosts are compared as parsed JSON.
COMMANDS = ["getVersion", "listCertificates", "checkUpdate"]

# The Rust crate carries its own version, so anything reporting it differs on
# purpose. Everything else must match exactly.
EXPECTED_DIFFERENCES = {
    ("getVersion", "version"),
    ("checkUpdate", "currentVersion"),
}


def rust_binary() -> Path:
    for candidate in (RUST_BIN, RUST_BIN_DEBUG):
        if candidate.exists():
            return candidate
    sys.exit(f"build the Rust host first: cargo build --release --manifest-path {REPO}/host-rs/Cargo.toml")


def run_python(command: str) -> dict:
    """Call the Python host through its dispatch layer, bypassing the CLI's
    subcommand names so both sides answer the same protocol command."""
    script = (
        "import json;from signer_host import protocol;"
        f"print(json.dumps(protocol.handle_message({{'id':'cmp','command':{command!r},'params':{{}}}})))"
    )
    out = subprocess.run(
        [str(PYTHON_BIN), "-c", script],
        capture_output=True, text=True, cwd=REPO, timeout=120,
    )
    if out.returncode != 0:
        sys.exit(f"python host failed for {command}:\n{out.stderr}")
    return json.loads(out.stdout)


def run_rust(binary: Path, command: str) -> dict:
    """Drive the Rust host over real native messaging framing, as Chrome does."""
    proc = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    payload = json.dumps({"id": "cmp", "command": command, "params": {}}).encode()
    proc.stdin.write(struct.pack("<I", len(payload)) + payload)
    proc.stdin.flush()

    header = proc.stdout.read(4)
    if len(header) < 4:
        sys.exit(f"rust host gave no reply for {command}")
    (length,) = struct.unpack("<I", header)
    response = json.loads(proc.stdout.read(length).decode())
    proc.stdin.close()
    proc.wait(timeout=10)
    return response


def walk(path: str, a, b, out: list) -> None:
    """Collect every leaf where a and b disagree."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            walk(f"{path}.{key}" if path else key, a.get(key), b.get(key), out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, f"{len(a)} items", f"{len(b)} items"))
            return
        for i, (x, y) in enumerate(zip(a, b)):
            walk(f"{path}[{i}]", x, y, out)
    elif a != b:
        out.append((path, a, b))


def sort_certificates(response: dict) -> dict:
    """Order is not part of the contract, so compare certificates by thumbprint."""
    certificates = response.get("result", {}).get("certificates")
    if isinstance(certificates, list):
        certificates.sort(key=lambda c: c.get("thumbprint", ""))
    return response


def main() -> int:
    binary = rust_binary()
    print(f"rust:   {binary.relative_to(REPO)}")
    print(f"python: {PYTHON_BIN.relative_to(REPO)}\n")

    failures = 0
    for command in COMMANDS:
        py = sort_certificates(run_python(command))
        rs = sort_certificates(run_rust(binary, command))

        differences = []
        walk("", py, rs, differences)
        unexpected = [
            d for d in differences
            if (command, d[0].rsplit(".", 1)[-1]) not in EXPECTED_DIFFERENCES
        ]

        certificates = py.get("result", {}).get("certificates", [])
        detail = f"{len(certificates)} certificates" if command == "listCertificates" else ""
        if unexpected:
            failures += 1
            print(f"FAIL  {command:18} {detail}")
            for where, a, b in unexpected[:20]:
                print(f"        {where}\n          python: {a!r}\n            rust: {b!r}")
        else:
            skipped = len(differences) - len(unexpected)
            note = f" ({skipped} expected difference)" if skipped else ""
            print(f"ok    {command:18} {detail}{note}")

    print()
    if failures:
        print(f"{failures} command(s) diverged")
        return 1
    print("the Rust host matches the Python host on every compared command")
    return 0


if __name__ == "__main__":
    sys.exit(main())
