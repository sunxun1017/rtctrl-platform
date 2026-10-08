#!/usr/bin/env python3
"""Freeze v9 while verifying every original v8 sealed evidence input."""
import json
import shutil
import subprocess
from pathlib import Path
from source_utils import sha

HERE = Path(__file__).resolve().parent
SOURCE = "sound/soc/rockchip/rockchip_i2s_tdm.c"


def checked_file(path, digest):
    if sha(path.read_bytes()) != digest:
        raise ValueError("evidence changed: " + str(path))


def check_functions_receipt(folder, digest):
    result = json.loads((folder / "result.json").read_text())
    if not result["passed"] or result["source_sha256"] != digest:
        raise ValueError("test did not pass against final source")
    for name, value in result["files_sha256"].items():
        checked_file(folder / name, value)
    for mode, run in result["runs"].items():
        if run["compile"]["exit_code"]:
            raise ValueError("compile failed")
        for stream in ["stdout", "stderr"]:
            checked_file(folder / (mode + "-compile." + stream), run["compile"][stream + "_sha256"])
        if "cases" in run:
            binary = folder / ("probe-" + mode)
            cases = run["cases"]
        else:
            prefix = "params-" if folder.name.startswith("params") else "config-" if folder.name.startswith("config") else "lifecycle-"
            binary = folder / (prefix + mode)
            cases = {"": run["execution"] | {"tests": run["tests"]}}
        checked_file(binary, run["binary_sha256"])
        for case, execution in cases.items():
            if execution["exit_code"] or execution["tests"]["passed"] != execution["tests"]["total"]:
                raise ValueError("case did not pass")
            for stream in ["stdout", "stderr"]:
                name = mode + ("-" + case if case else "") + "." + stream
                checked_file(folder / name, execution[stream + "_sha256"])
    return result


def main():
    output = HERE / "sealed-v2"
    output.mkdir(exist_ok=False)
    old_path = HERE / "sealed-v1/manifest.json"
    old = json.loads(old_path.read_text())
    if old["source_sha256"] != "33bd1208d379be53be8232cab11fe908f2d3096b94e66fc59d76a143c86cb3d0":
        raise ValueError("v8 baseline lock rejected")
    for name, digest in old["candidate_files_sha256"].items():
        checked_file(HERE / "driver-source-v8" / name, digest)
    for name, digest in old["evidence_sha256"].items():
        checked_file(HERE / name, digest)
    checked_file(HERE / "kbuild-object-v3/objects/rockchip_i2s_tdm.o", old["object_sha256"])
    candidate = HERE / "driver-source-v9"
    manifest = json.loads((candidate / "manifest.json").read_text())
    digest = manifest["source_sha256"]
    checked_file(candidate / SOURCE, digest)
    old_sealed_inventory = {str(p.relative_to(HERE)): sha(p.read_bytes()) for p in sorted((HERE / "sealed-v1").rglob("*")) if p.is_file()}
    paths = ["probe-review-tests-green-v3"] + ["review-regression-v1/" + name + "-tests-green-v1" for name in ["params", "lifecycle", "irq", "pm", "config"]]
    results = {path: check_functions_receipt(HERE / path, digest) for path in paths}
    red_path = HERE / "probe-review-tests-red-v4/result.json"
    red = json.loads(red_path.read_text())
    if red["source_sha256"] != old["source_sha256"] or any(r["compile"]["exit_code"] for r in red["runs"].values()):
        raise ValueError("v8 red not actual compiled baseline")
    red_error = (HERE / "probe-review-tests-red-v4/host-sanitized-late-fault.stderr").read_text()
    if "heap-use-after-free" not in red_error or "i2s_checked_probe_clock_release" not in red_error or "rockchip_i2s_tdm_probe" not in red_error:
        raise ValueError("full probe devres UAF was not reproduced")
    for name, value in red["files_sha256"].items():
        checked_file(HERE / "probe-review-tests-red-v4" / name, value)
    dt = json.loads((HERE / "actual-dt-review-profile-v1/result.json").read_text())
    if dt["candidate_source_sha256"] != digest or dt["compile_exit_code"] or dt["run_exit_code"] or dt["tests"] != {"passed": 31, "total": 31}:
        raise ValueError("actual DT receipt mismatch")
    for name, value in dt["files_sha256"].items():
        checked_file(HERE / "actual-dt-review-profile-v1" / name, value)
    build = json.loads((HERE / "kbuild-review-object-v1/result.json").read_text())
    checked_file(HERE / "kbuild-review-object-v1/objects/rockchip_i2s_tdm.o", build["object_sha256"])
    checked_file(HERE / "kbuild-review-object-v1/objects/rockchip_i2s_tdm.c", digest)
    if build["source_sha256"] != digest or build["exit_code"] or not build["original_source_clean"] or not build["original_abi_unchanged"] or (HERE / "kbuild-review-object-v1/build.stderr").read_bytes():
        raise ValueError("actual Kbuild proof failed")
    replay = output / "patch-replay"
    target = replay / SOURCE
    target.parent.mkdir(parents=True)
    target.write_bytes((HERE / "source-input-v1" / SOURCE).read_bytes())
    patch = candidate / "i2s-lifecycle-review.patch"
    checked_file(patch, manifest["patch_sha256"])
    applied = subprocess.run(["patch", "--batch", "-p1", "-d", str(replay), "-i", str(patch)], capture_output=True, text=True)
    (output / "patch.stdout").write_text(applied.stdout)
    (output / "patch.stderr").write_text(applied.stderr)
    if applied.returncode or target.read_bytes() != (candidate / SOURCE).read_bytes():
        raise ValueError("private patch replay differs")
    names = [p + "/result.json" for p in paths] + ["probe-review-tests-red-v4/result.json", "probe-review-tests-red-v4/host-sanitized-late-fault.stderr", "review-input-v1/input-manifest.json", "REVIEW-REVISION-PLAN-v1.md", "REVIEW-REVISION-RESULT-v1.md", "review-regression-v1/runner-provenance.json", "actual-dt-review-profile-v1/result.json", "kbuild-review-object-v1/result.json", "kbuild-review-object-v1/build.stdout", "kbuild-review-object-v1/build.stderr", "kbuild-review-object-v1/build-argv.json", "kbuild-review-object-v1/objects/.rockchip_i2s_tdm.o.cmd", "kbuild-review-object-v1/object-readelf.txt", "driver-review-revision.py", "test-probe-review.py", "probe-review-shim.h", "probe-review-adapter.h", "probe-review-main.c", "create-review-runners.py", "build-review-object.py", "verify-review-dt-profile.py", "seal-review-revision.py"]
    receipts = {p: sha((HERE / p).read_bytes()) for p in names}
    for p, value in old["evidence_sha256"].items():
        checked_file(HERE / p, value)
    record = {"candidate_version": "v9", "source_sha256": digest, "patch_sha256": manifest["patch_sha256"], "object_sha256": build["object_sha256"], "kernel_commit": manifest["kernel_commit"], "old_v8_sha256": old["source_sha256"], "old_v8_candidate_and_all_sealed_inputs_unchanged": True, "old_sealed_inventory_sha256": old_sealed_inventory, "candidate_files_sha256": {str(p.relative_to(candidate)): sha(p.read_bytes()) for p in sorted(candidate.rglob("*")) if p.is_file()}, "evidence_sha256": receipts, "test_assertions": {p: {mode: {case: c["tests"] for case, c in run["cases"].items()} if "cases" in run else run["tests"] for mode, run in result["runs"].items()} for p, result in results.items()}, "actual_dt_assertions": dt["tests"], "full_probe_control_flow_tested_with_explicit_api_models": True, "v8_full_probe_devres_uaf_red_reproduced": True, "patch_replay_identical": True, "original_kernel_clean": True, "original_abi_unchanged": True, "published": False, "deployable": False, "audio_start_allowed": False, "board_tested": False, "image_built": False, "full_duplex_supported": False, "independent_v9_review_completed": False, "c3_combined_lifecycle_tested": False, "remaining": ["Independent v9 review", "C3/generic DMA/PL330 allocation/callback combined lifecycle and readonly STOPPED/poison/quarantine/lease proof", "Built-in Image/link/package/hardware acceptance", "Real PM core/PREEMPT_RT lockdep/CCF/MMIO/FIFO/IRQ and external MCU/watchdog/reset acceptance"]}
    shutil.copy2(Path(__file__), output / "seal-review-revision.py")
    (output / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: record[k] for k in ["candidate_version", "source_sha256", "patch_sha256", "object_sha256", "old_v8_candidate_and_all_sealed_inputs_unchanged", "patch_replay_identical", "deployable", "c3_combined_lifecycle_tested"]} | {"manifest": str(output / "manifest.json")}))


if __name__ == "__main__":
    main()
