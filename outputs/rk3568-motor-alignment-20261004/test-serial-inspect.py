#!/usr/bin/env python3
"""Exercise the real static inspector on host PTYs, never a physical UART."""

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import termios


def require(condition, message):
    if not condition:
        raise ValueError(message)


def expected_report(settings):
    speeds = {
        getattr(termios, "B" + str(value)): value
        for value in [0, 50, 75, 110, 134, 150, 200, 300, 600, 1200,
                      1800, 2400, 4800, 9600, 19200, 38400, 57600,
                      115200, 230400, 460800, 500000, 576000, 921600,
                      1000000, 1152000, 1500000, 2000000, 2500000,
                      3000000, 3500000, 4000000]
        if hasattr(termios, "B" + str(value))
    }
    iflag, _, cflag, _, ispeed, ospeed, cc = settings
    parity = "none"
    if cflag & termios.PARENB:
        parity = "odd" if cflag & termios.PARODD else "even"
        if cflag & getattr(termios, "CMSPAR", 0x40000000):
            parity = "mark" if cflag & termios.PARODD else "space"
    bits = {
        termios.CS5: 5, termios.CS6: 6,
        termios.CS7: 7, termios.CS8: 8,
    }[cflag & termios.CSIZE]
    byte_value = lambda value: value if isinstance(value, int) else value[0]
    return {
        "input_baud": speeds[ispeed],
        "output_baud": speeds[ospeed],
        "data_bits": bits,
        "stop_bits": 2 if cflag & termios.CSTOPB else 1,
        "parity": parity,
        "hardware_flow": bool(cflag & termios.CRTSCTS),
        "ixon": bool(iflag & termios.IXON),
        "ixoff": bool(iflag & termios.IXOFF),
        "ixany": bool(iflag & termios.IXANY),
        "cread": bool(cflag & termios.CREAD),
        "clocal": bool(cflag & termios.CLOCAL),
        "vmin": byte_value(cc[termios.VMIN]),
        "vtime": byte_value(cc[termios.VTIME]),
    }


def invoke(qemu, binary, arguments):
    return subprocess.run(
        [str(qemu), str(binary), *arguments],
        capture_output=True,
        text=True,
        timeout=10,
    )


def pty_case(qemu, binary, speed, flow, stop_bits, validate_report=True):
    master, slave = pty.openpty()
    try:
        os.set_blocking(master, False)
        settings = termios.tcgetattr(slave)
        settings[0] &= ~(termios.IXON | termios.IXOFF | termios.IXANY)
        settings[1] = 0
        settings[2] &= ~(termios.CSIZE | termios.PARENB | termios.PARODD
                         | termios.CSTOPB | termios.CRTSCTS)
        settings[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
        if flow:
            settings[0] |= termios.IXON | termios.IXOFF | termios.IXANY
            settings[2] |= termios.CRTSCTS
        if stop_bits == 2:
            settings[2] |= termios.CSTOPB
        settings[3] = 0
        settings[4] = speed
        settings[5] = speed
        settings[6][termios.VMIN] = 1
        settings[6][termios.VTIME] = 0
        termios.tcsetattr(slave, termios.TCSANOW, settings)
        before = termios.tcgetattr(slave)
        # Bytes sent by this host fixture must remain pending at the slave.
        sentinel = b"host-pty-fixture\x00\xff"
        os.write(master, sentinel)
        result = invoke(qemu, binary, ["--inspect", os.ttyname(slave)])
        require(result.returncode == 0, "PTY inspection failed: " + result.stderr)
        require(termios.tcgetattr(slave) == before, "inspector changed termios")
        outgoing = b""
        if select.select([master], [], [], 0.1)[0]:
            try:
                outgoing = os.read(master, 4096)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
        require(outgoing == b"", "inspector sent bytes to the PTY")
        os.set_blocking(slave, False)
        require(os.read(slave, 4096) == sentinel,
                "inspector consumed pending PTY input")
        if validate_report:
            require(json.loads(result.stdout) == expected_report(before),
                    "reported termios differs from the host PTY")
            require(result.stderr == "", "unexpected inspector diagnostics")
        return {"argv": ["--inspect", os.ttyname(slave)],
                "stdout": result.stdout, "exit_code": result.returncode,
                "termios_unchanged": True, "tty_bytes_sent": 0,
                "pending_input_not_consumed": True}
    finally:
        os.close(slave)
        os.close(master)


def run_suite(qemu, binary, evidence_dir):
    evidence_dir.mkdir()
    cases = []
    for speed, flow, stop in [(termios.B115200, False, 1),
                              (termios.B9600, True, 2),
                              (termios.B1500000, False, 1)]:
        cases.append(pty_case(qemu, binary, speed, flow, stop))
    regular = evidence_dir / "ordinary-file"
    regular.write_bytes(b"ordinary-file-sentinel")
    link = evidence_dir / "symlink"
    link.symlink_to(regular.resolve())
    for arguments in [[], ["--inspect"], ["--wrong", str(regular.resolve())],
                      ["--inspect", str(regular.resolve()), "extra"],
                      ["--inspect", "relative-path"],
                      ["--inspect", str(regular.resolve())],
                      ["--inspect", str(link.resolve(strict=False).parent / "symlink")],
                      ["--inspect", str((evidence_dir / "missing").resolve())],
                      ["--inspect", "/dev/null"]]:
        result = invoke(qemu, binary, arguments)
        require(result.returncode == 2, "invalid input was accepted: " + repr(arguments))
        require(result.stdout == "", "failure printed a success report")
        cases.append({"argv": arguments, "exit_code": result.returncode,
                      "stderr": result.stderr})
    require(regular.read_bytes() == b"ordinary-file-sentinel", "regular file changed")
    # The actual target trace must only query termios, never set it.
    master, slave = pty.openpty()
    try:
        trace = subprocess.run(
            [str(qemu), "-strace", str(binary), "--inspect", os.ttyname(slave)],
            capture_output=True, text=True, timeout=10,
        )
        require(trace.returncode == 0, "QEMU termios trace failed")
        require("TCGETS" in trace.stderr, "trace has no termios query")
        require("TCSETS" not in trace.stderr and "TIOCSTI" not in trace.stderr,
                "trace includes tty mutation")
        (evidence_dir / "qemu-strace.txt").write_text(trace.stderr)
    finally:
        os.close(slave)
        os.close(master)
    record = {"status": "SERIAL_INSPECT_HOST_PTY_PASSED",
              "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "cases_passed": len(cases), "cases": cases,
              "qemu_termios_query_trace_passed": True,
              "physical_uart_tested": False, "board_tested": False,
              "open_may_have_hardware_side_effects": True}
    (evidence_dir / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--qemu", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    arguments = parser.parse_args()
    require(not os.path.lexists(arguments.evidence_dir), "refusing existing evidence")
    for path in [arguments.binary, arguments.qemu]:
        require(path.is_file() and not path.is_symlink(), "invalid executable input")
    record = run_suite(arguments.qemu.resolve(), arguments.binary.resolve(),
                       arguments.evidence_dir.resolve())
    print(record["status"], record["cases_passed"])


if __name__ == "__main__":
    main()
