#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Copy SHA-pinned libfdt sources and compile only inside a fresh local build."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def meta(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out).absolute()
    if out != out.resolve() or not out.is_relative_to(HERE / "build"):
        parser.error("Fresh ordinary own build path required")
    lock = json.loads((HERE / "source-lock-v2.json").read_text())
    inputs = {}
    for name, digest in lock["sources"].items():
        data = (ROOT / lock["library"] / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Locked source changed: " + name)
        inputs[name] = data
    out.mkdir(parents=True, exist_ok=False)
    source = out / "libfdt-source"
    source.mkdir()
    for name, data in inputs.items():
        (source / name).write_bytes(data)
    license_data = (ROOT / "third_party/linux-rk3588/LICENSES/preferred/BSD-2-Clause").read_bytes()
    (out / "BSD-2-Clause.txt").write_bytes(license_data)
    target = out / "libfdt-locked.so"
    compiler = Path("/usr/bin/gcc").resolve()
    command = [str(compiler), "-std=gnu11", "-O2", "-fPIC", "-shared", "-Wall", "-Wextra", "-Werror",
               "-I", str(source)] + [str(source / name) for name in sorted(inputs) if name.endswith(".c")]
    command += ["-o", str(target)]
    process = subprocess.run(command, capture_output=True, timeout=90)
    (out / "compile.stdout").write_bytes(process.stdout)
    (out / "compile.stderr").write_bytes(process.stderr)
    if process.returncode:
        raise ValueError("Real libfdt compile failed: " + process.stderr.decode())
    manifest = {"schema": 1, "command": command, "compiler": {"path": str(compiler), **meta(compiler.read_bytes()),
        "version": subprocess.check_output([str(compiler), "--version"], text=True)},
        "binary": meta(target.read_bytes()), "sources": {name: meta(data) for name, data in inputs.items()},
        "source_lock": meta((HERE / "source-lock-v2.json").read_bytes()), "license": meta(license_data),
        "board_tested": False, "library_is_not_exact_deployed_uboot_version": True}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest["binary"]))


if __name__ == "__main__":
    main()
