"""Isolated ftrace lifecycle and observed scheduler interval accounting."""
import importlib.util
from itertools import repeat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

MODULE = Path(__file__).resolve().parents[1] / 'deploy/companion/ftrace_sched.py'
spec = importlib.util.spec_from_file_location('ftrace_sched', MODULE)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


def switch(ts, prev, state, nxt):
    return f'x [000] d..2 {ts:.6f}: sched_switch: prev_comm=x prev_pid={prev} prev_prio=120 prev_state={state} ==> next_comm=y next_pid={nxt} next_prio=120\n'


def wake(ts, tid):
    return f'x [000] d..2 {ts:.6f}: sched_wakeup: comm=y pid={tid} prio=120 target_cpu=000\n'


class FtraceTests(unittest.TestCase):
    def test_wait_running_sleep_and_preemption(self):
        text = (wake(1, 7) + wake(1.05, 7) + switch(1.1, 1, 'R', 7) +
                switch(1.3, 7, 'S', 1) + wake(1.6, 7) + switch(1.7, 1, 'R', 7) +
                switch(1.8, 7, 'R+', 1) + switch(1.9, 1, 'R', 7))
        row = f.parse_trace(text, [7])['tids']['7']
        self.assertAlmostEqual(row['running_s'], .3)
        self.assertAlmostEqual(row['runnable_s'], .3)
        self.assertAlmostEqual(row['sleeping_s'], .3)
        self.assertAlmostEqual(row['offcpu_s'], .6)
        self.assertEqual(row['switches_in'], 3)

    def test_unknown_boundary_not_counted(self):
        result = f.parse_trace('unrelated text\n' + switch(3, 7, 'S', 1), [7])
        self.assertEqual(result['tids']['7']['offcpu_s'], 0)
        self.assertEqual(result['tids']['7']['running_s'], 0)

    def test_invalid_inputs_rejected_before_filesystem(self):
        with patch.object(f, 'Path') as path:
            for tids in ([], [True], [0], [-1], ['7'], [7, '8'], range(1, 130), repeat(7)):
                with self.assertRaises(ValueError):
                    f.SchedCapture().start(tids)
            for size in (True, 128, 1024, 256.0):
                with self.assertRaises(ValueError):
                    f.SchedCapture(size)
            path.assert_not_called()

    def test_unavailable_never_writes_or_mounts(self):
        with patch.object(f.Path, 'is_dir', return_value=False), patch.object(f.Path, 'write_text') as write:
            capture = f.SchedCapture()
            self.assertFalse(capture.start([7])['available'])
            write.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            result = capture.finish(directory)
            self.assertFalse(result['available'])
            self.assertEqual(result['cleanup_errors'], [])

    def test_existing_instance_is_never_modified(self):
        with patch.object(f.Path, 'is_dir', return_value=True), patch.object(f.Path, 'mkdir', side_effect=FileExistsError), patch.object(f.Path, 'write_text') as write, patch.object(f.Path, 'rmdir') as remove:
            self.assertFalse(f.SchedCapture().start([7])['available'])
            write.assert_not_called()
            remove.assert_not_called()

    def test_partial_start_cleans_only_owned_instance(self):
        capture = f.SchedCapture()
        writes = []
        def write(relative, value):
            writes.append((relative, str(value)))
            if relative == 'trace_clock':
                raise PermissionError('clock blocked')
        with patch.object(f.Path, 'is_dir', return_value=True), patch.object(f.Path, 'mkdir'), patch.object(f.Path, 'rmdir') as remove, patch.object(capture, '_write', side_effect=write):
            result = capture.start([7])
            self.assertFalse(result['available'])
            remove.assert_called_once()
            self.assertIsNone(capture.instance)
            self.assertIn(('events/sched/sched_switch/enable', '0'), writes)
            self.assertNotIn(('tracing_on', '1'), writes)

    def test_finish_loss_and_cleanup_on_read_failure(self):
        for fail in (False, True):
            capture = f.SchedCapture()
            capture.instance = MagicMock()
            capture.started = f.time.monotonic()
            capture.tids = [7]
            files = {}
            def child(name):
                return files.setdefault(name, MagicMock())
            capture.instance.__truediv__.side_effect = child
            child('trace').read_text.return_value = wake(1, 7) + switch(1.2, 1, 'R', 7)
            if fail:
                child('trace').read_text.side_effect = OSError('read failed')
            stat = MagicMock()
            stat.parent.name = 'cpu0'
            stat.read_text.return_value = 'entries: 2\noverrun: 3\ncommit overrun: 0\ndropped events: 0\n'
            child('per_cpu').glob.return_value = [stat]
            instance = capture.instance
            with tempfile.TemporaryDirectory() as directory:
                result = capture.finish(directory)
                self.assertTrue((Path(directory) / 'sched-summary.json').exists())
            instance.rmdir.assert_called_once()
            self.assertIsNone(capture.instance)
            if fail:
                self.assertIn('read failed', result['error'])
            else:
                self.assertTrue(result['lost_events'])
                self.assertFalse(result['reliable_intervals'])


if __name__ == '__main__':
    unittest.main()
