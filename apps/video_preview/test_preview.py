import json
import socket
import sys
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request

from preview import JpegFrames, Latest, Server, main


# APP segment deliberately contains EOI bytes; entropy has stuffing/restarts.
JPEG = (b"\xff\xd8\xff\xe0\x00\x06ab\xff\xd9"
        b"\xff\xda\x00\x02abc\xff\x00\xd9\xff\xd0xyz\xff\xd9")


class PreviewTest(unittest.TestCase):
    def test_all_split_points(self):
        for split in range(len(JPEG) + 1):
            parser = JpegFrames()
            frames = list(parser.feed(JPEG[:split])) + list(parser.feed(JPEG[split:]))
            self.assertEqual(frames, [JPEG], split)

    def test_bytewise_and_concatenated(self):
        parser = JpegFrames()
        result = []
        for value in b"vendor diagnostic\n" + JPEG * 3:
            result.extend(parser.feed(bytes([value])))
        self.assertEqual(result, [JPEG] * 3)
        self.assertEqual(list(JpegFrames().feed(JPEG * 3)), [JPEG] * 3)
        self.assertEqual(list(JpegFrames(limit=len(JPEG)).feed(JPEG * 2)), [JPEG] * 2)

    def test_dense_entropy_markers_and_chunk_boundaries(self):
        # Stuffed FF and all restart codes are entropy, including across reads.
        entropy = (b"abc\xff\x00" + b"".join(
            b"\xff" + bytes([code]) for code in range(0xD0, 0xD8))) * 20
        frame = b"\xff\xd8\xff\xda\x00\x02" + entropy + b"\xff\xff\xd9"
        for split in range(len(frame) + 1):
            parser = JpegFrames()
            result = list(parser.feed(frame[:split])) + list(parser.feed(frame[split:]))
            self.assertEqual(result, [frame], split)
        with self.assertRaises(ValueError):
            list(JpegFrames(limit=32).feed(frame[:-3]))

    def test_invalid_and_oversized(self):
        with self.assertRaises(ValueError):
            list(JpegFrames().feed(b"\xff\xd8\xff\xe0\x00\x01"))
        with self.assertRaises(ValueError):
            list(JpegFrames(limit=8).feed(JPEG))

    def test_http_latest_frame(self):
        latest = Latest("hardware")
        server = Server(("127.0.0.1", 0), latest)
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        base = "http://127.0.0.1:%d" % server.server_port
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + "/snapshot.jpg", timeout=2)
            self.assertEqual(error.exception.code, 503)
            for _ in range(1000):
                latest.publish(JPEG)
            with urllib.request.urlopen(base + "/status.json", timeout=2) as response:
                self.assertEqual(json.load(response)["frames"], 1000)
            with urllib.request.urlopen(base + "/snapshot.jpg", timeout=2) as response:
                self.assertEqual(response.headers["X-Frame-Sequence"], "1000")
                self.assertEqual(response.read(), JPEG)
            with urllib.request.urlopen(base + "/stream.mjpg", timeout=2) as response:
                self.assertEqual(response.readline(), b"--frame\r\n")
                self.assertEqual(response.readline(), b"Content-Type: image/jpeg\r\n")
                response.readline()
                response.readline()
                self.assertEqual(response.read(len(JPEG)), JPEG)
            with urllib.request.urlopen(base, timeout=2) as response:
                self.assertIn(b"/snapshot.jpg", response.read())
            with latest.condition:
                latest.received = time.monotonic() - 3
            with self.assertRaises(urllib.error.HTTPError) as stale:
                urllib.request.urlopen(base + "/snapshot.jpg", timeout=2)
            self.assertEqual(stale.exception.code, 503)
        finally:
            with latest.condition:
                latest.running = False
                latest.condition.notify_all()
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_slow_headers_release_slots(self):
        server = Server(("127.0.0.1", 0), Latest("hardware"))
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        clients = []
        try:
            for _ in range(8):
                client = socket.create_connection(server.server_address, timeout=2)
                client.sendall(b"GET / HTTP/1.0\r\nX-Incomplete: ")
                clients.append(client)
            time.sleep(2.5)
            with urllib.request.urlopen("http://127.0.0.1:%d/status.json" %
                                        server.server_port, timeout=2) as response:
                self.assertEqual(json.load(response)["frames"], 0)
        finally:
            for client in clients:
                client.close()
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_thread_start_failure_cleanup(self):
        with mock.patch.object(sys, "argv", ["preview.py"]), \
                mock.patch("preview.Server") as server, \
                mock.patch("preview.signal.signal"), \
                mock.patch("preview.open", mock.mock_open()), \
                mock.patch("preview.subprocess.Popen") as process, \
                mock.patch("preview.threading.Thread.start", side_effect=RuntimeError("start")):
            with self.assertRaisesRegex(RuntimeError, "start"):
                main()
            process.return_value.terminate.assert_called_once()
            process.return_value.wait.assert_called_once()
            server.return_value.shutdown.assert_not_called()
            server.return_value.server_close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
