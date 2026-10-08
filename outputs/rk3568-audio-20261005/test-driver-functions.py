#!/usr/bin/env python3
"""Execute real RK817 function bodies with host/QEMU kernel API fault shims."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ORIGINAL = ROOT / "third_party/linux-rk3588"
RELATIVE = "sound/soc/codecs/rk817_codec.c"
QEMU = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"
FUNCTIONS = ["rk817_reset", "rk817_probe", "rk817_remove",
             "rk817_codec_parse_dt_property", "rk817_platform_probe",
             "rk817_set_dai_fmt"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function(text, name):
    match = re.search(r"^static (?:int|void) " + re.escape(name) + r"\([^;]*?\)\s*\{", text, re.M)
    if not match:
        raise ValueError("Missing real function: " + name)
    offset = text.index("{", match.start()) + 1
    depth = 1
    while depth:
        depth += (text[offset] == "{") - (text[offset] == "}")
        offset += 1
    return text[match.start():offset] + "\n"


def new_output(path):
    if path.exists() or path.is_symlink():
        raise ValueError("Refuse existing output: " + str(path))
    for parent in path.parents:
        if parent == ROOT:
            return
        if parent.is_symlink():
            raise ValueError("Refuse symlink output parent")
    raise ValueError("Output escaped repository")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ORIGINAL)
    parser.add_argument("--label", required=True)
    parser.add_argument("--qemu", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", args.label):
        parser.error("label must be red-vN or green-vN")
    source_dir = args.source_dir.resolve(strict=True)
    source_dir.relative_to(ROOT)
    source = source_dir / RELATIVE
    header = source.with_suffix(".h")
    text = source.read_text()
    declaration = re.search(r"struct rk817_codec_priv \{.*?\n\};", text, re.S)
    if not declaration:
        raise ValueError("Missing real private structure")
    names = list(FUNCTIONS)
    if "static void rk817_regmap_release(" in text:
        names.insert(0, "rk817_regmap_release")
    bodies = "\n".join(function(text, name) for name in names)
    unit_text = '#include "' + str(HERE / "test-driver-shim.h") + '"\n'
    unit_text += '#include "' + str(header) + '"\n'
    unit_text += declaration.group() + "\n" + bodies
    unit_text += '#include "' + str(HERE / "test-driver-main.c") + '"\n'
    output = HERE / ("driver-tests-" + args.label)
    new_output(output)
    output.mkdir()
    unit = output / "real-functions.c"
    unit.write_text(unit_text)
    binary = output / "real-functions"
    compiler = "aarch64-linux-gnu-gcc" if args.qemu else "gcc"
    argv = [compiler, "-std=gnu11", "-O0", "-g", "-Wall", "-Wextra",
            "-Wno-unused-parameter", "-Wno-unused-function", "-Wno-unused-variable",
            str(unit), "-o", str(binary)]
    if args.qemu:
        argv.insert(1, "-static")
    compiled = subprocess.run(argv, capture_output=True, text=True)
    (output / "compile.txt").write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode:
        raise ValueError("Real-function harness compile failed; see compile.txt")
    run_argv = [str(QEMU), str(binary)] if args.qemu else [str(binary)]
    result = subprocess.run(run_argv, capture_output=True, text=True, timeout=10)
    (output / "run.txt").write_text(result.stdout + result.stderr)
    cases = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    if not cases:
        raise ValueError("Harness did not report test cases")
    record = {
        "source_sha256": {str(path.relative_to(ROOT)): sha(path) for path in [source, header]},
        "test_input_sha256": {path.name: sha(path) for path in [Path(__file__),
                                  HERE / "test-driver-shim.h", HERE / "test-driver-main.c"]},
        "functions": names, "real_private_structure": True,
        "function_bodies_sha256": hashlib.sha256(bodies.encode()).hexdigest(),
        "generated_unit_sha256": sha(unit), "binary_sha256": sha(binary),
        "compile_argv": argv, "run_argv": run_argv, "qemu": args.qemu,
        "cases": cases, "passed": sum(case["passed"] for case in cases),
        "total": len(cases), "exit_code": result.returncode,
        "board_tested": False, "kernel_module_loaded": False,
        "mocked_kernel_apis": True, "no_hardware_access": True,
        "limitations": ["Extracted real functions execute with mocked kernel APIs",
                        "Partial register writes are not rolled back on a reset failure",
                        "Runtime PCM/path, suspend/resume and full remove concurrency are out of scope"]}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"output": str(output), "passed": record["passed"],
                      "total": record["total"], "exit_code": result.returncode}))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
