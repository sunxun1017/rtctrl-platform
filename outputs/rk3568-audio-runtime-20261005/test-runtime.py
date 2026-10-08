#!/usr/bin/env python3
"""Compile and execute the real codec callbacks with bounded fault injection."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / "outputs/rk3568-audio-20261005"
spec = importlib.util.spec_from_file_location("codec_helpers", OLD / "test-driver-functions.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
NAMES = ["rk817_restart_dac_digital_clk", "rk817_restart_dac_digital_clk_and_apll",
         "rk817_restart_adc_digital_clk", "rk817_restart_adc_digital_clk_and_apll", "rk817_hw_params"]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=OLD / "driver-source-v5")
    parser.add_argument("--label", required=True)
    parser.add_argument("--qemu", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", args.label):
        parser.error("label must be red-vN or green-vN")
    directory = args.source_dir.resolve(strict=True)
    directory.relative_to(ROOT)
    source = directory / helper.RELATIVE
    text = source.read_text()
    declaration = re.search(r"struct rk817_codec_priv \{.*?\n\};", text, re.S).group()
    formats = re.search(r"^#define RK817_FORMATS .*?(?=\n\n)", text, re.M | re.S).group()
    output = HERE / ("runtime-tests-" + args.label)
    helper.new_output(output)
    output.mkdir()
    unit = output / "real-functions.c"
    bodies = "\n".join(helper.function(text, name) for name in NAMES)
    unit.write_text('#include "' + str(HERE / "test-runtime-shim.h") + '"\n' +
                    '#include "' + str(source.with_suffix(".h")) + '"\n' + declaration + "\n" +
                    formats + "\n" + bodies + '#include "' + str(HERE / "test-runtime-main.c") + '"\n')
    binary = output / "real-functions"
    argv = ["aarch64-linux-gnu-gcc" if args.qemu else "gcc", "-std=gnu11", "-O0", "-g",
            "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", str(unit), "-o", str(binary)]
    if args.qemu:
        argv.insert(1, "-static")
    compiled = subprocess.run(argv, capture_output=True, text=True)
    (output / "compile.txt").write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode:
        raise ValueError("Compilation failed; inspect compile.txt")
    run = [str(helper.QEMU), str(binary)] if args.qemu else [str(binary)]
    result = subprocess.run(run, capture_output=True, text=True, timeout=10)
    (output / "run.txt").write_text(result.stdout + result.stderr)
    cases = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    record = {"source_sha256": sha(source), "source_relative": str(source.relative_to(ROOT)),
              "header_sha256": sha(source.with_suffix(".h")), "unit_sha256": sha(unit),
              "test_inputs": {p.name: sha(p) for p in [Path(__file__), HERE / "test-runtime-main.c", HERE / "test-runtime-shim.h"]},
              "compile_argv": argv, "run_argv": run, "qemu": args.qemu,
              "callbacks": NAMES, "cases": cases, "passed": sum(c["passed"] for c in cases),
              "total": len(cases), "exit_code": result.returncode,
              "real_callback_bodies": True, "mocked_kernel_apis": True, "board_tested": False}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"passed": record["passed"], "total": record["total"], "exit_code": result.returncode}))
    raise SystemExit(result.returncode)

if __name__ == "__main__":
    main()
