#!/usr/bin/env python3
"""Build a static AArch64 fixed-address inspection helper and record its tests."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = HERE / "build/inspect-v1"
    if output.exists() or output.is_symlink() or (HERE / "build").is_symlink():
        raise ValueError("Refusing existing/symlink output")
    output.mkdir(parents=True)
    source = HERE / "sensor-inspect.c"
    test = HERE / "test-sensor-inspect.py"
    result = subprocess.run(["python3", str(test)], capture_output=True, check=True)
    (output / "tests.json").write_bytes(result.stdout)
    compiler = "aarch64-linux-gnu-gcc"
    argv = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", "-static", str(source),
            "-o", str(output / "sensor-inspect")]
    subprocess.run(argv, check=True)
    elf = subprocess.check_output(["aarch64-linux-gnu-readelf", "-h", "-l", "-d", str(output / "sensor-inspect")])
    (output / "elf.txt").write_bytes(elf)
    if b"AArch64" not in elf or b"INTERP" in elf or b"NEEDED" in elf:
        raise ValueError("Need static AArch64 helper")
    manifest = {"source_sha256": sha(source), "tests_source_sha256": sha(test),
                "binary_sha256": sha(output / "sensor-inspect"),
                "binary_bytes": (output / "sensor-inspect").stat().st_size,
                "compiler": subprocess.check_output([compiler, "--version"], text=True).splitlines()[0],
                "argv": argv, "tests_passed": len(json.loads(result.stdout)["passed"]),
                "board_tested": False, "fixed_address": "0x15", "registers": ["0x0f", "0x0d", "0x0b"],
                "register_data_writes": False, "register_pointer_writes": True,
                "bus_scan": False, "calibration": False}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
