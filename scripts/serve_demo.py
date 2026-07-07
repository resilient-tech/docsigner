"""Serve the repo root for the demo with caching turned off.

`python -m http.server` lets the browser cache demo.js and opensigner.js, so
after editing them the page keeps running the old copy until a hard refresh.
This dev server sends no-store on every response, so a plain reload always
picks up the latest code.

    python scripts/serve_demo.py            # http://127.0.0.1:8080/demo/

Run from the repo root so /demo/ and /js/ both resolve.
"""

import http.server
import socketserver
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()


if __name__ == "__main__":
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), NoCacheHandler) as httpd:
        print(f"serving repo root at http://127.0.0.1:{PORT}/demo/ (no-store)")
        httpd.serve_forever()
