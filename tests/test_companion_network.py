"""ConnMan tests use fake jobs and a local PTY; no network changes are made."""
import os
from pathlib import Path
import select
import subprocess
import sys
import termios
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.companion.network import NetworkManager, NetworkError, parse_services, parse_service_details

PSK = "wifi_dc8403cb2273_6950686f6e65_managed_psk"
OPEN = "wifi_dc8403cb2273_74657374_managed_none"
HIDDEN = "wifi_dc8403cb2273_hidden_managed_psk"
ENTERPRISE = "wifi_dc8403cb2273_656e74_managed_ieee8021x"
LISTING = "    iPhone               " + PSK + "\n*AO Guest network       " + OPEN + "\n                         " + HIDDEN + "\n    Enterprise           " + ENTERPRISE + "\n*AO Wired ethernet_ab_cable\n"


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError("background network job did not finish")


class FakePtyProcess:
    def __init__(self, argv, *, stdin, stdout, stderr, close_fds):
        self.argv = argv
        self.echo_flags = termios.tcgetattr(stdin)[3] & (termios.ECHO | termios.ECHONL)
        self.fd = os.dup(stdin)
        self.received = []
        self.returncode = None
        self.done = threading.Event()
        self.worker = threading.Thread(target=self.serve, daemon=True)
        self.worker.start()

    def serve(self):
        pending = b""
        service = None
        try:
            while not self.done.is_set():
                if not select.select([self.fd], [], [], .05)[0]:
                    continue
                pending += os.read(self.fd, 4096)
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    self.received.append(line)
                    if line == b"agent on":
                        os.write(self.fd, b"Agent registered\nconnmanctl> ")
                    elif line.startswith(b"connect "):
                        service = line[8:]
                        if service.endswith(b"_none"):
                            os.write(self.fd, b"Connected " + service + b"\n")
                        else:
                            os.write(self.fd, b"Passphrase? ")
                    else:
                        # Simulate readline echo split across reads, independently of ECHO.
                        os.write(self.fd, line[:4])
                        time.sleep(.01)
                        os.write(self.fd, line[4:] + b"\nConnected " + service + b"\n")
        except OSError:
            pass

    def poll(self):
        return self.returncode

    def terminate(self):
        self.done.set()
        self.returncode = -15

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        self.worker.join(timeout=timeout)
        return self.returncode

    def cleanup(self):
        self.terminate()
        self.worker.join(timeout=1)
        os.close(self.fd)


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.which = mock.patch("apps.companion.network.shutil.which", return_value="/usr/bin/connmanctl")
        self.which.start()
        self.manager = NetworkManager(enabled=True)
        self.manager._data["networks"] = parse_services(LISTING)
        self.manager._next_refresh = time.monotonic() + 3600

    def tearDown(self):
        self.manager.close()
        self.which.stop()

    def test_disabled_by_default_and_no_process(self):
        disabled = NetworkManager()
        self.assertFalse(disabled.snapshot()["available"])
        with self.assertRaises(ValueError):
            disabled.action({"action":"scan"})

    def test_service_parsing_and_ipv4(self):
        networks = parse_services(LISTING)
        self.assertEqual(len(networks), 4)
        self.assertEqual(networks[0]["ssid"], "iPhone")
        self.assertEqual(networks[1]["ssid"], "Guest network")
        self.assertTrue(networks[1]["connected"])
        self.assertEqual(networks[1]["security"], "open")
        self.assertTrue(networks[2]["hidden"])
        self.assertEqual(networks[3]["security"], "unsupported")
        details = parse_service_details("State = online\nIPv4 = [ Method=dhcp, Address=192.168.1.42, Netmask=255.255.255.0 ]")
        self.assertEqual(details, {"connected":True, "ipv4":"192.168.1.42"})
        self.assertNotIn("ipv4", parse_service_details("IPv4 = [ Address=999.1.1.1 ]"))

    def test_rejects_injection_unknown_hidden_enterprise_and_controls(self):
        cases = [{"action":"connect", "service":PSK + ";reboot", "password":"password"},
                 {"action":"connect", "service":"wifi_unknown_managed_psk", "password":"password"},
                 {"action":"connect", "service":HIDDEN, "password":"password"},
                 {"action":"connect", "service":ENTERPRISE, "password":"password"},
                 {"action":"connect", "service":PSK, "password":"secret\ncommand"},
                 {"action":"connect", "service":PSK, "password":"short"},
                 {"action":"connect", "service":OPEN, "password":"unexpected"},
                 {"action":"scan", "command":"disable ethernet"}]
        for body in cases:
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.manager.action(body)
        self.assertFalse(self.manager.snapshot()["busy"])

    def test_scan_retries_no_carrier_and_never_enables_wifi(self):
        replies = [(False,"Error: No carrier"), (True,""), (True,LISTING)]
        with mock.patch.object(self.manager, "_run", side_effect=replies) as run:
            self.manager.action({"action":"scan"})
            wait_for(lambda:not self.manager.snapshot()["busy"])
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [["scan","wifi"], ["scan","wifi"], ["services"]])
        self.assertEqual(self.manager.snapshot()["error"], "")
        self.assertEqual(len(self.manager.snapshot()["networks"]), 4)

    def test_enable_is_explicit_and_does_not_scan(self):
        with mock.patch.object(self.manager, "_run", return_value=(True,"")) as run:
            self.manager.action({"action":"enable"})
            wait_for(lambda:not self.manager.snapshot()["busy"])
        self.assertEqual([call.args[0] for call in run.call_args_list], [["enable", "wifi"]])

    def test_autoconnect_flag_does_not_mean_connected(self):
        listing = "*A  Saved " + PSK + "\n  R Guest " + OPEN
        networks = parse_services(listing)
        self.assertFalse(networks[0]["connected"])
        self.assertTrue(networks[1]["connected"])
        self.assertEqual(networks[1]["ssid"], "Guest")

    def test_single_job_busy_is_rejected_without_blocking(self):
        entered, finish = threading.Event(), threading.Event()
        def scan(deadline):
            entered.set()
            finish.wait(1)
        with mock.patch.object(self.manager, "_scan", side_effect=scan):
            status = self.manager.action({"action":"scan"})
            self.assertTrue(status["busy"])
            self.assertTrue(entered.wait(1))
            try:
                with self.assertRaisesRegex(ValueError, "正在处理"):
                    self.manager.action({"action":"scan"})
            finally:
                finish.set()
            wait_for(lambda:not self.manager.snapshot()["busy"])

    def test_pty_password_never_in_argv_and_echo_is_off(self):
        processes = []
        def spawn(*args, **kwargs):
            process = FakePtyProcess(*args, **kwargs)
            processes.append(process)
            return process
        try:
            with mock.patch("apps.companion.network.subprocess.Popen", side_effect=spawn):
                self.manager._connect(PSK, "Error: 1234", "psk", time.monotonic()+2)
                self.manager._connect(OPEN, "", "open", time.monotonic()+2)
            self.assertEqual(len(processes), 2)
            self.assertEqual(processes[0].argv, ["connmanctl"])
            self.assertEqual(processes[0].echo_flags, 0)
            self.assertEqual(processes[0].received, [b"agent on", ("connect "+PSK).encode(), b"Error: 1234"])
            self.assertEqual(len(processes[1].received), 2)
            self.assertNotIn("Error: 1234", str(self.manager.snapshot()))
        finally:
            for process in processes:
                process.cleanup()

    def test_errors_do_not_reflect_password_or_raw_command_output(self):
        with mock.patch.object(self.manager, "_connect", side_effect=RuntimeError("secret-password raw stderr")):
            self.manager.action({"action":"connect", "service":PSK, "password":"secret-password"})
            wait_for(lambda:not self.manager.snapshot()["busy"])
        self.assertEqual(self.manager.snapshot()["status"], "error")
        self.assertNotIn("secret", str(self.manager.snapshot()))
        self.assertNotIn("stderr", str(self.manager.snapshot()))

    def test_connect_and_disconnect_refresh_details(self):
        with mock.patch.object(self.manager, "_connect"), mock.patch.object(self.manager, "_run", return_value=(True,"State = online\nIPv4 = [ Address=192.168.1.2 ]")):
            self.manager.action({"action":"connect", "service":PSK, "password":"password"})
            wait_for(lambda:not self.manager.snapshot()["busy"])
        status = self.manager.snapshot()
        self.assertEqual(status["networks"][0]["ipv4"], "192.168.1.2")
        self.assertFalse(status["networks"][1]["connected"])
        with mock.patch.object(self.manager, "_run", side_effect=[(True,""),(True,"State = idle")]) as run:
            self.manager.action({"action":"disconnect", "service":PSK})
            wait_for(lambda:not self.manager.snapshot()["busy"])
        self.assertEqual(run.call_args_list[0].args[0], ["disconnect",PSK])
        self.assertFalse(self.manager.snapshot()["networks"][0]["connected"])
        self.assertNotIn("ipv4", self.manager.snapshot()["networks"][0])

    def test_command_reader_caps_output_and_reaps_child(self):
        real_popen = subprocess.Popen
        children = []
        def spawn(argv, **kwargs):
            self.assertEqual(argv, ["connmanctl", "services"])
            process = real_popen([sys.executable, "-c", "import sys; sys.stdout.write('x'*70000)"], **kwargs)
            children.append(process)
            return process
        with mock.patch("apps.companion.network.subprocess.Popen", side_effect=spawn):
            with self.assertRaisesRegex(NetworkError, "输出异常"):
                self.manager._run(["services"], time.monotonic()+2)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed)

    def test_command_timeout_is_bounded_and_close_stops_running_child(self):
        real_popen = subprocess.Popen
        children = []
        def spawn(argv, **kwargs):
            process = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
            children.append(process)
            return process
        with mock.patch("apps.companion.network.subprocess.Popen", side_effect=spawn):
            started = time.monotonic()
            with self.assertRaisesRegex(NetworkError, "超时"):
                self.manager._run(["services"], time.monotonic()+.05)
            self.assertLess(time.monotonic()-started, 1.5)
            self.manager.action({"action":"scan"})
            wait_for(lambda:len(children) == 2)
            started = time.monotonic()
            self.manager.close()
            self.assertLess(time.monotonic()-started, 3)
            self.assertFalse(self.manager._thread.is_alive())
        self.assertTrue(all(child.poll() is not None for child in children))

    def test_snapshot_refresh_is_read_only_and_throttled(self):
        responses = [(True, LISTING), (True, "State = online\nIPv4 = [ Address=192.168.1.50 ]")]
        self.manager._next_refresh = 0
        with mock.patch.object(self.manager, "_run", side_effect=responses) as run:
            self.assertTrue(self.manager.snapshot()["refreshing"])
            wait_for(lambda:not self.manager.snapshot()["refreshing"])
            for _ in range(10):
                self.manager.snapshot()
        state = self.manager.snapshot()
        self.assertFalse(state["stale"])
        self.assertTrue(state["service_available"])
        self.assertIsNotNone(state["last_updated"])
        self.assertEqual(state["networks"][1]["ipv4"], "192.168.1.50")
        self.assertEqual([call.args[0] for call in run.call_args_list], [["services"], ["services", OPEN]])
        self.assertEqual(run.call_args_list[0].args[1], run.call_args_list[1].args[1])

    def test_recent_fresh_status_remains_usable_during_background_refresh(self):
        entered, finish = threading.Event(), threading.Event()
        self.manager._data["stale"] = False
        self.manager._last_success = time.monotonic() - 6
        self.manager._next_refresh = 0
        def read(args, deadline):
            entered.set()
            finish.wait(1)
            return True, "    iPhone " + PSK
        with mock.patch.object(self.manager, "_run", side_effect=read):
            try:
                state = self.manager.snapshot()
                self.assertTrue(state["refreshing"])
                self.assertFalse(state["stale"])
                self.assertTrue(entered.wait(1))
                self.assertFalse(self.manager.snapshot()["stale"])
            finally:
                finish.set()
            wait_for(lambda:not self.manager.snapshot()["refreshing"])
        self.assertFalse(self.manager.snapshot()["stale"])

    def test_status_older_than_fifteen_seconds_is_stale_using_monotonic_time(self):
        self.manager._data.update(stale=False, last_updated=9999999999)
        self.manager._last_success = time.monotonic() - 16
        state = self.manager.snapshot()
        self.assertTrue(state["stale"])
        self.assertFalse(state["refreshing"])
        self.assertEqual(state["last_updated"], 9999999999)

    def test_refresh_observes_external_connection_change(self):
        changed = "*AR iPhone " + PSK + "\n    Guest network " + OPEN
        self.manager._next_refresh = 0
        with mock.patch.object(self.manager, "_run", side_effect=[(True, changed), (True, "State = ready\nIPv4 = [ Address=10.0.0.9 ]")]):
            self.manager.snapshot()
            wait_for(lambda:not self.manager.snapshot()["refreshing"])
        state = self.manager.snapshot()
        self.assertTrue(state["networks"][0]["connected"])
        self.assertEqual(state["networks"][0]["ipv4"], "10.0.0.9")
        self.assertFalse(state["networks"][1]["connected"])
        self.assertNotIn("ipv4", state["networks"][1])

    def test_refresh_failure_marks_unknown_without_stale_connected_claim(self):
        self.manager._data.update(last_updated=123, error="previous user action error")
        self.manager._data["networks"][1]["ipv4"] = "10.0.0.2"
        self.manager._next_refresh = 0
        with mock.patch.object(self.manager, "_run", side_effect=RuntimeError("secret raw stderr")):
            self.manager.snapshot()
            wait_for(lambda:not self.manager.snapshot()["refreshing"])
        state = self.manager.snapshot()
        self.assertTrue(state["available"])
        self.assertFalse(state["service_available"])
        self.assertTrue(state["stale"])
        self.assertEqual(state["last_updated"], 123)
        self.assertEqual(state["error"], "previous user action error")
        self.assertIn("状态未知", state["refresh_error"])
        self.assertNotIn("secret", str(state))
        self.assertFalse(any(item["connected"] for item in state["networks"]))
        self.assertTrue(all("ipv4" not in item for item in state["networks"]))

    def test_user_action_queues_ahead_of_refresh_and_second_action_rejects(self):
        entered, finish = threading.Event(), threading.Event()
        workers = []
        def read(args, deadline):
            self.assertEqual(args, ["services"])
            workers.append(threading.get_ident())
            entered.set()
            finish.wait(1)
            return True, "    iPhone " + PSK
        def scan(deadline):
            workers.append(threading.get_ident())
        self.manager._next_refresh = 0
        with mock.patch.object(self.manager, "_run", side_effect=read), mock.patch.object(self.manager, "_scan", side_effect=scan) as scan_call:
            self.manager.snapshot()
            self.assertTrue(entered.wait(1))
            try:
                state = self.manager.action({"action":"scan"})
                self.assertTrue(state["busy"])
                self.assertEqual(state["status"], "scanning")
                with self.assertRaisesRegex(ValueError, "正在处理"):
                    self.manager.action({"action":"scan"})
            finally:
                finish.set()
            wait_for(lambda:not self.manager.snapshot()["busy"])
        self.assertEqual(scan_call.call_count, 1)
        self.assertEqual(len(workers), 2)
        self.assertEqual(workers[0], workers[1])
        self.assertFalse(self.manager.snapshot()["refreshing"])

    def test_refresh_has_one_deadline_and_caps_connected_detail_queries(self):
        third = "wifi_extra_managed_none"
        listing = "*AR One " + PSK + "\n*AR Two " + OPEN + "\n*AR Three " + third
        self.manager._next_refresh = 0
        with mock.patch.object(self.manager, "_run", side_effect=[(True,listing), (True,"State = ready"), (True,"State = ready")]) as run:
            self.manager.snapshot()
            wait_for(lambda:not self.manager.snapshot()["refreshing"])
        self.assertEqual(run.call_count, 3)
        self.assertEqual(len({call.args[1] for call in run.call_args_list}), 1)

    def test_close_interrupts_pending_pty_and_joins(self):
        processes = []
        def spawn(*args, **kwargs):
            process = FakePtyProcess(*args, **kwargs)
            processes.append(process)
            return process
        try:
            with mock.patch("apps.companion.network.subprocess.Popen", side_effect=spawn), mock.patch.object(self.manager, "_run", side_effect=RuntimeError("cancelled")):
                self.manager.action({"action":"connect", "service":PSK, "password":"password"})
                wait_for(lambda:bool(processes))
                started = time.monotonic()
                self.manager.close()
                self.assertLess(time.monotonic()-started, 3)
                self.assertFalse(self.manager._thread.is_alive())
                self.assertIsNotNone(processes[0].poll())
        finally:
            for process in processes:
                process.cleanup()


if __name__ == "__main__":
    unittest.main()
