#!/usr/bin/env python3
"""Exercise fresh-build and path rejection without applying or building a kernel."""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "build/image-builder-v4-preflight-v1"
BUILDER = HERE / "build-audio-image-v4.py"
spec = importlib.util.spec_from_file_location("audio_v4_builder", BUILDER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
OUT.mkdir(exist_ok=False)
results = {}


def accepted(name, operation):
    operation()
    results[name] = "accepted"


def rejected(name, operation):
    try:
        operation()
    except ValueError as failure:
        results[name] = str(failure)
    else:
        raise RuntimeError("Invalid fixture was accepted: " + name)


accepted("actual_pristine_build_only_initial_config", lambda: module.fresh_build(module.BUILD))
accepted("actual_source_ordinary_ancestry", lambda: module.ordinary_directory(module.SOURCE))
accepted("actual_output_parent_ordinary_ancestry", lambda: module.ordinary_directory(module.OUT.parent))

fresh = OUT / "fresh"
fresh.mkdir()
(fresh / ".config").write_bytes(b"test configuration\n")
accepted("ordinary_fresh_fixture", lambda: module.fresh_build(fresh))
(fresh / "old-object.o").write_bytes(b"stale object\n")
rejected("stale_object_without_Image", lambda: module.fresh_build(fresh))

linked_config = OUT / "linked-config"
linked_config.mkdir()
(linked_config / ".config").symlink_to(fresh / ".config")
rejected("symlink_config", lambda: module.fresh_build(linked_config))

linked_directory = OUT / "linked-directory"
linked_directory.symlink_to(fresh, target_is_directory=True)
rejected("symlink_directory", lambda: module.ordinary_directory(linked_directory))
rejected("symlink_ancestor", lambda: module.ordinary_directory(linked_directory / ".config"))
rejected("file_below_symlink_ancestor", lambda: module.ordinary((linked_directory / ".config").relative_to(module.ROOT).as_posix()))
rejected("escaped_directory", lambda: module.ordinary_directory(module.ROOT.parent))

result = {"builder_sha256": hashlib.sha256(BUILDER.read_bytes()).hexdigest(),
          "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "checks": results, "check_count": len(results), "all_passed": True,
          "kernel_patch_or_build_executed": False, "hardware_or_network_operated": False,
          "scope": "Actual pristine directory and finite rejection fixtures only; no gate/model/Kbuild/Image assertion."}
(OUT / "result.json").write_bytes((json.dumps(result, indent=2) + "\n").encode())
print(json.dumps(result))
