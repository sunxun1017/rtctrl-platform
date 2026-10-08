#!/usr/bin/env python3
"""Recheck tested inputs; keep build/test evidence separate from board results."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def check(path, digest):
    if sha(path) != digest:
        raise ValueError("Changed tested input: " + str(path.relative_to(ROOT)))


def main():
    spec = importlib.util.spec_from_file_location("codec_builder", HERE / "build-codec.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    output = HERE / "build/host-checks-v1"
    builder.new_output(output)
    output.mkdir(parents=True)
    builder.check_locks()
    module_record = read(HERE / "driver-modules-v4/module-manifest.json")
    if builder.inventory(builder.ABI) != module_record["abi_metadata_sha256"]:
        raise ValueError("Original ABI inventory changed")
    for relative, digest in module_record["locked_input_sha256"].items():
        check(ROOT / relative, digest)
    check(HERE / "build-codec.py", module_record["builder_sha256"])
    module = HERE / "driver-modules-v4/modules/snd-soc-rk817.ko"
    audit = builder.audit_module(module, output, builder.symbols(builder.ABI / "Module.symvers"))
    if audit != module_record["modules"][module.name]:
        raise ValueError("Module audit differs from tested build")
    tests = {}
    for name in ["driver-tests-green-v5", "driver-tests-green-v6"]:
        path = HERE / name / "result.json"
        record = read(path)
        if len(record["cases"]) != 73 or not all(case["passed"] for case in record["cases"]):
            raise ValueError("Real function test evidence failed")
        for relative, digest in record["source_sha256"].items():
            check(ROOT / relative, digest)
        for relative, digest in record["test_input_sha256"].items():
            check(HERE / relative, digest)
        tests[name] = {"sha256": sha(path), "passed": 73, "qemu": record["qemu"]}
    for name, count, implementation in [
        ("driver-tests-prepare-v3", 9, "driver-prepare.py"),
        ("driver-tests-module-v3", 15, "build-codec.py"),
    ]:
        path = HERE / name / "result.json"
        record = read(path)
        if record["passed"] != count or record["total"] != count:
            raise ValueError("Generator/module evidence failed")
        key = "generator_sha256" if "prepare" in name else "builder_sha256"
        check(HERE / implementation, record[key])
        tests[name] = {"sha256": sha(path), "passed": count}
    dtb = read(HERE / "build/dtb-v3/manifest.json")
    board = ROOT / "platforms/rk3568/boards/aiot-3568pq"
    for path, key in [
        (HERE / "build/dtb-v3/audio.dtb", "dtb_sha256"),
        (board / "bsp/rk3568-aiot-3568pq-audio.dts", "source_sha256"),
        (HERE / "build-dtb.py", "builder_sha256"),
        (board / "verify-audio.py", "audit_script_sha256"),
        (board / "test-audio-audit.py", "fault_test_script_sha256"),
    ]:
        check(path, dtb[key])
    if dtb["checks_passed"] != 177 or dtb["faults_rejected"] != 23 or dtb["new_dtc_warnings"]:
        raise ValueError("DTB build evidence failed")
    helper = read(HERE / "build/inspect-v4/manifest.json")
    for path, key in [
        (HERE / "alsa-inspect.c", "source_sha256"),
        (HERE / "test-alsa-inspect.py", "test_script_sha256"),
        (HERE / "build-inspect.py", "builder_sha256"),
        (HERE / "build/inspect-v4/alsa-inspect", "binary_sha256"),
    ]:
        check(path, helper[key])
    for key in ["host", "aarch64_qemu"]:
        test = helper["tests"][key]
        check(HERE / ("build/inspect-tests-" + test["label"]) / "result.json", test["result_sha256"])
        if test["cases"] != 114 or test["failures"] != 0 or not test["deadline_case"]["passed"]:
            raise ValueError("Helper evidence failed")
    stage = read(HERE / "build/stage-tests-v1.json")
    check(HERE / "linux-stage.sh", stage["source_sha256"])
    check(HERE / "test-linux-stage.py", stage["test_sha256"])
    if stage["failures"] or len(stage["cases"]) != 18 or stage["old_cwd_guard_negative_control"]["passed"]:
        raise ValueError("Stage fixture evidence failed")
    current_checks = {}
    for script in ["check-runtime-commands.py", "test-return-guard.py"]:
        completed = subprocess.run(["python3", str(HERE / script)], check=True, capture_output=True, text=True)
        current_checks[script] = json.loads(completed.stdout)
        (output / (script + ".stdout.json")).write_text(completed.stdout)
    if len(current_checks["test-return-guard.py"]["passed"]) != 31:
        raise ValueError("Guard fixture count changed")
    runtime = read(HERE / "runtime-manifest.json")
    paths = {"audio.dtb": HERE / "build/dtb-v3/audio.dtb", "snd-soc-rk817.ko": module,
             "alsa-inspect": HERE / "build/inspect-v4/alsa-inspect"}
    for name, digest in runtime["files"].items():
        check(paths.get(name, HERE / name), digest)
    check(HERE / "linux-stage.sh", runtime["stage_script_sha256"])
    report = {"status": "AUDIO_CURRENT_HOST_INPUTS_VERIFIED", "original_kernel_clean": True,
              "original_abi_inventory_unchanged": True, "module_imports": len(audit["imports"]),
              "test_evidence": tests, "helper_tests": {"host": 114, "aarch64_qemu": 114},
              "dtb_checks": 177, "dtb_faults": 23, "stage_fixtures": 18,
              "runtime_checks": current_checks,
              "stage_result_sha256": sha(HERE / "build/stage-tests-v1.json"),
              "input_sha256": {str(path.relative_to(HERE)): sha(path) for path in [
                  HERE / "runtime-manifest.json", HERE / "driver-modules-v4/module-manifest.json",
                  HERE / "build/dtb-v3/manifest.json", HERE / "build/inspect-v4/manifest.json"]},
              "verifier_sha256": sha(Path(__file__)), "board_hardware_retested": False}
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print("AUDIO_CURRENT_HOST_INPUTS_VERIFIED: 32 module imports; 31 guard fixtures; tested hashes unchanged")


if __name__ == "__main__":
    main()
