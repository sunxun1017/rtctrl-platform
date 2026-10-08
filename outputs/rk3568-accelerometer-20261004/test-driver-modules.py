#!/usr/bin/env python3
"""Fault-inject real module files and exercise the production module auditor."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import re
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUILDER = HERE / "build-modules.py"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv):
    return subprocess.run(argv, text=True, capture_output=True, timeout=15)


def load_builder():
    specification = importlib.util.spec_from_file_location("sensor_module_builder", BUILDER)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    builder = load_builder()
    output = HERE / ("driver-module-tests-" + args.version)
    builder.new_output(output)
    output.mkdir()
    old = HERE / "driver-modules-v1"
    current = HERE / "driver-modules-v2"
    results = []
    original = {}
    for base in [old, current]:
        for relative in ["modules/sensor_dev.ko", "modules/mxc6655xa.ko", "module-manifest.json"]:
            original[str((base / relative).relative_to(ROOT))] = sha(base / relative)
    exports = builder.symbols(current / "kernel-abi/Module.symvers")
    paired = builder.symbols(current / "modules/Module.symvers")

    def accept(label, module):
        evidence = output / label
        evidence.mkdir()
        record = builder.audit_module(module, evidence, exports, paired)
        results.append({"name": label, "passed": True, "sha256": record["sha256"]})

    def reject(label, mutation, expected):
        evidence = output / label
        evidence.mkdir()
        candidate = evidence / "mxc6655xa.ko"
        shutil.copy2(current / "modules/mxc6655xa.ko", candidate)
        mutation(candidate, evidence)
        try:
            builder.audit_module(candidate, evidence, exports, paired)
        except ValueError as error:
            if expected not in str(error):
                raise AssertionError("Rejected for wrong reason: " + label + ": " + str(error))
            results.append({"name": label, "passed": True, "rejection": str(error),
                            "mutated_module_sha256": sha(candidate)})
        else:
            raise AssertionError("Accepted faulty real module: " + label)

    def architecture(path, evidence):
        data = bytearray(path.read_bytes())
        struct.pack_into("<H", data, 18, 62)
        path.write_bytes(data)

    def metadata(key, replacement):
        def mutate(path, evidence):
            section = evidence / "mutation.modinfo"
            subprocess.run(["aarch64-linux-gnu-objcopy", "--dump-section", ".modinfo=" + str(section),
                            str(path)], check=True)
            entries = section.read_bytes().split(b"\0")
            count = 0
            for index, entry in enumerate(entries):
                if entry.startswith(key.encode() + b"="):
                    entries[index] = (key + "=" + replacement).encode()
                    count += 1
            assert count == 1
            section.write_bytes(b"\0".join(entries))
            subprocess.run(["aarch64-linux-gnu-objcopy", "--update-section", ".modinfo=" + str(section),
                            str(path)], check=True)
        return mutate

    def missing_symbol(path, evidence):
        subprocess.run(["aarch64-linux-gnu-objcopy", "--redefine-sym",
                        "sensor_rx_data=deliberately_missing_sensor_rx_data", str(path)], check=True)

    for name in ["sensor_dev.ko", "mxc6655xa.ko"]:
        accept("accept-" + name, current / "modules" / name)
    reject("wrong-architecture", architecture, "not little-endian AArch64 ET_REL")
    reject("wrong-vermagic", metadata("vermagic", builder.VERMAGIC.replace("dirty", "wrong")), "Wrong module vermagic")
    reject("wrong-dependency", metadata("depends", "other_core"), "Wrong module dependency")
    reject("wrong-license", metadata("license", "MIT"), "Unexpected module license")
    reject("missing-import", missing_symbol, "Import not provided")

    for name in ["sensor_dev.ko", "mxc6655xa.ko"]:
        evidence = output / ("compare-" + name)
        evidence.mkdir()
        stripped = []
        raw_stripped = []
        for version, base in [("v1", old), ("v2", current)]:
            target = evidence / (version + ".ko")
            subprocess.run(["aarch64-linux-gnu-objcopy", "--strip-debug", "--remove-section=.note.gnu.build-id",
                            str(base / "modules" / name), str(target)], check=True)
            raw_stripped.append(sha(target))
            contents = target.read_bytes()
            if name == "mxc6655xa.ko":
                source_path = str(base / "modules/mxc6655xa.c").encode()
                canonical_path = str(old / "modules/mxc6655xa.c").encode()
                if contents.count(source_path) != 1 or len(source_path) != len(canonical_path):
                    raise AssertionError("Unexpected dynamic-debug source path count/length")
                contents = contents.replace(source_path, canonical_path)
            normalized = evidence / (version + "-normalized.ko")
            normalized.write_bytes(contents)
            stripped.append(sha(normalized))
        if stripped[0] != stripped[1]:
            raise AssertionError("v1/v2 module differs outside debug/build-id/known source path: " + name)
        results.append({"name": "v1-v2-same-code-" + name, "passed": True,
                        "transform": "objcopy --strip-debug --remove-section=.note.gnu.build-id; exactly one same-length dynamic-debug source path normalized in MXC only (private copies)",
                        "stripped_sha256_before_path_normalization": raw_stripped,
                        "transformed_sha256": stripped[0]})
    source_hashes = {}
    for name in ["sensor-dev.c", "sensor-i2c.c", "mxc6655xa.c"]:
        v1 = sha(old / "modules" / name)
        v2 = sha(current / "modules" / name)
        if v1 != v2:
            raise AssertionError("Different compiled source: " + name)
        source_hashes[name] = v1
    results.append({"name": "v1-v2-exact-same-source", "passed": True, "sha256": source_hashes})

    rejected_commands = [
        ("refuse-existing-build", ["python3", str(BUILDER), "--version", "v1"], "Refuse existing output"),
        ("refuse-escaping-version", ["python3", str(BUILDER), "--version", "../escape"], "version must be vN"),
        ("refuse-existing-source", ["python3", str(HERE / "driver-prepare.py")], "Refuse existing output"),
    ]
    for label, argv, expected in rejected_commands:
        result = run(argv)
        (output / (label + ".txt")).write_text(result.stdout + result.stderr)
        if result.returncode == 0 or expected not in result.stderr:
            raise AssertionError("Output refusal failed: " + label)
        results.append({"name": label, "passed": True, "exit_code": result.returncode})
    link = HERE / "driver-modules-v999980"
    builder.new_output(link)
    link.symlink_to(output, target_is_directory=True)
    try:
        result = run(["python3", str(BUILDER), "--version", "v999980"])
        (output / "refuse-symlink.txt").write_text(result.stdout + result.stderr)
        if result.returncode == 0 or "Refuse existing output" not in result.stderr:
            raise AssertionError("Symlink output accepted")
        results.append({"name": "refuse-symlink-build-output", "passed": True, "exit_code": result.returncode})
    finally:
        if link.is_symlink() and link.resolve() == output:
            link.unlink()
    for relative, digest in original.items():
        if sha(ROOT / relative) != digest:
            raise AssertionError("Original module/evidence changed")
    record = {"tests": results, "tests_passed": len(results), "failure_count": 0,
              "builder_sha256": sha(BUILDER), "test_script_sha256": sha(Path(__file__)),
              "original_inputs_sha256": original, "original_inputs_unchanged": True,
              "latest_function_tests_sha256": sha(HERE / "driver-tests-green-v3/result.json"),
              "source_commit": builder.COMMIT, "kernel_config_sha256": sha(builder.ABI / ".config"),
              "original_source_clean": not builder.read_command(["git", "-C", str(builder.KERNEL), "status", "--porcelain"]),
              "board_tested": False, "kernel_module_loaded": False}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
