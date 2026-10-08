#!/usr/bin/env python3
"""Run the actual one-shot reset gate against ordinary-file failure fixtures."""
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    source = HERE / "linux-return-guard.sh"
    cases = ["rejected probe", "identity off", "module read failure", "mount read failure", "process read failure",
             "unexpected module", "missing module", "persistent mount", "loop residual", "open input fd",
             "network worker", "unknown outcome", "extra firmware newline", "failed off readback",
             "wrong PID1 argv", "wrong PID1 ELF"]
    passed = []
    with tempfile.TemporaryDirectory(prefix="accel-reset-guard-") as directory:
        base = Path(directory)
        for index, case in enumerate(cases):
            fixture = base / str(index)
            fixture.mkdir()
            def write(name, value):
                path = fixture / name.lstrip("/")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
                return path
            write("proc/1/comm", "sh\n")
            write("proc/1/fd/.keep", "")
            write("proc/2/comm", "kthreadd\n")
            write("proc/2/fd/.keep", "")
            write("proc/mounts", "rootfs / rootfs rw 0 0\nproc /proc proc rw 0 0\n")
            write("proc/modules", "sensor_dev 100 1 mxc6655xa Live 0\nmxc6655xa 100 0 - Live 0\n")
            write("sys/module/sensor_dev/initstate", "live\n")
            write("sys/module/mxc6655xa/initstate", "live\n")
            write("sys/module/firmware_class/parameters/path", "\n")
            outcome = "identity-off\n" if case in ["identity off", "failed off readback"] else "probe-rejected\n"
            write("tmp/accel/outcome", outcome)
            helper = write("tmp/accel/sensor-inspect", "#!/bin/sh\nexit " + ("1" if case == "failed off readback" else "0") + "\n")
            helper.chmod(0o700)
            if outcome == "identity-off\n":
                driver = fixture / "sys/bus/i2c/devices/5-0015/driver"
                driver.parent.mkdir(parents=True)
                provider = fixture / "sys/bus/i2c/drivers/gsensor_mxc6655"
                provider.mkdir(parents=True)
                driver.symlink_to(provider)
            if case == "unexpected module":
                write("proc/modules", "bcmdhd 100 0 - Live 0\n")
            if case == "missing module":
                write("proc/modules", "sensor_dev 100 0 - Live 0\n")
            if case == "persistent mount":
                write("proc/mounts", "disk /mnt ext4 ro 0 0\n")
            if case == "open input fd":
                (fixture / "proc/2/fd/3").symlink_to("/dev/input/event0")
            if case == "network worker":
                write("proc/2/comm", "wpa_supplicant\n")
            if case == "unknown outcome":
                write("tmp/accel/outcome", "maybe\n")
            if case == "extra firmware newline":
                write("sys/module/firmware_class/parameters/path", "\n\n")
            tools = fixture / "tools"
            tools.mkdir()
            for name, content in {
                "uname": "printf '%s\\n' 5.10.160-rt89-g9f9e9d18574d-dirty\n",
                "losetup": "exit 0\n" if case != "loop residual" else "printf '%s\\n' /dev/loop0\n",
                "hexdump": 'case "$*" in\n*proc/1/cmdline*) printf ' +
                    ('00' if case == "wrong PID1 argv" else '2f62696e2f7368002f696e697400') +
                    ' ;;\n*) printf ' + ('0a0a' if case == "extra firmware newline" else '0a') + ' ;;\nesac\n',
                "sha256sum": "printf '%s  %s\\n' " +
                    ('wrong' if case == "wrong PID1 ELF" else '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1') + ' "$1"\n',
                "readlink": "case \"$*\" in\n*proc/1/exe*) printf '%s\\n' /bin/busybox ;;\n*5-0015/driver*) printf '%s\\n' /sys/bus/i2c/drivers/gsensor_mxc6655 ;;\n*) exec /usr/bin/readlink \"$@\" ;;\nesac\n",
            }.items():
                path = tools / name
                path.write_text("#!/bin/sh\n" + content)
                path.chmod(0o700)
            fail = {"module read failure": "proc/modules", "mount read failure": "proc/mounts",
                    "process read failure": "proc/2/comm"}.get(case)
            cat = tools / "cat"
            cat.write_text("#!/bin/sh\n" + (f'if test "$1" = "{fixture / fail}"; then exit 7; fi\n' if fail else "") +
                           'exec /usr/bin/cat "$@"\n')
            cat.chmod(0o700)
            script = source.read_text()
            script = re.sub(r"/(?:proc|sys|tmp|dev)/", lambda match: str(fixture) + match.group(0), script)
            # The fixture readlink returns the production provider path.
            script = script.replace(str(fixture) + "/sys/bus/i2c/drivers/gsensor_mxc6655",
                                    "/sys/bus/i2c/drivers/gsensor_mxc6655")
            # Keep FD target policy on real device path strings, not fixture paths.
            for line in script.splitlines():
                if "/dev/i2c-*|" in line:
                    script = script.replace(line, line.replace(str(fixture) + "/dev/", "/dev/"))
            gate = fixture / "gate.sh"
            gate.write_text(script)
            result = subprocess.run(["sh", str(gate)], env={**os.environ, "PATH": str(tools) + ":/usr/bin:/bin"},
                                    capture_output=True, text=True)
            expected_success = case in ["rejected probe", "identity off"]
            if (result.returncode == 0) != expected_success:
                raise AssertionError(f"{case}: exit {result.returncode}: {result.stdout} {result.stderr}")
            if ("ACCEL_RAM_ONLY_RESET_READY_SENSOR_MODULES_RETAINED" in result.stdout) != expected_success:
                raise AssertionError("Wrong gate success marker: " + case)
            passed.append(case)
    print(json.dumps({"status": "ACCEL_ACTUAL_RESET_GUARD_TESTS_PASSED", "passed": passed,
                      "guard_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "board_tested": False}, indent=2))


if __name__ == "__main__":
    main()
