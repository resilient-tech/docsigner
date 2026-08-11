"""Serve the demo, with caching off.

The plain http.server lets the browser hold on to old JS, so you edit a file
and the page keeps running yesterday's copy. This one always reloads.

    python scripts/serve_demo.py     # from the repo root
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
