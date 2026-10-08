#!/usr/bin/env python3
"""Validate final evidence, replay private patch and freeze one new receipt."""
import json
import shutil
import subprocess
from pathlib import Path
from source_utils import sha

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = "sound/soc/rockchip/rockchip_i2s_tdm.c"


def main():
    output = HERE / "sealed-v1"
    output.mkdir(exist_ok=False)
    candidate = HERE / "driver-source-v8"
    manifest = json.loads((candidate / "manifest.json").read_text())
    digest = sha((candidate / SOURCE).read_bytes())
    if digest != manifest["source_sha256"]:
        raise ValueError("candidate changed")
    tests = ["params-tests-green-v6", "lifecycle-tests-green-v4", "irq-tests-green-v4", "pm-tests-green-v6", "config-tests-green-v3"]
    evidence, counts = {}, {}
    for name in tests:
        folder = HERE / name
        result = json.loads((folder / "result.json").read_text())
        if not result["passed"] or result["source_sha256"] != digest:
            raise ValueError("final tests do not match source")
        for filename, expected in result["files_sha256"].items():
            if sha((folder / filename).read_bytes()) != expected:
                raise ValueError("test input changed: " + name + "/" + filename)
        for mode, run in result["runs"].items():
            if run["compile"]["exit_code"] or run["execution"]["exit_code"] or run["tests"]["passed"] != run["tests"]["total"]:
                raise ValueError("incomplete test run")
            for stage in ["compile", "execution"]:
                prefix = mode + ("-compile" if stage == "compile" else "")
                for stream in ["stdout", "stderr"]:
                    if sha((folder / (prefix + "." + stream)).read_bytes()) != run[stage][stream + "_sha256"]:
                        raise ValueError("test output changed")
            binary = folder / (("params-" if name.startswith("params") else "config-" if name.startswith("config") else "lifecycle-") + mode)
            if sha(binary.read_bytes()) != run["binary_sha256"]:
                raise ValueError("test binary changed")
        evidence[name + "/result.json"] = sha((folder / "result.json").read_bytes())
        counts[name] = {mode: run["tests"] for mode, run in result["runs"].items()}
    dt = json.loads((HERE / "actual-dt-profile-v2/result.json").read_text())
    if dt["candidate_source_sha256"] != digest or dt["run_exit_code"] or dt["compile_exit_code"] or dt["tests"] != {"passed": 31, "total": 31}:
        raise ValueError("actual DT profile not passed")
    for filename, expected in dt["files_sha256"].items():
        if sha((HERE / "actual-dt-profile-v2" / filename).read_bytes()) != expected:
            raise ValueError("actual DT test file changed")
    build_path = HERE / "kbuild-object-v3/result.json"
    build = json.loads(build_path.read_text())
    obj = HERE / "kbuild-object-v3/objects/rockchip_i2s_tdm.o"
    if build["source_sha256"] != digest or build["exit_code"] or sha(obj.read_bytes()) != build["object_sha256"] or not build["original_source_clean"] or not build["original_abi_unchanged"]:
        raise ValueError("actual object does not match source")
    if (HERE / "kbuild-object-v3/build.stderr").read_bytes():
        raise ValueError("unexpected object build stderr")
    replay = output / "patch-replay"
    target = replay / SOURCE
    target.parent.mkdir(parents=True)
    target.write_bytes((HERE / "source-input-v1" / SOURCE).read_bytes())
    patch = candidate / "i2s-lifecycle-review.patch"
    if sha(patch.read_bytes()) != manifest["patch_sha256"]:
        raise ValueError("private patch changed")
    applied = subprocess.run(["patch", "--batch", "-p1", "-d", str(replay), "-i", str(patch)], capture_output=True, text=True)
    (output / "patch.stdout").write_text(applied.stdout)
    (output / "patch.stderr").write_text(applied.stderr)
    if applied.returncode or target.read_bytes() != (candidate / SOURCE).read_bytes():
        raise ValueError("private patch replay differs")
    shutil.copy2(Path(__file__), output / "seal-candidate.py")
    inputs = ["PLAN.md", "README.md", "GUARD-EVIDENCE.md", "source-input-v1/manifest.json", "actual-dt-profile-v2/result.json", "kbuild-object-v3/result.json", "kbuild-object-v3/build-argv.json", "kbuild-object-v3/build.stdout", "kbuild-object-v3/build.stderr", "kbuild-object-v3/object-readelf.txt", "kbuild-object-v3/objects/.rockchip_i2s_tdm.o.cmd", "build-object.py", "verify-dt-profile.py", "seal-candidate.py"]
    evidence.update({p: sha((HERE / p).read_bytes()) for p in inputs})
    original = json.loads((HERE / "source-input-v1/manifest.json").read_text())
    for p, item in original["files"].items():
        if sha((HERE / "source-input-v1" / p).read_bytes()) != item["sha256"]:
            raise ValueError("original input snapshot changed")
    candidate_files = {str(p.relative_to(candidate)): sha(p.read_bytes()) for p in sorted(candidate.rglob("*")) if p.is_file()}
    record = {"candidate_version": "v8", "kernel_commit": manifest["kernel_commit"], "source_sha256": digest, "private_patch_sha256": manifest["patch_sha256"], "object_sha256": build["object_sha256"], "object_bytes": build["object_bytes"], "candidate_files_sha256": candidate_files, "evidence_sha256": evidence, "test_assertions": counts, "actual_dt_test_assertions": dt["tests"], "patch_replay_identical": True, "original_kernel_clean": True, "original_abi_unchanged": True, "published": False, "deployable": False, "board_tested": False, "image_built": False, "audio_start_allowed": False, "full_duplex_supported": False, "independent_review_completed": False, "c3_combined_lifecycle_tested": False, "limitations": ["CPU-only offline boundary models, no DMA-provider combined lifecycle", "Actual probe initial configuration block and profile, not full devres/ALSA registration simulation", "External object mode validates complete C/config/headers, not built-in Image/link/import closure", "Readonly state requires exclusive session and DMA STOPPED/poison/quarantine/lease observations before normal reboot", "Uncovered controls/other profiles, inactive nested PM callbacks and full-kernel lockdep need independent review", "Hardware MMIO/FIFO/IRQ/clock/external MCU/watchdog/reset acceptance remains pending"]}
    (output / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: record[k] for k in ["candidate_version", "source_sha256", "private_patch_sha256", "object_sha256", "patch_replay_identical", "deployable", "audio_start_allowed", "c3_combined_lifecycle_tested"]} | {"manifest": str(output / "manifest.json")}))


if __name__ == "__main__":
    main()
