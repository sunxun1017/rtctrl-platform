#!/usr/bin/env python3
"""Fresh helper execution in root-owned outputs; no actual ALSA access."""
import hashlib
import json
from pathlib import Path
import stat
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PEER = HERE / "pcm-peer-idle-v1"
OUT = HERE / "build/root-pcm-peer-idle-v1"
EXPECTED = {
    "pcm-peer-idle.c": "4edc171fd8bb57c10d844bbfdfa72f83dd090de3f96f143bab8459fd7e22c8d2",
    "parameters.h": "26ae04bc98a5e466bc24a18ab76b5841c9c52a0e265d5610cdedc2d4011536f9",
    "model.c": "a7ddb257ce91622a5cedb27139afd8c6b2e3723826920c57ff21e0d36f34a4e6",
    "run-models.py": "cee31266a3bf6f1ec03ce96d0062439931f4bf1e8917bc7ed265dd79cd6a262f",
    "models-green-v1/result.json": "29d6cafc9f5b9022c0d9e26280f92017715ac07a0efd18b30eb1dd38f6da35ba"
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ordinary(path):
    if not path.is_relative_to(ROOT) or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Ordinary repository input required")
    parent = path.parent
    while True:
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError("Nonordinary input ancestor")
        if parent == ROOT:
            break
        parent = parent.parent
    return path.read_bytes()


if OUT.exists():
    raise ValueError("Fresh root helper output required")
inputs = {}
for relative, expected in EXPECTED.items():
    data = ordinary(PEER / relative)
    if sha(data) != expected:
        raise ValueError("Reviewed helper input changed: " + relative)
    inputs[relative] = data
old_main = ordinary(HERE / "pcm-config.c")
assert sha(old_main) == "bf3c513fc98474c55346c77277e347c2bc0e194480c76c1fd6d1d2d9fbb98b2a"
assert old_main.startswith(inputs["parameters.h"])
OUT.mkdir()
snapshot = OUT / "snapshot"
snapshot.mkdir()
for relative in ["pcm-peer-idle.c", "parameters.h", "model.c"]:
    (snapshot / relative).write_bytes(inputs[relative])
(OUT / "author-green-result.json").write_bytes(inputs["models-green-v1/result.json"])
(OUT / "author-runner.py").write_bytes(inputs["run-models.py"])
runner = inputs["run-models.py"].decode()
for old, new in [("ROOT = HERE.parents[2]", "ROOT = HERE.parents[4]"),
                 ("RUNTIME = HERE.parent", "RUNTIME = HERE.parents[2]")]:
    assert runner.count(old) == 1
    runner = runner.replace(old, new, 1)
(snapshot / "run-models.py").write_bytes(runner.encode())
argv = ["/usr/bin/python3", "-B", str(snapshot / "run-models.py"),
        "--phase", "green", "--out", str(snapshot / "runs-green")]
with (OUT / "runner.stdout").open("wb") as stdout:
    with (OUT / "runner.stderr").open("wb") as stderr:
        process = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=180)
invocation = {"argv": argv, "exit": process.returncode,
              "root_runner_sha256": sha(Path(__file__).read_bytes()),
              "copied_runner_sha256": sha((snapshot / "run-models.py").read_bytes()),
              "author_runner_sha256": EXPECTED["run-models.py"],
              "only_runner_changes": ["ROOT depth", "RUNTIME depth"],
              "stdout_sha256": sha((OUT / "runner.stdout").read_bytes()),
              "stderr_sha256": sha((OUT / "runner.stderr").read_bytes())}
(OUT / "root-invocation.json").write_bytes((json.dumps(invocation, indent=2) + "\n").encode())
assert process.returncode == 0 and not (OUT / "runner.stderr").read_bytes()
result = json.loads((snapshot / "runs-green/result.json").read_bytes())
assert result["source_sha256"] == EXPECTED["pcm-peer-idle.c"]
assert result["parameters_header_sha256"] == EXPECTED["parameters.h"]
assert result["wrapper_sha256"] == EXPECTED["model.c"]
assert result["model_only"] and not result["board_tested"] and not result["real_ALSA_access"]
assert set(result["results"]) == {"host", "asan-ubsan", "aarch64-qemu"}
for name, run in result["results"].items():
    assert run["passed"] == 1032 and run["total"] == 1032 and len(run["cases"]) == 1032
    assert all(case["passed"] for case in run["cases"])
for relative, expected in EXPECTED.items():
    assert sha(ordinary(PEER / relative)) == expected
receipt = {"root_fresh_compile_and_execution": True, "inputs_sha256": EXPECTED,
           "actual_main_and_parameters_unchanged": True,
           "counts": {name: {"passed": run["passed"], "total": run["total"]}
                      for name, run in result["results"].items()},
           "invocation": invocation, "model_only": True, "board_tested": False,
           "START_authorized": False,
           "scope": "Actual main with syscall boundaries and interruptible SIGALRM model; no kernel PM/DMA or shared sysclk measurement."}
(OUT / "result.json").write_bytes((json.dumps(receipt, indent=2) + "\n").encode())
print(json.dumps(receipt))
