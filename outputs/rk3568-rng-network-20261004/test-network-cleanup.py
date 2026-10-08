#!/usr/bin/env python3
"""Run the actual cleanup script with ordinary fixtures and mocked operations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "linux-network-cleanup.sh"
RELEASE = "5.10.160-rt89-g9f9e9d18574d-dirty"

MOCKS = r'''
log() {
    printf '%s\n' "$*" >&3
}
uname() {
    log "uname $*"
    test "$1" = -r
    printf '%s\n' "$fixture_release"
}
cat() {
    log "cat $*"
    case "$1" in
        "$fixture_state/server.pid")
            command /bin/cat "$1"
            if test -f "$fixture/cat-fail"; then
                return 1
            fi
            ;;
        "$fixture_state/wpa.pid"|"$fixture_pm0")
            command /bin/cat "$1"
            ;;
        *) return 99 ;;
    esac
}
readlink() {
    log "readlink $*"
    test "$1" = -f
    case "$2" in
        "$fixture_proc/31001/exe")
            command /bin/cat "$2"
            if test -f "$fixture/readlink-fail"; then
                return 1
            fi
            ;;
        "$fixture_proc/31002/exe")
            command /bin/cat "$2"
            ;;
        *) return 99 ;;
    esac
}
kill() {
    log "kill $*"
    test "$1" = -TERM
    case "$2" in
        31001)
            if test -f "$fixture/kill-fail-once"; then
                command /bin/rm -f "$fixture/kill-fail-once"
                return 1
            fi
            ;;
        31002) ;;
        *) return 99 ;;
    esac
    command /bin/rm -f "$fixture_proc/$2/exe"
    command /bin/rmdir "$fixture_proc/$2"
}
sleep() {
    log "sleep $*"
    # No host waiting or real process management.
    return 0
}
rm() {
    log "rm $*"
    test "$1" = -f
    shift
    for target in "$@"; do
        case "$target" in
            "$fixture_state"/*|"$fixture_credential"|"$fixture_pm0") ;;
            *) return 99 ;;
        esac
    done
    if [ "$1" = "$fixture_credential" ] && test -f "$fixture/credential-fail-once"; then
        command /bin/rm -f "$fixture/credential-fail-once"
        return 1
    fi
    command /bin/rm -f "$@"
}
ip() {
    log "ip $*"
    case "$*" in
        'addr flush dev wlan0'|'link set wlan0 down') return 0 ;;
        *) return 99 ;;
    esac
}
rmmod() {
    log "rmmod $*"
    test "$1" = bcmdhd
    if test -f "$fixture/module-fail-once"; then
        command /bin/rm -f "$fixture/module-fail-once"
        return 1
    fi
    : > "$fixture_proc/modules"
    command /bin/rm -f "$fixture_wlan"
}
ps() {
    log ps
    for pid in 31001 31002; do
        if test -d "$fixture_proc/$pid"; then
            printf '%s mock ' "$pid"
            command /bin/cat "$fixture_proc/$pid/exe"
        fi
    done
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


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_path(path, boundary):
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(boundary) or path == boundary:
        raise ValueError("Path outside permitted test boundary: " + str(path))
    current = boundary
    for part in path.relative_to(boundary).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink path component: " + str(current))
    return path


def config_path(source):
    candidates = [path for path in ["/lib/firmware/rtctrl-pm0.txt", "/lib/firmware/config.txt"] if path in source]
    if len(candidates) != 1:
        raise ValueError("Need exactly one recognized owned PM configuration path")
    return candidates[0]


def setup(output, name, flag=None, executable="/bin/network-helper", pid="31001", pm0="PM=0"):
    folder = output / name
    folder.mkdir()
    state = folder / "state"
    proc = folder / "proc"
    state.mkdir()
    proc.mkdir()
    for process, binary in [(31001, executable), (31002, "/bin/wpa_supplicant")]:
        process_dir = proc / str(process)
        process_dir.mkdir()
        (process_dir / "exe").write_text(binary + "\n")
    (proc / "modules").write_text("bcmdhd 123456 0 - Live 0x0\n")
    (state / "server.pid").write_text(pid + "\n")
    (state / "wpa.pid").write_text("31002\n")
    for item in ["mode", "wpa.log", "server.log", "transfer.bin", "pm0-owned"]:
        (state / item).write_text("mock owned state\n")
    (folder / "wpa.conf").write_text("mock-no-credentials\n")
    (folder / "wlan0").write_text("mock interface\n")
    (folder / "pm0.txt").write_text(pm0 + "\n")
    if flag:
        (folder / flag).touch()
    return folder


def run_script(folder, source, attempt=1):
    state = folder / "state"
    proc = folder / "proc"
    credential = folder / "wpa.conf"
    wlan = folder / "wlan0"
    pm0 = folder / "pm0.txt"
    transformations = {
        "state=/tmp/rtctrl-rng-network-20261004": "state=" + shlex.quote(str(state)),
        "/proc/": str(proc) + "/",
        "/tmp/wpa.conf": str(credential),
        "/sys/class/net/wlan0": str(wlan),
        config_path(source): str(pm0),
    }
    transformed = source
    for old, new in transformations.items():
        assert old in source, "Cleanup path contract changed: " + old
        transformed = transformed.replace(old, new)
    prefix = "#!/bin/sh\nset -eu\n"
    prefix += "exec 3> " + shlex.quote(str(folder / ("trace-" + str(attempt) + ".txt"))) + "\n"
    for name, value in {
        "fixture": folder, "fixture_state": state, "fixture_proc": proc,
        "fixture_credential": credential, "fixture_wlan": wlan, "fixture_pm0": pm0,
        "fixture_release": RELEASE,
    }.items():
        prefix += name + "=" + shlex.quote(str(value)) + "\n"
    temporary_script = folder / ("exercise-" + str(attempt) + ".sh")
    temporary_script.write_text(prefix + MOCKS + transformed)
    result = subprocess.run(["/bin/sh", str(temporary_script)], capture_output=True, text=True, timeout=10)
    trace = (folder / ("trace-" + str(attempt) + ".txt")).read_text().splitlines()
    aliases = {str(state): "STATE", str(proc): "PROC", str(credential): "CREDENTIAL",
               str(wlan): "WLAN", str(pm0): "PM0"}
    for old, new in aliases.items():
        trace = [line.replace(old, new) for line in trace]
    assert not result.stderr, result.stderr
    assert not any("RESET" in line for line in trace), trace
    assert not (proc / "sysrq-trigger").exists()
    return {
        "attempt": attempt, "exit_code": result.returncode, "stdout": result.stdout.strip(),
        "commands": trace, "credential_remaining": credential.exists(),
        "server_remaining": (proc / "31001").exists(), "wpa_remaining": (proc / "31002").exists(),
        "module_remaining": bool((proc / "modules").read_text()), "interface_remaining": wlan.exists(),
        "pm0_remaining": pm0.exists(), "state_files": sorted(path.name for path in state.iterdir()),
    }


def failed(result, marker):
    assert result["exit_code"] == 1, result
    assert "WIFI_CLEANUP_INCOMPLETE_STAY_IN_LINUX" in result["stdout"], result
    assert marker not in result["stdout"], result


def succeeded(result, marker):
    assert result["exit_code"] == 0 and result["stdout"] == marker, result
    assert not result["credential_remaining"] and not result["server_remaining"] and not result["wpa_remaining"], result
    assert not result["module_remaining"] and not result["interface_remaining"] and not result["pm0_remaining"], result
    assert not result["state_files"], result


def later_cleanup_attempted(result):
    trace = result["commands"]
    required = ["kill -TERM 31002", "rm -f CREDENTIAL", "ip addr flush dev wlan0",
                "ip link set wlan0 down", "rmmod bcmdhd"]
    positions = [trace.index(command) for command in required]
    assert positions == sorted(positions), trace
    assert not result["wpa_remaining"] and not result["module_remaining"] and not result["interface_remaining"], result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--evidence-dir", type=Path, default=HERE / "build/cleanup-tests")
    args = parser.parse_args()
    source_path = checked_path(args.source, HERE)
    if not source_path.is_file():
        parser.error("Need an ordinary cleanup source file")
    source_bytes = source_path.read_bytes()
    source = source_bytes.decode()
    assert b"\r" not in source_bytes
    assert not re.search(r"\b(?:reboot|poweroff)\b|/proc/sysrq-trigger|sys\.powerctl", source)
    markers = re.findall(r"^echo ([A-Z0-9_]+)$", source, re.M)
    completion = markers[-1]
    output = checked_path(args.evidence_dir, HERE / "build")
    if output.exists() or output.is_symlink():
        raise ValueError("Refusing existing cleanup test evidence")
    if (HERE / "build").is_symlink():
        raise ValueError("Refusing symlink build parent")
    output.mkdir(parents=True)

    # Minimal wrong baseline: if ! suppresses errexit in the called function.
    # A readlink failure that happens to print a plausible identity must still stop.
    guard = 'actual=$(readlink -f "/proc/$pid/exe") || return 1'
    assert source.count(guard) == 1
    wrong = source.replace(guard, 'actual=$(readlink -f "/proc/$pid/exe")')
    red_folder = setup(output, "red-errexit-guard-removed", flag="readlink-fail")
    red = run_script(red_folder, wrong)
    observed_red = "kill -TERM 31001" in red["commands"] and red["exit_code"] == 0
    assert observed_red, "The failure test did not expose the wrong baseline"
    red_evidence = {"status": "EXPECTED_RED_FAILURE_OBSERVED", "mutation": "Remove only explicit readlink || return 1 guard",
                    "expected": "No server kill; exit 1; continue independent cleanup",
                    "actual": red, "original_source_sha256": digest(source_bytes),
                    "wrong_source_sha256": digest(wrong.encode()), "board_tested": False}
    (output / "red-result.json").write_text(json.dumps(red_evidence, indent=2) + "\n")

    results = []
    folder = setup(output, "green-success")
    success = run_script(folder, source)
    succeeded(success, completion)
    results.append({"case": "success", "result": success})

    folder = setup(output, "green-stop-failure-retry", flag="kill-fail-once")
    first = run_script(folder, source)
    failed(first, completion)
    later_cleanup_attempted(first)
    assert first["server_remaining"] and "server.pid" in first["state_files"], first
    assert first["commands"].index("kill -TERM 31001") < first["commands"].index("kill -TERM 31002"), first
    retry = run_script(folder, source, 2)
    succeeded(retry, completion)
    assert "kill -TERM 31001" in retry["commands"] and "kill -TERM 31002" not in retry["commands"], retry
    results.append({"case": "first_stop_failure_continues_cleanup_and_retry_succeeds", "first": first, "retry": retry})

    folder = setup(output, "green-ownership-mismatch", executable="/bin/unowned-process")
    mismatch = run_script(folder, source)
    failed(mismatch, completion)
    later_cleanup_attempted(mismatch)
    assert "kill -TERM 31001" not in mismatch["commands"] and mismatch["server_remaining"], mismatch
    assert "PROCESS_OWNERSHIP_MISMATCH" in mismatch["stdout"], mismatch
    results.append({"case": "identity_mismatch_never_killed", "result": mismatch})

    for flag in ["readlink-fail", "cat-fail"]:
        folder = setup(output, "green-" + flag, flag=flag)
        failure = run_script(folder, source)
        failed(failure, completion)
        later_cleanup_attempted(failure)
        assert "kill -TERM 31001" not in failure["commands"] and failure["server_remaining"], failure
        results.append({"case": flag + "_explicit_guard_survives_if_not_errexit", "result": failure})

    for flag in ["credential-fail-once", "module-fail-once"]:
        folder = setup(output, "green-" + flag, flag=flag)
        first = run_script(folder, source)
        failed(first, completion)
        assert "ip link set wlan0 down" in first["commands"] and "rmmod bcmdhd" in first["commands"], first
        retry = run_script(folder, source, 2)
        succeeded(retry, completion)
        results.append({"case": flag + "_retry_succeeds", "first": first, "retry": retry})

    for invalid_pid in ["0", "1", "not-a-pid"]:
        folder = setup(output, "green-invalid-pid-" + invalid_pid, pid=invalid_pid)
        result = run_script(folder, source)
        failed(result, completion)
        later_cleanup_attempted(result)
        assert "kill -TERM 31001" not in result["commands"], result
        assert "kill -TERM " + invalid_pid not in result["commands"], result
        results.append({"case": "invalid_pid_" + invalid_pid + "_never_killed", "result": result})

    folder = setup(output, "green-pm0-ownership-mismatch", pm0="PM=1")
    result = run_script(folder, source)
    failed(result, completion)
    assert result["pm0_remaining"] and "pm0-owned" in result["state_files"], result
    assert "rm -f PM0" not in result["commands"], result
    results.append({"case": "pm0_content_mismatch_preserved", "result": result})

    assert source_path.read_bytes() == source_bytes, "Actual source changed during tests"
    summary = {
        "status": "NETWORK_CLEANUP_HOST_TESTS_PASSED", "green_cases": len(results),
        "source_file": source_path.relative_to(HERE).as_posix(),
        "source_sha256": digest(source_bytes), "completion_marker": completion,
        "owned_configuration_path": config_path(source), "mock_configuration_bytes": 5,
        "red_failure_observed": True, "red_record": "red-result.json",
        "path_transformations": ["state directory", "/proc paths", "/tmp/wpa.conf", "/sys/class/net/wlan0", config_path(source)],
        "mocked_operations": ["uname", "cat", "readlink", "kill", "sleep", "rm", "ip", "rmmod", "ps"],
        "real_process_signal_or_network_or_module_operations": False,
        "reset_requested": False, "board_tested": False, "results": results,
    }
    (output / "green-result.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, indent=2))


if __name__ == "__main__":
    main()
