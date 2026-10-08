#!/usr/bin/env python3
"""Extract real RK817 mute functions, compile self-contained host/ASan/AArch64 suites."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = "sound/soc/codecs/rk817_codec.c"
NAMES = ["rk817_codec_ctl_gpio", "rk817_restart_dac_digital_clk",
         "rk817_digital_mute_dac", "rk817_digital_mute_adc", "rk817_digital_mute"]
QEMU = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def function(text, name):
    match = re.search(r"^static int " + name + r"\([^;]*?\)\s*\{", text, re.M)
    if not match:
        raise ValueError("missing function: " + name)
    depth = 0
    for index in range(text.index("{", match.start()), len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[match.start():index + 1]
    raise ValueError("unclosed function: " + name)


def run(argv, output, name):
    result = subprocess.run([str(arg) for arg in argv], capture_output=True, text=True, timeout=30)
    (output / (name + ".stdout")).write_text(result.stdout)
    (output / (name + ".stderr")).write_text(result.stderr)
    record = {"argv": [str(arg) for arg in argv], "returncode": result.returncode,
              "stdout_sha256": sha(result.stdout.encode()), "stderr_sha256": sha(result.stderr.encode())}
    return result, record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", args.label):
        parser.error("label must be red-vN or green-vN")
    output = HERE / ("mute-tests-" + args.label)
    output.mkdir(exist_ok=False)
    source = args.source_dir.resolve() / SOURCE
    text = source.read_text()
    declaration = re.search(r"^struct rk817_codec_priv \{.*?\n\};", text, re.M | re.S).group()
    definitions = "\n".join(re.findall(r"^#define CODEC_SET_(?:SPK|HP) .*", text, re.M))
    bodies = "\n\n".join(function(text, name) for name in NAMES)
    for name in ["test-mute-shim.h", "test-mute-main.c", "test-mute-functions.py"]:
        (output / name).write_bytes((HERE / name).read_bytes())
    (output / "rk817_codec.h").write_bytes(source.with_suffix(".h").read_bytes())
    extracted = text[:text.index("#include")] + definitions + "\n" + declaration + "\n\n" + bodies + "\n"
    (output / "extracted.c").write_text(extracted)
    unit = output / "real-functions.c"
    unit.write_text('#include "test-mute-shim.h"\n#include "rk817_codec.h"\n' + extracted + '\n#include "test-mute-main.c"\n')
    result = {"source_sha256": sha(source.read_bytes()), "source": str(source),
              "header_sha256": sha(source.with_suffix(".h").read_bytes()), "extracted_sha256": sha(extracted.encode()),
              "functions": NAMES, "unit_sha256": sha(unit.read_bytes()),
              "harness_sha256": {name: sha((output / name).read_bytes()) for name in
                                 ["test-mute-shim.h", "test-mute-main.c", "test-mute-functions.py"]},
              "board_tested": False,
              "boundary": "Verbatim production mute/GPIO/restart functions; fake component register/GPIO/delay boundaries with explicit cache-before-error fixture. No bus, electrical output, PMIC cache recovery, PCM/ASoC/DMA validation.",
              "runs": {}}
    failed = False
    for label, compiler, flags, launcher in [
        ("host", "gcc", [], []),
        ("host-sanitized", "gcc", ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"], []),
        ("aarch64", "aarch64-linux-gnu-gcc", ["-static"], [QEMU]),
    ]:
        binary = output / ("mute-" + label)
        argv = [compiler, "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                *flags, unit, "-o", binary]
        completed, compiled = run(argv, output, label + "-compile")
        record = {"compile": compiled,
                  "compiler_version": subprocess.run([compiler, "--version"], check=True, capture_output=True, text=True).stdout.splitlines()[0]}
        if completed.returncode:
            failed = True
        else:
            completed, execution = run([*launcher, binary], output, label)
            record.update({"execution": execution, "binary_sha256": sha(binary.read_bytes())})
            try:
                record["tests"] = json.loads(completed.stdout)
            except json.JSONDecodeError as error:
                record["parse_error"] = str(error)
                failed = True
            failed |= completed.returncode != 0
            elf = subprocess.run(["readelf", "-h", "-l", str(binary)], check=True, capture_output=True, text=True).stdout
            (output / (label + ".elf.txt")).write_text(elf)
            record["elf_sha256"] = sha(elf.encode())
            if label == "aarch64":
                if "AArch64" not in elf or "INTERP" in elf:
                    raise ValueError("expected static AArch64 executable")
                record["static_aarch64"] = True
                record["qemu_version"] = subprocess.run([str(QEMU), "--version"], check=True, capture_output=True, text=True).stdout.splitlines()[0]
        result["runs"][label] = record
    result["passed"] = not failed
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(output), "passed": not failed,
                      "tests": {label: {key: record.get("tests", {}).get(key) for key in
                                        ["total", "passed", "failed"]} for label, record in result["runs"].items()}}))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
