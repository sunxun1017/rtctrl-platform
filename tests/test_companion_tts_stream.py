"""Real Unix-socket framing tests, without models, audio or cloud requests."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.companion.audio import PcmStreamChunk
from apps.companion.local_voice import LocalVoiceTransport


def header(**values):
    return json.dumps(values).encode() + b"\n"


def audio(data):
    return header(type="audio", rate=44100, bytes=len(data)) + data


class TtsStreamClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "speech.sock")
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(self.path)
        self.listener.listen(1)
        self.listener.settimeout(2)
        self.messages = []
        self.errors = []
        self.transport = LocalVoiceTransport({"local_speech_socket": self.path,
            "local_tts_timeout_s": 2, "local_tts_prebuffer_s": 0}, self.messages.append, self.errors.append)
        self.transport._closed = False
        self.server_errors = []
        self.job = None

    def tearDown(self):
        self.transport.close()
        self.listener.close()
        if self.job:
            self.job.join(3)
            self.assertFalse(self.job.is_alive(), "fake server leaked")
        self.temp.cleanup()
        self.assertEqual(self.server_errors, [])

    def serve(self, handler):
        def run():
            try:
                with self.listener.accept()[0] as peer:
                    peer.settimeout(2)
                    line = bytearray()
                    while not line.endswith(b"\n"):
                        data = peer.recv(1)
                        if not data: raise RuntimeError("request ended early")
                        line.extend(data)
                    self.assertEqual(json.loads(line), {"operation": "tts_stream", "text": "测试回答"})
                    handler(peer)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Malformed-stream and cancellation tests close early.
            except BaseException as error:
                self.server_errors.append(error)
        self.job = threading.Thread(target=run)
        self.job.start()

    def execute(self):
        return self.transport._stream_tts(self.transport._generation, "测试回答")

    def assert_no_success_end(self):
        self.assertFalse(any(isinstance(m, PcmStreamChunk) and m.end for m in self.messages))
        self.assertFalse(any(isinstance(m, dict) and m.get("type") == "tts" and m.get("state") == "stop" for m in self.messages))

    def test_fragmented_pcm_start_order_and_done(self):
        first = b"\x01\x00" * 13
        second = b"\x02\x00" * 9
        observed = threading.Event()
        def receive(message):
            self.messages.append(message)
            if isinstance(message, PcmStreamChunk) and message.data == first: observed.set()
        self.transport.on_message = receive
        def handler(peer):
            for byte in audio(first): peer.sendall(bytes([byte]))
            self.assertTrue(observed.wait(1), "first audio waits for final completion")
            packet = audio(second) + header(type="done", ok=True)
            for offset in range(0, len(packet), 3): peer.sendall(packet[offset:offset+3])
        self.serve(handler);self.execute()
        chunks = [m for m in self.messages if isinstance(m, PcmStreamChunk)]
        self.assertEqual(b"".join(m.data for m in chunks), first + second)
        self.assertEqual([m.end for m in chunks], [False, False, True])
        start = next(i for i,m in enumerate(self.messages) if isinstance(m,dict) and m.get("state") == "start")
        first_chunk = next(i for i,m in enumerate(self.messages) if isinstance(m,PcmStreamChunk))
        self.assertLess(start, first_chunk)
        self.assertEqual(self.messages[-1]["state"], "stop")
        self.assertIsNone(self.transport._speech_peer)

    def test_default_prebuffer_waits_two_seconds_then_emits_before_done(self):
        self.transport.config.pop("local_tts_prebuffer_s")
        first = b"\x01\0" * 17640  # 0.4 seconds
        second = b"\x02\0" * 70560  # 1.6 seconds; exactly 2 cumulative
        tail = b"\x03\0" * 40
        heard = threading.Event()
        def receive(message):
            self.messages.append(message)
            if isinstance(message, PcmStreamChunk) and message.data == second: heard.set()
        self.transport.on_message = receive
        def handler(peer):
            peer.sendall(audio(first))
            self.assertFalse(heard.wait(.05))
            self.assertEqual(self.messages, [])
            peer.sendall(audio(second))
            self.assertTrue(heard.wait(1), "two-second buffer must release before done")
            self.assert_no_success_end()
            peer.sendall(audio(tail)+header(type="done",ok=True))
        self.serve(handler);self.execute()
        chunks=[m for m in self.messages if isinstance(m,PcmStreamChunk)]
        self.assertEqual([m.data for m in chunks], [first,second,tail,b""])
        self.assertEqual(b"".join(m.data for m in chunks),first+second+tail)

    def test_default_short_batch_released_only_on_done(self):
        self.transport.config.pop("local_tts_prebuffer_s")
        first=b"\x01\0"*17640
        def handler(peer):
            peer.sendall(audio(first))
            time.sleep(.05)
            self.assertEqual(self.messages, [])
            peer.sendall(header(type="done",ok=True))
        self.serve(handler);self.execute()
        self.assertEqual([m.data for m in self.messages if isinstance(m,PcmStreamChunk)], [first,b""])
        self.assertEqual(self.messages[-1]["state"],"stop")

    def test_cancel_discards_pending_prebuffer(self):
        self.transport.config.pop("local_tts_prebuffer_s")
        sent=threading.Event();client_errors=[]
        def handler(peer):
            peer.sendall(audio(b"\x01\0"*17640))
            sent.set()
            try:peer.recv(1)
            except ConnectionResetError:pass
        self.serve(handler)
        def run():
            try:self.execute()
            except (RuntimeError,ValueError,OSError) as error:client_errors.append(error)
        client=threading.Thread(target=run);client.start()
        self.assertTrue(sent.wait(1));time.sleep(.05)
        self.assertEqual(self.messages, [])
        self.transport.close();client.join(2)
        self.assertFalse(client.is_alive());self.assertTrue(client_errors)
        self.assertEqual(self.messages, [])

    def test_bad_headers(self):
        packets = [b"not-json\n", b"[]\n", b"x" * 4097,
                   header(type="audio", rate=44100, bytes=True),
                   header(type="audio", rate=44100, bytes=3),
                   header(type="audio", rate=16000, bytes=2),
                   header(type="audio", rate=44100, bytes=44100*2*45+2)]
        # Each malformed header uses its own accept/client cycle.
        for packet in packets:
            self.serve(lambda peer, packet=packet: peer.sendall(packet))
            with self.assertRaises((ValueError,RuntimeError)): self.execute()
            self.job.join(2);self.assert_no_success_end()

    def test_mid_pcm_eof(self):
        self.serve(lambda peer: peer.sendall(header(type="audio",rate=44100,bytes=100)+b"xx"))
        with self.assertRaises(RuntimeError):self.execute()
        self.assertEqual(self.messages, [])
        self.assert_no_success_end()

    def test_missing_done(self):
        self.serve(lambda peer: peer.sendall(audio(b"xx")))
        with self.assertRaises(RuntimeError):self.execute()
        self.assert_no_success_end()

    def test_done_failure_after_audio(self):
        self.serve(lambda peer: peer.sendall(audio(b"xx")+header(type="done",ok=False,error="failure")))
        with self.assertRaises(RuntimeError):self.execute()
        self.assert_no_success_end()

    def test_empty_success_rejected(self):
        self.serve(lambda peer: peer.sendall(header(type="done",ok=True)))
        with self.assertRaises(RuntimeError):self.execute()
        self.assert_no_success_end()

    def test_timeout_without_done(self):
        self.transport.config["local_tts_timeout_s"] = .05
        self.serve(lambda peer: time.sleep(.15))
        with self.assertRaises(TimeoutError):self.execute()
        self.assert_no_success_end()

    def test_cumulative_limit(self):
        block = b"\0\0" * (44100 * 20)
        self.serve(lambda peer: peer.sendall(audio(block)+audio(block)+header(type="audio",rate=44100,bytes=len(block))))
        with self.assertRaises(ValueError):self.execute()
        self.assertEqual(sum(len(m.data) for m in self.messages if isinstance(m,PcmStreamChunk)), len(block)*2)
        self.assert_no_success_end()

    def test_cancel_closes_peer_and_fences_end(self):
        ready = threading.Event();closed = threading.Event();client_errors=[]
        def handler(peer):
            ready.set()
            try:
                if peer.recv(1) == b"":closed.set()
            except ConnectionResetError:closed.set()
        self.serve(handler)
        def run_client():
            try:self.execute()
            except (RuntimeError,ValueError,OSError) as error:client_errors.append(error)
        client = threading.Thread(target=run_client);client.start()
        self.assertTrue(ready.wait(1))
        self.transport.close()
        client.join(2)
        self.assertFalse(client.is_alive())
        self.assertTrue(closed.wait(1))
        self.assertTrue(client_errors)
        self.assertEqual(self.messages, [])
        self.assertIsNone(self.transport._speech_peer)


if __name__ == "__main__":unittest.main()
