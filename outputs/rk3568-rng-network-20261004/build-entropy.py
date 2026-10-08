#!/usr/bin/env python3
"""Build a new static AArch64 one-shot entropy probe and retain host evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Need an ordinary input file: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ordinary_parent(path):
    current = HERE
    for part in path.relative_to(HERE).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink output component is forbidden")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.revision):
        parser.error("Revision must be v followed by a positive integer")
    destination = HERE / "entropy-check"
    manifest_path = HERE / "entropy-manifest.json"
    output = HERE / "build/entropy" / args.revision
    ordinary_parent(output)
    for path in [destination, manifest_path, output]:
        if os.path.lexists(path):
            parser.error("Refusing existing output: " + str(path))
    red_records = []
    for path in sorted((HERE / "build/entropy").glob("red-v*/result.json")):
        evidence = json.loads(path.read_text())
        if (evidence.get("status") == "EXPECTED_RED_FAILURE" and evidence.get("actual_exit") == 0
                and evidence.get("actual_stdout") == "CRNG_READY" and evidence.get("expected_exit") == 1
                and evidence.get("expected_stdout") == "CRNG_NOT_READY"
                and evidence.get("actual_stderr") == "GETRANDOM_CALLS=1"):
            red_records.append(path)
    if not red_records:
        parser.error("First run test-entropy.py --red-baseline and retain its expected EAGAIN failure")
    red_record = red_records[-1]
    compiler = shutil.which("aarch64-linux-gnu-gcc")
    readelf = shutil.which("aarch64-linux-gnu-readelf")
    if not compiler or not readelf:
        parser.error("Use the existing AArch64 compiler and readelf")
    source = HERE / "entropy-check.c"
    inputs = [source, HERE / "build-entropy.py", HERE / "test-entropy.py"]
    sources = {path.relative_to(ROOT).as_posix(): sha(path) for path in inputs}
    output.mkdir(parents=True)
    compiled = output / "entropy-check"
    command = [compiler, "-static", "-O2", "-Wall", "-Wextra", "-Werror",
               source.relative_to(ROOT).as_posix(), "-o", compiled.relative_to(ROOT).as_posix()]
    compilation = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    (output / "compile.log").write_text(compilation.stdout + compilation.stderr)
    if compilation.returncode:
        raise RuntimeError("Entropy compilation failed; retained compile.log")
    elf_command = [readelf, "-h", "-l", "-d", str(compiled)]
    elf = subprocess.run(elf_command, capture_output=True, text=True, check=True)
    (output / "elf.txt").write_text(elf.stdout + elf.stderr)
    if not re.search(r"Class:\s+ELF64", elf.stdout) or not re.search(r"Machine:\s+AArch64", elf.stdout):
        raise ValueError("Need ELF64 AArch64")
    if not re.search(r"Type:\s+EXEC", elf.stdout) or re.search(r"\b(?:INTERP|NEEDED)\b", elf.stdout):
        raise ValueError("Dynamic executable/interpreter is forbidden")
    test_command = ["python3", str(HERE / "test-entropy.py"), "--revision", "green-" + args.revision,
                    "--binary", str(compiled)]
    testing = subprocess.run(test_command, capture_output=True, text=True)
    (output / "test.stdout").write_text(testing.stdout)
    (output / "test.stderr").write_text(testing.stderr)
    if testing.returncode:
        raise RuntimeError("Entropy test failed; retained output and evidence")
    if sources != {path.relative_to(ROOT).as_posix(): sha(path) for path in inputs}:
        raise ValueError("Source changed during build/test")
    tests = json.loads(testing.stdout)
    compiler_version = subprocess.check_output([compiler, "--version"], text=True).strip()
    manifest = {
        "schema": 1, "source_files": sources, "compile_argv": command,
        "compiler_version": compiler_version, "compiler_real_path": str(Path(compiler).resolve(strict=True)),
        "compiler_sha256": sha(Path(compiler).resolve(strict=True)),
        "artifact": {"file": "entropy-check", "bytes": compiled.stat().st_size, "sha256": sha(compiled)},
        "static_elf": {"class": "ELF64", "machine": "AArch64", "interpreter": False, "dt_needed": False},
        "interface": {"arguments": ["none", "--check"], "getrandom_bytes": 1,
                      "flags": "GRND_NONBLOCK", "maximum_syscalls": 1, "retries": 0,
                      "ready_exit": 0, "not_ready_exit": 1, "failure_or_usage_exit": 2,
                      "random_bytes_output": False, "file_writes": False},
        "host_stub_checks": tests["stub_checks"], "real_host_syscall": tests["real_host_syscall"],
        "qemu_static_binary": tests["qemu_static_binary"],
        "test_evidence": (HERE / "build/entropy" / ("green-" + args.revision) / "result.json").relative_to(ROOT).as_posix(),
        "red_evidence": red_record.relative_to(ROOT).as_posix(), "red_evidence_sha256": sha(red_record),
        "board_tested": False, "source_linux_trng_binding_tested": False,
        "board_entropy_initialized_proven": False, "wifi_radio_problem_fixed": False,
    }
    with destination.open("xb") as stream:
        stream.write(compiled.read_bytes())
    destination.chmod(0o755)
    with manifest_path.open("x") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
