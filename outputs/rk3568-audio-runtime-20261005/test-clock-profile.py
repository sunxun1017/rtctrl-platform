#!/usr/bin/env python3
"""Exercise actual shell checker on the captured board clocks and altered faults."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    capture = HERE / "private/pcm-diagnose-v2.raw.txt"
    raw = capture.read_text().replace("\r", "")
    output = HERE / "build/clock-check-v1"
    if output.exists():
        raise ValueError("Refusing existing evidence")
    output.mkdir()
    def section(name):
        text = raw.split("cat /tmp/pcm/clocks-" + name + ".txt\n", 1)[1].split("\n# ", 1)[0]
        lines = [line for line in text.splitlines() if re.fullmatch(r" +\w+\s+(?:\d+\s+){6}\d+", line)]
        if len(lines) != 16:
            raise ValueError("Incomplete board clock capture")
        return "\n".join(lines) + "\n"
    before, after = section("before"), section("after")
    cases = {"real retained inactive RX configuration": (before, after, True),
             "old exact-byte restoration assumption": (before, before, False),
             "missing clock": (before, "\n".join(after.splitlines()[1:]) + "\n", False),
             "unexpected clock": (before, after + after.splitlines()[0] + "\n", False),
             "unknown replacement": (before, after.replace("i2s1_mclkout_rx", "unknown_clock"), False),
             "active RX": (before, re.sub(r"(clk_i2s1_8ch_rx_frac\s+)0", r"\g<1>1", after), False),
             "RX wrong frequency": (before, re.sub(r"(clk_i2s1_8ch_rx_frac\s+0\s+0\s+0\s+)12288000", r"\g<1>12000000", after), False),
             "TX changed frequency": (before, re.sub(r"(clk_i2s1_8ch_tx_frac\s+1\s+1\s+0\s+)12288000", r"\g<1>12000000", after), False),
             "RX wrong parent depth": (before, after.replace("                clk_i2s1_8ch_rx ", "             clk_i2s1_8ch_rx "), False),
             "unaffected parent changed": (before, after.replace("                hclk_i2s1_8ch ", "             hclk_i2s1_8ch "), False),
             "unexpected extra field": (before, after.replace("12000000          0     0  50000", "12000000          0     0  50000 extra"), False),
             "before RX frequency changed": (before.replace("1188000000", "1200000000", 2), after, False)}
    checker = HERE / "verify-clock-profile.sh"
    qemu = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"
    busybox = ROOT / "outputs/rk3568-rng-network-20261004/build/busybox-module-options/v1/busybox"
    results = []
    for index, (name, (left, right, accepted)) in enumerate(cases.items()):
        folder = output / str(index)
        folder.mkdir()
        a, b = folder / "before.txt", folder / "after.txt"
        a.write_text(left)
        b.write_text(right)
        for platform, argv in [("host", ["sh", str(checker), str(a), str(b)]),
                               ("exact-BusyBox-shell", [str(qemu), str(busybox), "sh", str(checker), str(a), str(b)])]:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
            matched = (result.returncode == 0) == accepted
            (folder / (platform + ".txt")).write_text(result.stdout + result.stderr)
            results.append({"case": name, "runtime": platform, "exit_code": result.returncode, "passed": matched})
    record = {"source_capture_sha256": hashlib.sha256(capture.read_bytes()).hexdigest(),
              "checker_sha256": hashlib.sha256(checker.read_bytes()).hexdigest(),
              "total": len(results), "passed": sum(item["passed"] for item in results), "cases": results,
              "boundary": "Real shell and captured clock rows; host grep in shell execution. Board BusyBox grep regex checked separately; no hardware I/O."}
    # Explicitly exercise the same regex with the exact target grep binary.
    probe = subprocess.run([str(qemu), str(busybox), "grep", "-E", "^[[:space:]]*clk_i2s1_8ch_rx[[:space:]]"],
                           input=after, capture_output=True, text=True, check=True)
    assert "12288000" in probe.stdout
    record["target_grep_regex_verified"] = True
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"total": record["total"], "passed": record["passed"]}))
    assert record["total"] == record["passed"]


if __name__ == "__main__":
    main()
