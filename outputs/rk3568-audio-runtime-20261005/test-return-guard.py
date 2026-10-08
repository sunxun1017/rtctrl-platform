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
    cases = ["verified", "rejected", "codec retained", "codec busy", "codec duplicate", "codec dependency", "nonroot", "wrong kernel", "wrong PID1 exe", "wrong PID1 argv",
             "wrong PID1 ELF", "unexpected module", "module read failure", "mount read failure",
             "process read failure", "fd read failure", "persistent mount", "loop residual", "loop query failure",
             "open input", "open SPI", "open control", "open PCM", "open UART0", "network worker", "helper still running", "pcm helper still running", "unknown outcome",
             "extra firmware newline", "network interface", "MCU node", "cache still mounted"]
    passed = []
    with tempfile.TemporaryDirectory(prefix="cap-reset-guard-") as directory:
        base = Path(directory)
        for index, case in enumerate(cases):
            fixture = base / str(index)
            fixture.mkdir()

            def write(name, value):
                path = fixture / name.lstrip("/")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
                return path

            write("proc/self/status", "Uid:\t" + ("2000\t2000\t2000\t2000" if case == "nonroot" else "0\t0\t0\t0") + "\n")
            for pid, comm in [(1, "init"), (2, "kthreadd")]:
                write(f"proc/{pid}/comm", comm + "\n")
                write(f"proc/{pid}/fd/.keep", "")
            write("proc/mounts", "rootfs / rootfs rw 0 0\nproc /proc proc rw 0 0\n")
            write("proc/modules", "" if case == "rejected" else "snd_soc_rk817 520656 1 - Live 0\n")
            write("sys/module/firmware_class/parameters/path", "\n")
            write("tmp/pcm/outcome", "pcm-rejected\n" if case == "rejected" else "pcm-verified\n")
            if case.startswith("codec "):
                modules = "snd_soc_rk817 520656 1 - Live 0\n"
                if case == "codec busy":
                    modules = modules.replace(" 1 - ", " 2 - ")
                if case == "codec dependency":
                    modules = modules.replace(" - ", " other ")
                if case == "codec duplicate":
                    modules += modules
                write("proc/modules", modules)
            if case == "unexpected module":
                write("proc/modules", "bcmdhd 1 0 - Live 0\n")
            if case == "persistent mount":
                write("proc/mounts", "disk /mnt ext4 ro 0 0\n")
            fd_target = {"open input": "/dev/input/event0", "open SPI": "/dev/spidev3.0",
                         "open control": "/dev/snd/controlC1", "open PCM": "/dev/snd/pcmC1D0p", "open UART0": "/dev/ttyS0", "fd read failure": "/dev/spidev3.0"}.get(case)
            if fd_target:
                (fixture / "proc/2/fd/3").symlink_to(fd_target)
            if case in ["network worker", "helper still running"]:
                write("proc/2/comm", "wpa_supplicant\n" if case == "network worker" else "alsa-inspect\n")
            if case == "pcm helper still running":
                write("proc/2/comm", "pcm-config\n")
            if case == "unknown outcome":
                write("tmp/pcm/outcome", "maybe\n")
            if case == "network interface":
                write("sys/class/net/wlan0", "")
            if case == "MCU node":
                write("dev/McuCom", "")
            if case == "cache still mounted":
                write("tmp/pcm-cache/rtctrl-pcm-20261005", "")
            tools = fixture / "tools"
            tools.mkdir()
            commands = {
                "uname": "printf '%s\\n' " + ("wrong" if case == "wrong kernel" else "5.10.160-rt89-g9f9e9d18574d-dirty") + "\n",
                "losetup": "exit 7\n" if case == "loop query failure" else
                    ("printf '%s\\n' /dev/loop0\n" if case == "loop residual" else "exit 0\n"),
                "hexdump": 'case "$*" in\n*proc/1/cmdline*) printf ' +
                    ('00' if case == "wrong PID1 argv" else '2f62696e2f7368002f696e697400') +
                    ' ;;\n*) printf ' + ('0a0a' if case == "extra firmware newline" else '0a') + ' ;;\nesac\n',
                "sha256sum": "printf '%s  %s\\n' " +
                    ('wrong' if case == "wrong PID1 ELF" else '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1') + ' "$1"\n',
                "readlink": 'case "$*" in\n*proc/1/exe*) printf "%s\\n" ' +
                    ('/bin/sh' if case == "wrong PID1 exe" else '/bin/busybox') + ' ;;\n' +
                    ('*proc/2/fd/3*) exit 7 ;;\n' if case == "fd read failure" else '') +
                    '*) exec /usr/bin/readlink "$@" ;;\nesac\n',
            }
            fail = {"module read failure": "proc/modules", "mount read failure": "proc/mounts",
                    "process read failure": "proc/2/comm"}.get(case)
            commands["cat"] = (f'if test "$1" = "{fixture / fail}"; then exit 7; fi\n' if fail else "") + 'exec /usr/bin/cat "$@"\n'
            for name, content in commands.items():
                path = tools / name
                path.write_text("#!/bin/sh\n" + content)
                path.chmod(0o700)
            script = re.sub(r"/(?:proc|sys|tmp|dev)/", lambda m: str(fixture) + m.group(0), source.read_text())
            # Keep FD target policy on real device paths, not fixture paths.
            for line in script.splitlines():
                if "/dev/spidev*|" in line:
                    script = script.replace(line, line.replace(str(fixture) + "/dev/", "/dev/"))
            gate = fixture / "gate.sh"
            gate.write_text(script)
            result = subprocess.run(["sh", str(gate)], env={**os.environ, "PATH": str(tools) + ":/usr/bin:/bin"},
                                    capture_output=True, text=True)
            expected = case in ["verified", "rejected", "codec retained"]
            if (result.returncode == 0) != expected or ("PCM_RAM_ONLY_RESET_READY" in result.stdout) != expected:
                raise AssertionError(f"{case}: exit {result.returncode}: {result.stdout} {result.stderr}")
            passed.append(case)
    print(json.dumps({"status": "CAP_ACTUAL_RESET_GUARD_TESTS_PASSED", "passed": passed,
                      "guard_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "board_tested": False}, indent=2))


if __name__ == "__main__":
    main()
