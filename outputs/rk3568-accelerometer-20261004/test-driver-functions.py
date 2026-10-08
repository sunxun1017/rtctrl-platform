#!/usr/bin/env python3
"""Compile and execute unmodified real driver function bodies with fake I2C."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ORIGINAL = ROOT / "third_party/linux-rk3588/drivers/input/sensors"


def function(source, name):
    match = re.search(r"^(?:static )?(?:int|void) (?:__(?:init|exit) )?" + re.escape(name) + r"\([^;]*?\)\s*\{", source, re.M)
    if not match:
        raise ValueError("Missing real function: " + name)
    begin = source.index("{", match.start())
    depth = 1
    offset = begin + 1
    while depth:
        depth += (source[offset] == "{") - (source[offset] == "}")
        offset += 1
    return source[match.start():offset] + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ORIGINAL)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", args.label):
        parser.error("label must be red-vN or green-vN")
    args.source_dir = args.source_dir.resolve(strict=True)
    args.source_dir.relative_to(ROOT)
    output = HERE / ("driver-tests-" + args.label)
    if output.is_symlink() or any(parent.is_symlink() for parent in output.parents if parent != ROOT):
        raise ValueError("Refuse symlink evidence output")
    output.mkdir()
    paths = [args.source_dir / "sensor-i2c.c", args.source_dir / "sensor-dev.c",
             args.source_dir / "accel/mxc6655xa.c"]
    texts = [path.read_text() for path in paths]
    bus = re.sub(r"^#include .*\n", "", texts[0], flags=re.M)
    bus = re.sub(r"#ifdef CONFIG_HAS_EARLYSUSPEND.*?#endif", "", bus, flags=re.S)
    mxc_defines = "\n".join(line for line in texts[2].splitlines() if line.startswith("#define"))
    pieces = [bus, mxc_defines,
              function(texts[2], "sensor_active"), function(texts[2], "sensor_init")]
    pieces += [function(texts[1], name) for name in [
        "sensor_get_id", "sensor_initial", "sensor_chip_init", "sensor_irq_init", "sensor_probe", "sensor_register_device"]]
    real = "\n".join(pieces)
    lifecycle = "\n".join(function(texts[1], name) for name in [
        "sensor_class_init", "sensor_init", "sensor_exit"])
    suites = []
    for label, content, prefix in [("functions", real, "test-driver"),
                                   ("class", lifecycle, "test-driver-class")]:
        generated = '#include "' + str(HERE / (prefix + "-shim.h")) + '"\n' + content
        generated += '\n#include "' + str(HERE / (prefix + "-main.c")) + '"\n'
        unit = output / ("real-" + label + ".c")
        unit.write_text(generated)
        binary = output / ("real-" + label)
        argv = ["gcc", "-std=gnu11", "-O0", "-g", "-funsigned-char",
                "-Wall", "-Wno-unused-parameter", "-Wno-unused-function", str(unit), "-o", str(binary)]
        compiled = subprocess.run(argv, capture_output=True, text=True)
        (output / (label + "-compile.txt")).write_text(compiled.stdout + compiled.stderr)
        if compiled.returncode:
            raise ValueError("Harness compile failed: " + label)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        (output / (label + "-run.txt")).write_text(result.stdout + result.stderr)
        suites.append({"name": label, "compile_argv": argv, "exit_code": result.returncode,
                       "extracted_function_text_sha256": hashlib.sha256(content.encode()).hexdigest(),
                       "stdout": result.stdout, "stderr": result.stderr})
        print(result.stdout, end="")
    record = {"source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
              "test_input_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in HERE.glob("test-driver-*") if path.is_file()},
              "suites": suites, "exit_code": int(any(suite["exit_code"] for suite in suites)),
              "fake_bus_only": True, "full_real_sensor_probe_body": True,
              "real_sensor_irq_init_body": True,
              "board_tested": False, "kernel_module_loaded": False}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    raise SystemExit(record["exit_code"])


if __name__ == "__main__":
    main()
