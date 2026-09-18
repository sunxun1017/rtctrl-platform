"""Duplex lifecycle tests using no hardware or models."""
import queue
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.companion.local_voice import LocalVoiceTransport


class DuplexTests(unittest.TestCase):
    def setUp(self):
        self.messages = []
        self.errors = []
        self.t = LocalVoiceTransport({"full_duplex": True}, self.messages.append, self.errors.append)
        self.t._closed = False
        self.t._codec = MagicMock()
        self.t._asr_stream = MagicMock()
        self.t._asr_stream.exchange.side_effect = lambda op, *args: {
            "text": "测试" if op in (1, 2) else "", "endpoint": op == 1}
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()
        self.t.close()
        for thread in (self.t._listener, self.t._worker):
            if thread:
                thread.join(2)

    def wait(self, predicate):
        end = time.monotonic() + 2
        while not predicate() and time.monotonic() < end:
            time.sleep(.005)
        self.assertTrue(predicate())

    def start(self):
        self.t.send({"type": "listen", "state": "start", "mode": "auto"})
        self.wait(lambda: any(m.get("type") == "duplex_waiting" for m in self.messages))

    def speech(self):
        for _ in range(3):
            self.t.send_pcm(b"\x64\x00\x9c\xff" * 480)

    def test_reply_does_not_stop_listener_and_forbids_overlap(self):
        self.start()
        self.t._run = lambda *a, **kw: self.release.wait(2)
        self.t.send({"type": "reply", "text": "第一句"})
        with self.assertRaises(RuntimeError):
            self.t.send({"type": "reply", "text": "第二句"})
        self.speech()
        self.wait(lambda: any(m.get("type") == "duplex_final" for m in self.messages))
        self.assertTrue(self.t._recording)
        self.assertTrue(self.t._worker.is_alive())
        self.assertFalse(any(m.get("type") in ("stt", "asr_endpoint") for m in self.messages))
        self.release.set()
        self.wait(lambda: any(m.get("type") == "response_complete" for m in self.messages))
        self.assertIsNone(self.t._worker)

    def test_quiet_does_not_run_asr(self):
        frames = queue.Queue()
        for _ in range(1000):
            frames.put(bytes(1920))
        frames.put(None)
        self.t._duplex_listen(0, frames, self.t._asr_stream)
        self.t._asr_stream.exchange.assert_not_called()

    def test_abort_cancels_native_and_fences_reply(self):
        self.start()
        self.t._run = lambda *a, **kw: self.release.wait(2)
        self.t.send({"type": "reply", "text": "测试"})
        self.t.send({"type": "abort"})
        self.t._asr_stream.close.assert_called_once()
        self.assertFalse(self.t._recording)
        self.release.set()
        self.wait(lambda: self.t._worker is None)
        self.assertFalse(any(m.get("type") == "response_complete" for m in self.messages))

    def test_pcm_limit_finalizes_without_native_endpoint(self):
        self.t._asr_stream.exchange.side_effect = lambda op, *args: {"text": "测试", "endpoint": False}
        frames = queue.Queue()
        for _ in range(500):
            frames.put(b"\x64\x00\x9c\xff" * 480)
        frames.put(None)
        self.t._duplex_listen(0, frames, self.t._asr_stream)
        total = 0
        finalized = []
        for call in self.t._asr_stream.exchange.call_args_list:
            if call.args[0] == 3:
                total = 0
            elif call.args[0] == 1:
                total += len(call.args[1])
                self.assertLessEqual(total, 29 * 32000)
            elif call.args[0] == 2:
                finalized.append(total)
        self.assertEqual(finalized[0], 29 * 32000)
        self.assertEqual(len(finalized), 2)

    def test_completion_can_dispatch_next_reply_reentrantly(self):
        self.start()
        self.t._run = MagicMock()
        completed = threading.Event()
        def receive(message):
            self.messages.append(message)
            if message.get("type") == "response_complete":
                if len([m for m in self.messages if m.get("type") == "response_complete"]) == 1:
                    self.assertIsNone(self.t._worker)
                    self.t.send({"type": "reply", "text": "下一句"})
                else:
                    completed.set()
        self.t.on_message = receive
        self.t.send({"type": "reply", "text": "第一句"})
        self.assertTrue(completed.wait(2))
        self.assertEqual(self.t._run.call_count, 2)

    def test_empty_endpoint_rearms_without_finalize(self):
        self.t._asr_stream.exchange.side_effect = lambda op, *args: {"text": "", "endpoint": op == 1}
        self.start()
        self.speech()
        self.wait(lambda: len([m for m in self.messages if m.get("type") == "duplex_waiting"]) == 2)
        self.assertNotIn(2, [c.args[0] for c in self.t._asr_stream.exchange.call_args_list])
        self.assertTrue(self.t._recording)


if __name__ == "__main__":
    unittest.main()
