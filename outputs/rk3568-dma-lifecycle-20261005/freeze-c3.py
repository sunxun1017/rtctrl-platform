#!/usr/bin/env python3
"""Freeze exact C3/CPU inputs, full series replay, tests and actual Kbuild evidence."""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from source_utils import sha, function, declaration
from freeze_c1_import import strict_replay

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / "third_party/linux-rk3588"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
CPU_ROOT = ROOT / "outputs/rk3568-i2s-lifecycle-20261005"
CPU_PATH = "sound/soc/rockchip/rockchip_i2s_tdm.c"
CPU_SHA = "cbd19c1a8b128d442f6321ebb9ce1d51524633536282862b6c06fa76b4f77b59"
CPU_PATCH_SHA = "ec857605a70abccce88ac71c1e5070b866fb245717ad90ae0db2af26fc9aa495"
GREEN = [
    ("pl330-c3-tests-green-v2", 67),
    ("pl330-c3-hw-tests-green-v1", 17),
    ("pl330-debugfs-tests-green-v4", 2),
    ("dma-admission-tests-green-v4", 9),
    ("trigger-cpu-tests-green-v5", 47),
    ("dma-pcm-tests-green-v9", 17),
    ("core-lifecycle-tests-green-v2", 6),
]
RED = ["core-lifecycle-tests-red-v2", "dma-pcm-tests-red-v1", "trigger-tests-red-v3"]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def gate():
    for args, wanted in [(["rev-parse", "HEAD"], COMMIT), (["status", "--porcelain"], "")]:
        result = subprocess.run(["git", "-C", str(KERNEL), *args], check=True,
                                capture_output=True, text=True)
        require(result.stdout.strip() == wanted, "original locked kernel gate rejected")


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def check_hash(path, wanted):
    require(path.is_file() and sha(path.read_bytes()) == wanted, "hash mismatch: " + str(path))


def patch_paths(data):
    paths = re.findall(r"^diff --git a/(\S+) b/\1$", data.decode(), re.M)
    require(paths and len(paths) == len(set(paths)), "invalid or duplicate patch targets")
    return paths


def replay_exact(before, data):
    # Only 0001 has a Git index metadata line. It carries no hunk semantics.
    text = re.sub(r"^index [0-9a-f]+\.\.[0-9a-f]+ 100644\n", "", data.decode(), flags=re.M)
    names = patch_paths(data)
    return strict_replay({name: before[name] for name in names}, text)


def verify_result(folder, source_map, count=None):
    result = json.loads((folder / "result.json").read_text())
    if count is not None:
        require(result.get("passed") is True, "green not passing")
    for table in ["files_sha256", "harness_sha256"]:
        for name, wanted in result.get(table, {}).items():
            check_hash(folder / name, wanted)
    known = {
        "extracted_sha256": "extracted.c", "unit_sha256": "real-functions.c",
        "constants_sha256": "constants.h", "probe_sha256": "probe-excerpt.c",
        "abi_sha256": "dmaengine-types.h", "native_extracted_sha256": "native-extracted.c",
        "dma_buffer_abi_sha256": "dma-buffer-types.h", "dma_abi_sha256": "dmaengine-types.h",
        "trigger_constants_sha256": "pcm-trigger-constants.h",
        "allocator_constants_sha256": "memalloc-constants.h",
        "iteration_macros_sha256": "asoc-iteration-macros.h",
        "native_sha256": "native-input.c", "memalloc_sha256": "memalloc-input.h",
        "allocator_source_sha256": "allocator-input.c", "soc_header_sha256": "soc-header-input.h",
        "cpu_source_sha256": "cpu-source-input.c", "cpu_header_sha256": "cpu-register-input.h",
    }
    for field, filename in known.items():
        if field in result:
            if field == "constants_sha256" and (folder / "pl330-constants.h").exists():
                filename = "pl330-constants.h"
            check_hash(folder / filename, result[field])
    if "source_sha256" in result:
        hashes = result["source_sha256"]
        if isinstance(hashes, str):
            check_hash(folder / "source-input.c", hashes)
            if count is not None:
                wanted = source_map["drivers/dma/dmaengine.c"] if folder.name.startswith("dma-admission") else source_map["drivers/dma/pl330.c"]
                require(hashes == wanted, "scalar test source binds another candidate")
        elif count is not None:
            for name, wanted in hashes.items():
                actual = CPU_SHA if name == "cpu-v10/rockchip_i2s_tdm.c" else source_map.get(name)
                if actual is None:
                    actual = sha((KERNEL / name).read_bytes())
                require(actual == wanted, "test source map binds another input: " + name)
    if count is not None and "cpu_source_sha256" in result:
        require(result["cpu_source_sha256"] == CPU_SHA and not result["cpu_final_rebind_pending"],
                "CPU final binding rejected")
    # Validate every published function digest against full immutable inputs.
    pool = []
    for path in folder.iterdir():
        if path.is_file() and (path.name.endswith(".input") or path.name.endswith("-input.c")
                              or path.name.endswith("-input.h")):
            pool.append(path.read_text())
    # Historical scalar suites do not copy every helper header, so use the locked input.
    if "dmaengine_source_sha256" in result:
        data = (KERNEL / "drivers/dma/dmaengine.h").read_bytes()
        require(sha(data) == result["dmaengine_source_sha256"], "private DMA ABI drift")
        pool.append(data.decode())
    if "dmaengine_public_source_sha256" in result:
        require(result["dmaengine_public_source_sha256"] == source_map["include/linux/dmaengine.h"],
                "public DMA ABI drift")
        pool.append((HERE / "driver-source-c3-v5/include/linux/dmaengine.h").read_text())
    aliases = {"direction": "snd_pcm_substream_to_dma_direction", "setbuf": "snd_pcm_set_runtime_buffer",
               "component:get_drvdata": "snd_soc_component_get_drvdata",
               "generic:trigger": "dmaengine_pcm_trigger", "generic:quiesce": "dmaengine_pcm_quiesce",
               "component:quiesce": "dmaengine_pcm_quiesce", "cpu:component_trigger": "i2s_checked_component_trigger",
               "pcm:show": "dma_quarantine_bytes_show"}
    for table in ["excerpts_sha256", "dmaengine_excerpts_sha256", "public_helpers_sha256", "cpu_excerpts_sha256"]:
        for label, wanted in result.get(table, {}).items():
            name = aliases.get(label, label.rsplit(":", 1)[-1])
            matched = False
            for text in pool:
                try:
                    matched |= sha(function(text, name).encode()) == wanted
                except ValueError:
                    pass
            require(matched, "production excerpt digest rejected: " + folder.name + ":" + label)
    for name, wanted in result.get("declarations_sha256", {}).items():
        matched = False
        for text in pool:
            for kind in ["struct", "enum"]:
                try:
                    matched |= sha(declaration(text, kind, name).encode()) == wanted
                except ValueError:
                    pass
        require(matched, "real declaration rejected: " + name)
    require(set(result["runs"]) == {"host", "host-sanitized", "aarch64"}, "environment coverage missing")
    for environment, run in result["runs"].items():
        for stage, stem in [("compile", environment + "-compile"), ("execution", environment)]:
            if stage not in run:
                continue
            for suffix in ["stdout", "stderr"]:
                check_hash(folder / (stem + "." + suffix), run[stage][suffix + "_sha256"])
            if count is not None:
                require(run[stage]["returncode"] == 0, "nonzero final compile/execution")
        if "binary_sha256" in run:
            # Use the copied executable, not the absolute path in the original argv.
            binary = Path(run["execution"]["argv"][-1]).name
            check_hash(folder / binary, run["binary_sha256"])
        if count is not None:
            expected = {"total": count, "passed": count, "failed": 0}
            require(run["tests"] == expected and json.loads((folder / (environment + ".stdout")).read_text()) == expected,
                    "count/result stdout disagree")
    return result


def verify_production(folder, candidate_map, final):
    result = json.loads((folder / "result.json").read_text())
    require(result["original_tree_clean"] and result["kernel_commit"] == COMMIT, "production input rejected")
    if final:
        require(result["objects_build_passed"] and result["source_sha256"] == candidate_map, "production source mismatch")
        require(result["cpu"]["source_sha256"] == CPU_SHA and result["cpu"]["patch_sha256"] == CPU_PATCH_SHA,
                "production CPU mismatch")
        require(len(result["objects_sha256"]) == 12, "production object coverage missing")
    check_hash(folder / "build/.config", result["config_sha256"])
    for name, wanted in result["objects_sha256"].items():
        check_hash(folder / "build" / name, wanted)
    for name, wanted in result.get("kbuild_commands_sha256", {}).items():
        check_hash(folder / "build" / name, wanted)
    for stem, command in zip(["defconfig", "merge", "olddefconfig", "objects"], result["commands"]):
        if final:
            require(command["returncode"] == 0, "production command failed")
        for suffix in ["stdout", "stderr"]:
            check_hash(folder / (stem + "." + suffix), command[suffix + "_sha256"])
    for name, wanted in result["replay_files_sha256"].items():
        check_hash(folder / "replay" / name, wanted)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="v1")
    args = parser.parse_args()
    require(re.fullmatch(r"v[1-9][0-9]*", args.revision), "fresh revision required")
    review = HERE / ("C3-review-" + args.revision)
    require(not review.exists(), "review output already exists")
    gate()
    candidate = HERE / "driver-source-c3-v5"
    manifest = json.loads((candidate / "manifest.json").read_text())
    candidate_map = manifest["source_sha256"]
    for name, wanted in candidate_map.items():
        check_hash(candidate / name, wanted)
    for name, wanted in manifest["generator_sha256"].items():
        check_hash(HERE / name, wanted)
    patch = candidate / "C3-lifecycle-review.patch"
    check_hash(patch, manifest["patch_sha256"])
    check_hash(HERE / "C1-review-v5/receipt.json", manifest["c1_receipt_sha256"])
    check_hash(HERE / "driver-source-c2-v3/manifest.json", manifest["c2_manifest_sha256"])
    check_hash(CPU_ROOT / "driver-source-v10" / CPU_PATH, CPU_SHA)
    check_hash(CPU_ROOT / "driver-source-v10/i2s-lifecycle-pm.patch", CPU_PATCH_SHA)
    cpu_seal = json.loads((CPU_ROOT / "sealed-v3/manifest.json").read_text())
    require(cpu_seal["source_sha256"] == CPU_SHA and cpu_seal["patch_sha256"] == CPU_PATCH_SHA,
            "CPU seal mismatch")
    production = verify_production(HERE / "production-v6", candidate_map, True)
    require(production["candidate_manifest_sha256"] == sha((candidate / "manifest.json").read_bytes()),
            "production candidate manifest drift")
    patches = []
    all_names = set(candidate_map)
    for item in production["patch_series"]:
        name = item["patch"]
        path = HERE / "production-v6/patch-inputs" / name
        check_hash(path, item["sha256"])
        if name.startswith("0011-"):
            require(path.read_bytes() == patch.read_bytes(), "incremental patch differs")
        elif name.startswith("0012-"):
            require(item["sha256"] == CPU_PATCH_SHA, "CPU series mismatch")
        else:
            check_hash(ROOT / "platforms/rk3568/boards/aiot-3568pq/patches" / name, item["sha256"])
        data = path.read_bytes()
        all_names.update(patch_paths(data))
        patches.append((name, data))
    before = {name: (KERNEL / name).read_bytes() for name in all_names}
    replay = dict(before)
    before_c3 = None
    for index, (name, data) in enumerate(patches):
        if index == 10:
            before_c3 = dict(replay)
            for target, wanted in manifest["before_sha256"].items():
                require(sha(replay[target]) == wanted, "incremental base differs: " + target)
        replay.update(replay_exact(replay, data))
    require(len(patches) == 12, "full public series missing")
    for name, wanted in production["replay_files_sha256"].items():
        require(sha(replay[name]) == wanted, "strict series differs from production replay: " + name)
    require(all(sha(replay[name]) == wanted for name, wanted in candidate_map.items()), "candidate replay mismatch")
    require(sha(replay[CPU_PATH]) == CPU_SHA, "CPU replay mismatch")
    tamper = dict(before_c3)
    key = "drivers/dma/pl330.c"
    tamper[key] = tamper[key].replace(b"#include <linux/dma-mapping.h>", b"#include <linux/bogus.h>", 1)
    require(tamper[key] != before_c3[key], "tamper anchor missing")
    rejected = False
    try:
        replay_exact(tamper, patch.read_bytes())
    except ValueError:
        rejected = True
    require(rejected, "exact context accepted tampered input")
    require(sha(patch.read_bytes() + b"tamper") != manifest["patch_sha256"], "hash tamper not rejected")
    # The regression harness generator must reproduce its final manually reviewed main.
    generated = (HERE / "test-pl330-start-main.c").read_text().replace(
        "memset(registers,0,sizeof(registers));dmac.base=registers;",
        "memset(registers,0,sizeof(registers));atomic_store(&dmac.owned_descs.value,2);dmac.base=registers;")
    generated = generated.replace("int main(void){", "int main(void){\n    (void)pl330_reader_deadline;")
    require(generated == (HERE / "test-pl330-c3-main.c").read_text(), "harness generation differs")
    verified = []
    for name, count in GREEN:
        result = verify_result(HERE / name, candidate_map, count)
        verified.append({"directory": name, "tests_per_environment": count,
                         "result_sha256": sha((HERE / name / "result.json").read_bytes()),
                         "source_sha256": result["source_sha256"]})
    for name in RED:
        verify_result(HERE / name, candidate_map)
    for name in ["production-v1", "production-v3", "production-v4"]:
        failed = verify_production(HERE / name, candidate_map, False)
        require(not failed["objects_build_passed"], "failed production evidence lost")
    review.mkdir()
    shutil.copytree(candidate, review / "source")
    shutil.copytree(HERE / "production-v6/patch-inputs", review / "patch-inputs")
    for name, data in before.items():
        target = review / "original-inputs" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for name, data in replay.items():
        target = review / "full-replay" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for name, _ in GREEN:
        shutil.copytree(HERE / name, review / "tests" / name)
    for name in RED:
        shutil.copytree(HERE / name, review / "red-evidence" / name)
    independent = Path("/tmp/rtctrl-c3-independent-review-toja28_c/independent-model")
    require(independent.exists(), "independent probe IRQ evidence missing")
    for pattern in ["*probe-irq.stdout", "*probe-irq.stderr", "audit-main.c", "real-functions.c", "*.h"]:
        for path in independent.glob(pattern):
            copy_file(path, review / "red-evidence/independent-probe-irq" / path.name)
    copy_file(CPU_ROOT / "driver-source-v10" / CPU_PATH, review / "cpu/source" / CPU_PATH)
    copy_file(CPU_ROOT / "driver-source-v10/manifest.json", review / "cpu/candidate-manifest.json")
    copy_file(CPU_ROOT / "sealed-v3/manifest.json", review / "cpu/sealed-v3-manifest.json")
    copy_file(CPU_ROOT / "pm-revision-v1/probe-review-tests-green-v3/result.json",
              review / "cpu/author-owner-conflict-result.json")
    for revision in ["v1", "v3", "v4"]:
        source = HERE / ("driver-source-c3-" + revision)
        shutil.copytree(source, review / "red-evidence" / source.name)
    for directory in ["production-v6", "production-v1", "production-v3", "production-v4"]:
        src = HERE / directory
        dst = review / ("production" if directory == "production-v6" else "red-evidence/" + directory)
        result = json.loads((src / "result.json").read_text())
        for path in sorted(src.glob("*")):
            if path.is_file():
                copy_file(path, dst / path.name)
        for path in [".config", "include/generated/autoconf.h", "include/config/auto.conf", "include/config/kernel.release"]:
            if (src / "build" / path).exists():
                copy_file(src / "build" / path, dst / "build" / path)
        for table in ["objects_sha256", "kbuild_commands_sha256"]:
            for path in result.get(table, {}):
                copy_file(src / "build" / path, dst / "build" / path)
    for name in ["platforms/rk3568/linux-5.10.cfg", "platforms/rk3568/boards/aiot-3568pq/firstboot.cfg",
                 "platforms/rk3568/boards/aiot-3568pq/firstboot-candidate.json"]:
        copy_file(ROOT / name, review / "production/profile" / name)
    generators = [*manifest["generator_sha256"], "build-production.py", "freeze-c3.py", "freeze_c1_import.py",
                  "freeze-c1.py", "prepare-c3-regression-harness.py", "prepare-integration-harness.py"]
    for name in generators:
        copy_file(HERE / name, review / "generators" / name)
    for name in ["C3-REVIEW.md", "READONLY-SCOPE.md", "C3-PLAN.md", "C2-PLAN.md", ".gitignore"]:
        copy_file(HERE / name, review / name)
    copy_file(HERE / "C1-review-v5/receipt.json", review / "base-inputs/C1-review-v5-receipt.json")
    copy_file(HERE / "driver-source-c2-v3/manifest.json", review / "base-inputs/C2-v3-manifest.json")
    gate()
    files = {str(path.relative_to(review)): sha(path.read_bytes())
             for path in sorted(review.rglob("*")) if path.is_file()}
    receipt = {
        "c3_frozen": True, "candidate_rejected": True,
        "rejection": "Independent pending IRQ enters pl330_update before pl330_add initializes controller lock/req_done/thread state; host/QEMU SIGSEGV and ASan SEGV",
        "rejection_evidence": "red-evidence/independent-probe-irq",
        "published": False, "deployable": False, "board_tested": False,
        "image_built": False, "production_objects_compiled": True, "independent_group_review_pending": True,
        "kernel_commit": COMMIT, "original_kernel_clean_before_and_after": True,
        "candidate": str(candidate), "candidate_manifest_sha256": sha((candidate / "manifest.json").read_bytes()),
        "source_sha256": candidate_map, "incremental_patch": "patch-inputs/0011-pl330-pcm-lifecycle.patch",
        "patch_sha256": manifest["patch_sha256"], "incremental_base": "locked original + exact public 0001–0010",
        "patch_series": [{"path": "patch-inputs/" + name, "sha256": sha(data)} for name, data in patches],
        "strict_full_series_replay_matches": True, "exact_context_tamper_rejected": True,
        "patch_hash_tamper_rejected": True, "public_0011_created": False,
        "cpu": {"accepted_version": "v10", "final_rebind_pending": False,
                "source_path": str(CPU_ROOT / "driver-source-v10" / CPU_PATH), "source_sha256": CPU_SHA,
                "patch_path": str(CPU_ROOT / "driver-source-v10/i2s-lifecycle-pm.patch"), "patch_sha256": CPU_PATCH_SHA,
                "seal_sha256": sha((CPU_ROOT / "sealed-v3/manifest.json").read_bytes())},
        "tests_per_environment": sum(count for _, count in GREEN),
        "environments": ["host", "host-sanitized (ASan+UBSan)", "static aarch64 under QEMU"],
        "green_results": verified, "red_results_retained": RED,
        "production_result": "production/result.json", "production_objects": 12,
        "kbuild_config_sha256": production["config_sha256"], "compiler": production["compiler"],
        "c1_receipt_sha256": manifest["c1_receipt_sha256"], "c2_manifest_sha256": manifest["c2_manifest_sha256"],
        "documentation": ["C3-REVIEW.md", "READONLY-SCOPE.md"],
        "remaining": ["new candidate must close probe IRQ publication and reverse-order error cleanup", "independent entire C1/C2/C3 + CPU group review", "root full Image/link and external codec module ABI validation",
                      "single-direction physical MMIO/AXI/STOPPED and lifetime verification before any board START",
                      "root teardown proof: closed FDs, codec/card unregister, CPU+DMA readonly ready and zero global quarantine"],
        "unsupported": ["full duplex", "active driver unbind recovery", "forced module unload", "IOMMU/unknown allocator",
                        "automatic warm reboot after poison/quarantine/failstop", "external watchdog reset guarantee"],
        "files_sha256": files,
    }
    (review / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"receipt": str(review / "receipt.json"), "receipt_sha256": sha((review / "receipt.json").read_bytes()),
                      "files": len(files), "tests_per_environment": receipt["tests_per_environment"], "objects": 12,
                      "published": False, "deployable": False}))


if __name__ == "__main__":
    main()
