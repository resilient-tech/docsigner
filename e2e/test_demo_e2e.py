"""Live demo e2e: is the demo functional?

Two halves:
  - The demo is served and its asset graph resolves: /demo/ loads, demo.js
    loads, and the ../js/opensigner.js module it imports resolves (the exact
    breakage the README warns about when serving the repo root).
  - The demo's no-hardware flows work end to end against the live server:
    server-side PDF, XAdES, and CAdES — the same endpoints demo.js posts to —
    each producing output the server then validates.
"""

import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from helpers import b64, make_blank_pdf, make_xml

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def demo_base():
    """Serve the repo root exactly as `scripts/serve_demo.py` does, so /demo/
    and /js/ both resolve."""
    handler = partial(SimpleHTTPRequestHandler, directory=str(REPO_ROOT))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def web():
    with httpx.Client(timeout=15, trust_env=False) as client:
        yield client


# ---------------------------------------------------------- served + asset graph

def test_demo_page_serves(demo_base, web):
    r = web.get(f"{demo_base}/demo/")
    assert r.status_code == 200
    assert 'id="server"' in r.text
    assert 'src="demo.js"' in r.text


def test_demo_asset_graph_resolves(demo_base, web):
    # demo.js imports ../js/opensigner.js — both must be reachable from the root.
    demo_js = web.get(f"{demo_base}/demo/demo.js")
    assert demo_js.status_code == 200
    assert 'from "../js/opensigner.js"' in demo_js.text
    assert web.get(f"{demo_base}/js/opensigner.js").status_code == 200, "opensigner.js not served"


def test_demo_default_server_url_is_local(demo_base, web):
    html = web.get(f"{demo_base}/demo/").text
    m = re.search(r'id="server"[^>]*value="([^"]+)"', html)
    assert m, "demo has no default server URL input"
    assert m.group(1).startswith("http://127.0.0.1:"), m.group(1)


# ------------------------------------------------- demo's no-hardware flows live

def test_demo_server_side_pdf_functional(api):
    """The demo's server-side PDF path: post, download, validate."""
    r = api.post("/sign-server-side", json={
        "document": b64(make_blank_pdf()), "options": {"profile": "B-B"}})
    r.raise_for_status()
    signed = api.get(r.json()["download_url"].replace("/api", "", 1))
    signed.raise_for_status()
    assert signed.content[:5] == b"%PDF-"
    v = api.post("/validate", json={"document": b64(signed.content)})
    sig = v.json()["signatures"][0]
    assert sig["valid"] and sig["intact"]


def test_demo_xades_functional(api):
    r = api.post("/xades/sign-server-side", json={"document": b64(make_xml()), "options": {}})
    r.raise_for_status()
    out = api.get(r.json()["download_url"].replace("/api", "", 1))
    assert out.status_code == 200 and b"Signature" in out.content


def test_demo_cades_functional(api):
    r = api.post("/cades/sign-server-side", json={
        "document": b64(b"demo detached bytes"), "options": {"profile": "B-B"}})
    r.raise_for_status()
    out = api.get(r.json()["download_url"].replace("/api", "", 1))
    assert out.status_code == 200 and len(out.content) > 100
