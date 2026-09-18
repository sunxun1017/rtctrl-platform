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


if __name__ == "__main__":
    unittest.main()
