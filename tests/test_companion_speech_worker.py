"""Private warm-worker IPC without importing real models or audio devices."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
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


class RknnAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runner = self.root / "npu-asr" / "rknn_zipformer_demo"
        self.runner.parent.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, body, timeout=2):
        from apps.companion.speech_worker import RknnRecognizer
        self.runner.write_text("#!" + sys.executable + "\n" + body)
        self.runner.chmod(0o700)
        return RknnRecognizer(self.root, timeout).recognize(self.root / "sample.wav")

    def test_text_and_fixed_arguments(self):
        text = self.run_script("import sys, os\nassert sys.argv[1:4] == ['model/encoder.rknn', 'model/decoder.rknn', 'model/joiner.rknn']\nassert os.path.basename(os.getcwd()) == 'npu-asr'\nprint('load model')\nprint('Zipformer output: 测试文字')\n")
        self.assertEqual(text, "测试文字")

    def test_nonzero_rejected_even_with_text(self):
        with self.assertRaises(ValueError):
            self.run_script("print('Zipformer output: 假结果')\nraise SystemExit(1)\n")

    def test_timeout(self):
        with self.assertRaises(TimeoutError):
            self.run_script("import time\ntime.sleep(5)\n", timeout=.05)

    def test_missing_and_empty_result(self):
        for output in ('ready', 'Zipformer output: '):
            with self.assertRaises(ValueError):
                self.run_script('print(' + repr(output) + ')\n')

    def test_bounded_output(self):
        with self.assertRaises(ValueError):
            self.run_script("print('x' * (2 * 1024 * 1024))\n")

    def test_rknn_keeps_tts_but_does_not_load_cpu_asr(self):
        from apps.companion.speech_worker import SherpaEngine
        sherpa = MagicMock()
        with patch.dict(sys.modules, {"sherpa_onnx": sherpa}):
            previous_path = list(sys.path)
            try:
                engine = SherpaEngine(self.root, asr_backend="rknn")
            finally:
                sys.path[:] = previous_path
        self.assertIsNone(engine.asr)
        sherpa.OfflineRecognizer.from_zipformer_ctc.assert_not_called()
        sherpa.OfflineTts.assert_called_once()

    def test_config_defaults_and_validation(self):
        from apps.companion.config import validate
        self.assertEqual(validate({})['local_asr_backend'], 'cpu')
        self.assertEqual(validate({'local_asr_backend': 'rknn'})['local_asr_backend'], 'rknn')
        for invalid in ('cuda', True, None):
            with self.assertRaises(ValueError):
                validate({'local_asr_backend': invalid})


class SampleConversionTests(unittest.TestCase):
    def test_thread_budget_rejects_invalid_values(self):
        from apps.companion.speech_worker import SherpaEngine
        for threads in (0, 3, True, 1.5):
            with self.assertRaises(ValueError):
                SherpaEngine(Path("/unused"), threads=threads)

    def test_pcm_full_range_preserved(self):
        import numpy as np
        from apps.companion.speech_worker import pcm16_to_float
        samples = np.arange(-32768, 32768, dtype="<i2")
        actual = pcm16_to_float(samples.tobytes())
        self.assertEqual(actual.dtype, np.float32)
        np.testing.assert_array_equal(actual, samples.astype(np.float32) / 32768)

    def test_synthesis_matches_scalar_and_rejects_nonfinite(self):
        import array
        import numpy as np
        from apps.companion.speech_worker import float_to_pcm16
        samples = np.concatenate((np.linspace(-1.5, 1.5, 10001, dtype=np.float32),
                                  np.array([-1, 0, 1, 1/32767, -1/32767], dtype=np.float32)))
        expected = array.array("h", (max(-32768, min(32767, int(value * 32767))) for value in samples))
        if sys.byteorder != "little":
            expected.byteswap()
        self.assertEqual(float_to_pcm16(samples), expected.tobytes())
        for value in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                float_to_pcm16([value])


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
            try:
                with socket.socket(socket.AF_UNIX) as probe:
                    probe.settimeout(.1)
                    probe.connect(str(self.worker.socket_path))
                    probe.sendall(b'{"operation":"health"}\n')
                    if json.loads(probe.recv(4096)).get("ready"):
                        break
            except (OSError, ValueError):
                time.sleep(.005)
        else:
            self.fail("Speech worker did not become ready")

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

    def test_profile_reports_resources_and_rejects_wrong_pid(self):
        with wave.open(str(self.source), "wb") as output:
            output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            output.writeframes(b"\0" * 320)
        script = Path(__file__).resolve().parents[1] / "deploy/companion/profile-speech.py"
        command = [sys.executable, str(script), "--pid", str(os.getpid()),
                   "--socket", str(self.worker.socket_path), "--wav", str(self.source), "--rounds", "1"]
        # Profiling creates its own real /tmp private turn directory.
        previous = self.worker.temp_root
        self.worker.temp_root = Path(tempfile.gettempdir()).resolve()
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual([row.get("operation") for row in rows[1:]], ["asr", "tts"])
            self.assertGreater(rows[-1]["audio_s"], 0)
            self.assertNotIn("测试识别", result.stdout)
            command[command.index("--pid") + 1] = str(os.getpid() + 1)
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Socket peer does not match worker PID", result.stderr)
        finally:
            self.worker.temp_root = previous

    def test_success_ack_is_sent_only_after_busy_is_released(self):
        original = self.worker._send
        completion_states = []
        def checked_send(peer, value):
            if value == {"ok": True}:
                completion_states.append(self.worker.busy.locked())
            original(peer, value)
        self.worker._send = checked_send
        self.assertTrue(self.request(self.asr())["ok"])
        self.assertEqual(completion_states, [False])

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
