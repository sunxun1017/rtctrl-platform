#!/usr/bin/env python3
"""Test v3 cleanup/reset scripts and retain v2 false-restoration red evidence."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build/runtime-v2-tests"
RELEASE = "5.10.160-rt89-g9f9e9d18574d-dirty"
CLEANED = ""
READY = "RAM_ONLY_RESOURCES_RELEASED"
RAM_MOUNTS = ("rootfs / rootfs rw 0 0\n"
              "devtmpfs /dev devtmpfs rw 0 0\n"
              "proc /proc proc rw 0 0\n"
              "sysfs /sys sysfs rw 0 0\n"
              "tmpfs /tmp tmpfs rw 0 0\n")

MOCKS = r'''
log() {
    printf '%s\n' "$*" >&3
}
fail_once() {
    if test -f "$fixture/fail-$1"; then
        command /bin/rm -f "$fixture/fail-$1"
        return 0
    fi
    return 1
}
uname() {
    log "uname $*"
    test "$*" = -r || return 99
    printf '%s\n' "$fixture_release"
}
cat() {
    log "cat $*"
    test "$#" = 1 || return 99
    case "$1" in
        "$fixture/proc/modules")
            if fail_once module-read; then
                return 7
            fi
            ;;
        "$fixture/proc/mounts")
            if fail_once mounts-read; then
                return 7
            fi
            ;;
        "$fixture/firmware-path")
            if fail_once path-read; then
                return 7
            fi
            ;;
        "$fixture/state/firmware-class-path"|"$fixture/config.txt") ;;
        *) return 99 ;;
    esac
    command /bin/cat "$1"
    if test "$1" = "$fixture/firmware-path" && test -f "$fixture/getter-adds-newline"; then
        # Model the real param_get_string show suffix, not the raw parameter buffer.
        printf '\n'
    fi
}
ps() {
    log ps
    if fail_once ps-read; then
        return 7
    fi
    command /bin/cat "$fixture/processes"
}
losetup() {
    log "losetup $*"
    test "$*" = -a || return 99
    if fail_once loops-read; then
        return 7
    fi
    command /bin/cat "$fixture/loops"
}
hexdump() {
    log "hexdump $*"
    test "$#" = 4 && test "$1" = -v && test "$2" = -e || return 99
    test "$3" = '1/1 "%02x"' && test "$4" = "$fixture/firmware-path" || return 99
    if fail_once firmware-show; then
        return 7
    fi
    # This ordinary file represents raw kps->string; the real getter adds one newline.
    (
        command /bin/cat "$fixture/firmware-path"
        printf '\n'
    ) | command /usr/bin/od -An -v -tx1 | command /usr/bin/tr -d ' \n'
}
ip() {
    log "ip $*"
    case "$*" in
        'addr flush dev wlan0')
            if fail_once flush; then
                return 1
            fi
            ;;
        'link set wlan0 down')
            if fail_once down; then
                return 1
            fi
            ;;
        *) return 99 ;;
    esac
}
rmmod() {
    log "rmmod $*"
    test "$*" = bcmdhd || return 99
    if fail_once rmmod; then
        return 1
    fi
    : > "$fixture/proc/modules"
    command /bin/rm -f "$fixture/wlan0"
}
rm() {
    log "rm $*"
    for target in "$@"; do
        case "$target" in
            "$fixture/config.txt"|"$fixture/state/config-owned"|\
            "$fixture/state/firmware-path-owned"|"$fixture/state/firmware-class-path") ;;
            *) return 99 ;;
        esac
    done
    command /bin/rm "$@"
}
ls() {
    log "ls $*"
    if test "$1" = -l; then
        # The guard's explicitly best-effort FD snapshot has no host processes.
        return 0
    fi
    test "$#" = 2 && test "$1" = -A && test "$2" = "$fixture/state" || return 99
    command /bin/ls -A "$2"
}
grep() {
    log "grep $*"
    # Only ordinary fixture files or stdin are passed by the transformed scripts.
    command /bin/grep "$@"
}
reboot() {
    log FORBIDDEN_RESET
    return 99
}
poweroff() {
    log FORBIDDEN_RESET
    return 99
}
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_output(path):
    require(path == BUILD or BUILD in path.parents, "test output escaped owned directory")
    current = HERE
    for part in path.relative_to(HERE).parts:
        require(part not in ["", ".", ".."], "invalid output component")
        current = current / part
        require(not current.is_symlink(), "symlink output component refused")


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def fixture(output, name, loaded=False, previous="", path_owned=False):
    folder = output / name
    folder.mkdir()
    (folder / "proc").mkdir()
    (folder / "state").mkdir()
    (folder / "proc/modules").write_text("bcmdhd 12345 0 - Live 0x0\n" if loaded else "")
    (folder / "proc/mounts").write_text(RAM_MOUNTS)
    (folder / "processes").write_text("1 root /bin/sh /init\n")
    (folder / "loops").write_text("")
    (folder / "firmware-path").write_text("/lib/firmware" if path_owned else previous)
    if loaded:
        (folder / "wlan0").touch()
        (folder / "config.txt").write_text("PM=0\nband=a\n")
        (folder / "state/config-owned").touch()
        if path_owned:
            (folder / "state/firmware-path-owned").touch()
            (folder / "state/firmware-class-path").write_text(previous + "\n")
    return folder


def exercise(folder, source, name, attempt=1):
    transformations = {
        "/tmp/rtctrl-motor-module-options": str(folder / "state"),
        "/tmp/wpa.conf": str(folder / "wpa.conf"),
        "/sys/class/net/wlan0": str(folder / "wlan0"),
        "/lib/firmware/config-uart-stage.txt": str(folder / "config.txt"),
        "/sys/module/firmware_class/parameters/path": str(folder / "firmware-path"),
        "/proc/modules": str(folder / "proc/modules"),
        "/proc/mounts": str(folder / "proc/mounts"),
        "/proc/[0-9]*/fd/*": str(folder / "proc/[0-9]*/fd/*"),
    }
    transformed = source
    applied = {}
    for old, new in transformations.items():
        if old in transformed:
            transformed = transformed.replace(old, new)
            applied[old] = new
    require(re.search(r"(?<![A-Za-z0-9_/])/(proc|sys)/", transformed) is None
            and "sysrq" not in transformed, "unmapped kernel path in test copy")
    prefix = "#!/bin/sh\nset -eu\nexport PATH=/nonexistent-mock-commands\n"
    prefix += "exec 3> " + shlex.quote(str(folder / f"{name}-trace-{attempt}.txt")) + "\n"
    prefix += "fixture=" + shlex.quote(str(folder)) + "\n"
    prefix += "fixture_release=" + shlex.quote(RELEASE) + "\n"
    path = folder / f"{name}-actual-{attempt}.sh"
    with path.open("x") as stream:
        stream.write(prefix + MOCKS + transformed)
    result = subprocess.run(["/bin/sh", str(path)], capture_output=True, text=True, timeout=10)
    trace = (folder / f"{name}-trace-{attempt}.txt").read_text().splitlines()
    require(not any("FORBIDDEN_RESET" in line for line in trace), "reset command attempted")
    require(result.stderr == "", "unexpected mock diagnostic: " + result.stderr)
    record = {
        "script": name, "attempt": attempt, "exit_code": result.returncode,
        "stdout": result.stdout, "commands": [line.replace(str(folder), "FIXTURE") for line in trace],
        "transformations": applied,
        "remaining_state": sorted(path.name for path in (folder / "state").iterdir()),
        "config_remaining": (folder / "config.txt").exists(),
        "interface_remaining": (folder / "wlan0").exists(),
        "module_remaining": (folder / "proc/modules").read_text() != "",
        "firmware_path": (folder / "firmware-path").read_text().rstrip("\n"),
        "firmware_path_raw_hex": (folder / "firmware-path").read_bytes().hex(),
        "reset_attempted": False,
    }
    write_json(folder / f"{name}-result-{attempt}.json", record)
    return record


def cleanup_success(record, previous=""):
    require(record["exit_code"] == 0 and record["stdout"] == CLEANED + "\n",
            "cleanup did not finish successfully")
    require(not record["remaining_state"] and not record["config_remaining"]
            and not record["module_remaining"] and not record["interface_remaining"],
            "cleanup left an owned resource")
    require(record["firmware_path_raw_hex"] == previous.encode().hex(),
            "v3 cleanup changed the firmware parameter bytes")


def cleanup_failed(record):
    require(record["exit_code"] == 1 and CLEANED not in record["stdout"]
            and "MODULE_CLEANUP_INCOMPLETE_STAY_IN_LINUX" in record["stdout"],
            "cleanup failure was reported as successful")


def guard_failed(record):
    require(record["exit_code"] != 0 and READY not in record["stdout"],
            "reset guard accepted unknown or residual state")


def guard_success(record):
    require(record["exit_code"] == 0 and record["stdout"].endswith(READY + "\n"),
            "clean RAM-only state was rejected")


def main():
    global CLEANED
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="v1")
    parser.add_argument("--cleanup-source", type=Path, default=HERE / "linux-module-cleanup-v3.sh")
    arguments = parser.parse_args()
    require(re.fullmatch(r"v[1-9][0-9]*", arguments.revision) is not None, "invalid revision")
    output = BUILD / arguments.revision
    checked_output(output)
    require(not os.path.lexists(output), "refusing existing evidence directory")
    output.mkdir(parents=True)
    cleanup_path = arguments.cleanup_source.absolute()
    require(cleanup_path.parent == HERE and not cleanup_path.is_symlink(), "invalid cleanup source")
    sources = {name: (HERE / name).read_text() for name in [
        cleanup_path.name, "linux-module-options-v3.sh", "linux-module-cleanup-v2.sh",
        "linux-return-guard.sh", "linux-return-guard-v3.sh",
        "linux-module-cleanup.sh",
    ]}
    hashes = {name: digest((HERE / name).read_bytes()) for name in sources}
    cleanup = sources[cleanup_path.name]
    guard = sources["linux-return-guard.sh"]
    require(guard == sources["linux-return-guard-v3.sh"], "actual board guard copy differs")
    require("firmware_class" not in cleanup and "firmware-path-owned" not in cleanup,
            "v3 cleanup unexpectedly mutates global firmware path")
    markers = re.findall(r"^echo (MODULE_[A-Z_]*RELEASED)$", cleanup, re.MULTILINE)
    require(len(markers) == 1, "cleanup success marker contract changed")
    CLEANED = markers[0]

    # Execute the actual old cleanup with a failed first flush: independent cleanup is lost.
    red_folder = fixture(output, "red-old-cleanup", loaded=True)
    (red_folder / "fail-flush").touch()
    red_cleanup = exercise(red_folder, sources["linux-module-cleanup.sh"], "old-cleanup")
    require(red_cleanup["exit_code"] != 0 and red_cleanup["config_remaining"]
            and red_cleanup["module_remaining"]
            and not any(line.startswith("rmmod ") for line in red_cleanup["commands"]),
            "old cleanup red failure not observed")

    # These exact pre-v2 guard lines were captured and tested in the preceding review.
    old_guards = [
        ("losetup-read-error", 'test -z "$(losetup -a)"', "losetup() { return 7; }\n"),
        ("mount-read-error", "test -z \"$(grep -vE '^[^ ]+ [^ ]+ (rootfs|devtmpfs|proc|sysfs|tmpfs) ' /proc/mounts || true)\"",
         "grep() { return 2; }\n"),
    ]
    red_guards = []
    for label, fragment, mock in old_guards:
        script = mock + "set -eu\n" + fragment + "\nprintf 'OLD_GUARD_ACCEPTED\\n'\n"
        result = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, timeout=5)
        require(result.returncode == 0 and result.stdout == "OLD_GUARD_ACCEPTED\n",
                "historical guard red failure not observed")
        red_guards.append({"case": label, "historical_exact_fragment": fragment,
                           "exit_code": result.returncode, "stdout": result.stdout,
                           "provenance": "pre-v2 review captured guard fragments"})
    # Execute the actual v2 restoration logic. A kernel show adds another newline.
    path_red = fixture(output, "red-v2-firmware-show-newline", loaded=True,
                       previous="", path_owned=True)
    (path_red / "getter-adds-newline").touch()
    expected_show = b"\n"
    result = exercise(path_red, sources["linux-module-cleanup-v2.sh"], "v2-cleanup")
    actual_show = (path_red / "firmware-path").read_bytes() + b"\n"
    require(result["exit_code"] == 0
            and "MODULE_CONFIG_AND_FIRMWARE_PATH_RELEASED" in result["stdout"]
            and actual_show == b"\n\n" and actual_show != expected_show,
            "v2 shell-substitution false-restoration red was not observed")
    path_red_record = {"actual_v2_script_result": result, "expected_show_hex": expected_show.hex(),
                       "actual_show_hex": actual_show.hex(), "raw_bytes_restored": False,
                       "getter_mock": "kernel param_get_string appends one newline",
                       "kernel_params_sha256": digest((HERE.parents[1] / "third_party/linux-rk3588/kernel/params.c").read_bytes()),
                       "board_tested": False}
    write_json(output / "v2-path-newline-red.json", path_red_record)
    write_json(output / "red-result.json", {"status": "EXPECTED_RED_RUNTIME_FAILURES_OBSERVED",
                                            "old_cleanup": red_cleanup, "old_guard_fragments": red_guards,
                                            "v2_path_restoration": path_red_record,
                                            "board_tested": False})

    cases = []
    folder = fixture(output, "cleanup-success", loaded=True)
    result = exercise(folder, cleanup, "cleanup")
    cleanup_success(result)
    guard_success(exercise(folder, guard, "guard"))
    cases.append({"case": "normal-cleanup-and-guard", "passed": True})

    for flag in ["flush", "down", "rmmod"]:
        folder = fixture(output, "cleanup-" + flag + "-fails", loaded=True)
        (folder / ("fail-" + flag)).touch()
        result = exercise(folder, cleanup, "cleanup")
        cleanup_failed(result)
        commands = result["commands"]
        require("ip addr flush dev wlan0" in commands
                and "ip link set wlan0 down" in commands and "rmmod bcmdhd" in commands,
                "failed first operation skipped a later network cleanup")
        require(not result["config_remaining"] and not result["remaining_state"]
                and result["firmware_path_raw_hex"] == "",
                "network cleanup failure skipped independent config/path cleanup")
        if flag == "rmmod":
            guard_failed(exercise(folder, guard, "guard"))
        retry = exercise(folder, cleanup, "cleanup", attempt=2)
        cleanup_success(retry)
        guard_success(exercise(folder, guard, "guard", attempt=2))
        require(not any(line.startswith("rm ") for line in retry["commands"]),
                "retry deleted already released config/path resources")
        cases.append({"case": flag + "-failure-continues-independent-cleanup-and-retry", "passed": True})

    folder = fixture(output, "cleanup-module-read-error", loaded=True)
    (folder / "fail-module-read").touch()
    result = exercise(folder, cleanup, "cleanup")
    cleanup_failed(result)
    require(not result["config_remaining"] and not result["remaining_state"]
            and result["firmware_path_raw_hex"] == "",
            "module metadata failure skipped independent cleanup")
    guard_failed(exercise(folder, guard, "guard"))
    cleanup_success(exercise(folder, cleanup, "cleanup", attempt=2))
    cases.append({"case": "module-read-error-cleans-independent-resources", "passed": True})

    folder = fixture(output, "v3-default-firmware-path-unchanged", loaded=True, previous="")
    result = exercise(folder, cleanup, "cleanup")
    cleanup_success(result, "")
    require(not any("firmware-path" in line for line in result["commands"]),
            "v3 cleanup unexpectedly accessed global firmware path")
    cases.append({"case": "v3-default-firmware-path-bytes-unchanged", "passed": True})

    for flag in ["loops-read", "mounts-read", "module-read", "ps-read", "firmware-show"]:
        folder = fixture(output, "guard-" + flag + "-fails")
        (folder / ("fail-" + flag)).touch()
        result = exercise(folder, guard, "guard")
        guard_failed(result)
        require(result["exit_code"] == 7, "metadata failure exit code not preserved")
        cases.append({"case": flag + "-failure-refuses-reset", "passed": True})

    for label, target, value in [
        ("nonram-ext4-mount", "proc/mounts", RAM_MOUNTS + "/dev/loop0 /mnt/root ext4 ro 0 0\n"),
        ("empty-mount-read", "proc/mounts", ""),
        ("residual-module-later-line", "proc/modules", "other 1 0 - Live 0x0\nbcmdhd 1 0 - Live 0x0\n"),
        ("residual-loop", "loops", "/dev/loop0: [001]:1 (fixture.img)\n"),
        ("residual-network-process", "processes", "42 root /bin/wpa_supplicant\n"),
        ("firmware-extra-newline", "firmware-path", "\n"),
    ]:
        folder = fixture(output, "guard-" + label)
        (folder / target).write_text(value)
        guard_failed(exercise(folder, guard, "guard"))
        cases.append({"case": label + "-refuses-reset", "passed": True})

    guard_success(exercise(fixture(output, "guard-clean-ram"), guard, "guard"))
    cases.append({"case": "clean-ram-guard-passes", "passed": True})
    for name, expected in hashes.items():
        require(digest((HERE / name).read_bytes()) == expected, "source changed during tests")
    record = {"status": "RUNTIME_V3_REAL_SCRIPT_MOCK_TESTS_PASSED", "cases_passed": len(cases),
              "cases": cases, "actual_script_sha256": hashes,
              "cleanup_source": cleanup_path.name,
              "test_script_sha256": digest(Path(__file__).read_bytes()),
              "options_setup_runtime_exercised": False,
              "cleanup_and_guard_full_scripts_exercised": True,
              "historical_guard_red_is_captured_exact_fragments": True,
              "real_host_module_network_process_operations": False,
              "board_tested": False, "physical_uart_opened": False}
    write_json(output / "green-result.json", record)
    print(record["status"], record["cases_passed"])


if __name__ == "__main__":
    main()
