#!/usr/bin/env python3
"""Execute the production reset guard with ordinary-file failure fixtures."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    source = HERE / "linux-return-guard.sh"
    cases = ["verified", "rejected", "nonroot", "wrong kernel", "wrong PID1 exe", "wrong PID1 argv",
             "wrong PID1 ELF", "unexpected module", "module read failure", "mount read failure",
             "process read failure", "fd read failure", "persistent mount", "loop residual", "loop query failure",
             "open input", "open SPI", "open control", "open PCM", "open UART0", "open framebuffer", "open DRM", "open block", "open physical console", "network worker", "helper still running", "unknown outcome",
             "extra firmware newline", "network interface", "MCU node", "cache still mounted", "console stdio BB", "FIQ stdio BB", "PID1 saved console", "extra console FD", "saved console child", "console wrong exe", "console wrong ELF", "wrong binding", "binding module", "missing verified binding", "normal missing outcome", "normal missing marker", "normal incomplete stage", "stage rejected clean", "stage rejected absent marker", "stage rejected wrong marker", "stage rejected completed", "stage rejected with outcome", "stage rejected unexpected module", "stage rejected persistent mount", "stage rejected wrong PID1 ELF", "stage rejected open framebuffer", "stage rejected extra firmware newline", "stage rejected wrong binding", "stage rejected missing binding"]
    assert source.is_file(), "Display return guard feature is not implemented"
    passed = []
    with tempfile.TemporaryDirectory(prefix="cap-reset-guard-") as directory:
        base = Path(directory)
        for index, case in enumerate(cases):
            fixture = base / str(index)
            fixture.mkdir()
            recovery = case.startswith("stage rejected ")
            scenario = case[len("stage rejected "):] if recovery else case

            def write(name, value):
                path = fixture / name.lstrip("/")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
                return path

            write("proc/self/status", "Uid:\t" + ("2000\t2000\t2000\t2000" if scenario == "nonroot" else "0\t0\t0\t0") + "\n")
            for pid, comm in [(1, "init"), (2, "kthreadd")]:
                write(f"proc/{pid}/comm", comm + "\n")
                write(f"proc/{pid}/fd/.keep", "")
            write("proc/mounts", "rootfs / rootfs rw 0 0\nproc /proc proc rw 0 0\n")
            write("proc/modules", "")
            write("sys/module/firmware_class/parameters/path", "\n")
            write("tmp/display/outcome", "interface-rejected\n" if scenario == "rejected" else "interface-verified\n")
            write("tmp/display-return-guard.sh", "ordinary guard fixture")
            write("tmp/display-stage.sh", "ordinary stage fixture")
            attempt = "display-stage-v2\n" + "514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1  " + str(fixture / "tmp/display-return-guard.sh") + "\n" + "514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1  " + str(fixture / "tmp/display-stage.sh") + "\n"
            write("tmp/display-stage-attempt", attempt)
            write("tmp/display/stage-complete", "display-stage-v2-complete\n")
            if recovery:
                (fixture / "tmp/display/stage-complete").unlink()
                (fixture / "tmp/display/outcome").unlink()
            if scenario in ["absent marker", "normal missing marker"]:
                (fixture / "tmp/display-stage-attempt").unlink()
            if scenario == "wrong marker":
                write("tmp/display-stage-attempt", "foreign-session\n")
            if scenario == "completed":
                write("tmp/display/stage-complete", "display-stage-v2-complete\n")
            if scenario == "with outcome":
                write("tmp/display/outcome", "interface-rejected\n")
            if scenario == "normal missing outcome":
                (fixture / "tmp/display/outcome").unlink()
            if scenario == "normal incomplete stage":
                (fixture / "tmp/display/stage-complete").unlink()
            bindings = {
                "platform": [("display-subsystem", "rockchip-drm"), ("fe040000.vop", "rockchip-vop2"),
                             ("fe060000.dsi", "dw-mipi-dsi-rockchip"), ("fe850000.phy", "inno-dsidphy"),
                             ("backlight", "pwm-backlight")],
                "mipi-dsi": [("fe060000.dsi.0", "panel-simple-dsi")],
            }
            for bus, pairs in bindings.items():
                for device, driver in pairs:
                    target = fixture / ("sys/bus/" + bus + "/drivers/" + driver)
                    target.mkdir(parents=True)
                    directory = fixture / ("sys/bus/" + bus + "/devices/" + device)
                    directory.mkdir(parents=True)
                    (directory / "driver").symlink_to(target)
            if scenario == "verified":
                write("tmp/display/interface-verified", "")
            if scenario == "wrong binding":
                link = fixture / "sys/bus/platform/devices/fe040000.vop/driver"
                link.unlink()
                target = fixture / "sys/bus/platform/drivers/wrong-driver"
                target.mkdir()
                link.symlink_to(target)
            if scenario == "binding module":
                write("sys/bus/platform/drivers/rockchip-vop2/module", "module")
            if scenario in ["missing verified binding", "missing binding"]:
                (fixture / "sys/bus/platform/devices/fe040000.vop/driver").unlink()
            console = {
                "console stdio BB": (2, 0, "/dev/console"), "FIQ stdio BB": (2, 1, "/dev/ttyFIQ0"),
                "PID1 saved console": (1, 11, "/dev/console"), "extra console FD": (2, 3, "/dev/console"),
                "saved console child": (2, 11, "/dev/console"), "console wrong exe": (2, 1, "/dev/console"),
                "console wrong ELF": (2, 1, "/dev/console"),
            }.get(scenario)
            if console:
                pid, fd, target = console
                (fixture / f"proc/{pid}/fd/{fd}").symlink_to(target)
            if scenario == "unexpected module":
                write("proc/modules", "bcmdhd 1 0 - Live 0\n")
            if scenario == "persistent mount":
                write("proc/mounts", "disk /mnt ext4 ro 0 0\n")
            fd_target = {"open input": "/dev/input/event0", "open SPI": "/dev/spidev3.0",
                         "open framebuffer": "/dev/fb0", "open DRM": "/dev/dri/card0", "open block": "/dev/mmcblk0p1", "open physical console": "/dev/ttyFIQ0",
                         "open control": "/dev/snd/controlC1", "open PCM": "/dev/snd/pcmC1D0p", "open UART0": "/dev/ttyS0", "fd read failure": "/dev/spidev3.0"}.get(scenario)
            if fd_target:
                (fixture / "proc/2/fd/3").symlink_to(fd_target)
            if case != "rejected":
                write("tmp/display/interface-verified", "")
            if scenario in ["network worker", "helper still running"]:
                write("proc/2/comm", "wpa_supplicant\n" if scenario == "network worker" else "display-probe\n")
            if scenario == "unknown outcome":
                write("tmp/display/outcome", "maybe\n")
            if scenario == "network interface":
                write("sys/class/net/wlan0", "")
            if scenario == "MCU node":
                write("dev/McuCom", "")
            if scenario == "cache still mounted":
                write("tmp/display-cache/rtctrl-display-20261005-v1", "")
            tools = fixture / "tools"
            tools.mkdir()
            commands = {
                "uname": "printf '%s\\n' " + ("wrong" if scenario == "wrong kernel" else "5.10.160-rt89-g9f9e9d18574d-dirty") + "\n",
                "losetup": "exit 7\n" if scenario == "loop query failure" else
                    ("printf '%s\\n' /dev/loop0\n" if scenario == "loop residual" else "exit 0\n"),
                "hexdump": 'case "$*" in\n*proc/1/cmdline*) printf ' +
                    ('00' if scenario == "wrong PID1 argv" else '2f62696e2f7368002f696e697400') +
                    ' ;;\n*) printf ' + ('0a0a' if scenario == "extra firmware newline" else '0a') + ' ;;\nesac\n',
                "sha256sum": "printf '%s  %s\\n' " +
                    ('wrong' if scenario in ["wrong PID1 ELF", "console wrong ELF"] else '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1') + ' "$1"\n',
                "readlink": 'case "$*" in\n*proc/1/exe*) printf "%s\\n" ' +
                    ('/bin/sh' if scenario == "wrong PID1 exe" else '/bin/busybox') + ' ;;\n' +
                    ('*proc/2/fd/3*) exit 7 ;;\n' if scenario == "fd read failure" else '') +
                    '*proc/2/exe*) printf \"%s\\n\" ' + ('/other' if scenario == 'console wrong exe' else '/bin/busybox') + ' ;;\n' +
                    '*) exec /usr/bin/readlink "$@" ;;\nesac\n',
            }
            fail = {"module read failure": "proc/modules", "mount read failure": "proc/mounts",
                    "process read failure": "proc/2/comm"}.get(scenario)
            commands["cat"] = (f'if test "$1" = "{fixture / fail}"; then exit 7; fi\n' if fail else "") + 'exec /usr/bin/cat "$@"\n'
            for name, content in commands.items():
                path = tools / name
                path.write_text("#!/bin/sh\n" + content)
                path.chmod(0o700)
            script = re.sub(r"/(?:proc|sys|tmp|dev)/", lambda m: str(fixture) + m.group(0), source.read_text())
            # Keep FD target policy on real device paths, not fixture paths.
            for line in script.splitlines():
                if str(fixture) + "/dev/" in line and (line.lstrip().startswith(str(fixture) + "/dev/") or 'test "$target"' in line):
                    script = script.replace(line, line.replace(str(fixture) + "/dev/", "/dev/"))
            gate = fixture / "gate.sh"
            gate.write_text(script)
            result = subprocess.run(["sh", str(gate), *(["--stage-rejected"] if recovery else [])], env={**os.environ, "PATH": str(tools) + ":/usr/bin:/bin"},
                                    capture_output=True, text=True)
            expected = (recovery and scenario in ["clean", "missing binding"]) or (not recovery and scenario in ["verified", "rejected", "console stdio BB", "FIQ stdio BB", "PID1 saved console"])
            marker = "DISPLAY_STAGE_REJECTED_RAM_ONLY_RESET_READY" if recovery else "DISPLAY_RAM_ONLY_RESET_READY"
            if (result.returncode == 0) != expected or (marker in result.stdout) != expected:
                raise AssertionError(f"{case}: exit {result.returncode}: {result.stdout} {result.stderr}")
            passed.append(case)
    record = {"status": "DISPLAY_ACTUAL_RESET_GUARD_TESTS_PASSED", "passed": passed,
                      "guard_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "board_tested": False}
    output = HERE / "build/staging-v8/test-return-guard.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
