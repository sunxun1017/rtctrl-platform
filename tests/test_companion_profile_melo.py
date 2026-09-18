"""Controller protocol and bounded direct-child cleanup without model/board access."""
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location('profile_melo', Path(__file__).resolve().parents[1] / 'deploy/companion/profile-melo.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class ProfileTests(unittest.TestCase):
    def test_ready_then_release_target_then_observer_natural_exit(self):
        code = ('import os,json,sys;print("startup",flush=True);'
                'print(json.dumps({"ready":True,"pid":os.getpid()}),flush=True);'
                'assert sys.stdin.readline().strip()=="start";print("complete",flush=True)')
        child = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        observer = None
        try:
            p.wait_ready(child, 3)
            # Stand-in for perf's target-lifetime behavior, independent of perf permissions.
            observer = subprocess.Popen([sys.executable, '-c',
                'import os,time,sys\npid=int(sys.argv[1])\nwhile os.path.exists("/proc/"+str(pid)): time.sleep(.01)', str(child.pid)])
            child.stdin.write(b'start\n'); child.stdin.flush()
            output, _ = child.communicate(timeout=3)
            self.assertEqual(child.returncode, 0)
            self.assertIn(b'complete', output)
            warnings = []
            p.stop_process(observer, warnings, 'observer', natural_timeout=3)
            self.assertEqual(observer.returncode, 0)
            self.assertEqual(warnings, [])
        finally:
            for process in (child, observer):
                if process is not None:
                    p.stop_process(process, [], 'test cleanup')
            if child.stdin: child.stdin.close()
            if child.stdout: child.stdout.close()

    def test_early_child_failure_is_reported(self):
        child = subprocess.Popen([sys.executable, '-c', 'raise SystemExit(4)'], stdout=subprocess.PIPE)
        try:
            with self.assertRaises(RuntimeError):
                p.wait_ready(child, 3)
        finally:
            p.stop_process(child, [], 'failed child')
            child.stdout.close()
        self.assertIsNotNone(child.returncode)

    def test_readiness_timeout_then_reap(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            with self.assertRaises(TimeoutError):
                p.wait_ready(child, .05)
        finally:
            warnings = []
            p.stop_process(child, warnings, 'unready child')
            child.stdout.close()
        self.assertIsNotNone(child.returncode)
        self.assertTrue(warnings)

    def test_cleanup_escalates_and_reaps_only_supplied_process(self):
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired('child', 0), subprocess.TimeoutExpired('child', 3), 0]
        warnings = []
        p.stop_process(process, warnings, 'stuck child')
        process.send_signal.assert_called_once_with(signal.SIGINT)
        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_count, 3)
        self.assertTrue(any('forced termination' in w for w in warnings))


if __name__ == '__main__':
    unittest.main()
