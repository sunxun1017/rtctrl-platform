#!/usr/bin/env python3
"""Audit final candidate, verbatim extraction and immutable red/green evidence."""
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("extract", HERE / "test-asoc-functions.py")
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = HERE / "verification-v1.json"
    if output.exists():
        raise ValueError("refuse overwriting audit evidence")
    files = {}
    checks = []

    def check(name, condition):
        checks.append({"name": name, "passed": bool(condition)})

    def bound(path, expected):
        actual = sha(path)
        files[str(path)] = actual
        check("hash bound " + str(path.relative_to(extract.ROOT)), actual == expected)

    candidate = HERE / "driver-source-v2"
    manifest = json.loads((candidate / "manifest.json").read_text())
    for relative, expected in manifest["source_sha256"].items():
        bound(candidate / relative, expected)
        bound(candidate / "replay" / relative, expected)
    for relative, expected in manifest["replay_files_sha256"].items():
        bound(candidate / "replay" / relative, expected)
    public = extract.ROOT / "platforms/rk3568/boards/aiot-3568pq/patches/0010-asoc-prepare-free-errors.patch"
    bound(public, manifest["patch_sha256"])
    bound(candidate / public.name, manifest["patch_sha256"])
    bound(HERE / "driver-prepare.py", manifest["generator_sha256"])
    bound(HERE / "test-asoc-functions.py", manifest["extractor_sha256"])
    for record in manifest["full_board_patch_replay"]:
        bound(candidate / "patch-inputs" / record["patch"], record["sha256"])
        bound(public.parent / record["patch"], record["sha256"])
    for label, totals in [("red-v3", (198,42,156)), ("green-v2", (198,198,0))]:
        directory = HERE / ("asoc-tests-" + label)
        result = json.loads((directory / "result.json").read_text())
        files[str(directory / "result.json")] = sha(directory / "result.json")
        for relative, expected in result["source_sha256"].items():
            bound(directory / "source-inputs" / relative, expected)
            if relative not in [extract.SOC, extract.PCM]:
                check("helper locked bytes " + relative + " " + label,
                      (directory / "source-inputs" / relative).read_bytes() == extract.locked(relative))
            elif label.startswith("green"):
                check("green binds final source " + relative,
                      expected == manifest["source_sha256"][relative])
            else:
                check("red binds original source " + relative,
                      (directory / "source-inputs" / relative).read_bytes() == extract.locked(relative))
        for record in result["excerpts"]:
            text = (directory / "source-inputs" / record["file"]).read_text()
            body = {"function": extract.function, "declaration": extract.declaration,
                    "macro": extract.macro}[record["kind"]](text, record["name"])
            check("verbatim excerpt " + record["name"] + " " + label,
                  hashlib.sha256(body.encode()).hexdigest() == record["sha256"])
        for name, expected in result["harness_sha256"].items():
            bound(directory / name, expected)
            bound(HERE / name, expected)
        bound(directory / "extracted.c", result["extracted_sha256"])
        bound(directory / "real-functions.c", result["unit_sha256"])
        check("unit includes sealed harness only " + label,
              '../' not in (directory / "real-functions.c").read_text())
        for run, record in result["runs"].items():
            check("run counts " + run + " " + label,
                  tuple(record["tests"][k] for k in ["total","passed","failed"]) == totals)
            check("compile success " + run + " " + label, record["compile"]["returncode"] == 0)
            check("execution status " + run + " " + label,
                  record["execution"]["returncode"] == (0 if label.startswith("green") else 1))
            bound(directory / ("asoc-" + run), record["binary_sha256"])
            bound(directory / (run + ".elf.txt"), record["elf_sha256"])
            for stage, stem in [("compile",run+"-compile"),("execution",run)]:
                for channel in ["stdout","stderr"]:
                    bound(directory / (stem+"."+channel), record[stage][channel+"_sha256"])
    prepare = HERE / "prepare-tests-v1/result.json"
    data = json.loads(prepare.read_text())
    check("generator preflight 36/36", (data["total"],data["passed"],data["failed"]) == (36,36,0))
    bound(HERE / "test-driver-prepare.py", data["test_sha256"])
    bound(HERE / "driver-prepare.py", data["generator_sha256"])
    ignore_targets = [candidate / extract.SOC, HERE / "asoc-tests-green-v2/test-asoc-main.c",
                      HERE / "test-asoc-main.c", HERE / "test-asoc-shim.h"]
    ignored = subprocess.run(["git", "-C", extract.ROOT, "check-ignore", "-v", *ignore_targets],
                             check=True, capture_output=True, text=True).stdout
    check("all generated/harness paths ignored", len(ignored.splitlines()) == len(ignore_targets))
    check("original tree clean", subprocess.run(["git", "-C", extract.KERNEL, "status", "--porcelain"],
                                                check=True, capture_output=True).stdout == b"")
    check("original commit locked", subprocess.run(["git", "-C", extract.KERNEL, "rev-parse", "HEAD"],
                                                   check=True, capture_output=True,text=True).stdout.strip() == extract.COMMIT)
    for path in [candidate / "manifest.json", prepare, HERE / "PLAN.md", HERE / "RESULTS.md", HERE / ".gitignore", Path(__file__)]:
        files[str(path)] = sha(path)
    result = {"total": len(checks), "passed": sum(c["passed"] for c in checks),
              "failed": sum(not c["passed"] for c in checks), "checks": checks,
              "files_sha256": files, "git_check_ignore_stdout": ignored,
              "original_tree_clean": True, "board_tested": False, "production_build_completed": False}
    output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"result": str(output), "total": result["total"], "passed": result["passed"], "failed": result["failed"]}))
    return int(result["failed"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
