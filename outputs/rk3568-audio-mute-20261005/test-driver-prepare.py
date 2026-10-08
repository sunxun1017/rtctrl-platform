#!/usr/bin/env python3
"""Real CLI/input rejection and independent full codec patch replay checks."""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("mute_prepare", HERE / "driver-prepare.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def main():
    output = HERE / "prepare-tests-v1"
    output.mkdir(exist_ok=False)
    records = []
    base = (prepare.BASE / prepare.SOURCE).read_bytes()
    target = (HERE / "driver-source-v2" / prepare.SOURCE).read_bytes()
    header = (HERE / "driver-source-v2" / prepare.HEADER).read_bytes()
    patch = prepare.PATCH.read_bytes()

    def check(name, value):
        records.append({"name": name, "passed": bool(value)})

    check("runtime input SHA locked", prepare.sha(base) == prepare.BASE_SHA)
    check("deterministic candidate equals published source", prepare.candidate(base.decode()).encode() == target)
    check("original license notice retained", base[:base.index(b"#include")] == target[:target.index(b"#include")])
    check("public patch equals final preview", patch == (HERE / "driver-source-v2" / prepare.PATCH.name).read_bytes())
    check("headers unchanged", header == (prepare.BASE / prepare.HEADER).read_bytes())

    replay_dir = output / "independent-replay"
    for relative in [prepare.SOURCE, prepare.HEADER]:
        file = replay_dir / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(prepare.command(["git", "-C", prepare.KERNEL, "show", prepare.COMMIT + ":" + relative]))
    for applied in [*prepare.PREVIOUS, prepare.PATCH]:
        completed = subprocess.run(["patch", "--batch", "--forward", "--fuzz=0", "-p1", "-i", str(applied)],
                                   cwd=replay_dir, capture_output=True, text=True)
        (output / (applied.name + ".log")).write_text(completed.stdout + completed.stderr)
        check("real replay " + applied.name, completed.returncode == 0)
    check("full replay C byte identical", (replay_dir / prepare.SOURCE).read_bytes() == target)
    check("full replay H byte identical", (replay_dir / prepare.HEADER).read_bytes() == header)

    for name, args in [("invalid version rejected", ["--version", "../escape"]),
                       ("existing output rejected", ["--version", "v2"])]:
        completed = subprocess.run(["python3", str(HERE / "driver-prepare.py"), *args], capture_output=True, text=True)
        check(name, completed.returncode != 0)
        (output / (name.replace(" ", "-") + ".log")).write_text(completed.stderr)

    saved_here, saved_base, saved_patch, saved_previous = prepare.HERE, prepare.BASE, prepare.PATCH, prepare.PREVIOUS
    saved_argv = sys.argv
    try:
        for scenario in ["changed-base", "bad-dependency", "conflicting-patch"]:
            fixture = output / scenario
            fixture.mkdir()
            prepare.HERE = fixture
            prepare.BASE = saved_base
            prepare.PATCH = fixture / "0009-rk817-mute-errors.patch"
            prepare.PREVIOUS = saved_previous
            if scenario == "changed-base":
                copy = fixture / "input" / prepare.SOURCE
                copy.parent.mkdir(parents=True)
                copy.write_bytes(base + b"\n/* changed input */\n")
                prepare.BASE = fixture / "input"
            elif scenario == "bad-dependency":
                wrong = fixture / saved_previous[-1].name
                wrong.write_bytes(saved_previous[-1].read_bytes().replace(b"rk817_codec.c", b"nonexistent_codec.c"))
                prepare.PREVIOUS = [saved_previous[0], wrong]
            else:
                prepare.PATCH.write_bytes(b"existing unrelated candidate\n")
            sys.argv = ["driver-prepare.py", "--version", "v1", "--publish"]
            capture = io.StringIO()
            try:
                with contextlib.redirect_stdout(capture):
                    prepare.main()
            except (ValueError, subprocess.CalledProcessError) as error:
                check(scenario + " rejected", True)
                (fixture / "rejection.txt").write_text(str(error) + "\n")
            else:
                check(scenario + " rejected", False)
            check(scenario + " leaves no successful manifest", not (fixture / "driver-source-v1/manifest.json").exists())
            if scenario == "conflicting-patch":
                check("conflicting public fixture preserved", prepare.PATCH.read_bytes() == b"existing unrelated candidate\n")
    finally:
        prepare.HERE, prepare.BASE, prepare.PATCH, prepare.PREVIOUS = saved_here, saved_base, saved_patch, saved_previous
        sys.argv = saved_argv
    check("runtime input preserved", (prepare.BASE / prepare.SOURCE).read_bytes() == base)
    check("public patch preserved", prepare.PATCH.read_bytes() == patch)
    check("original locked tree still clean", not prepare.command(["git", "-C", prepare.KERNEL, "status", "--porcelain"]))
    result = {"total": len(records), "passed": sum(record["passed"] for record in records), "checks": records,
              "base_sha256": prepare.sha(base), "source_sha256": prepare.sha(target), "patch_sha256": prepare.sha(patch),
              "script_sha256": prepare.sha(Path(__file__).read_bytes()), "generator_sha256": prepare.sha((HERE / "driver-prepare.py").read_bytes())}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"total": result["total"], "passed": result["passed"]}))
    return 0 if result["total"] == result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
