"""Loopback-only HTTP control surface with bounded connections and same-origin writes."""
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

WEB = pathlib.Path(__file__).with_name("web")

class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 8

    def __init__(self, address, companion, network=None):
        self.companion = companion
        self.network = network
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        request.settimeout(15)
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

class Handler(BaseHTTPRequestHandler):
    server_version = "rtctrl-companion"
    def log_message(self, *args):
        pass

    def _reply(self, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        host = self.headers.get("Host", "")
        try:
            parsed = urlsplit("http://" + host)
            port = parsed.port
            return parsed.hostname in ("localhost", "127.0.0.1") and port == self.server.server_port
        except ValueError:
            return False

    def do_GET(self):
        if not self._host_ok():
            return self._reply(403, {"error": "invalid Host"})
        path = urlsplit(self.path).path
        if path == "/api/network":
            return self._reply(200, self.server.network.snapshot() if self.server.network else {"available": False, "busy": False, "status": "未启用Wi-Fi管理", "error": "", "networks": []})
        if path == "/api/status":
            return self._reply(200, self.server.companion.snapshot())
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8")}
        if path not in assets:
            return self._reply(404, {"error": "not found"})
        name, mime = assets[path]
        self._reply(200, (WEB / name).read_bytes(), mime)

    def do_POST(self):
        origin = self.headers.get("Origin")
        expected = "http://" + self.headers.get("Host", "")
        if not self._host_ok() or (origin is not None and origin != expected):
            return self._reply(403, {"error": "cross-origin request rejected"})
        if self.path not in ("/api/action", "/api/network"):
            return self._reply(404, {"error": "not found"})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._reply(415, {"error": "application/json required"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024 or self.headers.get("Transfer-Encoding"):
                raise ValueError("invalid body size")
            body = json.loads(self.rfile.read(length))
            if self.path == "/api/network":
                if not self.server.network:
                    return self._reply(400, {"error": "未启用Wi-Fi管理"})
                try:
                    result = self.server.network.action(body)
                except ValueError as exc:
                    return self._reply(400, {"error": str(exc)})
                return self._reply(202, result)
            if not isinstance(body, dict) or set(body) != {"action"} or not isinstance(body["action"], str):
                raise ValueError("expected an action")
            result = self.server.companion.action(body["action"])
            self._reply(200, result)
        except (json.JSONDecodeError, UnicodeError):
            self._reply(400, {"error": "请求格式无效"})
        except ValueError as exc:
            self._reply(400, {"error": str(exc)})
        except TimeoutError:
            self._reply(408, {"error": "request timed out"})
