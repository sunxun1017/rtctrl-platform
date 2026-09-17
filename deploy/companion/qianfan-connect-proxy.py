#!/usr/bin/env python3
"""Development-only loopback CONNECT relay for a directly cabled board.

Forward through SSH -R 127.0.0.1:18080:127.0.0.1:18080. TLS stays end-to-end
between the board and Qianfan. Only the fixed Qianfan HTTPS endpoint is allowed.
No request bodies, tokens, or connection contents are logged.
"""
import argparse
import select
import socket
import socketserver
import threading
import time

TARGET = "qianfan.baidubce.com"

class Relay(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    def __init__(self, address):
        self.slots = threading.BoundedSemaphore(4)
        super().__init__(address, Handler)
    def process_request(self, request, client_address):
        if not self.slots.acquire(False):
            request.close()
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

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(10)
        try:
            line = self.rfile.readline(4097)
            if line.strip() not in (f"CONNECT {TARGET}:443 HTTP/1.0".encode(),
                                    f"CONNECT {TARGET}:443 HTTP/1.1".encode()):
                self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                return
            total = len(line)
            while True:
                line = self.rfile.readline(4097)
                total += len(line)
                if not line or total > 8192:
                    return
                if line in (b"\r\n", b"\n"):
                    break
            with socket.create_connection((TARGET, 443), timeout=10) as upstream:
                self.request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                sockets = (self.request, upstream)
                deadline, count = time.monotonic() + 120, 0
                while time.monotonic() < deadline:
                    readable, _, _ = select.select(sockets, [], [], min(30, deadline-time.monotonic()))
                    if not readable:
                        return
                    for source in readable:
                        data = source.recv(16384)
                        count += len(data)
                        if not data or count > 8 * 1024 * 1024:
                            return
                        (upstream if source is self.request else self.request).sendall(data)
        except (OSError, ValueError):
            return

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    with Relay(("127.0.0.1", args.port)) as server:
        print(f"Qianfan TLS relay on 127.0.0.1:{args.port}", flush=True)
        server.serve_forever()

if __name__ == "__main__":
    main()
