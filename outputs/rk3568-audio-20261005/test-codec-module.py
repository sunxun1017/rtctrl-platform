#!/usr/bin/env python3
"""Run the actual module auditor on valid ELF and concrete corrupted ELF fixtures."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load():
    spec = importlib.util.spec_from_file_location("codec_build", HERE / "build-codec.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--module-version", default="v3")
    args = parser.parse_args()
    module = load()
    for value in [args.version, args.module_version]:
        if not module.re.fullmatch(r"v[1-9][0-9]*", value):
            parser.error("version must be vN")
    output = HERE / ("driver-tests-module-" + args.version)
    module.new_output(output)
    source = HERE / ("driver-modules-" + args.module_version) / "modules/snd-soc-rk817.ko"
    module.ordinary_input(source)
    kernel_exports = module.symbols(module.ABI / "Module.symvers")
    original = source.read_bytes()
    output.mkdir()
    cases = []

    def run_case(name, change=None, exports_change=None, expected=""):
        case = output / name
        case.mkdir()
        target = case / source.name
        target.write_bytes(original)
        exports = copy.deepcopy(kernel_exports)
        if change:
            change(target, case)
        if exports_change:
            exports_change(exports)
        error = ""
        try:
            audit = module.audit_module(target, case, exports)
            passed = not expected and audit["sha256"] == sha(source) and audit["imports_resolved"]
        except ValueError as caught:
            error = str(caught)
            passed = bool(expected) and expected in error
        cases.append({"name": name, "passed": passed, "error": error,
                      "fixture_module_sha256": sha(target), "real_auditor": True})

    def header_change(offset, value):
        def change(target, case):
            data = bytearray(target.read_bytes())
            struct.pack_into("<H", data, offset, value)
            target.write_bytes(data)
        return change

    def section_change(before, after):
        def change(target, case):
            section = case / "mutated.modinfo"
            subprocess.run(["aarch64-linux-gnu-objcopy", "--dump-section", ".modinfo=" + str(section), str(target)], check=True)
            data = section.read_bytes()
            if data.count(before) != 1:
                raise ValueError("Fixture mutation token changed")
            section.write_bytes(data.replace(before, after))
            subprocess.run(["aarch64-linux-gnu-objcopy", "--update-section", ".modinfo=" + str(section), str(target)], check=True)
        return change

    def rename(target, case):
        subprocess.run(["aarch64-linux-gnu-objcopy", "--redefine-sym", "regmap_read=rtctrl_missing_import", str(target)], check=True)

    def weak(target, case):
        subprocess.run(["aarch64-linux-gnu-objcopy", "--weaken-symbol", "regmap_read", str(target)], check=True)

    run_case("valid_exact_abi_module")
    run_case("wrong_machine", header_change(18, 62), expected="AArch64 ET_REL")
    run_case("dynamic_elf_type", header_change(16, 3), expected="AArch64 ET_REL")
    run_case("wrong_vermagic", section_change(module.VERMAGIC.encode(), module.VERMAGIC.replace("rt89", "rt88").encode()), expected="Wrong module vermagic")
    run_case("wrong_name", section_change(b"name=snd_soc_rk817", b"name=snd_soc_rk818"), expected="license/name")
    run_case("wrong_license", section_change(b"license=GPL v2", b"license=Proprietary"), expected="license/name")
    run_case("external_module_dependency", section_change(b"depends=\0", b"depends=foreign\0"), expected="external module dependencies")
    run_case("missing_kernel_import", exports_change=lambda exports: exports.pop("regmap_read"), expected="not available from the exact Image")
    run_case("wrong_import_provider", exports_change=lambda exports: exports["regmap_read"].update(provider="other_module"), expected="not available from the exact Image")
    run_case("unimported_symbol_namespace", exports_change=lambda exports: exports["regmap_read"].update(namespace="UNIMPORTED"), expected="not available from the exact Image")
    run_case("unknown_actual_undefined_symbol", rename, expected="not available from the exact Image")
    run_case("actual_weak_import_refused", weak, expected="Unreviewed weak/other")
    for name, target in [("existing_build_output_refused", HERE / ("driver-modules-" + args.module_version)),
                         ("outside_repository_refused", HERE.parents[2] / "codec-unowned-output")]:
        try:
            module.new_output(target)
            passed = False
            error = "accepted"
        except ValueError as caught:
            error = str(caught)
            passed = "Refuse existing output" in error if name.startswith("existing") else "escaped repository" in error
        cases.append({"name": name, "passed": passed, "error": error, "real_auditor": True})
    symlink = output / "linked"
    symlink.symlink_to(output, target_is_directory=True)
    try:
        module.new_output(symlink / "child")
        passed = False
        error = "accepted"
    except ValueError as caught:
        error = str(caught)
        passed = "symlink output parent" in error
    cases.append({"name": "symlink_build_parent_refused", "passed": passed, "error": error, "real_auditor": True})
    record = {"cases": cases, "passed": sum(case["passed"] for case in cases), "total": len(cases),
              "builder_sha256": sha(HERE / "build-codec.py"), "test_sha256": sha(Path(__file__)),
              "module_sha256": sha(source), "module_bytes": source.stat().st_size,
              "abi_symvers_sha256": sha(module.ABI / "Module.symvers"),
              "board_tested": False, "kernel_module_loaded": False, "real_elf_corruption_and_nm": True}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"output": str(output), "passed": record["passed"], "total": record["total"]}))
    raise SystemExit(record["passed"] != record["total"])


if __name__ == "__main__":
    main()
