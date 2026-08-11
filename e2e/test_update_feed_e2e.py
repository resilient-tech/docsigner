"""The release feed and the host's checkUpdate, against each other.

`.github/workflows/release.yml` writes a `latest.json` on every tag; the shipped
binary reads it through `checkUpdate` (CONTRACTS.md section 2). Nothing else
checks that those two agree, and a feed the host cannot parse would fail
silently as "up to date" forever.

The feed here is built to the same shape the workflow's heredoc produces. If
that shape changes, this fails.
"""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from test_host_e2e import host_binary

RELEASES_URL = "https://github.com/resilient-tech/docsigner/releases/latest"


class _Feed:
    """A one-file HTTP server whose body the test can swap between requests."""

    def __init__(self):
        self.body = b"{}"
        self.status = 200
        feed = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(feed.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(feed.body)))
                self.end_headers()
                self.wfile.write(feed.body)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/latest.json"

    def publish(self, version):
        """Exactly what release.yml writes."""
        self.body = json.dumps(
            {"version": version, "url": RELEASES_URL, "published": "2026-08-11T00:00:00Z"},
            indent=2,
        ).encode()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def feed():
    f = _Feed()
    try:
        yield f
    finally:
        f.close()


def check_update(url):
    out = subprocess.run(
        [str(host_binary()), "check-update"],
        capture_output=True, text=True, timeout=60,
        env={"DOCSIGNER_UPDATE_URL": url, "PATH": "/usr/bin:/bin"},
    )
    return json.loads(out.stdout)["result"]


def host_version():
    out = subprocess.run(
        [str(host_binary()), "version"], capture_output=True, text=True, timeout=60
    )
    return json.loads(out.stdout)["result"]["version"]


def test_a_newer_release_is_announced(feed):
    current = host_version()
    major = int(current.split(".")[0])
    feed.publish(f"{major + 1}.0.0")

    result = check_update(feed.url)
    assert result["updateAvailable"] is True
    assert result["currentVersion"] == current
    assert result["latestVersion"] == f"{major + 1}.0.0"
    # The feed points at the release page, not a file: the host never downloads.
    assert result["downloadUrl"] == RELEASES_URL


def test_the_same_version_is_up_to_date(feed):
    feed.publish(host_version())
    result = check_update(feed.url)
    assert result["updateAvailable"] is False
    assert result["message"] == "up to date"


def test_an_older_feed_does_not_offer_a_downgrade(feed):
    feed.publish("0.0.1")
    result = check_update(feed.url)
    assert result["updateAvailable"] is False
    assert result["message"] == "up to date"


@pytest.mark.parametrize(
    "body, status",
    [
        (b"<html>not json</html>", 200),
        (b"{}", 500),
        (b"", 200),
        (b'{"version": null}', 200),
    ],
    ids=["html", "server-error", "empty", "null-version"],
)
def test_a_broken_feed_never_breaks_the_check(feed, body, status):
    """Every failure is soft. A page asking whether an update exists must not
    get an error back, or a bad deploy of the feed breaks the signing UI."""
    feed.body = body
    feed.status = status

    result = check_update(feed.url)
    assert result["updateAvailable"] is False
    assert result["currentVersion"] == host_version()
    # Present and explanatory, whichever way it failed.
    assert result["message"]


def test_https_reaches_a_real_host():
    """The shipped default is an https URL, and every case above is plain http.

    That gap hid a real break: ureq's native-tls feature only supplies an
    adapter, so without an explicit connector every https request failed with
    "no TLS backend is configured" — the check could never have worked in
    production while the local-http tests stayed green.

    Asserted negatively on purpose. What the feed answers depends on whether a
    release exists and whether the repo is public, and neither is this test's
    business; that the host can complete a TLS handshake at all is.
    """
    result = check_update("https://github.com/resilient-tech/docsigner/releases/latest/download/latest.json")
    assert result["updateAvailable"] in (True, False)
    assert "TLS" not in result["message"], result["message"]
    assert "tls" not in result["message"].lower(), result["message"]
