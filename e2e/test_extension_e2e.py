"""Live extension e2e, independent of the server and host.

Runnable anywhere: invokes the extension's own Node test suite (manifest,
script parse, icons) as a live subprocess, and checks the page-bridge event
names against CONTRACTS.md.

Gated (OPENSIGNER_E2E_BROWSER=1, needs Chrome + `pip install playwright` and
`playwright install chromium`): loads the unpacked extension in a real browser
on the demo page and confirms the page-to-extension bridge answers `ping`.
"""

import os
import shutil
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT_DIR = REPO_ROOT / "extension"
JS_DIR = REPO_ROOT / "js"


def test_extension_node_suite():
    """The extension's own checks, run live. Reuses js/test rather than
    reimplementing manifest/parse/icon verification."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    result = subprocess.run(
        [node, "--test"], cwd=str(JS_DIR),
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_bridge_event_names_match_contract():
    """content.js must use the exact bridge event names the contract freezes."""
    content = (EXT_DIR / "content.js").read_text()
    assert "org.opensigner.request" in content
    assert "org.opensigner.response" in content


def test_manifest_native_messaging_permission():
    import json
    manifest = json.loads((EXT_DIR / "manifest.json").read_text())
    assert manifest["manifest_version"] == 3
    assert "nativeMessaging" in manifest["permissions"]


# ------------------------------------------------------------ gated browser run

@pytest.mark.skipif(
    os.environ.get("OPENSIGNER_E2E_BROWSER") != "1",
    reason="browser path: set OPENSIGNER_E2E_BROWSER=1 (needs Chrome + playwright)",
)
def test_extension_bridge_in_browser(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")

    port = int(os.environ.get("E2E_DEMO_PORT", "8898"))
    handler = partial(SimpleHTTPRequestHandler, directory=str(REPO_ROOT))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with playwright.sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(tmp_path / "profile"),
                headless=False,  # extensions need a headed Chromium
                args=[f"--disable-extensions-except={EXT_DIR}",
                      f"--load-extension={EXT_DIR}"],
            )
            page = ctx.new_page()
            page.goto(f"http://127.0.0.1:{port}/demo/")
            # The demo loads OpenSigner as an ES module, so there is no page
            # global; import it the same way and ping through the
            # content-script bridge (proves the extension is installed).
            installed = page.evaluate(
                """async () => {
                     const { OpenSigner } = await import("/js/opensigner.js");
                     const s = new OpenSigner();
                     try { await s.init({ timeout: 3000 }); return true; }
                     catch (e) { return e.code || String(e); }
                   }""")
            ctx.close()
    finally:
        httpd.shutdown()
    assert installed is True, f"bridge did not answer ping: {installed}"
