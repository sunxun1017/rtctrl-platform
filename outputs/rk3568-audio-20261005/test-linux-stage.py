#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Execute the actual Linux stage shell script with private paths and fake mounts."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "linux-stage.sh"
RESULT = HERE / "build/stage-tests-v1.json"
MARKER = "AUDIO_INPUTS_IN_RAM_CACHE_RELEASED"
PID_SHA = "514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1"
FILES = ["audio.dtb", "alsa-inspect", "snd-soc-rk817.ko", "linux-interface.sh",
         "linux-return-guard.sh"]
SHIM = r'''#!/usr/bin/python3
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

command = Path(sys.argv[0]).name
arguments = sys.argv[1:]
root = Path(os.environ["STAGE_FIXTURE"])
scenario = os.environ["STAGE_SCENARIO"]
log_path = root / "calls.jsonl"
previous = [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []
event = {"command": command, "arguments": arguments, "cwd": os.getcwd()}
with log_path.open("a") as log:
    log.write(json.dumps(event) + "\n")

if command == "uname":
    print("wrong-kernel" if scenario == "kernel-mismatch" else "5.10.160-rt89-g9f9e9d18574d-dirty")
    sys.exit(0)
if command == "readlink":
    print("/bin/other" if scenario == "pid-exe-mismatch" else "/bin/busybox")
    sys.exit(0)
if command == "hexdump":
    if arguments[:-1] != ["-v", "-e", '1/1 "%02x"']:
        print("unexpected hexdump arguments", file=sys.stderr)
        sys.exit(2)
    sys.stdout.write(Path(arguments[-1]).read_bytes().hex())
    sys.exit(0)
if command == "sha256sum":
    if arguments == [str(root / "proc/1/exe")]:
        digest = "bad" if scenario == "pid-sha-mismatch" else os.environ["STAGE_PID_SHA"]
        print(digest + "  " + arguments[0])
        sys.exit(0)
    count = sum(item["command"] == "sha256sum" and item["arguments"] == ["-c", "upload.sha256"]
                for item in previous) + 1
    if (scenario == "first-sha-fail" and count == 1 or
        scenario == "second-sha-fail" and count == 2):
        print("injected SHA verification failure", file=sys.stderr)
        sys.exit(1)
    sys.exit(subprocess.call(["/usr/bin/sha256sum", *arguments]))
if command == "cp":
    if scenario == "cp-fail":
        shutil.copy2(arguments[0], Path(arguments[-1]) / Path(arguments[0]).name)
        print("injected partial copy failure", file=sys.stderr)
        sys.exit(1)
    sys.exit(subprocess.call(["/usr/bin/cp", *arguments]))
if command == "mount":
    expected = ["-t", "ext4", "-o", "ro,noload", str(root / "dev/mmcblk0p12"), str(root / "cache")]
    if arguments != expected:
        print("unsafe mount arguments", file=sys.stderr)
        sys.exit(2)
    if scenario == "mount-fail":
        print("injected mount failure", file=sys.stderr)
        sys.exit(1)
    target = root / "cache/rtctrl-audio-20261005"
    target.mkdir()
    for name in json.loads(os.environ["STAGE_FILES"]):
        (target / name).write_text("fixture payload for " + name + "\n")
    entries = []
    for name in json.loads(os.environ["STAGE_FILES"]):
        digest = hashlib.sha256((target / name).read_bytes()).hexdigest()
        entries.append(digest + "  " + name + "\n")
    (target / "upload.sha256").write_text("".join(entries))
    (root / "mounted-state").write_text("mounted")
    sys.exit(0)
if command == "umount":
    cache = root / "cache"
    cwd = Path.cwd()
    if arguments != [str(cache)] or cwd == cache or cache in cwd.parents:
        print("unmount while cwd inside cache or incorrect target", file=sys.stderr)
        sys.exit(2)
    if scenario == "umount-fail":
        print("injected unmount failure", file=sys.stderr)
        sys.exit(1)
    if not (root / "mounted-state").exists():
        print("duplicate unmount", file=sys.stderr)
        sys.exit(2)
    (root / "mounted-state").unlink()
    sys.exit(0)
print("unexpected shim command", file=sys.stderr)
sys.exit(2)
'''


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def fixture(source_text, scenario):
    with tempfile.TemporaryDirectory(prefix="rtctrl-stage-fixture-") as name:
        root = Path(name)
        (root / "proc/self").mkdir(parents=True)
        (root / "proc/1").mkdir()
        (root / "dev").mkdir()
        (root / "bin").mkdir()
        uid = "Uid:\t0\t0\t0\t0\n"
        if scenario == "uid-mismatch":
            uid = "Uid:\t0\t2000\t0\t0\n"
        if scenario == "uid-malformed":
            uid = "Uid:\t0\t0\t0\n"
        (root / "proc/self/status").write_text(uid)
        command_line = b"/bin/sh\x00/init\x00"
        if scenario == "pid-cmdline-mismatch":
            command_line = b"/bin/sh\x00/other\x00"
        (root / "proc/1/cmdline").write_bytes(command_line)
        (root / "proc/1/exe").write_text("fake PID executable; its fingerprint is mocked\n")
        modules = "unexpected 100 0 - Live 0x0\n" if scenario == "residual-module" else ""
        if scenario != "modules-read-fail":
            (root / "proc/modules").write_text(modules)
        mounts = "rootfs / rootfs rw 0 0\nproc /proc proc rw 0 0\ntmpfs /tmp tmpfs rw 0 0\n"
        if scenario == "non-ram-mount":
            mounts += "/dev/mmcblk0p1 /external ext4 ro 0 0\n"
        if scenario != "mounts-read-fail":
            (root / "proc/mounts").write_text(mounts)
        if scenario == "mcu-present":
            (root / "dev/McuCom").write_text("fixture only")
        if scenario == "ram-directory-exists":
            (root / "ram").mkdir()
        replacements = {
            "/proc/self/status": str(root / "proc/self/status"),
            "/proc/1/exe": str(root / "proc/1/exe"),
            "/proc/1/cmdline": str(root / "proc/1/cmdline"),
            "/proc/modules": str(root / "proc/modules"),
            "/proc/mounts": str(root / "proc/mounts"),
            "/dev/McuCom": str(root / "dev/McuCom"),
            "/dev/mmcblk0p12": str(root / "dev/mmcblk0p12"),
            "/tmp/audio": str(root / "ram"),
            "/tmp/audio-cache": str(root / "cache")
        }
        for original in replacements:
            if original not in source_text:
                raise ValueError("Expected source path absent: " + original)
        pattern = "|".join(re.escape(original) for original in sorted(replacements, key=len, reverse=True))
        transformed = re.sub(pattern, lambda match: replacements[match.group(0)], source_text)
        script = root / "actual-stage.sh"
        script.write_text(transformed)
        shim = root / "shim.py"
        shim.write_text(SHIM)
        shim.chmod(0o700)
        for command in ["uname", "readlink", "hexdump", "sha256sum", "cp", "mount", "umount"]:
            (root / "bin" / command).symlink_to(shim)
        environment = dict(os.environ, PATH=str(root / "bin") + ":/usr/bin:/bin",
                           STAGE_FIXTURE=str(root), STAGE_SCENARIO=scenario,
                           STAGE_PID_SHA=PID_SHA, STAGE_FILES=json.dumps(FILES))
        result = subprocess.run(["/bin/sh", str(script)], env=environment, cwd=root,
                                capture_output=True, text=True, timeout=10)
        log_path = root / "calls.jsonl"
        calls = [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []
        mount_calls = [call for call in calls if call["command"] == "mount"]
        umount_calls = [call for call in calls if call["command"] == "umount"]
        expected_mount = ["-t", "ext4", "-o", "ro,noload", str(root / "dev/mmcblk0p12"), str(root / "cache")]
        safe_mount = all(call["arguments"] == expected_mount for call in mount_calls)
        released_cwd = all(not Path(call["cwd"]).is_relative_to(root / "cache") for call in umount_calls)
        success = scenario == "success"
        transfer_failures = ["first-sha-fail", "cp-fail", "second-sha-fail"]
        expected_mount_count = 1 if scenario in ["success", "mount-fail", "umount-fail", *transfer_failures] else 0
        expected_umount_count = 2 if scenario == "umount-fail" else 1 if scenario in ["success", *transfer_failures] else 0
        state_exists = (root / "mounted-state").exists()
        passed = (result.returncode == 0 if success else result.returncode != 0)
        passed = (passed and (MARKER in result.stdout) == success and safe_mount and released_cwd and
                  len(mount_calls) == expected_mount_count and len(umount_calls) == expected_umount_count and
                  state_exists == (scenario == "umount-fail"))
        if success:
            passed = passed and result.stdout.endswith(MARKER + "\n")
        if scenario == "cp-fail":
            passed = passed and (root / "ram/audio.dtb").exists()
        checks = [call for call in calls if call["command"] == "sha256sum" and call["arguments"] == ["-c", "upload.sha256"]]
        copies = [call for call in calls if call["command"] == "cp"]
        if scenario == "first-sha-fail":
            passed = passed and len(checks) == 1 and not copies
        if scenario == "cp-fail":
            passed = passed and len(checks) == 1 and len(copies) == 1
        if scenario == "second-sha-fail":
            passed = passed and len(checks) == 2 and len(copies) == 1
        return {"name": scenario, "passed": bool(passed), "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr, "calls": calls,
                "mount_arguments_read_only": safe_mount, "cwd_released_before_umount": released_cwd,
                "logical_mount_remains": state_exists, "expected_mount_calls": expected_mount_count,
                "expected_umount_calls": expected_umount_count,
                "transformed_script_sha256": sha_bytes(transformed.encode()),
                "path_replacements": replacements, "uid_fixture": uid,
                "pid_cmdline_hex": command_line.hex(), "modules_fixture": modules,
                "mounts_fixture": mounts}


def main():
    if RESULT.exists() or RESULT.is_symlink() or any(parent.is_symlink() for parent in RESULT.parents):
        raise ValueError("Refuse existing or symlink stage evidence")
    if SOURCE.is_symlink() or not SOURCE.is_file():
        raise ValueError("Ordinary actual stage source required")
    source = SOURCE.read_text()
    scenarios = ["success", "first-sha-fail", "cp-fail", "second-sha-fail", "mount-fail", "umount-fail",
                 "uid-mismatch", "uid-malformed", "kernel-mismatch", "pid-exe-mismatch",
                 "pid-cmdline-mismatch", "pid-sha-mismatch", "residual-module", "modules-read-fail",
                 "non-ram-mount", "mounts-read-fail", "mcu-present", "ram-directory-exists"]
    cases = [fixture(source, scenario) for scenario in scenarios]
    # Historical negative control: execute the same actual function without its
    # newly added cd / guard. The mock then returns EBUSY-equivalent failure when
    # release_cache tries to unmount while the shell still occupies cache.
    old_line = "        cd / || return 1\n"
    if source.count(old_line) != 1:
        raise ValueError("Expected actual release_cache cwd guard changed")
    old = source.replace(old_line, "", 1)
    red = fixture(old, "first-sha-fail")
    if red["passed"] or red["cwd_released_before_umount"] or not red["logical_mount_remains"]:
        raise ValueError("Old cwd behavior was not actually reproduced")
    record = {"source": str(SOURCE), "source_sha256": sha_bytes(SOURCE.read_bytes()),
              "test_sha256": sha_bytes(Path(__file__).read_bytes()), "shim_sha256": sha_bytes(SHIM.encode()),
              "cases": cases, "failures": sum(not case["passed"] for case in cases),
              "old_cwd_guard_negative_control": red,
              "negative_control_transform": "Remove exactly one release_cache cd / || return 1 line",
              "actual_script_executed": True, "real_sha256_and_copy_on_private_payloads": True,
              "kernel_and_pid_metadata_mocked": True, "real_mounts": False, "board_tested": False}
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(record, indent=2) + "\n")
    for case in cases:
        print(case["name"] + " " + ("PASS" if case["passed"] else "FAIL"))
    print("OLD_CWD_NEGATIVE_CONTROL_REPRODUCED")
    print("TOTAL_FAILURES=" + str(record["failures"]))
    raise SystemExit(int(record["failures"] != 0))


if __name__ == "__main__":
    main()
