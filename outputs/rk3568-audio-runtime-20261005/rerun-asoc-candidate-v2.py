#!/usr/bin/env python3
"""Fresh root red/green caller execution with byte-exact production bodies."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = HERE / "full-duplex-contract-v1"
CANDIDATE = HERE / "asoc-open-rollback-v1"
OUT = HERE / "build/root-asoc-candidate-v2"
VERSIONS = {
    "red": {"manifest": "8b82cbadb4aa0e65adf0cb868bda301205d83c237f505fb4bbb1ab13758560c0",
            "receipt": "148f5b0e7b78e8237010077d7a0759a31179d91aa0e5399b9f14d42e442da1b7",
            "functions": 68, "passed": 0},
    "green": {"manifest": "4c043676fe48a47a983375ef392a45a930adcbc9ecdab3c68bd3511215b6630b",
              "receipt": "20e1f2fb880cefe7d870c530e9528de19aca0404ab88fdc18a7744fa93213fc5",
              "functions": 70, "passed": 21}
}
RUNNER_SHA = "e7436d6884d8a91201343ecd8b3f9955a27765b5926b4f8c00b1f083434fda20"
GROUP_FILES = {
    "cpu": "rockchip_i2s_tdm.c", "codec": "rk817_codec.c", "dai": "soc-dai.c",
    "component": "soc-component.c", "simple": "simple-card-utils.c", "link": "soc-link.c",
    "pcm": "soc-pcm.c", "compress": "soc-compress.c", "soc-header": "soc.h",
    "component-header": "soc-component.h"
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def ordinary(path):
    if not path.is_relative_to(ROOT) or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Nonordinary or escaped input: " + str(path))
    parent = path.parent
    while True:
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError("Nonordinary input ancestry")
        if parent == ROOT:
            break
        parent = parent.parent
    return path.read_bytes()


def write_json(path, data):
    path.write_bytes((json.dumps(data, indent=2) + "\n").encode())


def actual_function(source, name):
    if name != "snd_soc_component_active":
        return module.function(source, name)
    # The actual locked header has a return type on the preceding line.
    prefix = "static inline unsigned int\nsnd_soc_component_active("
    if source.count(prefix) != 1:
        raise ValueError("Unique actual inline declaration required")
    start = source.index(prefix)
    depth = 0
    for end in range(source.index("{", start), len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise ValueError("Unterminated actual inline body")


if OUT.exists():
    raise ValueError("Fresh root execution directory required")
baseline_data = ordinary(BASE / "model-v5/input-manifest.json")
assert digest(baseline_data) == "abfa327867d421e13b39bb7d2f71e25f519f3652cbd0af39b427af577b80c954"
baseline = json.loads(baseline_data)
original_sources = {}
for relative, entry in baseline["input_files"].items():
    source = ordinary(ROOT / relative)
    snapshot = ordinary(BASE / entry["snapshot"])
    assert source == snapshot and len(source) == entry["size"] and digest(source) == entry["sha256"]
    original_sources[Path(relative).name] = source.decode()
util = HERE / "cpu-lifecycle-v12/source_utils.py"
assert digest(ordinary(util)) == "3d5deab6d6eea70d067c9b0b8336d66f39ce1cc0e18a8a7938a4f60d66c43440"
spec = importlib.util.spec_from_file_location("locked_source_utils", util)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert digest(ordinary(CANDIDATE / "run-model.py")) == RUNNER_SHA
OUT.mkdir()
summary = {"root_fresh_compile_and_execution": True,
           "root_runner_sha256": digest(Path(__file__).read_bytes()),
           "model_only": True, "board_tested": False,
           "full_duplex_passed": False, "duplex_START_authorized": False, "versions": {}}


def recorded_run(argv, directory, stem):
    result = subprocess.run(argv, capture_output=True, timeout=45)
    (directory / (stem + ".stdout")).write_bytes(result.stdout)
    (directory / (stem + ".stderr")).write_bytes(result.stderr)
    return result, {"argv": argv, "exit": result.returncode,
                    "stdout_sha256": digest(result.stdout), "stderr_sha256": digest(result.stderr)}


for kind, expected in VERSIONS.items():
    model = CANDIDATE / ("model-" + kind + "-v2")
    runs = CANDIDATE / ("runs-" + kind + "v1")
    manifest_data = ordinary(model / "input-manifest.json")
    author_receipt_data = ordinary(runs / "receipt.json")
    assert digest(manifest_data) == expected["manifest"]
    assert digest(author_receipt_data) == expected["receipt"]
    manifest = json.loads(manifest_data)
    author = json.loads(author_receipt_data)
    assert manifest["mode"] == kind and author["runner_sha256"] == RUNNER_SHA
    assert digest(ordinary(runs / "runner-snapshot.py")) == RUNNER_SHA
    assert set(author["runs"]) == {"host", "asan-ubsan", "aarch64-qemu"}
    assert len(manifest["production_functions_sha256"]) == expected["functions"]
    sources = dict(original_sources)
    for relative, entry in manifest["source_files"].items():
        data = ordinary(CANDIDATE / entry["source"])
        assert digest(data) == entry["sha256"]
        sources[Path(relative).name] = data.decode()
    for key, expected_body_sha in manifest["production_functions_sha256"].items():
        group, name = key.split(":", 1)
        source_body = actual_function(sources[GROUP_FILES[group]], name)
        extracted = actual_function(ordinary(model / ("actual-" + group + "-functions.c")).decode(), name)
        assert source_body == extracted and digest(source_body.encode()) == expected_body_sha, key
    directory = OUT / kind
    snapshot_model = directory / "model"
    snapshot_model.mkdir(parents=True)
    (directory / "author-receipt.json").write_bytes(author_receipt_data)
    model_inventory = {}
    for filename, expected_sha in author["model_files_sha256"].items():
        assert Path(filename).name == filename
        data = ordinary(model / filename)
        assert digest(data) == expected_sha
        (snapshot_model / filename).write_bytes(data)
        model_inventory[filename] = {"bytes": len(data), "sha256": expected_sha}
    assert set(model_inventory) == {path.name for path in model.iterdir() if path.is_file()}
    write_json(directory / "model-inventory.json", model_inventory)
    result_record = {"production_functions_verified": expected["functions"],
                     "manifest_sha256": expected["manifest"],
                     "author_receipt_sha256": expected["receipt"], "runs": {}}
    expected_counts = {"contract_total": 25, "contract_passed": expected["passed"],
                       "boundary_total": 110, "boundary_passed": 110}
    for label, entry in author["runs"].items():
        binary = directory / ("caller-chain-" + label)
        compile_argv = list(entry["compile"]["argv"])
        compile_argv[compile_argv.index(str(model / "unit.c"))] = str(snapshot_model / "unit.c")
        compile_argv[compile_argv.index("-o") + 1] = str(binary)
        compiled, compile_record = recorded_run(compile_argv, directory, label + "-compile")
        assert compiled.returncode == 0 and not compiled.stderr
        execution_argv = list(entry["execution"]["argv"])
        execution_argv[-1] = str(binary)
        executed, execution_record = recorded_run(execution_argv, directory, label)
        lines = executed.stdout.decode().splitlines()
        contract_lines = [line for line in lines if line.startswith("CONTRACT_CHECK ")]
        boundary_lines = [line for line in lines if line.startswith("BOUNDARY_CHECK ")]
        failures = [line.split()[1] for line in contract_lines if line.endswith(" 0")]
        assert len(contract_lines) == 25 and len(boundary_lines) == 110
        assert sum(line.endswith(" 1") for line in contract_lines) == expected["passed"]
        assert all(line.endswith(" 1") for line in boundary_lines)
        assert json.loads(lines[-1]) == expected_counts
        assert failures == author["expected_remaining_failures"]
        assert executed.returncode == 1 and not executed.stderr
        # Deterministic per-case output must also match the complete author log.
        assert execution_record["stdout_sha256"] == entry["execution"]["stdout_sha256"]
        assert digest(ordinary(runs / (label + ".stdout"))) == execution_record["stdout_sha256"]
        result_record["runs"][label] = {"compile": compile_record, "execution": execution_record,
                                        "binary_sha256": digest(binary.read_bytes()),
                                        "counts": expected_counts, "remaining_failures": failures,
                                        "complete_observation_log_matches_author": True}
        write_json(directory / "result.json", result_record)
    summary["versions"][kind] = result_record
    write_json(OUT / "result.json", summary)
summary["all_six_fresh_compiles_and_runs_match"] = True
write_json(OUT / "result.json", summary)
print(json.dumps({"root_fresh_completed": True,
                  "versions": {kind: {"functions": value["production_functions_verified"],
                                          "runs": {label: entry["counts"] for label, entry in value["runs"].items()}}
                               for kind, value in summary["versions"].items()},
                  "board_tested": False, "full_duplex_passed": False}))
