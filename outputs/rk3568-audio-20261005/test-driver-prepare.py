#!/usr/bin/env python3
"""Test real preparation entrypoint against matching, tampered and unsafe outputs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load():
    spec = importlib.util.spec_from_file_location("codec_prepare", HERE / "driver-prepare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--source-version", default="v3")
    parser.add_argument("--rebuild-version", default="v4")
    args = parser.parse_args()
    module = load()
    for value in [args.version, args.source_version, args.rebuild_version]:
        if not module.re.fullmatch(r"v[1-9][0-9]*", value):
            parser.error("version must be vN")
    output = HERE / ("driver-tests-prepare-" + args.version)
    module.new_output(output)
    patch_before = module.PATCH.read_bytes()
    candidate = HERE / ("driver-source-" + args.source_version)
    original_candidate = {relative: sha(candidate / relative) for relative in [module.SOURCE, module.HEADER]}
    output.mkdir()
    cases = []

    def run_case(name, mode, marker):
        case = output / name
        case.mkdir()
        private_patch = case / "codec.patch"
        phase = case / "phase"
        if mode == "symlink-parent":
            target = case / "target"
            target.mkdir()
            phase.symlink_to(target, target_is_directory=True)
        else:
            phase.mkdir()
        if mode not in ["missing", "symlink-patch"]:
            private_patch.write_bytes(patch_before + (b"\n# tampered\n" if mode == "tampered" else b""))
        if mode == "symlink-patch":
            target = case / "real.patch"
            target.write_bytes(patch_before)
            private_patch.symlink_to(target)
        if mode == "existing-output":
            (phase / "driver-source-v1").mkdir()
        if mode == "symlink-output":
            target = case / "target"
            target.mkdir()
            (phase / "driver-source-v1").symlink_to(target, target_is_directory=True)
        runner = case / "run.py"
        runner.write_text("import importlib.util, pathlib, sys\n"
                          "spec = importlib.util.spec_from_file_location('prepare', " + repr(str(HERE / "driver-prepare.py")) + ")\n"
                          "module = importlib.util.module_from_spec(spec)\n"
                          "spec.loader.exec_module(module)\n"
                          "module.HERE = pathlib.Path(" + repr(str(phase)) + ")\n"
                          "module.PATCH = pathlib.Path(" + repr(str(private_patch)) + ")\n"
                          "sys.argv = ['driver-prepare.py', '--version', " + repr("../../escape" if mode == "version" else "v1") + "]\n"
                          "module.main()\n")
        before = private_patch.read_bytes() if private_patch.exists() else None
        result = subprocess.run([sys.executable, str(runner)], capture_output=True, text=True)
        (case / "stdout.txt").write_text(result.stdout)
        (case / "stderr.txt").write_text(result.stderr)
        if mode in ["matching", "missing"]:
            built = phase / "driver-source-v1"
            record = json.loads((built / "driver-source-manifest.json").read_text())
            passed = result.returncode == 0 and private_patch.read_bytes() == patch_before
            passed &= all(sha(built / relative) == digest for relative, digest in original_candidate.items())
            passed &= record["existing_identical_patch_reused"] == (mode == "matching")
        else:
            passed = result.returncode != 0 and marker in result.stderr
            passed &= private_patch.read_bytes() == before
        cases.append({"name": name, "passed": passed, "exit_code": result.returncode,
                      "expected_message": marker, "real_entrypoint": True,
                      "test_path_substitutions_only": ["HERE", "PATCH"]})

    run_case("published_matching_patch_rebuild", "matching", "")
    run_case("missing_patch_created_exclusively", "missing", "")
    run_case("tampered_patch_refused", "tampered", "Existing published patch differs")
    run_case("existing_source_output_refused", "existing-output", "Refuse existing output")
    run_case("symlink_source_output_refused", "symlink-output", "Refuse symlink output")
    run_case("symlink_source_parent_refused", "symlink-parent", "Refuse symlink output parent")
    run_case("symlink_patch_refused", "symlink-patch", "Refuse symlink output")
    run_case("escaped_version_refused", "version", "version must be vN")
    public_reuse = subprocess.run([sys.executable, str(HERE / "driver-prepare.py"), "--version", args.rebuild_version],
                                 capture_output=True, text=True)
    (output / "public-reuse-stdout.txt").write_text(public_reuse.stdout)
    (output / "public-reuse-stderr.txt").write_text(public_reuse.stderr)
    public = HERE / ("driver-source-" + args.rebuild_version)
    public_record = json.loads((public / "driver-source-manifest.json").read_text()) if public_reuse.returncode == 0 else {}
    cases.append({"name": "actual_public_rebuild_same_candidate_patch_unchanged",
                  "passed": public_reuse.returncode == 0 and public_record.get("existing_identical_patch_reused") is True and
                            all(sha(public / relative) == digest for relative, digest in original_candidate.items()) and
                            module.PATCH.read_bytes() == patch_before,
                  "exit_code": public_reuse.returncode, "version": args.rebuild_version,
                  "real_entrypoint": True, "test_path_substitutions_only": []})
    record = {"cases": cases, "passed": sum(item["passed"] for item in cases), "total": len(cases),
              "generator_sha256": sha(HERE / "driver-prepare.py"), "test_sha256": sha(Path(__file__)),
              "published_patch_sha256": sha(module.PATCH), "published_patch_unchanged": module.PATCH.read_bytes() == patch_before,
              "candidate_sources": original_candidate, "board_tested": False, "kernel_source_modified": False,
              "minimum_inputs": ["Clean locked kernel commit", "Python 3 + git", "Published 0006 exact bytes or absent patch"],
              "public_reproduce": "python3 outputs/rk3568-audio-20261005/driver-prepare.py [--version vN]"}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"output": str(output), "passed": record["passed"], "total": record["total"]}))
    raise SystemExit(record["passed"] != record["total"])


if __name__ == "__main__":
    main()
