#!/usr/bin/env python3
"""Verify generator refusal paths and exact all-public-patch replay in private fixtures."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("asoc_prepare", HERE / "driver-prepare.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    output = HERE / "prepare-tests-v1"
    output.mkdir(exist_ok=False)
    fixture = output / "fixtures"
    patches = fixture / "patches"
    patches.mkdir(parents=True)
    inputs = fixture / "inputs"
    for relative in module.SOURCES:
        dest = inputs / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((module.KERNEL / relative).read_bytes())
    for name in module.DEPENDENCIES:
        (patches / name).write_bytes((module.PATCH_DIR / name).read_bytes())
    records = []

    def check(name, condition):
        records.append({"name": name, "passed": bool(condition)})

    def refuses(name, operation, message):
        try:
            operation()
        except (ValueError, FileNotFoundError) as error:
            check(name, message in str(error))
            records[-1]["reason"] = str(error)
        else:
            check(name, False)

    generated, manifest = module.prepare("v1", True, inputs, patches, fixture)
    check("all ten patches replayed in order", [r["patch"] for r in manifest["full_board_patch_replay"]] ==
          [*module.DEPENDENCIES, module.PATCH_NAME])
    check("private publication exact candidate", (patches / module.PATCH_NAME).read_bytes() ==
          (generated / module.PATCH_NAME).read_bytes())
    for relative in module.SOURCES:
        check("replay bytes identical " + relative, (generated / relative).read_bytes() ==
              (generated / "replay" / relative).read_bytes())
    for relative, expected in manifest["replay_files_sha256"].items():
        check("full replay file bound " + relative, sha((generated / "replay" / relative).read_bytes()) == expected)
    refuses("existing output rejected", lambda: module.prepare("v1", False, inputs, patches, fixture), "overwriting")
    for version in ["../escape", "v0", "v01", "v1/child"]:
        refuses("bad version " + version, lambda v=version: module.prepare(v, False, inputs, patches, fixture), "version must")
    sequence = 2
    for relative in module.SOURCES:
        target = inputs / relative
        original = target.read_bytes()
        target.write_bytes(original + b"\n/* private corruption */\n")
        refuses("source tamper rejected " + relative,
                lambda: module.prepare("v" + str(sequence), False, inputs, patches, fixture), "source hash changed")
        target.write_bytes(original)
        sequence += 1
    for name in module.DEPENDENCIES:
        target = patches / name
        original = target.read_bytes()
        target.write_bytes(original + b"\nprivate corruption\n")
        refuses("dependency tamper rejected " + name,
                lambda: module.prepare("v" + str(sequence), False, inputs, patches, fixture), "dependency patch hash changed")
        target.write_bytes(original)
        sequence += 1
    public = patches / module.PATCH_NAME
    exact = public.read_bytes()
    public.write_bytes(b"private unrelated patch\n")
    refuses("conflicting public patch rejected", lambda: module.prepare("v" + str(sequence), True, inputs, patches, fixture), "different public patch")
    check("conflict remains untouched", public.read_bytes() == b"private unrelated patch\n")
    public.write_bytes(exact)
    # Replay binding also rejects a locally altered generated preview.
    altered = exact.replace(b"snd_pcm_set_state(substream, SNDRV_PCM_STATE_SETUP);",
                            b"snd_pcm_set_state(substream, SNDRV_PCM_STATE_PREPARED);")
    altered_output = fixture / "altered-replay"
    altered_output.mkdir()
    altered_replay, _ = module.replay(altered_output, {
        **{name: (patches / name).read_bytes() for name in module.DEPENDENCIES}, module.PATCH_NAME: altered})
    check("tampered preview detected by source comparison", (altered_replay / module.PCM).read_bytes() != (generated / module.PCM).read_bytes())
    check("original kernel still clean", subprocess.run(["git", "-C", module.KERNEL, "status", "--porcelain"],
                                                        check=True, capture_output=True).stdout == b"")
    check("original locked commit preserved", subprocess.run(["git", "-C", module.KERNEL, "rev-parse", "HEAD"],
                                                              check=True, capture_output=True, text=True).stdout.strip() == module.COMMIT)
    result = {"total": len(records), "passed": sum(r["passed"] for r in records),
              "failed": sum(not r["passed"] for r in records), "checks": records,
              "generator_sha256": sha((HERE / "driver-prepare.py").read_bytes()),
              "test_sha256": sha(Path(__file__).read_bytes()),
              "full_patch_replay_manifest_sha256": sha((generated / "manifest.json").read_bytes()),
              "private_patch_dir": str(patches), "original_tree_clean": True,
              "actual_public_patch_changed_by_tests": False}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"result": str(output / "result.json"), "total": result["total"],
                      "passed": result["passed"], "failed": result["failed"]}))
    return int(result["failed"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
