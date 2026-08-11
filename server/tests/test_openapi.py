"""The committed OpenAPI document is the contract other languages build against.

There are no hand-written SDKs: a Rails or Node or Go shop generates a client
from `server/openapi.json`. That only works if the document stays accurate and
stays descriptive, so this file guards both.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO / "server" / "openapi.json"

sys.path.insert(0, str(REPO / "scripts"))
import export_openapi  # noqa: E402


@pytest.fixture(scope="module")
def spec():
    return json.loads(SPEC_PATH.read_text())


def test_the_committed_spec_is_current():
    """Regenerate and compare. A route change without re-exporting fails here,
    where it is one command to fix, rather than in someone else's build."""
    assert SPEC_PATH.exists(), "run: python scripts/export_openapi.py"
    expected = export_openapi.render(export_openapi.build())
    actual = SPEC_PATH.read_text()
    assert actual == expected, (
        "server/openapi.json is out of date with the routes.\n"
        "Regenerate it with:  python scripts/export_openapi.py"
    )


def test_every_endpoint_in_the_contract_is_present(spec):
    """The paths CONTRACTS.md section 1 promises. Dropping one silently would
    break every generated client."""
    for path in [
        "/api/signatures",
        "/api/signatures/{session_id}/complete",
        "/api/signatures/batch",
        "/api/signatures/batch-complete",
        "/api/documents/{document_id}",
        "/api/sign-server-side",
        "/api/validate",
        "/api/cades/signatures",
        "/api/cades/signatures/{session_id}/complete",
        "/api/cades/sign-server-side",
        "/api/xades/sign-server-side",
    ]:
        assert path in spec["paths"], f"{path} vanished from the API"


def test_no_request_body_is_an_untyped_blob(spec):
    """The reason this file exists. Every body used to come out as `object`,
    which made a generated client barely better than raw HTTP."""
    untyped = []
    for path, operations in spec["paths"].items():
        for verb, operation in operations.items():
            body = (
                operation.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            if body and not (body.get("$ref") or body.get("allOf")):
                untyped.append(f"{verb.upper()} {path}")
    assert not untyped, f"untyped request bodies: {untyped}"


def test_no_json_response_is_an_untyped_blob(spec):
    """Same for responses, except the document download, which is bytes and is
    declared as binary content rather than JSON."""
    untyped = []
    for path, operations in spec["paths"].items():
        for verb, operation in operations.items():
            content = operation.get("responses", {}).get("200", {}).get("content", {})
            if "application/json" not in content:
                continue  # binary download
            schema = content["application/json"].get("schema", {})
            if not (schema.get("$ref") or schema.get("allOf") or schema.get("type")):
                untyped.append(f"{verb.upper()} {path}")
    assert not untyped, f"untyped responses: {untyped}"


def test_failures_are_documented_not_just_the_happy_path(spec):
    """A generated client should be able to type its error branch."""
    for path, operations in spec["paths"].items():
        for verb, operation in operations.items():
            responses = operation.get("responses", {})
            documented = {code for code in responses if code.startswith(("4", "5"))}
            assert documented, f"{verb.upper()} {path} documents no failures"


def test_the_error_shape_lists_every_contract_code(spec):
    """The codes in CONTRACTS.md, so a client can switch on them exhaustively."""
    codes = spec["components"]["schemas"]["ErrorBody"]["properties"]["code"]["enum"]
    assert set(codes) == {
        "DOCUMENT_INVALID",
        "CERT_INVALID",
        "SESSION_NOT_FOUND",
        "SESSION_EXPIRED",
        "SIGNATURE_INVALID",
        "PROFILE_UNSUPPORTED",
        "INTERNAL",
    }


def test_options_stays_open_to_new_fields(spec):
    """A client built against an older spec must still be able to send a newer
    option and get a real answer, not a schema rejection."""
    options = spec["components"]["schemas"]["SigningOptions"]
    assert options.get("additionalProperties") is not False, (
        "SigningOptions must not forbid extra fields: options grow with the standards"
    )


def test_the_spec_is_valid_openapi():
    """Parse it with a real validator if one is installed; otherwise check the
    structural essentials, so this still means something in a bare environment."""
    spec = json.loads(SPEC_PATH.read_text())
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["title"]
    assert spec["paths"]

    try:
        from openapi_spec_validator import validate as validate_spec
    except ImportError:
        pytest.skip("openapi-spec-validator not installed")
    validate_spec(spec)


def test_export_script_is_idempotent(tmp_path, monkeypatch):
    """Running it twice must not produce a diff, or the CI check above would
    fail at random."""
    first = export_openapi.render(export_openapi.build())
    second = export_openapi.render(export_openapi.build())
    assert first == second


def test_export_script_runs_standalone():
    """It is also a command people run by hand."""
    result = subprocess.run(
        [sys.executable, "scripts/export_openapi.py"],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "openapi.json" in result.stdout
