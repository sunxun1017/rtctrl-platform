#!/usr/bin/env python3
"""Fresh root read-only re-audit of actual codec inputs, module ELF and imports."""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CODEC = HERE / "codec-image-v4-v1"
ACTUAL = CODEC / "build-v2"
OUT = HERE / "build/root-codec-image-v4-audit-v1"
BUILDER_SHA = "ac8e0fabbb5ee9dee12b136e576560c98e2efe9484727db1227338507a5c1fee"
MANIFEST_SHA = "32241d1dfe9f2cbf17bae023065d87ee436173ba319a9f40b81ad5c7b1eb8e3c"
MODULE_SHA = "aa594a46d660c929cdae71f81024659cf9f4beca032baf9a193ad6ded3476171"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    builder = CODEC / "codec_builder.py"
    if sha(builder) != BUILDER_SHA or sha(ACTUAL / "builder-snapshot.py") != BUILDER_SHA:
        raise ValueError("Reviewed builder changed")
    spec = importlib.util.spec_from_file_location("reviewed_codec", builder)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    if helper.ROOT != ROOT:
        raise ValueError("Incorrect reviewed helper root")
    for path in [builder, ACTUAL / "builder-snapshot.py", ACTUAL / "manifest.json"]:
        helper.ordinary(path)
    if sha(ACTUAL / "manifest.json") != MANIFEST_SHA:
        raise ValueError("Actual manifest changed")
    record = json.loads((ACTUAL / "manifest.json").read_bytes())
    if record["status"] != "ACTUAL_COMPLETED_IMAGE_CODEC_ABI_VERIFIED" or record["build_exit_code"] != 0:
        raise ValueError("Actual module build not complete")
    for key in ["board_tested", "loaded", "unload_tested", "deployed", "full_duplex_passed", "accepted_for_board"]:
        if record[key] is not False:
            raise ValueError("Offline codec scope expanded")
    for step in record["steps"]:
        if step["exit"] != 0:
            raise ValueError("Actual command failed")
        for stream in ["stdout", "stderr"]:
            path = helper.ordinary(ACTUAL / (step["label"] + "." + stream))
            if sha(path) != step[stream + "_sha256"]:
                raise ValueError("Actual diagnostic stream changed")
            if stream == "stderr" and path.stat().st_size:
                raise ValueError("Unexpected actual stderr")
    locks = json.loads(helper.ordinary(ACTUAL / "locks.json").read_bytes())
    for relative, digest in locks.items():
        if sha(helper.ordinary(ROOT / relative)) != digest:
            raise ValueError("Locked input changed")
    before_abi = json.loads(helper.ordinary(ACTUAL / "before-ABI.json").read_bytes())
    before_source = json.loads(helper.ordinary(ACTUAL / "before-source-headers-scripts.json").read_bytes())
    if json.loads(helper.ordinary(ACTUAL / "after-ABI.json").read_bytes()) != before_abi:
        raise ValueError("ABI before/after differs")
    if json.loads(helper.ordinary(ACTUAL / "after-source-headers-scripts.json").read_bytes()) != before_source:
        raise ValueError("Source before/after differs")
    current_abi = helper.inventory(helper.ABI, helper.COPY_DIRS + helper.COPY_FILES)
    current_source = helper.inventory(helper.SOURCE, helper.SOURCE_SELECTIONS, True)
    if current_abi != before_abi or current_source != before_source:
        raise ValueError("Current inputs differ from actual compiled inputs")
    image_inventory = json.loads(helper.ordinary(helper.IMAGE / "integrated-source-inventory.json").read_bytes())
    helper.source_matches_image_inventory(current_source, image_inventory, helper.SOURCE_SELECTIONS)
    root_abi = json.loads(helper.ordinary(helper.ROOT_ABI / "inventory.json").read_bytes())
    helper.generated_matches_root_snapshot(current_abi, root_abi)
    helper.generated_matches_root_snapshot(helper.inventory(helper.ROOT_ABI / "snapshot", helper.COPY_DIRS + helper.COPY_FILES), root_abi)
    for name, expected in [("rk817_codec.c", record["source_sha256"]), ("rk817_codec.h", record["header_sha256"])]:
        if sha(helper.ordinary(ACTUAL / "modules" / name)) != expected:
            raise ValueError("Actual compiled codec source/header changed")
    command = helper.ordinary(ACTUAL / "modules/.rk817_codec.o.cmd")
    if sha(command) != record["actual_primary_Kbuild_command_sha256"]:
        raise ValueError("Actual Kbuild command changed")
    text = command.read_text().splitlines()[0]
    if "-DMODULE" not in text or str(ACTUAL / "modules/rk817_codec.c") not in text:
        raise ValueError("Frozen source not selected by actual Kbuild")
    module = helper.ordinary(ACTUAL / "modules/snd-soc-rk817.ko")
    if sha(module) != MODULE_SHA or module.stat().st_size != 519072:
        raise ValueError("Actual module changed")
    if helper.symbols(ACTUAL / "modules/Module.symvers"):
        raise ValueError("Unexpected module exports")
    if OUT.exists() or OUT.is_symlink():
        raise ValueError("Fresh root audit output required")
    OUT.mkdir()
    steps = []
    audited = helper.audit_module(module, OUT, steps, helper.symbols(helper.ABI / "Module.symvers"), helper.symbols(helper.ABI / "vmlinux.symvers"))
    if audited != record["module"] or audited != record["actual_module"]:
        raise ValueError("Fresh root ELF/import audit differs from actual author record")
    if helper.inventory(helper.ABI, helper.COPY_DIRS + helper.COPY_FILES) != current_abi or helper.inventory(helper.SOURCE, helper.SOURCE_SELECTIONS, True) != current_source:
        raise ValueError("Read-only audit changed protected input")
    if sha(builder) != BUILDER_SHA or sha(ACTUAL / "manifest.json") != MANIFEST_SHA or sha(module) != MODULE_SHA:
        raise ValueError("Audit inputs changed")
    result = {"root_fresh_actual_codec_audit_passed": True,
              "manifest_sha256": MANIFEST_SHA, "module_sha256": MODULE_SHA,
              "actual_author_commands_rechecked": len(record["steps"]),
              "root_fresh_read_only_ELF_commands": steps,
              "generated_ABI_ordinary_files_rechecked": len(record["abi_inventory"]),
              "source_ordinary_files_rechecked": current_source["regular_file_count"],
              "source_SDK_file_links": 4, "source_SDK_directory_links": 13,
              "DTC_directory_target_contents_traversed": False,
              "actual_Module_and_vmlinux_symvers_imports": len(audited["imports"]),
              "MODVERSIONS_enabled": False, "CRC_runtime_enforcement_claimed": False,
              "root_current_ABI_snapshot_rechecked": True,
              "generated_inventory_signed_at_Image_compile_time": False,
              "audit_helper_sha256": BUILDER_SHA, "root_audit_tool_sha256": sha(Path(__file__)),
              "module_recompiled_during_root_audit": False,
              "board_tested": False, "START_authorized": False}
    (OUT / "receipt.json").write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print(json.dumps({"passed": True, "imports": len(audited["imports"]), "receipt_sha256": sha(OUT / "receipt.json")}))


if __name__ == "__main__":
    main()
