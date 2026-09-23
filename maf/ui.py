"""Local-only flow editor. No model calls or provider/account changes."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import webbrowser

from . import core, flows


PAGE = (Path(__file__).parent / "static" / "index.html").read_text()


def state():
    return {"flows": flows.catalog(), "settings": flows.settings()}


def server(port=0):
    token = secrets.token_hex(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def reply(self, status, body, content_type="application/json; charset=utf-8"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'none'; connect-src 'self'; style-src 'nonce-" + token
                             + "'; script-src 'nonce-" + token + "'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            port = self.server.server_port
            return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

        def do_GET(self):
            if not self.allowed():
                return self.reply(403, b"Forbidden", "text/plain")
            if self.path == "/":
                return self.reply(200, PAGE.replace("__MAF_TOKEN__", token), "text/html; charset=utf-8")
            if self.path == "/api/state" and self.headers.get("X-MAF-Token") == token:
                try:
                    return self.reply(200, json.dumps(state(), ensure_ascii=False))
                except (core.FlowError, OSError, ValueError) as exc:
                    return self.reply(409, json.dumps({"error": str(exc)}))
            self.reply(404, b"Not found", "text/plain")

        def do_POST(self):
            if not self.allowed() or self.headers.get("X-MAF-Token") != token:
                return self.reply(403, b"Forbidden", "text/plain")
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{self.server.server_port}",
                                         f"http://localhost:{self.server.server_port}"):
                return self.reply(403, b"Forbidden", "text/plain")
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                return self.reply(415, b"JSON required", "text/plain")
            try:
                length = int(self.headers.get("Content-Length", "-1"))
                if not 0 < length <= 65536:
                    raise ValueError("Request must be 1..65536 bytes.")
                body = json.loads(self.rfile.read(length))
                if self.path == "/api/flow" and isinstance(body, dict) and set(body) == {"name", "flow"}:
                    flows.save(body["name"], body["flow"])
                elif self.path == "/api/settings" and isinstance(body, dict) and set(body) == {"herdr_enabled"}:
                    flows.set_herdr(body["herdr_enabled"])
                else:
                    return self.reply(400, json.dumps({"error": "Unknown operation or payload."}))
                self.reply(200, json.dumps(state(), ensure_ascii=False))
            except (core.FlowError, OSError, ValueError, TypeError, KeyError) as exc:
                self.reply(409, json.dumps({"error": str(exc)}))

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(port=0, open_browser=True):
    if not 0 <= port <= 65535:
        raise core.FlowError("Port must be 0..65535.")
    http = server(port)
    url = f"http://127.0.0.1:{http.server_port}/"
    print(f"MAF Flow Studio: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        http.serve_forever()
    finally:
        http.server_close()
