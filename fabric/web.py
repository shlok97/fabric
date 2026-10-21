"""Loopback-only dashboard and authenticated, bounded read operations."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .core import FabricError, canonical


def make_server(store, port=4790):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *_):
            # No private queries, paths, request bodies or bearer tokens in access logs.
            pass

        def send(self, status, body, content_type="application/json; charset=utf-8"):
            raw = body.encode() if isinstance(body, str) else canonical(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def guard(self):
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in hosts:
                raise FabricError("Invalid local host.", "forbidden", 403)
            origin = self.headers.get("Origin")
            if origin is not None and origin not in {"http://" + host for host in hosts}:
                raise FabricError("Cross-origin access denied.", "forbidden", 403)

        def do_GET(self):
            try:
                self.guard()
                path = urlsplit(self.path).path
                if path == "/health":
                    return self.send(200, {"status": "ok", "version": "0.1.0", "mode": "local-poc"})
                assets = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                          "/style.css": ("style.css", "text/css; charset=utf-8")}
                if path in assets:
                    name, kind = assets[path]
                    return self.send(200, (Path(__file__).with_name("static") / name).read_text(), kind)
                raise FabricError("Not found.", "not_found", 404)
            except FabricError as e:
                self.send(e.status, {"error": {"code": e.code, "message": str(e)}})

        def do_POST(self):
            try:
                self.guard()
                if urlsplit(self.path).path != "/api/call":
                    raise FabricError("Not found.", "not_found", 404)
                auth = self.headers.get("Authorization", "")
                token = auth[7:] if auth.startswith("Bearer ") else ""
                # Reject unknown credentials before parsing even a valid request body.
                with store.connect() as db:
                    store.authenticate(db, token)
                if self.headers.get("Transfer-Encoding"):
                    raise FabricError("Chunked requests are not supported.")
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise FabricError("Content-Type must be application/json.")
                try:
                    length = int(self.headers.get("Content-Length", "-1"))
                    if not 0 < length <= 16384:
                        raise ValueError()
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise ValueError()
                    data = json.loads(raw)
                except (ValueError, UnicodeError) as e:
                    raise FabricError("Invalid or oversized JSON request.") from e
                if not isinstance(data, dict) or set(data) - {"operation", "arguments"} or not isinstance(data.get("operation"), str):
                    raise FabricError("Expected operation and arguments only.")
                result = store.execute(token, data["operation"], data.get("arguments", {}))
                self.send(200, result)
            except FabricError as e:
                self.send(e.status, {"error": {"code": e.code, "message": str(e)}})
            except (OSError, TimeoutError):
                self.close_connection = True
            except Exception:
                self.send(500, {"error": {"code": "internal_error", "message": "Operation failed. No source writes were performed."}})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
