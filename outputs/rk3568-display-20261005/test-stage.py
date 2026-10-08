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
RESULT = HERE / "build/staging-v8/test-stage.json"
MARKER = "DISPLAY_INPUTS_IN_RAM_CACHE_RELEASED"
PID_SHA = "514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1"
FILES = ["Image", "display.dtb", "initramfs.cpio.gz", "linux-inspect.sh", "linux-return-guard.sh", "prepare-android.sh", "linux-stage.sh"]
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
    if arguments == ["-f", str(root / "proc/1/exe")]:
        print("/bin/other" if scenario == "pid-exe-mismatch" else "/bin/busybox")
        sys.exit(0)
    sys.exit(subprocess.call(["/usr/bin/readlink", *arguments]))
if command == "losetup":
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
    if arguments == ["-c", "upload.sha256"] and (scenario == "first-sha-fail" and count == 1 or
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
    target = root / "cache/rtctrl-display-20261005-v1"
    target.mkdir()
    for name in json.loads(os.environ["STAGE_FILES"]):
        (target / name).write_text("fixture payload for " + name + "\n")
    entries = []
    for name in json.loads(os.environ["STAGE_FILES"]):
        digest = hashlib.sha256((target / name).read_bytes()).hexdigest()
        entries.append(digest + "  " + name + "\n")
    (target / "upload.sha256").write_text("".join(entries))
    (root / "mounted-state").write_text("mounted")
    (root / "proc/mounts").write_text("rootfs / rootfs rw 0 0\nproc /proc proc rw 0 0\n/dev/mmcblk0p12 " + str(root / "cache") + " ext4 ro,noload 0 0\n")
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
    (root / "proc/mounts").write_text("rootfs / rootfs rw 0 0\nproc /proc proc rw 0 0\n")
    (root / "cache/rtctrl-display-20261005-v1").rename(root / "released-cache-data")
    sys.exit(0)
print("unexpected shim command", file=sys.stderr)
sys.exit(2)
'''


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def fixture(source_text, scenario, check_recovery=False):
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
        (root / "proc/1/comm").write_text("init\n")
        (root / "proc/1/fd").mkdir()
        (root / "sys/module/firmware_class/parameters").mkdir(parents=True)
        (root / "sys/module/firmware_class/parameters/path").write_text("\n")
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
            "/tmp/display": str(root / "ram"),
            "/tmp/display-cache": str(root / "cache"),
            "/tmp/display-stage-attempt": str(root / "tmp/display-stage-attempt"),
            "/tmp/display-return-guard.sh": str(root / "tmp/display-return-guard.sh"),
            "/tmp/display-stage.sh": str(root / "tmp/display-stage.sh")
        }
        for original in replacements:
            if original not in source_text:
                raise ValueError("Expected source path absent: " + original)
        pattern = "|".join(re.escape(original) for original in sorted(replacements, key=len, reverse=True))
        transformed = re.sub(pattern, lambda match: replacements[match.group(0)], source_text)
        script = root / "actual-stage.sh"
        script.write_text(transformed)
        early_guard = root / "tmp/display-return-guard.sh"
        early_guard.parent.mkdir(parents=True, exist_ok=True)
        guard_text = re.sub(r"/(?:proc|sys|tmp|dev)/", lambda match: str(root) + match.group(0), (HERE / "linux-return-guard.sh").read_text())
        guard_text = guard_text.replace(str(root / "tmp/display") + "/", str(root / "ram") + "/")
        guard_text = guard_text.replace(str(root / "tmp/display-cache") + "/", str(root / "cache") + "/")
        early_guard.write_text(guard_text)
        early_stage = root / "tmp/display-stage.sh"
        early_stage.write_text(transformed)
        stage_attempt = root / "tmp/display-stage-attempt"
        stage_attempt.write_text("display-stage-v2\n" + sha_bytes(early_guard.read_bytes()) + "  " + str(early_guard) + "\n" + sha_bytes(early_stage.read_bytes()) + "  " + str(early_stage) + "\n")
        shim = root / "shim.py"
        shim.write_text(SHIM)
        shim.chmod(0o700)
        for command in ["uname", "readlink", "hexdump", "sha256sum", "cp", "mount", "umount", "losetup"]:
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
            passed = passed and (root / "ram/Image").exists()
        checks = [call for call in calls if call["command"] == "sha256sum" and call["arguments"] == ["-c", "upload.sha256"]]
        copies = [call for call in calls if call["command"] == "cp"]
        if scenario == "first-sha-fail":
            passed = passed and len(checks) == 1 and not copies
        if scenario == "cp-fail":
            passed = passed and len(checks) == 1 and len(copies) == 1
        if scenario == "second-sha-fail":
            passed = passed and len(checks) == 2 and len(copies) == 1
        recovery_record = None
        if check_recovery:
            returned = subprocess.run(["/bin/sh", str(early_guard), "--stage-rejected"], env=environment, cwd=root,
                                      capture_output=True, text=True, timeout=10)
            allowed_recovery = scenario in ["first-sha-fail", "cp-fail", "second-sha-fail", "mount-fail", "ram-directory-exists"]
            recovered = returned.returncode == 0 and "DISPLAY_STAGE_REJECTED_RAM_ONLY_RESET_READY" in returned.stdout
            passed = passed and recovered == allowed_recovery
            recovery_record = {"allowed": allowed_recovery, "exit_code": returned.returncode,
                               "stdout": returned.stdout, "stderr": returned.stderr,
                               "independent_guard_exists": early_guard.is_file(),
                               "attempt_remains": stage_attempt.is_file(),
                               "failed_stage_never_marked_complete": not (root / "ram/stage-complete").exists()}
        return {"name": ("stage to return " if check_recovery else "") + scenario, "passed": bool(passed),
                "recovery": recovery_record, "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr, "calls": calls,
                "mount_arguments_read_only": safe_mount, "cwd_released_before_umount": released_cwd,
                "logical_mount_remains": state_exists, "expected_mount_calls": expected_mount_count,
                "expected_umount_calls": expected_umount_count,
                "transformed_script_sha256": sha_bytes(transformed.encode()),
                "path_replacements": replacements, "uid_fixture": uid,
                "pid_cmdline_hex": command_line.hex(), "modules_fixture": modules,
                "mounts_fixture": mounts}


def android_fixture(scenario):
    source = HERE / "prepare-android.sh"
    with tempfile.TemporaryDirectory(prefix="display-android-fixture-") as directory:
        root = Path(directory)
        work = root / "data/local/tmp/rtctrl-display-20261005-v1"
        work.mkdir(parents=True)
        cache = root / "cache"
        cache.mkdir()
        target = cache / "rtctrl-display-20261005-v1"
        files = ["Image", "display.dtb", "initramfs.cpio.gz", "linux-inspect.sh", "linux-return-guard.sh", "prepare-android.sh", "linux-stage.sh"]
        hashes = []
        for name in files:
            path = work / name
            path.write_text("ordinary payload " + name + "\n")
            hashes.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + name + "\n")
        (work / "upload.sha256").write_text("".join(hashes))
        if scenario == "tampered input":
            (work / "Image").write_text("tampered")
        if scenario == "symlink input":
            (work / "Image").rename(work / "Image-real")
            (work / "Image").symlink_to(work / "Image-real")
        if scenario == "existing cache":
            target.mkdir()
            (target / "keep").write_text("must remain")
        if scenario == "symlink cache":
            target.symlink_to(root / "missing")
        tools = root / "tools"
        tools.mkdir()
        commands = {
            "id": "printf '%s\\n' " + ("2000" if scenario == "nonroot" else "0") + "\n",
            "uname": "printf '%s\\n' " + ("wrong" if scenario == "wrong kernel" else "4.19.232") + "\n",
            "getprop": 'case "$1" in\nro.build.version.release) printf ' + ("10" if scenario == "wrong Android" else "11") + ' ;;\nsys.boot_completed) printf ' + ("0" if scenario == "boot incomplete" else "1") + ' ;;\n*) exit 7 ;;\nesac\n',
            "df": "exit 7\n" if scenario == "df read failure" else "printf '%s\\n' 'Filesystem 1K-blocks Used Available Use% Mounted on' '/dev/disk 364504 200000 " + ("40959" if scenario == "insufficient space" else "40960") + " 55% /cache'\n",
            "sync": "exit 0\n",
            "readlink": ('printf /wrong\n' if scenario == "cache alias" else 'exec /usr/bin/readlink "$@"\n'),
            "cp": ('/usr/bin/cp "$@"\nexit 7\n' if scenario == "partial copy failure" else 'exec /usr/bin/cp "$@"\n'),
        }
        commands["sha256sum"] = ('if test "$PWD" = "' + str(target) + '"; then exit 7; fi\n' if scenario == "second SHA failure" else "") + 'exec /usr/bin/sha256sum "$@"\n'
        for name, code in commands.items():
            path = tools / name
            path.write_text("#!/bin/sh\n" + code)
            path.chmod(0o700)
        text = source.read_text().replace("/data/local/tmp/", str(root) + "/data/local/tmp/").replace("/cache", str(cache))
        script = root / "actual-android.sh"
        script.write_text(text)
        result = subprocess.run(["sh", str(script)], env={**os.environ, "PATH": str(tools) + ":/usr/bin:/bin"}, capture_output=True, text=True)
        allowed = scenario == "success boundary 40MiB"
        passed = (result.returncode == 0) == allowed and ("DISPLAY_INPUTS_STAGED" in result.stdout) == allowed
        if scenario == "existing cache":
            passed = passed and (target / "keep").read_text() == "must remain"
        if allowed:
            passed = passed and all((target / name).read_bytes() == (work / name).read_bytes() for name in files)
        return {"name": "Android " + scenario, "passed": passed, "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}


def inspect_fixture(scenario):
    import importlib.util
    root_repo = HERE.parents[1]
    spec = importlib.util.spec_from_file_location("inspect_dt_fixture", root_repo / "platforms/rk3568/boards/aiot-3568pq/verify-firstboot.py")
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    tree, _ = base.read_dtb(HERE / "build/dtb-v5/display.dtb")
    source = HERE / "linux-inspect.sh"
    with tempfile.TemporaryDirectory(prefix="display-inspect-fixture-") as directory:
        root = Path(directory)
        def write(path, value):
            target = root / path.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value if isinstance(value, bytes) else value.encode())
            return target
        write("proc/self/status", "Uid:\t0\t0\t0\t0\n")
        write("proc/1/cmdline", b"/bin/sh\0/init\0")
        write("proc/1/exe", "fixture exe")
        write("proc/modules", "")
        write("proc/cmdline", "rdinit=/init ro")
        write("proc/mounts", "rootfs / rootfs rw 0 0\n")
        write("proc/fb", "0 rockchipdrmfb\n")
        write("sys/firmware/fdt", (HERE / "build/dtb-v5/display.dtb").read_bytes())
        for path, value in tree.items():
            write("sys/firmware/devicetree/base" + path, value)
        bindings = {"platform": [("display-subsystem", "rockchip-drm"), ("fe040000.vop", "rockchip-vop2"),
                                 ("fe060000.dsi", "dw-mipi-dsi-rockchip"), ("fe850000.phy", "inno-dsidphy"),
                                 ("backlight", "pwm-backlight")], "mipi-dsi": [("fe060000.dsi.0", "panel-simple-dsi")]}
        for bus, pairs in bindings.items():
            for device, driver in pairs:
                target = root / ("sys/bus/" + bus + "/drivers/" + driver)
                target.mkdir(parents=True)
                location = root / ("sys/bus/" + bus + "/devices/" + device)
                location.mkdir(parents=True)
                (location / "driver").symlink_to(target)
                write(str(location.relative_to(root)) + "/power/runtime_status", "active\n")
        for path, value in {
            "sys/class/drm/card0-DSI-1/status": "connected\n", "sys/class/drm/card0-DSI-1/modes": "720x720\n",
            "sys/class/graphics/fb0/name": "rockchipdrmfb\n", "sys/class/graphics/fb0/virtual_size": "720,720\n",
            "sys/class/graphics/fb0/bits_per_pixel": "32\n", "sys/class/graphics/fb0/stride": "2880\n",
            "sys/class/backlight/backlight/brightness": "0\n", "sys/class/backlight/backlight/max_brightness": "255\n",
            "sys/class/backlight/backlight/actual_brightness": "0\n", "sys/class/backlight/backlight/bl_power": "0\n",
            "tmp/display-debug/gpio": "gpio-5 (reset) out hi\ngpio-21 (enable) out hi\n",
            "tmp/display-debug/pinctrl/pinctrl-rockchip-pinctrl/pinmux-pins": "pin 5 (gpio0-5)\npin 19 (gpio0-19)\npin 21 (gpio0-21)\n",
            "tmp/display-debug/pwm": "pwm4\n", "tmp/display-debug/clk/clk_summary": "vop dsi dphy pwm\n",
            "tmp/display-debug/regulator/regulator_summary": "vcc3v3_lcd0_n 3300000\n",
            "tmp/display-debug/dri/0/state": "crtc vp1\n", "tmp/display-debug/dri/0/summary": "720x720\n",
        }.items():
            write(path, value)
        drm = root / "sys/class/drm/card0"
        drm.mkdir()
        (drm / "device").symlink_to(root / "sys/bus/platform/devices/display-subsystem")
        ram = root / "tmp/display"
        ram.mkdir()
        write("tmp/display/upload.sha256", "")
        if scenario == "missing brightness read":
            (root / "sys/class/backlight/backlight/brightness").unlink()
        if scenario == "nonzero brightness":
            write("sys/class/backlight/backlight/brightness", "1\n")
        tools = root / "tools"
        tools.mkdir()
        commands = {
            "uname": "printf '%s\\n' 5.10.160-rt89-g9f9e9d18574d-dirty\n",
            "readlink": 'case "$*" in\n*proc/1/exe*) printf /bin/busybox ;;\n*) exec /usr/bin/readlink "$@" ;;\nesac\n',
            "sha256sum": 'case "$*" in\n*proc/1/exe*) printf "%s  %s\\n" ' + PID_SHA + ' "$1" ;;\n-c*) exit 0 ;;\n*) exec /usr/bin/sha256sum "$@" ;;\nesac\n',
            "dmesg": 'printf "%s\\n" "panel initialization sequence completed (' + ('179' if scenario == 'missing completed marker' else '180') + ' commands)"\n',
            "mount": "exit 7\n" if scenario == "debugfs mount failure" else 'printf "mounted\\n" > "' + str(root / "mount-log") + '"\n',
            "umount": 'printf "released\\n" >> "' + str(root / "mount-log") + '"\n',
            "hexdump": '#!/usr/bin/python3\nimport pathlib,sys\np=pathlib.Path(sys.argv[-1])\nsys.stdout.write(p.read_bytes().hex())\n',
        }
        for name, code in commands.items():
            path = tools / name
            path.write_text(code if code.startswith("#!") else "#!/bin/sh\n" + code)
            path.chmod(0o700)
        text = re.sub(r"/(?:proc|sys|tmp|dev)/", lambda match: str(root) + match.group(0), source.read_text())
        # The private mountpoint already contains fixture debugfs records. Only
        # its exclusive creation is adjusted; mount/umount calls stay real script.
        text = text.replace('test ! -e ' + str(root / 'tmp/display-debug'), 'test -d ' + str(root / 'tmp/display-debug'))
        text = text.replace('mkdir ' + str(root / 'tmp/display-debug'), 'test -d ' + str(root / 'tmp/display-debug'))
        script = root / "actual-inspect.sh"
        script.write_text(text)
        # Execute the exact session shape: a rejected script must never emit
        # the success exit marker, even when its completion text is printed.
        session_command = "sh " + str(script) + " && echo DISPLAY_INSPECTION_EXIT_ZERO"
        result = subprocess.run(["sh", "-c", session_command], env={**os.environ, "PATH": str(tools) + ":/usr/bin:/bin"}, capture_output=True, text=True, timeout=15)
        allowed = scenario == "success"
        statuses = (ram / "inspect/status.tsv").read_text() if (ram / "inspect/status.tsv").exists() else ""
        passed = ((result.returncode == 0) == allowed and
                  ("DISPLAY_INTERFACE_METADATA_VERIFIED_AT_ZERO_BRIGHTNESS" in result.stdout) == allowed and
                  "DISPLAY_INSPECTION_COMPLETE_NO_DEVICE_OPEN_NO_BRIGHTNESS_WRITE" in result.stdout and
                  ("DISPLAY_INSPECTION_EXIT_ZERO" in result.stdout) == allowed)
        if not allowed:
            passed = passed and "FAILED" in statuses and (ram / "outcome").read_text() == "interface-rejected\n"
        if scenario != "debugfs mount failure":
            passed = passed and (root / "mount-log").read_text() == "mounted\nreleased\n"
        return {"name": "inspect " + scenario, "passed": passed, "exit_code": result.returncode,
                "statuses": statuses, "stdout": result.stdout, "stderr": result.stderr,
                "real_hardware_reads": False, "only_paths_and_mountpoint_creation_transformed": True}


def main():
    if RESULT.exists() or RESULT.is_symlink() or any(parent.is_symlink() for parent in RESULT.parents):
        raise ValueError("Refuse existing or symlink stage evidence")
    assert SOURCE.is_file() and not SOURCE.is_symlink(), "Display stage feature is not implemented"
    source = SOURCE.read_text()
    guard_source = (HERE / "linux-return-guard.sh").read_text()
    assert '--stage-rejected' in guard_source, "Display stage-rejected return branch is not implemented"
    scenarios = ["success", "first-sha-fail", "cp-fail", "second-sha-fail", "mount-fail", "umount-fail",
                 "uid-mismatch", "uid-malformed", "kernel-mismatch", "pid-exe-mismatch",
                 "pid-cmdline-mismatch", "pid-sha-mismatch", "residual-module", "modules-read-fail",
                 "non-ram-mount", "mounts-read-fail", "mcu-present", "ram-directory-exists"]
    cases = [fixture(source, scenario) for scenario in scenarios]
    cases += [fixture(source, scenario, True) for scenario in ["first-sha-fail", "cp-fail", "second-sha-fail", "mount-fail", "umount-fail", "ram-directory-exists", "uid-mismatch", "residual-module", "non-ram-mount"]]
    cases += [android_fixture(scenario) for scenario in ["success boundary 40MiB", "nonroot", "wrong kernel", "wrong Android", "boot incomplete", "cache alias", "existing cache", "symlink cache", "symlink input", "tampered input", "insufficient space", "df read failure", "partial copy failure", "second SHA failure"]]
    cases += [inspect_fixture(scenario) for scenario in ["success", "missing brightness read", "nonzero brightness", "missing completed marker", "debugfs mount failure"]]
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
