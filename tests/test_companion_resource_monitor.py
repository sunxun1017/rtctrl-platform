"""Linux worker resource accounting, independent of real models and devices."""
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.companion.monitor import Monitor


class WorkerResourceTests(unittest.TestCase):
    def setUp(self):
        self.worker = SimpleNamespace(pid=42, poll=Mock(return_value=None))
        self.monitor = Monitor(SimpleNamespace(speech_worker=self.worker))
        self.monitor.clock_ticks = 100
        self.monitor.read_process = Mock(return_value=(1000, 10, 5, {"VmRSS": 12.5, "VmHWM": 20.0}))

    def test_first_sample_unknown_then_multicore_cpu(self):
        first = self.monitor.sample_worker(10)
        self.assertIsNone(first["local_speech_cpu_percent"])
        self.assertEqual(first["local_speech_threads"], 5)
        self.assertEqual(first["local_speech_rss_mb"], 12.5)
        self.assertEqual(first["local_speech_peak_rss_mb"], 20)
        self.monitor.read_process.return_value = (1000, 310, 5, {})
        self.assertEqual(self.monitor.sample_worker(12)["local_speech_cpu_percent"], 150)

    def test_pid_reuse_and_counter_reset_do_not_make_false_spike(self):
        self.monitor.sample_worker(10)
        self.monitor.read_process.return_value = (2000, 5000, 5, {})
        self.assertIsNone(self.monitor.sample_worker(11)["local_speech_cpu_percent"])
        self.monitor.read_process.return_value = (2000, 5, 5, {})
        self.assertIsNone(self.monitor.sample_worker(12)["local_speech_cpu_percent"])

    def test_dead_worker_clears_stale_metrics(self):
        self.monitor.sample_worker(10)
        self.worker.poll.return_value = 1
        result = self.monitor.sample_worker(11)
        self.assertFalse(result["local_speech_running"])
        for name in ("rss_mb", "peak_rss_mb", "cpu_percent", "threads"):
            self.assertIsNone(result["local_speech_" + name])
        self.assertIsNone(self.monitor.worker_sample)

    def test_proc_race_clears_previous_cpu_baseline(self):
        self.monitor.sample_worker(10)
        self.monitor.read_process.side_effect = FileNotFoundError()
        self.assertIsNone(self.monitor.sample_worker(11)["local_speech_rss_mb"])
        self.monitor.read_process.side_effect = None
        self.assertIsNone(self.monitor.sample_worker(12)["local_speech_cpu_percent"])

    def test_equal_timestamp_does_not_divide_by_zero(self):
        self.monitor.sample_worker(10)
        self.assertIsNone(self.monitor.sample_worker(10)["local_speech_cpu_percent"])

    def test_proc_parser_handles_spaces_and_parentheses_in_comm(self):
        # Fields 3..22. utime=14, stime=15, num_threads=20, starttime=22.
        fields = ["0"] * 20
        fields[0], fields[11], fields[12], fields[17], fields[19] = "S", "120", "30", "6", "999"
        stat = "42 (voice (worker)) " + " ".join(fields)
        status = "Name:\tvoice\nVmRSS:\t1536 kB\nVmHWM:\t2048 kB\n"
        with patch("builtins.open", side_effect=[io.StringIO(stat), io.StringIO(status)]):
            self.assertEqual(Monitor.read_process(42), (999, 150, 6, {"VmRSS": 1.5, "VmHWM": 2.0}))


class BoardResourceTests(unittest.TestCase):
    def setUp(self):
        self.monitor = Monitor(SimpleNamespace())

    def sample_cpu(self, values, cores=4):
        raw = "cpu " + values + "\n" + "".join(
            "cpu%d 0 0 0 0 0 0 0 0\n" % index for index in range(cores))
        with patch("builtins.open", return_value=io.StringIO(raw)):
            return self.monitor.sample_system_cpu()

    def test_aggregate_cpu_excludes_guest_and_normalizes_all_cores(self):
        first = self.sample_cpu("100 0 50 500 10 0 0 0 90 0")
        self.assertIsNone(first["system_cpu_percent"])
        self.assertEqual(first["cpu_logical_cores"], 4)
        # Busy +100, idle +280, iowait +20 -> 25%, irrespective of guest +90.
        result = self.sample_cpu("180 0 70 780 30 0 0 0 180 0")
        self.assertEqual(result["system_cpu_percent"], 25)
        self.assertEqual(result["cpu_logical_cores"], 4)

    def test_cpu_idle_busy_and_no_progress(self):
        self.sample_cpu("0 0 0 0 0 0 0 0")
        self.assertEqual(self.sample_cpu("0 0 0 40 0 0 0 0")["system_cpu_percent"], 0)
        self.assertEqual(self.sample_cpu("40 0 0 40 0 0 0 0")["system_cpu_percent"], 100)
        self.assertIsNone(self.sample_cpu("40 0 0 40 0 0 0 0")["system_cpu_percent"])

    def test_cpu_reset_and_hotplug_rebaseline(self):
        self.sample_cpu("100 0 50 500 10 0 0 0")
        self.assertIsNone(self.sample_cpu("0 0 0 0 0 0 0 0")["system_cpu_percent"])
        self.assertEqual(self.sample_cpu("20 0 0 20 0 0 0 0")["system_cpu_percent"], 50)
        self.assertIsNone(self.sample_cpu("40 0 0 40 0 0 0 0", cores=2)["system_cpu_percent"])

    def test_cpu_unreadable_or_malformed_is_unknown_and_clears_baseline(self):
        for raw in ("", "intr 123\n", "cpu 1 2 3\n", "cpu x 0 0 0 0 0 0 0\ncpu0 0\n",
                    "cpu -1 0 0 0 0 0 0 0\ncpu0 0\n", "cpu 0 0 0 0 0 0 0 0\n"):
            with self.subTest(raw=raw):
                self.sample_cpu("10 0 0 10 0 0 0 0")
                with patch("builtins.open", return_value=io.StringIO(raw)):
                    self.assertEqual(self.monitor.sample_system_cpu(),
                                     {"system_cpu_percent": None, "cpu_logical_cores": None})
                self.assertIsNone(self.monitor.system_cpu_sample)
        with patch("builtins.open", side_effect=PermissionError()):
            self.assertIsNone(self.monitor.sample_system_cpu()["system_cpu_percent"])

    def test_npu_valid_load_including_zero(self):
        for value in (0, 10, 100):
            with patch("builtins.open", return_value=io.StringIO("NPU load: %d%%\n" % value)) as opened:
                self.assertEqual(Monitor.sample_npu(), {"npu_load_percent": value})
                opened.assert_called_once_with("/sys/kernel/debug/rknpu/load")

    def test_npu_missing_or_invalid_never_claims_zero(self):
        for raw in ("", "NPU load: 101%", "NPU load: -1%", "NPU load: 1.5%",
                    "NPU load: 10% unexpected", "Core0: 10%", "NPU load: 10%\nNPU load: 20%"):
            with self.subTest(raw=raw), patch("builtins.open", return_value=io.StringIO(raw)):
                self.assertIsNone(Monitor.sample_npu()["npu_load_percent"])
        for error in (PermissionError(), FileNotFoundError()):
            with patch("builtins.open", side_effect=error):
                self.assertIsNone(Monitor.sample_npu()["npu_load_percent"])


if __name__ == "__main__":
    unittest.main()
