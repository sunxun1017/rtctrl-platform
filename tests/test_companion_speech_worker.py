"""Private warm-worker IPC without importing real models or audio devices."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.companion.speech_worker import SpeechWorker


class Engine:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def recognize(self, source):
        self.entered.set()
        self.release.wait(2)
        return "测试识别"

    def synthesize(self, text):
        return b"\0" * 100, 22050


class SpeechWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.turn = self.root / "rtctrl-voice-test"
        self.turn.mkdir(mode=0o700)
        self.source = self.turn / "input.wav"
        self.source.write_bytes(b"fake-wave")
        self.output = self.turn / "asr.json"
        self.engine = Engine()
        self.worker = SpeechWorker(self.engine, self.root / "speech.sock", self.root)
        self.thread = threading.Thread(target=self.worker.serve)
        self.thread.start()
        for _ in range(100):
            if self.worker.socket_path.exists():
                break
            time.sleep(.005)

    def tearDown(self):
        self.engine.release.set()
        self.worker.stop.set()
        self.thread.join(3)
        if self.worker.job:
            self.worker.job.join(3)
        self.directory.cleanup()

    def request(self, value, close=True):
        peer = socket.socket(socket.AF_UNIX)
        peer.settimeout(2)
        peer.connect(str(self.worker.socket_path))
        peer.sendall(json.dumps(value).encode() + b"\n")
        if not close:
            return peer
        with peer:
            return json.loads(peer.recv(4096))

    def asr(self):
        return {"operation": "asr", "input": str(self.source), "output": str(self.output)}

    def test_health_and_socket_private(self):
        self.assertTrue(self.request({"operation": "health"})["ready"])
        self.assertEqual(self.worker.socket_path.stat().st_mode & 0o777, 0o600)

    def test_successful_asr_and_tts(self):
        self.assertTrue(self.request(self.asr())["ok"])
        self.assertEqual(json.loads(self.output.read_text())["text"], "测试识别")
        self.assertTrue(self.request({"operation": "tts", "text": "你好", "output": str(self.turn / "tts.wav")})["ok"])

    def test_native_8khz_tts_wave_accepted(self):
        self.engine.synthesize = lambda text: (b"\0" * 160, 8000)
        target = self.turn / "native.wav"
        self.assertTrue(self.request({"operation": "tts", "text": "你好", "output": str(target)})["ok"])
        with wave.open(str(target), "rb") as source:
            self.assertEqual(source.getframerate(), 8000)
            self.assertEqual(source.getnframes(), 80)

    def test_arbitrary_path_and_symlink_rejected(self):
        request = self.asr()
        request["output"] = str(self.root / "outside.json")
        self.assertFalse(self.request(request)["ok"])
        self.output.symlink_to(self.source)
        self.assertFalse(self.request(self.asr())["ok"])
        self.assertEqual(self.source.read_bytes(), b"fake-wave")

    def test_nonprivate_turn_directory_rejected(self):
        self.turn.chmod(0o755)
        self.assertFalse(self.request(self.asr())["ok"])

    def test_busy_does_not_block_health(self):
        self.engine.release.clear()
        peer = self.request(self.asr(), close=False)
        self.assertTrue(self.engine.entered.wait(1))
        self.assertTrue(self.request({"operation": "health"})["busy"])
        self.assertFalse(self.request(self.asr())["ok"])
        self.engine.release.set()
        peer.close()

    def test_disconnected_request_does_not_write(self):
        self.engine.release.clear()
        peer = self.request(self.asr(), close=False)
        self.assertTrue(self.engine.entered.wait(1))
        peer.close()
        self.engine.release.set()
        self.worker.job.join(2)
        self.assertFalse(self.output.exists())

    def test_deleted_directory_not_recreated(self):
        self.engine.release.clear()
        peer = self.request(self.asr(), close=False)
        self.assertTrue(self.engine.entered.wait(1))
        self.source.unlink()
        self.turn.rmdir()
        self.engine.release.set()
        with peer:
            self.assertFalse(json.loads(peer.recv(4096))["ok"])
        self.assertFalse(self.turn.exists())

    def test_reclaims_owned_stale_socket(self):
        stale = self.root / "stale.sock"
        with socket.socket(socket.AF_UNIX) as peer:
            peer.bind(str(stale))
        worker = SpeechWorker(self.engine, stale, self.root)
        worker.stop.set()
        worker.serve()
        self.assertFalse(stale.exists())

    def test_refuses_unrelated_existing_path(self):
        path = self.root / "unrelated"
        path.write_text("keep")
        with self.assertRaises(ValueError):
            SpeechWorker(self.engine, path, self.root).serve()
        self.assertEqual(path.read_text(), "keep")

    def test_invalid_or_oversized_text_rejected(self):
        for text in ("", "a" * 121, 1):
            self.assertFalse(self.request({"operation": "tts", "text": text, "output": str(self.output)})["ok"])


if __name__ == "__main__":
    unittest.main()
