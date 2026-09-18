import json
import sys
import time
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.companion.diagnostics import Diagnostics
from apps.companion.core import Companion
from apps.companion.config import validate
from test_companion import FakeAudio, FakeCodec, wait_for
from test_companion_streaming import StreamTransport

class DiagnosticsTests(unittest.TestCase):
    def test_fixed_templates_bounds_and_copy(self):
        log = Diagnostics(capacity=3)
        for _ in range(6): log.emit("microphone_muted")
        log.emit("secret transcript and token")
        result = log.snapshot()
        self.assertEqual(len(result["entries"]), 3)
        self.assertEqual(result["entries"][-1]["id"], 6)
        self.assertNotIn("secret", json.dumps(result))
        result["entries"][0]["message"] = "changed"
        self.assertNotEqual(log.snapshot()["entries"][0]["message"], "changed")

    def test_system_only_returns_fixed_summaries_and_caches(self):
        calls=[]
        def read():
            calls.append(1)
            return "[1.2] rknpu init token=private\n[2.3] ALSA error transcript=private\n[3] arbitrary private", True
        log=Diagnostics(system_reader=read)
        result=log.snapshot(source="system")
        self.assertEqual(len(result["entries"]), 2)
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(len(log.snapshot(source="system",level="error")["entries"]), 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["entries"][0]["timestamp"], "boot+1.2s")

    def test_unavailable_system_and_invalid_filters(self):
        log=Diagnostics(system_reader=lambda:("secret",False))
        self.assertFalse(log.snapshot(source="system")["supported"])
        self.assertEqual(log.snapshot(source="system")["entries"], [])
        with self.assertRaises(ValueError):log.snapshot(source="/etc/shadow")
        with self.assertRaises(ValueError):log.snapshot(level="debug")

class DeviceLifetimeTests(unittest.TestCase):
    def setUp(self):
        config=validate(dict(mode="live", voice_backend="local",local_asr_backend="rknn",
            local_asr_streaming=True, local_speech_root="/models",local_speech_socket="/speech.sock",
            local_asr_command=["/bin/true"],local_tts_command=["/bin/true"],
            aec_enabled=True,aec_library="/fake.so",full_duplex=True))
        config["standalone_voice"] = True
        self.core=Companion(config,FakeAudio,FakeCodec,StreamTransport)
    def tearDown(self):self.core.close()
    def start(self):
        self.core.start();self.core.action("connect")
        wait_for(lambda:self.core.snapshot()["connected"])
        self.assertTrue(self.core.snapshot()["muted"])
        self.core.action("unmute");self.core.action("continuous")

    def test_default_muted_and_browser_absence_does_not_stop(self):
        self.assertTrue(self.core.snapshot()["muted"])
        self.assertEqual(self.core.snapshot()["control_mode"],"device")
        self.start()
        self.core.auto_until=time.monotonic()-1
        time.sleep(.15)
        self.assertTrue(self.core.snapshot()["continuous"])
        self.assertTrue(self.core.audio.recording)
        self.core.action("keep_listening")
        self.assertLess(self.core.auto_until,time.monotonic())
        self.core.action("mute")
        self.assertTrue(self.core.snapshot()["muted"])
        self.assertFalse(self.core.snapshot()["continuous"])

    def test_failure_stops_capture_and_logs_no_private_text(self):
        self.start();audio=self.core.audio
        self.core.post("error","private backend token")
        wait_for(lambda:self.core.snapshot()["state"]=="error")
        self.assertFalse(audio.recording)
        self.assertTrue(self.core.snapshot()["muted"])
        self.assertFalse(self.core.snapshot()["continuous"])
        logs=json.dumps(self.core.diagnostics.snapshot())
        self.assertNotIn("private",logs)
        self.assertIn("session_failed",logs)

    def test_disconnect_stops_device_owned_capture(self):
        self.start();audio=self.core.audio
        self.core.action("disconnect")
        self.assertFalse(audio.recording)
        self.assertTrue(self.core.snapshot()["muted"])
        self.assertFalse(self.core.snapshot()["continuous"])

    def test_browser_mode_retains_expiry(self):
        self.core.config["standalone_voice"]=False
        self.start()
        self.core.auto_until=time.monotonic()-1
        wait_for(lambda:not self.core.snapshot()["continuous"])
        self.assertTrue(self.core.snapshot()["muted"])

if __name__ == "__main__": unittest.main()
