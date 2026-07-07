"""Terminal test tool speaking the same dispatch layer as the browser host.

Examples:
    opensigner-host-cli version
    opensigner-host-cli list
    opensigner-host-cli sign --thumbprint ab12cd... --hash <b64> --alg sha256

Set OPENSIGNER_PIN to skip the PIN dialog.
"""

import argparse
import json
import sys

from . import protocol


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="opensigner-host-cli",
        description="Exercise the OpenSigner host commands from a terminal.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="show host and protocol version")
    sub.add_parser("list", help="list certificates on all connected tokens")
    sign = sub.add_parser("sign", help="sign one or more base64 digests")
    sign.add_argument("--thumbprint", required=True,
                      help="SHA-1 thumbprint of the certificate, lowercase hex")
    sign.add_argument("--hash", action="append", required=True, dest="hashes",
                      help="base64 digest to sign; repeat for a batch")
    sign.add_argument("--alg", default="sha256",
                      help="digest algorithm: sha256, sha384 or sha512 (default sha256)")
    args = parser.parse_args(argv)

    command = {"version": "getVersion", "list": "listCertificates", "sign": "signHash"}[args.command]
    params = {}
    if args.command == "sign":
        params = {"thumbprint": args.thumbprint, "hashes": args.hashes,
                  "digestAlgorithm": args.alg}

    response = protocol.handle_message({"id": "cli", "command": command, "params": params})
    print(json.dumps(response, indent=2, ensure_ascii=False))
    for reader in response.get("result", {}).get("readers", []):
        if not reader["driverFound"]:
            print("note: %s detected but no matching driver is installed"
                  % (reader["token"] or reader["name"]), file=sys.stderr)
    return 0 if "result" in response else 1


if __name__ == "__main__":
    sys.exit(main())
