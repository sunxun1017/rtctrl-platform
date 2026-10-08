#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Decode every original DT with separately built dtc and compare root identity."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DTC = ROOT / ".deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc"
DTC_SHA = "3be6ad1bcef2e36b35624e9f2cd6c13957949e08818868ad04ad070b4fd9e896"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roundtrip", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ram-candidate", action="store_true")
    args = parser.parse_args()
    source = Path(args.roundtrip).resolve()
    out = Path(args.out).absolute()
    if out != out.resolve() or not out.is_relative_to(HERE / "build"):
        parser.error("Need fresh ordinary evidence path")
    if hashlib.sha256(DTC.read_bytes()).hexdigest() != DTC_SHA:
        parser.error("Locked independent dtc SHA mismatch")
    audit = json.loads((source / "audit.json").read_text())
    out.mkdir(parents=True, exist_ok=False)
    work = [("rsce-" + str(e["index"]), source / "rsce" / e["path"], e["fdt"])
            for e in audit["resource"]["entries"] if e["path"].endswith(".dtb")]
    work += [(f"concat-{e['index']:02}", source / "dtb-concat" / f"{e['index']:02}.dtb", e)
             for e in audit["concatenated_dtbs"]]
    cases = []
    for name, dtb, expected in work:
        result = subprocess.run([str(DTC), "-I", "dtb", "-O", "dts", str(dtb)],
                                capture_output=True, timeout=30)
        (out / (name + ".dts")).write_bytes(result.stdout)
        (out / (name + ".warnings")).write_bytes(result.stderr)
        properties = dict(re.findall(r'^\t(model|compatible) = "([^"\n]*)";',
                                     result.stdout.decode("ascii"), re.M))
        model = properties.get("model", "").split(r"\0") if "model" in properties else []
        compatible = properties.get("compatible", "").split(r"\0")
        passed = (result.returncode == 0 and model == expected["root_model"] and
                  compatible == expected["root_compatible"])
        cases.append({"name": name, "passed": passed, "returncode": result.returncode,
                      "warning_bytes": len(result.stderr), "model": model,
                      "compatible": compatible, "dtb_sha256": hashlib.sha256(dtb.read_bytes()).hexdigest()})
    report = {"dtc_sha256": DTC_SHA, "cases": cases, "total": len(cases),
              "passed": sum(case["passed"] for case in cases), "board_tested": False,
              "warnings_are_not_binding_or_hardware_validation": True}
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("total", "passed", "board_tested")}))
    if report["passed"] != report["total"] or report["total"] != (10 if args.ram_candidate else 20):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
