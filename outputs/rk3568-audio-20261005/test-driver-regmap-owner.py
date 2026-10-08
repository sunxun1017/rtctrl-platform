#!/usr/bin/env python3
"""Expose parent lookup UAF with actual locked regmap functions under ASan."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / "third_party/linux-rk3588"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(text, name):
    match = re.search(r"^(?:static )?(?:int|void) " + re.escape(name) + r"\([^;]*?\)\s*\{", text, re.M)
    if not match:
        raise ValueError("Missing real function: " + name)
    offset = text.index("{", match.start()) + 1
    depth = 1
    while depth:
        depth += (text[offset] == "{") - (text[offset] == "}")
        offset += 1
    return text[match.start():offset] + "\n"


def main():
    spec = importlib.util.spec_from_file_location("builder", HERE / "build-codec.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    output = HERE / "driver-tests-regmap-owner-v1"
    builder.new_output(output)
    source = KERNEL / "drivers/base/regmap/regmap.c"
    codec = HERE / "driver-source-v3/sound/soc/codecs/rk817_codec.c"
    original = source.read_text()
    bodies = "\n".join(extract(original, name) for name in [
        "regmap_attach_dev", "regmap_exit", "dev_get_regmap_match"])
    bodies += extract(codec.read_text(), "rk817_regmap_release")
    output.mkdir()
    unit = output / "real-regmap-owner.c"
    unit.write_text('#include "' + str(HERE / "test-driver-regmap-owner-shim.h") + '"\n' +
                    bodies + '\n#include "' + str(HERE / "test-driver-regmap-owner-main.c") + '"\n')
    binary = output / "real-regmap-owner"
    argv = ["gcc", "-std=gnu11", "-O1", "-g", "-fsanitize=address", "-fno-omit-frame-pointer",
            str(unit), "-o", str(binary)]
    compile_result = subprocess.run(argv, capture_output=True, text=True)
    (output / "compile.txt").write_text(compile_result.stdout + compile_result.stderr)
    if compile_result.returncode:
        raise ValueError("Real regmap functions failed to compile")
    cases = []
    for mode in ["child-exit-parent-lookup", "parent-lifetime-lookup"]:
        result = subprocess.run([str(binary), mode], capture_output=True, text=True)
        (output / (mode + ".stdout.txt")).write_text(result.stdout)
        (output / (mode + ".stderr.txt")).write_text(result.stderr)
        red = mode.startswith("child")
        expected = "heap-use-after-free" in result.stderr and "dev_get_regmap_match" in result.stderr
        passed = result.returncode != 0 and expected if red else result.returncode == 0
        cases.append({"mode": mode, "passed": passed, "exit_code": result.returncode,
                      "asan_heap_use_after_free_observed": expected})
    record = {"cases": cases, "passed": sum(case["passed"] for case in cases), "total": len(cases),
              "source_sha256": {str(path.relative_to(ROOT)): sha(path) for path in [source, codec]},
              "test_input_sha256": {path.name: sha(path) for path in [Path(__file__),
                 HERE / "test-driver-regmap-owner-shim.h", HERE / "test-driver-regmap-owner-main.c"]},
              "function_bodies_sha256": hashlib.sha256(bodies.encode()).hexdigest(), "compile_argv": argv,
              "real_locked_functions": ["regmap_attach_dev", "regmap_exit", "dev_get_regmap_match"],
              "real_candidate_function": "rk817_regmap_release", "board_tested": False,
              "kernel_module_loaded": False, "scope": "ASan proves dangling parent lookup from candidate child free; no full devres or concurrency claim"}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"output": str(output), "passed": record["passed"], "total": record["total"]}))
    raise SystemExit(record["passed"] != record["total"])


if __name__ == "__main__":
    main()
