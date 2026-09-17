from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.companion.device import DeviceManager, DeviceError, run_bounded


class Mixer:
    def __init__(self):
        self.values = {"DACL": 191, "DACR": 191, "Speaker": 1, "spk switch": 0,
                       "ADCL PGA": 8, "ADCR PGA": 8}
        self.calls = []
        self.fail_once = None
        self.ignore = None

    def __call__(self, argv):
        self.calls.append(argv)
        command, name = argv[3:5]
        if command == "sset":
            if name == self.fail_once:
                self.fail_once = None
                raise DeviceError("测试写入失败")
            if name != self.ignore:
                self.values[name] = {"on": 1, "off": 0}.get(argv[5], argv[5])
                self.values[name] = int(self.values[name])
        value = self.values[name]
        if name in ("Speaker", "spk switch"):
            return "  Mono: Playback [" + ("on" if value else "off") + "]\n"
        return "  Mono: Playback " + str(value) + " [75%] [0.00dB]\n"


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        (self.path / "max_brightness").write_text("255")
        (self.path / "brightness").write_text("200")
        self.mixer = Mixer()
        self.device = DeviceManager(True, self.mixer, self.path)

    def tearDown(self):
        self.device.close()
        self.temp.cleanup()

    def test_default_disabled_never_reads_or_writes(self):
        device = DeviceManager(runner=self.mixer, backlight_path=self.path)
        self.assertFalse(device.snapshot()["available"])
        with self.assertRaises(ValueError):
            device.action({"action": "set_volume", "value": 50})
        self.assertEqual(self.mixer.calls, [])

    def test_snapshot_reads_without_mutation(self):
        state = self.device.snapshot()
        self.assertEqual(state["volume_percent"], 100)
        self.assertEqual(state["mic_gain_db"], 24)
        self.assertFalse(state["speaker_enabled"])
        self.assertEqual(state["brightness_percent"], 78)
        self.assertTrue(all(call[3] == "sget" for call in self.mixer.calls))

    def test_explicit_safe_controls_and_readback(self):
        for operation, value, key in (("set_volume", 50, "volume_percent"),
                                      ("set_mic_gain", 6, "mic_gain_db"),
                                      ("set_speaker", True, "speaker_enabled"),
                                      ("set_brightness", 10, "brightness_percent")):
            state = self.device.action({"action": operation, "value": value})
            self.assertEqual(state["error"], "")
            self.assertEqual(state[key], value)
        self.assertEqual(self.mixer.values["DACL"], 96)
        self.assertEqual(self.mixer.values["DACR"], 96)
        self.assertEqual(self.mixer.values["spk switch"], 1)
        self.assertEqual((self.path / "brightness").read_text(), "26")

    def test_invalid_body_never_calls_hardware(self):
        for body in ({"action": "set_volume", "value": True},
                     {"action": "set_volume", "value": "50; reboot"},
                     {"action": "set_volume", "value": 101},
                     {"action": "set_mic_gain", "value": 30},
                     {"action": "set_brightness", "value": 0},
                     {"action": "set_speaker", "value": 1},
                     {"action": "set_speaker", "value": True, "name": "anything"},
                     {"action": [], "value": 5}):
            with self.assertRaises(ValueError):
                self.device.action(body)
        self.assertEqual(self.mixer.calls, [])

    def test_partial_channel_failure_rolls_back(self):
        self.mixer.fail_once = "DACR"
        state = self.device.action({"action": "set_volume", "value": 20})
        self.assertIn("已恢复", state["error"])
        self.assertEqual(self.mixer.values["DACL"], 191)
        self.assertEqual(self.mixer.values["DACR"], 191)

    def test_followup_refresh_clears_transient_error(self):
        self.mixer.fail_once = "DACR"
        result = self.device.action({"action": "set_volume", "value": 20})
        self.assertTrue(result["error"])
        self.device._next_read = 0
        self.assertEqual(self.device.snapshot()["error"], "")

    def test_all_controls_missing_report_unavailable(self):
        self.device._runner = lambda argv: "invalid"
        (self.path / "brightness").unlink()
        result = self.device.snapshot()
        self.assertFalse(result["available"])
        self.assertTrue(result["error"])

    def test_silent_write_failure_detected(self):
        self.mixer.ignore = "DACR"
        state = self.device.action({"action": "set_volume", "value": 20})
        self.assertTrue(state["error"])
        self.assertEqual(state["volume_percent"], 100)

    def test_read_failure_reports_unknown(self):
        self.device._runner = lambda argv: "unrecognized output"
        state = self.device.snapshot()
        self.assertIsNone(state["volume_percent"])
        self.assertIsNone(state["speaker_enabled"])
        self.assertFalse(state["supported"]["volume"])

    def test_busy_and_closed_reject_writes(self):
        self.device._lock.acquire()
        try:
            self.assertTrue(self.device.snapshot()["busy"])
            with self.assertRaises(ValueError):
                self.device.action({"action": "set_volume", "value": 10})
        finally:
            self.device._lock.release()
        self.device.close()
        with self.assertRaises(ValueError):
            self.device.action({"action": "set_volume", "value": 10})

    def test_bounded_process_timeout_and_output(self):
        with self.assertRaises(DeviceError):
            run_bounded([sys.executable, "-c", "import time; time.sleep(5)"], 0.05)
        with self.assertRaises(DeviceError):
            run_bounded([sys.executable, "-c", "print('x'*20000)"], 1)
        self.assertEqual(run_bounded([sys.executable, "-c", "print('ok')"]), "ok\n")

    def test_asymmetric_and_amplified_channels_not_misrepresented(self):
        self.mixer.values["DACR"] = 190
        self.assertIsNone(self.device.snapshot()["volume_percent"])
        self.device._next_read = 0
        self.mixer.values.update(DACL=220, DACR=220)
        self.assertIsNone(self.device.snapshot()["volume_percent"])


if __name__ == "__main__":
    unittest.main()
