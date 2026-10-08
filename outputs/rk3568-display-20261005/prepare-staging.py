#!/usr/bin/env python3
"""Prepare hash-bound, reviewable display sessions without communicating or deploying."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LOCKED = {
    "Image": (HERE / "build/image-v1/Image", "dafdda0cc331605471c1b24a33cb4f037bf4af79b4145eabf12513dabf4d86a7", 34755072, "6c3715bf"),
    "display.dtb": (HERE / "build/dtb-v5/display.dtb", "650228482eaed6f95d9892fce217f436072d851cc47398696d52b85e08200f70", 166090, None),
    "initramfs.cpio.gz": (ROOT / "outputs/rk3568-motor-alignment-20261004/initramfs.cpio.gz", "f0965ceed549acab8d5bd87df8bb831bb06a95d08b5b7bf3c5582045933323ee", 4308268, "74fea1e6"),
}
PID_SHA = "514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_path(path):
    if path.exists() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Refusing existing or symlink output: " + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.revision):
        raise ValueError("Invalid revision")
    staging = HERE / "build" / ("staging-" + args.revision)
    if args.revision != "v1":
        # Earlier fixture evidence occupies these ordinary parent directories.
        # Each runtime payload still has its own exclusively created directory.
        staging = staging / "payload"
    names = ["display-load-" + args.revision + ".json", "display-boot-" + args.revision + ".json",
             "display-stage-" + args.revision + ".json", "display-inspect-" + args.revision + ".json",
             "display-return-" + args.revision + ".json", "display-android-" + args.revision + ".json",
             "display-stage-rejected-return-" + args.revision + ".json",
             "runtime-manifest-" + args.revision + ".json"]
    for path in [staging, *(HERE / name for name in names)]:
        new_path(path)
    files = {}
    artifact = {}
    for name, (path, expected, size, crc) in LOCKED.items():
        if not path.is_file() or path.is_symlink() or sha(path) != expected or path.stat().st_size != size:
            raise ValueError("Frozen input mismatch: " + name)
        actual_crc = f"{zlib.crc32(path.read_bytes()):08x}"
        if crc is not None and actual_crc != crc:
            raise ValueError("Frozen CRC mismatch: " + name)
        files[name] = path
        artifact[name] = {"sha256": expected, "bytes": size, "crc32": actual_crc}
    image_header = LOCKED["Image"][0].read_bytes()[:64]
    text_offset, memory_size = struct.unpack_from("<QQ", image_header, 8)
    if text_offset != 0 or memory_size != 35389440:
        raise ValueError("Frozen arm64 Image load extent changed")
    board = ROOT / "platforms/rk3568/boards/aiot-3568pq"
    spec = importlib.util.spec_from_file_location("display_runtime_audit", board / "verify-display.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    dtb_result = audit.audit(*audit.uart.rng.wifi.base.read_dtb(LOCKED["display.dtb"][0]))
    if dtb_result["default_brightness_index"] != 0:
        raise ValueError("Only zero-brightness DTB is authorized")
    scripts = ["prepare-android.sh", "linux-stage.sh", "linux-inspect.sh", "linux-return-guard.sh"]
    for name in scripts:
        path = HERE / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("Need ordinary script: " + name)
        files[name] = path
    busybox = ROOT / "outputs/rk3568-rng-network-20261004/build/busybox-module-options/v1/busybox"
    qemu = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"
    if sha(busybox) != PID_SHA:
        raise ValueError("Exact RAM BusyBox changed")
    applets = subprocess.check_output([str(qemu), str(busybox), "--list"], text=True).splitlines()
    required = {"cat", "grep", "readlink", "hexdump", "sha256sum", "uname", "ls", "mkdir", "mount", "umount",
                "cp", "touch", "dmesg", "losetup", "printf", "sh", "sleep"}
    if len(applets) != 52 or required - set(applets):
        raise ValueError("Exact RAM BusyBox applet contract changed")
    for name in scripts[1:]:
        subprocess.run([str(qemu), str(busybox), "sh", "-n", str(HERE / name)], check=True)
    parameter_tests = {}
    for label, arguments, allowed in [
        ("hexdump", ["hexdump", "-v", "-e", '1/1 "%02x"', str(HERE / "linux-stage.sh")], True),
        ("integer-sleep", ["sleep", "1"], True),
        ("fractional-sleep-refused", ["sleep", "0.01"], False),
    ]:
        result = subprocess.run([str(qemu), str(busybox), *arguments], capture_output=True, timeout=5)
        if (result.returncode == 0) != allowed:
            raise ValueError("Actual BusyBox parameter mismatch: " + label)
        parameter_tests[label] = {"exit_code": result.returncode, "passed": True}
    staging.mkdir(parents=True)
    for name, path in files.items():
        shutil.copyfile(path, staging / name)
    hashes = {name: sha(staging / name) for name in files}
    checksum = staging / "upload.sha256"
    checksum.write_text("".join(f"{digest}  {name}\n" for name, digest in hashes.items()))
    checksum_sha = sha(checksum)
    cache = "/rtctrl-display-20261005-v1/"

    def step(command, expect=None, wait=1):
        record = {"command": command, "wait": wait}
        if expect is not None:
            record["expect"] = expect
        return record

    def write(name, value):
        with (HERE / name).open("x") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")

    load = []
    for name, address in [("Image", "400000"), ("display.dtb", "3000000"), ("initramfs.cpio.gz", "4000000")]:
        record = artifact[name]
        load += [step(f"ext4load mmc 0:c {address} {cache}{name}", f"{record['bytes']} bytes read", 4),
                 step(f"crc32 {address} {record['bytes']:x}", "==> " + record["crc32"])]
    load += [step("fdt addr 3000000"), step("fdt rsvmem print"), step("fdt print /reserved-memory", "no-map"),
             step("fdt print /backlight default-brightness-level", "<0x00000000>")]
    write(names[0], load)
    boot = json.loads((ROOT / "outputs/rk3568-cap1188-20261004/boot-ram.json").read_text())
    # Only volatile environment/FDT fields are changed by the reviewed booti plan.
    write(names[1], boot)
    stage_data = (HERE / "linux-stage.sh").read_bytes()
    stage_sha = hashlib.sha256(stage_data).hexdigest()
    guard_data = (HERE / "linux-return-guard.sh").read_bytes()
    guard_sha = hashlib.sha256(guard_data).hexdigest()
    steps = [step("test ! -e /tmp/display-return-guard.sh && test ! -L /tmp/display-return-guard.sh && "
                  "test ! -e /tmp/display-stage.sh && test ! -L /tmp/display-stage.sh && "
                  "test ! -e /tmp/display-stage-attempt && test ! -L /tmp/display-stage-attempt && "
                  "echo DISPLAY_RECOVERY_AND_STAGE_PATHS_ABSENT",
                  r"(?m)^DISPLAY_RECOVERY_AND_STAGE_PATHS_ABSENT\r?$")]
    for data, target, digest, marker in [
        (guard_data, "/tmp/display-return-guard.sh", guard_sha, "DISPLAY_EARLY_RETURN_GUARD_SHA_VERIFIED"),
        (stage_data, "/tmp/display-stage.sh", stage_sha, "DISPLAY_STAGE_SCRIPT_SHA_VERIFIED"),
    ]:
        for offset in range(0, len(data), 96):
            encoded = "".join("\\0" + f"{byte:03o}" for byte in data[offset:offset + 96])
            redirect = ">" if offset == 0 else ">>"
            steps.append(step(f"printf '%b' '{encoded}' {redirect} {target}", wait=0.05))
        steps.append(step(f"test \"$(sha256sum {target})\" = '{digest}  {target}' && echo {marker}",
                          "(?m)^" + marker + r"\r?$"))
    import shlex
    # Use one printf invocation so no partial state looks like a valid attempt.
    attempt_command = ("set -eu\n"
                       "test ! -e /tmp/display-stage-attempt\n"
                       "test ! -L /tmp/display-stage-attempt\n"
                       "(\n"
                       "    set -C\n"
                       f"    printf '%s\\n' 'display-stage-v2' '{guard_sha}  /tmp/display-return-guard.sh' "
                       f"'{stage_sha}  /tmp/display-stage.sh' > /tmp/display-stage-attempt\n"
                       ")\n"
                       "sh /tmp/display-stage.sh\n"
                       "echo DISPLAY_STAGE_EXIT_ZERO")
    wrapper = attempt_command.encode("ascii") + b"\n"
    (staging / "run-stage.sh").write_bytes(wrapper)
    subprocess.run([str(qemu), str(busybox), "sh", "-n", str(staging / "run-stage.sh")], check=True)
    wrapper_sha = hashlib.sha256(wrapper).hexdigest()
    steps.append(step("test ! -e /tmp/display-run-stage.sh && test ! -L /tmp/display-run-stage.sh && echo DISPLAY_RUN_SCRIPT_ABSENT",
                      r"(?m)^DISPLAY_RUN_SCRIPT_ABSENT\r?$"))
    for offset in range(0, len(wrapper), 96):
        encoded = "".join("\\0" + f"{byte:03o}" for byte in wrapper[offset:offset + 96])
        decoded = subprocess.check_output([str(qemu), str(busybox), "printf", "%b", encoded])
        if decoded != wrapper[offset:offset + 96]:
            raise ValueError("Exact BusyBox wrapper round-trip failed")
        redirect = ">" if offset == 0 else ">>"
        steps.append(step(f"printf '%b' '{encoded}' {redirect} /tmp/display-run-stage.sh", wait=0.05))
    steps.append(step(f"test \"$(sha256sum /tmp/display-run-stage.sh)\" = '{wrapper_sha}  /tmp/display-run-stage.sh' && sh /tmp/display-run-stage.sh",
                      r"(?m)^DISPLAY_INPUTS_IN_RAM_CACHE_RELEASED\r?$[\s\S]*^DISPLAY_STAGE_EXIT_ZERO\r?$", 5))
    if any(re.search(r"[^\x20-\x7e]", item["command"]) for item in steps):
        raise ValueError("Serial commands must be single-line printable ASCII")
    write(names[2], steps)
    write(names[3], [step("sh /tmp/display/linux-inspect.sh && echo DISPLAY_INSPECTION_EXIT_ZERO",
                         r"(?m)^DISPLAY_INTERFACE_METADATA_VERIFIED_AT_ZERO_BRIGHTNESS\r?$[\s\S]*^DISPLAY_INSPECTION_EXIT_ZERO\r?$", 10)])
    write(names[4], [step("sh /tmp/display-return-guard.sh", r"(?m)^DISPLAY_RAM_ONLY_RESET_READY\r?$", 5),
                     step("dmesg", wait=2), step("echo b > /proc/sysrq-trigger", wait=40)])
    work = "/data/local/tmp/rtctrl-display-20261005-v1"
    android_script = f"set -eu\ncd {work}\ntest \"$(sha256sum upload.sha256)\" = '{checksum_sha}  upload.sha256'\nsha256sum -c upload.sha256\nsh prepare-android.sh"
    android_command = "sh -c " + shlex.quote(android_script)
    write(names[5], [step(android_command, r"(?m)^DISPLAY_INPUTS_STAGED\r?$", 10)])
    write(names[6], [step("sh /tmp/display-return-guard.sh --stage-rejected",
                         r"(?m)^DISPLAY_STAGE_REJECTED_RAM_ONLY_RESET_READY\r?$", 5),
                     step("dmesg", wait=2), step("echo b > /proc/sysrq-trigger", wait=40)])
    write(names[7], {"files": hashes, "upload_sha256": checksum_sha, "stage_script_sha256": stage_sha,
                     "stage_wrapper_sha256": wrapper_sha, "all_stage_serial_commands_printable_ascii": True,
                     "early_return_guard_sha256": guard_sha, "stage_attempt_version": "display-stage-v2",
                     "staging": str(staging.relative_to(ROOT)), "android_work": work, "cache_directory": "/cache" + cache.rstrip("/"),
                     "artifact": artifact, "image_memory_bytes": memory_size, "image_text_offset": text_offset,
                     "pid1_busybox_sha256": PID_SHA, "busybox_applet_count": len(applets),
                     "required_applets": sorted(required), "actual_busybox_parameter_tests": parameter_tests,
                     "transport": "octal printf; host and board SHA; U-Boot CRC binds newly built Image",
                     "image_identity_not_proven_by_kernel_release_alone": True,
                     "default_brightness_index": 0, "brightness_write_allowed": False, "display_device_open_allowed": False,
                     "board_tested": False, "deployment_performed": False, "physical_screen_connected": False,
                     "physical_display_response_tested": False, "sessions": names[:-1],
                     "generator_sha256": sha(Path(__file__))})
    print(json.dumps({"status": "DISPLAY_STAGING_AND_REVIEW_SESSIONS_PREPARED", "staging": str(staging),
                      "files": hashes, "artifact": artifact, "busybox_applets": len(applets)}, indent=2))


if __name__ == "__main__":
    main()
