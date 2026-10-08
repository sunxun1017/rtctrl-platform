#!/usr/bin/env python3
"""Build a separate BusyBox and test real module argument propagation under QEMU."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / ".deps/busybox-firstboot/busybox-1.36.1.tar.bz2"
ARCHIVE_SHA = "b8cc24c9574d809e7279c3be349795c5d5ceb6fdf19ca709f80cde50e47de314"
OLD = ROOT / "outputs/rk3568-persistent-linux-20261003/busybox/busybox-1.36.1"
OLD_CONFIG = ROOT / "outputs/rk3568-persistent-linux-20261003/busybox.config"
OLD_CONFIG_SHA = "6cb6e35779c81d7758a5597795edef8e3d2b8a01de00e88d3c7f043b8a5b30be"
OLD_BINARY_SHA = "5c2f1c653fdfe92d21c5baa68a64a460dd9aff3b8947d526048314700e1d5844"
QEMU = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"
FLAG = "CONFIG_FEATURE_CMDLINE_MODULE_OPTIONS"

WRAPPER = r'''#define _GNU_SOURCE
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/syscall.h>

/* This test implementation never forwards any raw syscall to a kernel. */
long __wrap_syscall(long number, ...) {
    va_list arguments;
    va_start(arguments, number);
    if (number == __NR_finit_module) {
        int fd = va_arg(arguments, int);
        const char *options = va_arg(arguments, const char *);
        int flags = va_arg(arguments, int);
        va_end(arguments);
        if (fd < 0 || options == NULL || flags != 0) {
            fputs("MOCK_INVALID_MODULE_SYSCALL\n", stdout);
            errno = EINVAL;
            return -1;
        }
        printf("MOCK_FINIT_OPTIONS=[%s]\n", options);
        if (getenv("BB_MOCK_FINIT_FALLBACK") != NULL) {
            errno = ENOSYS;
            return -1;
        }
        return 0;
    }
    if (number == __NR_init_module) {
        const void *image = va_arg(arguments, const void *);
        size_t length = va_arg(arguments, size_t);
        const char *options = va_arg(arguments, const char *);
        va_end(arguments);
        if (image == NULL || length == 0 || options == NULL) {
            fputs("MOCK_INVALID_MODULE_SYSCALL\n", stdout);
            errno = EINVAL;
            return -1;
        }
        printf("MOCK_INIT_OPTIONS=[%s]\n", options);
        return 0;
    }
    va_end(arguments);
    printf("MOCK_UNSUPPORTED_SYSCALL=%ld\n", number);
    errno = ENOSYS;
    return -1;
}
'''


def sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Need ordinary file: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_values(text):
    values = {}
    for line in text.splitlines():
        if line.startswith("CONFIG_"):
            key, value = line.split("=", 1)
            values[key] = value
        elif line.startswith("# CONFIG_") and line.endswith(" is not set"):
            values[line.split()[1]] = "n"
    return values


def extract_source(output):
    with tarfile.open(ARCHIVE) as archive:
        for member in archive.getmembers():
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != "busybox-1.36.1" or ".." in parts or member.name.startswith("/"):
                raise ValueError("Unsafe archive path")
            if not member.isdir() and not member.isfile():
                raise ValueError("Only ordinary source files/directories are accepted")
            path = output.joinpath(*parts)
            if member.isdir():
                path.mkdir(mode=member.mode, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    shutil.copyfileobj(archive.extractfile(member), stream)
                path.chmod(member.mode)
    return output / "busybox-1.36.1"


def run(argv, output, stem, cwd=ROOT, environment=None):
    with (output / (stem + ".stdout")).open("xb") as stdout, (output / (stem + ".stderr")).open("xb") as stderr:
        result = subprocess.run(argv, cwd=cwd, env=environment, stdout=stdout, stderr=stderr)
    if result.returncode:
        raise RuntimeError("Command failed; see " + str(output / (stem + ".stderr")))
    return (output / (stem + ".stdout")).read_text()


def relink_mock(source, destination, wrapper, output, stem):
    """Use the actual successful object/archive link recipe, changing only outputs/syscall."""
    lines = (source / "busybox_unstripped.out").read_text().splitlines()
    if lines[0] != "Output of:":
        raise ValueError("Missing actual BusyBox link recipe")
    arguments = shlex.split(lines[1])
    if Path(arguments[0]).name != "aarch64-linux-gnu-gcc" or "-static" not in arguments:
        raise ValueError("Unexpected previous link compiler/type")
    rewritten = []
    inputs = {}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "-o":
            rewritten.extend([argument, str(destination)])
            index += 2
            continue
        if argument.startswith("-Wl,-Map,"):
            rewritten.append("-Wl,-Map," + str(destination) + ".map")
        elif argument.endswith(".a") or argument.endswith(".o"):
            path = source / argument
            inputs[path.relative_to(ROOT).as_posix()] = sha(path)
            rewritten.append(str(path))
        else:
            rewritten.append(argument)
        index += 1
    rewritten += [str(wrapper), "-Wl,--wrap=syscall"]
    run(rewritten, output, stem)
    if inputs != {name: sha(ROOT / name) for name in inputs}:
        raise ValueError("Actual link objects changed during mocked relink")
    return {"argv": rewritten, "inputs": inputs, "artifact_sha256": sha(destination)}


def module_probe(binary, fixture, options, fallback=False):
    environment = dict(os.environ)
    environment.pop("BB_MOCK_FINIT_FALLBACK", None)
    if fallback:
        environment["BB_MOCK_FINIT_FALLBACK"] = "1"
    result = subprocess.run([str(QEMU), str(binary), "insmod", str(fixture)] + options,
                            env=environment, capture_output=True, text=True, timeout=10)
    if result.returncode != 0 or result.stderr:
        raise AssertionError((result.returncode, result.stdout, result.stderr))
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.revision):
        parser.error("Need revision vN")
    build = HERE / "build/busybox-module-options"
    output = build / args.revision
    manifest_path = HERE / "busybox-module-options-manifest.json"
    current = HERE
    for part in output.relative_to(HERE).parts:
        current = current / part
        if current.is_symlink():
            parser.error("Symlink output component is forbidden")
    if os.path.lexists(output) or os.path.lexists(manifest_path):
        parser.error("Refusing previous output/evidence")
    if sha(ARCHIVE) != ARCHIVE_SHA or sha(OLD_CONFIG) != OLD_CONFIG_SHA or sha(OLD / "busybox") != OLD_BINARY_SHA:
        parser.error("Original verified source/config/binary SHA differs")
    before = {"config": sha(OLD_CONFIG), "old_build_config": sha(OLD / ".config"), "binary": sha(OLD / "busybox")}
    if (OLD / ".config").read_bytes() != OLD_CONFIG.read_bytes():
        parser.error("Original build config no longer matches")
    output.mkdir(parents=True)
    new_source = extract_source(output)
    original_config = OLD_CONFIG.read_text()
    disabled = "# " + FLAG + " is not set"
    if original_config.splitlines().count(disabled) != 1:
        parser.error("Original option must be disabled exactly once")
    (new_source / ".config").write_text(original_config.replace(disabled, FLAG + "=y"))
    environment = dict(os.environ)
    environment["PATH"] = str(ROOT / ".deps/host-tools/bin") + os.pathsep + environment["PATH"]
    configure = ["make", "-C", str(new_source), "CROSS_COMPILE=aarch64-linux-gnu-", "oldconfig"]
    with (output / "oldconfig.stdout").open("xb") as stdout, (output / "oldconfig.stderr").open("xb") as stderr:
        subprocess.run(configure, env=environment, input=b"", stdout=stdout, stderr=stderr, check=True)
    final_config = (new_source / ".config").read_text()
    original_values = config_values(original_config)
    final_values = config_values(final_config)
    changes = {key: {"before": original_values.get(key), "after": final_values.get(key)}
               for key in sorted(set(original_values) | set(final_values)) if original_values.get(key) != final_values.get(key)}
    (output / "config.diff").write_text("".join(difflib.unified_diff(
        original_config.splitlines(keepends=True), final_config.splitlines(keepends=True),
        fromfile="original-busybox.config", tofile="new-busybox.config")))
    if changes != {FLAG: {"before": "n", "after": "y"}}:
        raise ValueError("Unexpected derived configuration change: " + str(changes))
    compile_command = ["make", "-C", str(new_source), "CROSS_COMPILE=aarch64-linux-gnu-", "-j4"]
    run(compile_command, output, "build", environment=environment)
    production = output / "busybox"
    with production.open("xb") as stream:
        stream.write((new_source / "busybox").read_bytes())
    production.chmod(0o755)
    elf = run(["aarch64-linux-gnu-readelf", "-h", "-l", "-d", str(production)], output, "elf")
    if not re.search(r"Machine:\s+AArch64", elf) or not re.search(r"Class:\s+ELF64", elf):
        raise ValueError("Not AArch64 ELF64")
    if re.search(r"\b(?:INTERP|NEEDED)\b", elf):
        raise ValueError("BusyBox must remain static")
    old_symbols = run(["aarch64-linux-gnu-nm", str(OLD / "modutils/modutils.o")], output, "old-module-symbols")
    new_symbols = run(["aarch64-linux-gnu-nm", str(new_source / "modutils/modutils.o")], output, "new-module-symbols")
    linked_symbols = run(["aarch64-linux-gnu-nm", str(new_source / "busybox_unstripped")], output, "linked-symbols")
    if "parse_cmdline_module_options" in old_symbols or not re.search(r"\bT parse_cmdline_module_options\b", new_symbols):
        raise ValueError("Parser compilation did not change as expected")
    if not re.search(r"\bT parse_cmdline_module_options\b", linked_symbols):
        raise ValueError("Parser was not linked into actual BusyBox")
    applets = run([str(QEMU), str(production), "--list"], output, "qemu-applets")
    old_applets = (ROOT / "outputs/rk3568-persistent-linux-20261003/busybox-applets.txt").read_text()
    if applets != old_applets:
        raise ValueError("Unrelated applet inventory changed")
    sanity = run([str(QEMU), str(production), "sh", "-c", "test 7 -eq 7\nprintf 'BUSYBOX_SHELL_OK\\n'\n"],
                 output, "qemu-shell")
    if sanity != "BUSYBOX_SHELL_OK\n":
        raise ValueError("Static QEMU shell failed")
    wrapper_source = output / "mock-module-syscall.c"
    wrapper_source.write_text(WRAPPER)
    wrapper_object = output / "mock-module-syscall.o"
    wrapper_command = ["aarch64-linux-gnu-gcc", "-O2", "-Wall", "-Wextra", "-Werror", "-c",
                       str(wrapper_source), "-o", str(wrapper_object)]
    run(wrapper_command, output, "mock-compile")
    old_mock = output / "busybox-old-mock"
    new_mock = output / "busybox-new-mock"
    mock_links = {"old": relink_mock(OLD, old_mock, wrapper_object, output, "mock-old-link"),
                  "new": relink_mock(new_source, new_mock, wrapper_object, output, "mock-new-link")}
    fixture = output / "ordinary-not-a-real-module.ko"
    fixture.write_bytes(b"\x7fELF" + bytes(60))
    options = ["config_path=/lib/firmware/rtctrl-pm0.txt", "power_save=0", "empty="]
    old_actual = module_probe(old_mock, fixture, options)
    if old_actual != "MOCK_FINIT_OPTIONS=[]\n":
        raise ValueError("Original compiled baseline did not demonstrate discarded options")
    red = {"status": "EXPECTED_RED_MODULE_OPTIONS_LOSS", "requested_options": options,
           "expected": "MOCK_FINIT_OPTIONS=[" + " ".join(options) + " ]",
           "actual": old_actual.strip(), "real_kernel_module_syscalls_forwarded": False, "board_tested": False}
    (output / "red-result.json").write_text(json.dumps(red, indent=2) + "\n")
    cases = []
    for arguments, fallback in [([], False), (["one=1"], False), (options, False), (options, True)]:
        joined = " ".join(arguments) + (" " if arguments else "")
        expected = "MOCK_FINIT_OPTIONS=[" + joined + "]\n"
        if fallback:
            expected += "MOCK_INIT_OPTIONS=[" + joined + "]\n"
        actual = module_probe(new_mock, fixture, arguments, fallback)
        if actual != expected:
            raise ValueError("New real BusyBox objects lost module options: " + repr(actual))
        cases.append({"arguments": arguments, "finit_to_init_fallback": fallback, "captured": actual.strip()})
    green = {"status": "REAL_BUSYBOX_OBJECT_MODULE_OPTIONS_PASSED", "cases": cases,
             "test_only_syscall_replacement": True, "real_kernel_module_syscalls_forwarded": False,
             "production_binary_mocked": False, "board_tested": False}
    (output / "green-result.json").write_text(json.dumps(green, indent=2) + "\n")
    after = {"config": sha(OLD_CONFIG), "old_build_config": sha(OLD / ".config"), "binary": sha(OLD / "busybox")}
    if before != after:
        raise ValueError("Original verified inputs changed")
    compiler = shutil.which("aarch64-linux-gnu-gcc")
    manifest = {
        "schema": 1, "version": "BusyBox 1.36.1", "archive_sha256": ARCHIVE_SHA,
        "original_config_sha256": OLD_CONFIG_SHA, "original_busybox_sha256": OLD_BINARY_SHA,
        "new_config_sha256": sha(new_source / ".config"), "config_changes": changes,
        "complete_config_diff": (output / "config.diff").relative_to(ROOT).as_posix(),
        "complete_config_diff_sha256": sha(output / "config.diff"),
        "artifact": {"path": production.relative_to(ROOT).as_posix(), "bytes": production.stat().st_size,
                     "sha256": sha(production), "static_aarch64": True},
        "source_script_sha256": sha(Path(__file__)),
        "modutils_source_sha256": sha(new_source / "modutils/modutils.c"),
        "insmod_source_sha256": sha(new_source / "modutils/insmod.c"),
        "license_sha256": sha(new_source / "LICENSE"),
        "configure_argv": configure, "compile_argv": compile_command,
        "compiler_version": subprocess.check_output([compiler, "--version"], text=True).strip(),
        "parser_symbol_in_new_module_object_and_linked_busybox": True,
        "qemu_shell_passed": True, "applet_inventory_unchanged": True,
        "module_argument_red_observed": True, "module_argument_mock_cases_passed": len(cases),
        "module_argument_evidence": {"red": (output / "red-result.json").relative_to(ROOT).as_posix(),
                                     "green": (output / "green-result.json").relative_to(ROOT).as_posix()},
        "mock_relinks": mock_links, "real_kernel_module_syscalls_forwarded": False,
        "original_inputs_unchanged": True, "board_tested": False,
        "board_module_parameter_behavior_tested": False,
    }
    with manifest_path.open("x") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    print(json.dumps({key: value for key, value in manifest.items() if key != "mock_relinks"}, indent=2))


if __name__ == "__main__":
    main()
