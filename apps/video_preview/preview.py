#!/usr/bin/env python3
"""Standalone V4L2 -> JPEG browser preview; Python sees compressed frames only."""
import argparse
import collections
import http.server
import json
import os
import signal
import subprocess
import threading
import time


class JpegFrames:
    """Incremental JPEG framing, including segment lengths and entropy stuffing."""
    def __init__(self, limit=4 * 1024 * 1024):
        self.data = bytearray()
        self.pos = 0
        self.entropy = False
        self.limit = limit

    def feed(self, chunk):
        self.data.extend(chunk)
        while True:
            if not self.pos:
                start = self.data.find(b"\xff\xd8")
                if start < 0:
                    self.data[:] = self.data[-1:]
                    return
                del self.data[:start]
                self.pos = 2
                self.entropy = False
            if self.pos > self.limit:
                raise ValueError("JPEG exceeds size limit")
            p = self.pos
            if self.entropy:
                p = self.data.find(b"\xff", p)
                if p < 0:
                    if len(self.data) > self.limit:
                        raise ValueError("JPEG exceeds size limit")
                    self.pos = len(self.data)
                    return
            if len(self.data) < p + 2:
                self.pos = p
                return
            if p + 2 > self.limit:
                raise ValueError("JPEG exceeds size limit")
            if self.data[p] != 255:
                raise ValueError("Invalid JPEG marker")
            marker = self.data[p + 1]
            if marker == 255:
                self.pos = p + 1
                continue
            if self.entropy and (marker == 0 or 0xD0 <= marker <= 0xD7):
                self.pos = p + 2
                continue
            if marker == 0xD9:
                frame = bytes(self.data[:p + 2])
                del self.data[:p + 2]
                self.pos = 0
                yield frame
                continue
            if len(self.data) < p + 4:
                self.pos = p
                return
            size = int.from_bytes(self.data[p + 2:p + 4], "big")
            if size < 2:
                raise ValueError("Invalid JPEG segment size")
            if p + 2 + size > self.limit:
                raise ValueError("JPEG exceeds size limit")
            if len(self.data) < p + 2 + size:
                self.pos = p
                return
            self.entropy = marker == 0xDA
            self.pos = p + 2 + size


def pipeline(args):
    command = ["gst-launch-1.0", "-q", "v4l2src", "device=" + args.device,
               "io-mode=" + ("dmabuf" if args.mode == "hardware" else "mmap"),
               "!", "video/x-raw,format=NV12,width=%d,height=%d" %
               (args.input_width, args.input_height), "!", "queue",
               "leaky=downstream", "max-size-buffers=1", "max-size-bytes=0",
               "max-size-time=0", "!"]
    if args.mode == "hardware":
        command += ["mppjpegenc", "width=%d" % args.width,
                    "height=%d" % args.height, "q-factor=%d" % args.quality,
                    "max-pending=1", "zero-copy-pkt=true"]
    else:
        command += ["videoscale", "!", "video/x-raw,format=NV12,width=%d,height=%d" %
                    (args.width, args.height), "!", "jpegenc",
                    "quality=%d" % args.quality]
    # Separate binary FD: vendor libraries can print diagnostics to stdout.
    return command + ["!", "fdsink", "fd=%d" % args.output_fd, "sync=false"]


class Latest:
    def __init__(self, mode):
        self.condition = threading.Condition()
        self.jpeg = b""
        self.sequence = 0
        self.received = 0.0
        self.times = collections.deque(maxlen=120)
        self.error = ""
        self.running = True
        self.mode = mode

    def publish(self, jpeg):
        with self.condition:
            self.jpeg = jpeg
            self.sequence += 1
            self.received = time.monotonic()
            self.times.append(self.received)
            self.condition.notify_all()

    def status(self):
        with self.condition:
            span = self.times[-1] - self.times[0] if len(self.times) > 1 else 0
            age = (time.monotonic() - self.received) * 1000 if self.received else None
            return dict(running=self.running, mode=self.mode, frames=self.sequence,
                        fps=(len(self.times) - 1) / span if span and age < 2000 else 0,
                        jpeg_bytes=len(self.jpeg), encoded_frame_age_ms=age,
                        error=self.error)


PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>摄像头实时预览</title><style>
body{background:#101820;color:#edf2f7;font:17px system-ui;margin:24px}
main{max-width:1100px;margin:auto}img{width:100%;background:#000;border-radius:12px}
p{color:#bbc7d3}strong{color:#7fe0bb}#status{min-height:28px}</style>
<main><h1>摄像头实时预览</h1><p id="status">正在连接…</p>
<img id="video" alt="摄像头实时画面"><p>独立视频预览 · 仅保留最新帧</p>
<p>帧龄从服务器收到 JPEG 起算，不代表摄像头到屏幕的总延迟。</p></main>
<script>
const video=document.getElementById('video'), status=document.getElementById('status');
video.onerror=()=>setTimeout(()=>video.src='/stream.mjpg?t='+Date.now(),1500);
video.src='/stream.mjpg';
async function poll(){try{const s=await(await fetch('/status.json',{cache:'no-store'})).json();
status.textContent=(s.mode==='hardware'?'硬件缩放 / JPEG':'软件缩放 / JPEG')+
' · '+s.fps.toFixed(1)+' FPS · '+Math.round(s.jpeg_bytes/1024)+' KB/帧'+
(s.error?' · '+s.error:(!s.running?' · 已停止':''));}catch(e){status.textContent='连接中断，正在重试…'}
setTimeout(poll,1000)}poll();</script></html>""".encode()


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, latest):
        self.latest = latest
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class Handler(http.server.BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(2)
        super().setup()

    def log_message(self, *args):
        pass

    def reply(self, code, kind, data):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        latest = self.server.latest
        path = self.path.split("?", 1)[0]
        try:
            if path == "/":
                self.reply(200, "text/html; charset=utf-8", PAGE)
            elif path == "/status.json":
                self.reply(200, "application/json", json.dumps(latest.status()).encode())
            elif path == "/snapshot.jpg":
                with latest.condition:
                    jpeg = latest.jpeg
                self.reply(200 if jpeg else 503, "image/jpeg", jpeg)
            elif path == "/stream.mjpg":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                sequence = 0
                while True:
                    with latest.condition:
                        latest.condition.wait_for(
                            lambda: latest.sequence != sequence or not latest.running,
                            timeout=2)
                        if not latest.running:
                            break
                        if sequence == latest.sequence:
                            continue
                        jpeg, sequence = latest.jpeg, latest.sequence
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                                     str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
            else:
                self.reply(404, "text/plain", b"Not found")
        except (OSError, ConnectionError):
            pass


def read_frames(stream, latest):
    parser = JpegFrames()
    try:
        while True:
            chunk = os.read(stream, 65536)
            if not chunk:
                raise RuntimeError("Encoder stream ended; check pipeline.log")
            for jpeg in parser.feed(chunk):
                latest.publish(jpeg)
    except (OSError, ValueError, RuntimeError) as error:
        with latest.condition:
            latest.error = str(error)
            latest.running = False
            latest.condition.notify_all()
    finally:
        os.close(stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="/dev/video31")
    parser.add_argument("--mode", choices=("hardware", "software"), default="hardware")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--input-width", type=int, default=2112)
    parser.add_argument("--input-height", type=int, default=1568)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=712)
    parser.add_argument("--quality", type=int, default=75)
    parser.add_argument("--duration", type=float, default=0, help="Stop after seconds; 0=unlimited")
    parser.add_argument("--log", default="pipeline.log")
    args = parser.parse_args()
    for dimension in (args.input_width, args.input_height, args.width, args.height):
        if not 16 <= dimension <= 8192 or dimension % 2:
            parser.error("Dimensions must be even and between 16 and 8192")
    if not 1 <= args.quality <= 99 or not 1 <= args.port <= 65535 or args.duration < 0:
        parser.error("Invalid quality, port, or duration")
    latest = Latest(args.mode)
    server = Server((args.bind, args.port), latest)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    read_fd, write_fd = os.pipe()
    args.output_fd = write_fd
    process = None
    serving = False
    try:
        with open(args.log, "wb") as log:
            process = subprocess.Popen(pipeline(args), stdout=log, stderr=log,
                                       pass_fds=(write_fd,))
        os.close(write_fd)
        write_fd = None
        reader = threading.Thread(target=read_frames, args=(read_fd, latest), daemon=True)
        reader.start()
        read_fd = None
        threading.Thread(target=server.serve_forever, daemon=True).start()
        serving = True
        start = time.monotonic()
        print(json.dumps(dict(url="http://%s:%d/" % (args.bind, args.port),
                              mode=args.mode, pipeline_pid=process.pid)), flush=True)
        while not stop.wait(0.2):
            now = time.monotonic()
            if args.duration and now - start >= args.duration:
                break
            if not latest.running or now - (latest.received or start) > 5:
                if not latest.error:
                    latest.error = "No JPEG received for 5 seconds; check pipeline.log"
                print(latest.error, flush=True)
                return 1
        return 0
    finally:
        with latest.condition:
            latest.running = False
            latest.condition.notify_all()
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if serving:
            server.shutdown()
        server.server_close()
        if read_fd is not None:
            os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


if __name__ == "__main__":
    raise SystemExit(main())
