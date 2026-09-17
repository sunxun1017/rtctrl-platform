import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "deploy/companion/service-control.py"


class ServiceControlTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.bundle = self.base / "bundle"
        self.bundle.mkdir()
        self.state = self.base / "state"
        self.config = self.base / "config.json"
        self.config.write_text("{}")
        self.env = self.base / "service.env"
        self.env.write_text("RTCTRL_VOICE_TOKEN=private-sentinel-123\nALSA_CONFIG_PATH=/private/asound.conf\n")
        self.env.chmod(0o600)
        self.script = self.bundle / "child.py"
        self.script.write_text(
            "import os,time,signal\n"
            "print('environment='+os.environ.get('RTCTRL_VOICE_TOKEN',''),flush=True)\n"
            "print('alsa='+os.environ.get('ALSA_CONFIG_PATH',''),flush=True)\n"
            "while True: time.sleep(.1)\n")
        (self.bundle / "run-companion.sh").write_text(
            "#!/bin/sh\nexec " + sys.executable + " -B " + str(self.script) + "\n")

    def tearDown(self):
        self.run_control("stop", check=False)
        self.temp.cleanup()

    def run_control(self, action, check=True, full=True):
        command = [sys.executable, "-B", str(CONTROL), action,
                   "--state-dir", str(self.state)]
        if full:
            command += ["--bundle", str(self.bundle), "--config", str(self.config),
                        "--env-file", str(self.env)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def record(self):
        return json.loads((self.state / "service.json").read_text())

    def test_real_start_duplicate_status_stop(self):
        self.run_control("start")
        first = self.record()
        self.run_control("start")
        self.assertEqual(self.record()["pid"], first["pid"])
        result = self.run_control("status", full=False)
        self.assertTrue(json.loads(result.stdout)["running"])
        cmdline = Path("/proc/%d/cmdline" % first["pid"]).read_bytes()
        self.assertNotIn(b"private-sentinel", cmdline)
        time.sleep(.2)
        log = (self.state / "service.log").read_text()
        self.assertNotIn("private-sentinel", log)
        self.assertIn("[redacted]", log)
        self.run_control("stop", full=False)
        result = self.run_control("status", check=False, full=False)
        self.assertEqual(result.returncode, 3)
        self.assertFalse(json.loads(result.stdout)["running"])

    def test_restart_uses_new_owned_process(self):
        self.run_control("start")
        first = self.record()["pid"]
        self.run_control("restart")
        self.assertNotEqual(self.record()["pid"], first)

    def test_stale_record_does_not_kill_unrelated_process(self):
        unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
        try:
            self.state.mkdir(mode=0o700)
            (self.state / "service.json").write_text(json.dumps({
                "pid": unrelated.pid,
                "start": Path("/proc/%d/stat" % unrelated.pid).read_text().rsplit(")", 1)[1].split()[19],
                "child_pid": unrelated.pid, "child_start": "stale",
                "instance": "a" * 32, "status": "running"}))
            self.run_control("stop", full=False)
            self.assertIsNone(unrelated.poll())
            self.run_control("start")
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=2)

    def test_bad_permission_or_shell_style_env_rejected(self):
        self.env.chmod(0o644)
        self.assertNotEqual(self.run_control("start", check=False).returncode, 0)
        self.env.chmod(0o600)
        self.env.write_text("export RTCTRL_VOICE_TOKEN=no\n")
        self.assertNotEqual(self.run_control("start", check=False).returncode, 0)

    def test_log_rotation_is_bounded_and_secret_not_written(self):
        self.script.write_text("import time\nfor i in range(3000): print('X'*160,flush=True)\n"
                               "print('private-sentinel-123',flush=True)\nwhile True: time.sleep(.1)\n")
        self.run_control("start")
        time.sleep(.3)
        logs = list(self.state.glob("service.log*"))
        self.assertLessEqual(len(logs), 3)
        self.assertLessEqual(sum(path.stat().st_size for path in logs), 3 * 66000)
        for path in logs:
            self.assertNotIn("private-sentinel-123", path.read_text())

    def test_failed_child_is_not_reported_started(self):
        self.script.write_text("raise SystemExit(7)\n")
        self.assertNotEqual(self.run_control("start", check=False).returncode, 0)
        result = self.run_control("status", check=False)
        self.assertFalse(json.loads(result.stdout)["running"])

    def test_term_ignoring_child_is_killed_within_bound(self):
        self.script.write_text("import signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                               "while True: time.sleep(.1)\n")
        self.run_control("start")
        started = time.monotonic()
        self.run_control("stop", full=False)
        self.assertLess(time.monotonic() - started, 11)



    def test_control_lock_has_deadline(self):
        self.state.mkdir(mode=0o700)
        with (self.state / "control.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            started = time.monotonic()
            result = self.run_control("status", check=False, full=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("busy", result.stderr)
            self.assertLess(time.monotonic() - started, 14)



    def test_crashed_leader_cleans_up_its_helper(self):
        helper_file = self.base / "helper.pid"
        lines = [
            "import subprocess,sys,time",
            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])",
            "open(" + repr(str(helper_file)) + ",'w').write(str(p.pid))",
            "time.sleep(.8)",
            "raise SystemExit(9)",
        ]
        self.script.write_text("\n".join(lines) + "\n")
        self.run_control("start")
        helper_pid = int(helper_file.read_text())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            path = Path("/proc/%d/stat" % helper_pid)
            if not path.exists() or path.read_text().rsplit(")", 1)[1].split()[0] == "Z":
                break
            time.sleep(.05)
        else:
            self.fail("Helper survived its service process group")

if __name__ == "__main__":
    unittest.main()
