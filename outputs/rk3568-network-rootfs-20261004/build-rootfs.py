#!/usr/bin/env python3
"""Build a new ordinary 64 MiB ext4 file; never mount or format a device."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SIZE = 64 * 1024 * 1024
RELEASE = "5.10.160-rt89-g9f9e9d18574d-dirty"
IMAGE_SHA = "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457"
CONFIG_SHA = "1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
PERSISTENT = "outputs/rk3568-persistent-linux-20261003/"
WIFI = "outputs/rk3568-source-wifi-20261004/"
USERSPACE = "outputs/rk3568-source-userspace-20261004/"
QEMU = ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"

BINARIES = {
    "bin/busybox": (PERSISTENT + "busybox/busybox-1.36.1/busybox",
                    "5c2f1c653fdfe92d21c5baa68a64a460dd9aff3b8947d526048314700e1d5844"),
    "usr/bin/wpa_supplicant": (WIFI + "wpa_supplicant",
                           "81ce62f07e3c73e91e160714ac262593460d342161d1cbec04bcded38e9cce8d"),
    "usr/bin/wpa_cli": (WIFI + "wpa_cli",
                   "6c9de62c15b0fd6e7130811dbde5a5780bfd8064c1bd9ae195a59e0ac95d2c90"),
    "usr/bin/network-helper": (WIFI + "network-helper",
                          "b713e277bfcd25384975acb31253254b93bdad4a70e529b403368f6dbb4dc6f6"),
    "usr/bin/codec-test": (None,
                           "18fd4744d881e46661d16ad60112f395262b6a6e97ce83f246a4334f6448234c"),
    "usr/bin/pty-test": (None,
                         "5eb5fd9aba8133933dce602d5e0dbd3acf5f1829f700615dc77a67b5f1d0cbda"),
    "lib/modules/" + RELEASE + "/bcmdhd.ko": (WIFI + "bcmdhd.ko",
        "cbf55f844b59a57fb4ff67c1754df09dcee716a6385dbb463cce1ae846e4d956"),
}
FIRMWARE = {
    "fw_bcm43456c5_ag.bin": "06d3bebe4b193b5db97b7f99bde94e2e85ca95dc35677079ecf86f8f9b0eb734",
    "nvram_ap6256.txt": "c36643f35c32b9248bbb34870a3ab152237907713e999533592acd925dd04410",
}
ARCHIVES = {
    ".deps/busybox-firstboot/busybox-1.36.1.tar.bz2":
        "b8cc24c9574d809e7279c3be349795c5d5ceb6fdf19ca709f80cde50e47de314",
    ".deps/wifi-source/wpa_supplicant-2.11.proxy.tar.gz":
        "912ea06f74e30a8e36fbb68064d6cdff218d8d591db0fc5d75dee6c81ac7fc0a",
    ".deps/wifi-source/libnl-3.11.0.proxy.tar.gz":
        "2a56e1edefa3e68a7c00879496736fdbf62fc94ed3232c0baba127ecfa76874d",
}
DIRECTORIES = [
    "bin", "dev", "dev/pts", "etc", "etc/rtctrl", "lib", "lib/firmware",
    "lib/modules", "lib/modules/" + RELEASE, "mnt", "proc", "sys", "tmp",
    "usr", "usr/bin", "usr/share", "usr/share/licenses", "var", "var/lib",
    "var/lib/rtctrl",
]
LINKS = {
    "etc/resolv.conf": "/tmp/resolv.conf",
    "run": "tmp/run",
    "var/run": "../run",
    "var/log": "../tmp/log",
    "var/tmp": "../tmp",
    "lib/modules/bcmdhd.ko": RELEASE + "/bcmdhd.ko",
}
TEXT_FILES = {
    "etc/rtctrl/runtime-requirements.txt": (
        "Manual short-lived chroot only. No init, switch_root, or autostart.\n"
        "Before running networking, bind the RAM /tmp onto this root's /tmp.\n"
        "Create /tmp/run and /tmp/log in that RAM mount, with mode 0755.\n"
        "Bind /dev and /dev/pts; explicitly mount proc and sysfs when needed.\n"
        "Credentials, WPA control socket/log/PID and DNS resolver data stay in RAM.\n"
        "The two Wi-Fi firmware files are binary dependencies from the original board.\n"
        "Their redistribution permission has not been established.\n"
        "MCU cached diagnostics for Android 4.19 are deliberately absent.\n"
    ),
    "etc/rtctrl/source-tests.sha256": (
        BINARIES["usr/bin/codec-test"][1] + "  /usr/bin/codec-test\n"
        + BINARIES["usr/bin/pty-test"][1] + "  /usr/bin/pty-test\n"
    ),
    "usr/share/licenses/firmware-status.txt": (
        "Private local testing only. Firmware/NVRAM are original-board binary inputs.\n"
        "Corresponding source and redistribution permission have not been obtained.\n"
        "No open-source license is inferred from their inclusion in this private image.\n"
    ),
}
COPIES = {
    "usr/bin/check-base.sh": (USERSPACE + "check-base.sh", 0o755),
    "usr/bin/start-wifi.sh": (WIFI + "start-wifi.sh", 0o755),
    "etc/udhcpc.sh": (WIFI + "dhcp-script.sh", 0o755),
    "usr/share/licenses/BusyBox": (PERSISTENT + "busybox-LICENSE", 0o644),
    "usr/share/licenses/wpa_supplicant": (WIFI + "wpa-LICENSE", 0o644),
    "usr/share/licenses/libnl": (WIFI + "libnl-LICENSE", 0o644),
    "usr/share/licenses/rtctrl-platform": ("LICENSE", 0o644),
    "usr/share/licenses/Linux": ("third_party/linux-rk3588/COPYING", 0o644),
    "usr/share/licenses/GPL-2.0": ("third_party/linux-rk3588/LICENSES/preferred/GPL-2.0", 0o644),
    "usr/share/licenses/Linux-syscall-note": ("third_party/linux-rk3588/LICENSES/exceptions/Linux-syscall-note", 0o644),
}


def fail(message):
    raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bounded_path(path, boundary, exists=True, regular=False):
    """Reject traversal, all symlink ancestors, and nonordinary input files."""
    path = Path(os.path.abspath(path))
    boundary = Path(os.path.abspath(boundary))
    if not path.is_relative_to(boundary):
        fail("Path outside allowed boundary: " + str(path))
    if boundary.is_symlink():
        fail("Symlink boundary: " + str(boundary))
    current = boundary
    for part in path.relative_to(boundary).parts:
        current = current / part
        if current.is_symlink():
            fail("Symlink path component: " + str(current))
    if exists and not path.exists():
        fail("Missing input: " + str(path))
    if regular and not stat.S_ISREG(path.stat().st_mode):
        fail("Input is not an ordinary file: " + str(path))
    return path


def read_input(relative, expected=None):
    path = bounded_path(ROOT / relative, ROOT, regular=True)
    data = path.read_bytes()
    if expected is not None and sha(data) != expected:
        fail("Input SHA mismatch: " + relative)
    return path, data


def check_elf(data, module=False):
    if len(data) < 64 or data[:6] != b"\x7fELF\x02\x01":
        fail("Expected little-endian ELF64")
    if struct.unpack_from("<H", data, 18)[0] != 183:
        fail("Expected AArch64 ELF")
    kind = struct.unpack_from("<H", data, 16)[0]
    if kind != (1 if module else 2):
        fail("Wrong ELF type")
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, phnum = struct.unpack_from("<HH", data, 54)
    if phnum and (phsize < 56 or phoff + phsize * phnum > len(data)):
        fail("Invalid ELF program header bounds")
    for index in range(phnum):
        offset = phoff + index * phsize
        header_type = struct.unpack_from("<I", data, offset)[0]
        if header_type == 3:
            fail("Dynamic ELF interpreter is forbidden")
        if header_type == 2:
            start = struct.unpack_from("<Q", data, offset + 8)[0]
            size = struct.unpack_from("<Q", data, offset + 32)[0]
            if start + size > len(data) or size % 16:
                fail("Invalid dynamic segment")
            for position in range(start, start + size, 16):
                if struct.unpack_from("<q", data, position)[0] == 1:
                    fail("DT_NEEDED dependency is forbidden")
    if module:
        signature = ("vermagic=" + RELEASE + " SMP preempt_rt mod_unload aarch64\0").encode()
        if signature not in data:
            fail("Module does not match tested kernel release/configuration")


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, **kwargs)


def applets():
    _, content = read_input(PERSISTENT + "busybox-applets.txt")
    names = content.decode().splitlines()
    if len(names) != len(set(names)) or any(not re.fullmatch(r"[a-zA-Z0-9_\[\]-]+", name) for name in names):
        fail("Unsafe or duplicate BusyBox applet")
    required = {"sh", "ip", "udhcpc", "insmod", "rmmod", "chroot", "mount", "umount", "sha256sum"}
    if not required <= set(names):
        fail("Missing required BusyBox applets")
    return names


def program_path(destination, relative):
    if relative is not None:
        return relative
    target = "rtctrl_patchx_codec_test" if destination.endswith("codec-test") else "rtctrl_patchx_pty_test"
    location = ROOT / "outputs/rk3568-mcu-baseline-20261003/private/source-tests"
    matches = list(location.rglob(target))
    if len(matches) != 1:
        fail("Need exactly one existing source-built target: " + target)
    return matches[0].relative_to(ROOT).as_posix()


def module_exports(path):
    _, symbols = read_input(".deps/kernel/aiot-3568pq-rcu-reset/vmlinux.symvers")
    exports = {line.split()[1] for line in symbols.decode().splitlines()}
    output = run(["aarch64-linux-gnu-nm", "-u", str(path)], text=True).stdout
    undefined = {line.split()[-1] for line in output.splitlines()}
    if not undefined <= exports:
        fail("Missing kernel exports: " + str(sorted(undefined - exports)))
    return len(undefined)


def specifications():
    """Fixed content whitelist. No directories or archives are broadly extracted."""
    specs = {name: {"type": "directory", "mode": 0o1777 if name == "tmp" else 0o755} for name in DIRECTORIES}
    inputs = {}
    for name, (relative, expected) in BINARIES.items():
        relative = program_path(name, relative)
        path, data = read_input(relative, expected)
        check_elf(data, module=name.endswith(".ko"))
        inputs[relative] = sha(data)
        specs[name] = {"type": "file", "mode": 0o644 if name.endswith(".ko") else 0o755, "data": data}
        if name.endswith(".ko"):
            module_exports(path)
    for name, (relative, mode) in COPIES.items():
        _, data = read_input(relative)
        if name.endswith(".sh") and (not data.startswith(b"#!/bin/sh\n") or b"\r" in data):
            fail("Shell input must be LF /bin/sh text: " + relative)
        inputs[relative] = sha(data)
        specs[name] = {"type": "file", "mode": mode, "data": data}
    archive_path, archive_data = read_input(PERSISTENT + "wifi-original.tar.gz")
    inputs[archive_path.relative_to(ROOT).as_posix()] = sha(archive_data)
    with tarfile.open(archive_path) as archive:
        for name, expected in FIRMWARE.items():
            matches = [member for member in archive.getmembers() if member.name == "etc/firmware/" + name]
            if len(matches) != 1 or not matches[0].isfile() or matches[0].size > 1024 * 1024:
                fail("Firmware member is not a unique bounded ordinary file")
            data = archive.extractfile(matches[0]).read()
            if sha(data) != expected:
                fail("Firmware SHA mismatch: " + name)
            specs["lib/firmware/" + name] = {"type": "file", "mode": 0o644, "data": data}
    for name, text in TEXT_FILES.items():
        specs[name] = {"type": "file", "mode": 0o644, "data": text.encode()}
    driver_source = "third_party/linux-rk3588/drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/dhd_linux.c"
    _, driver_text = read_input(driver_source)
    if not driver_text.startswith(b"/*") or b"*/" not in driver_text:
        fail("Missing source driver license header")
    license_header = driver_text.split(b"*/", 1)[0] + b"*/\n"
    inputs[driver_source] = sha(driver_text)
    specs["usr/share/licenses/bcmdhd-source-header"] = {
        "type": "file", "mode": 0o644, "data": license_header,
    }
    checksums = "".join(
        sha(item["data"]) + "  /" + name + "\n"
        for name, item in sorted(specs.items()) if item["type"] == "file"
    )
    specs["etc/rtctrl/payload.sha256"] = {
        "type": "file", "mode": 0o644, "data": checksums.encode(),
    }
    for name, target in LINKS.items():
        specs[name] = {"type": "symlink", "mode": 0o777, "target": target}
    for name in applets():
        specs["bin/" + name] = {"type": "symlink", "mode": 0o777, "target": "busybox"}
    return specs, inputs


def source_inputs():
    paths = [
        "LICENSE", "CMakeLists.txt", "cmake/toolchains/linux-cross.cmake",
        PERSISTENT + "build-busybox.sh", PERSISTENT + "busybox.config",
        PERSISTENT + "busybox-applets.txt", USERSPACE + "build-userspace.py",
        "outputs/rk3568-mcu-baseline-20261003/build-source-tests.sh",
        WIFI + "build-module.sh", WIFI + "build-network-tools.sh", WIFI + "build-helper.sh",
        WIFI + "network-helper.c", WIFI + "test-network-helper.py", WIFI + "wpa-build.config",
        WIFI + "verify-module.py", ".deps/kernel/aiot-3568pq-rcu-reset/vmlinux.symvers",
        ".deps/busybox-firstboot/busybox-1.36.1.tar.bz2",
        ".deps/wifi-source/wpa_supplicant-2.11.proxy.tar.gz",
        ".deps/wifi-source/libnl-3.11.0.proxy.tar.gz",
    ]
    for folder in ["adapters/actuator/patchx", "adapters/transport/serial"]:
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file():
                paths.append(path.relative_to(ROOT).as_posix())
    board = "platforms/rk3568/boards/aiot-3568pq/"
    paths += [board + "firstboot.cfg"]
    paths += [board + "patches/" + name for name in [
        "0001-arm64-cache-kasan-include.patch", "0002-rk817-feedback-diagnostic.patch",
        "0003-printk-rcu-flush-context.patch", "0004-bcmdhd-out-of-tree-include.patch",
    ]]
    paths += [(HERE / name).relative_to(ROOT).as_posix() for name in [
        "build-rootfs.py", "verify-rootfs.py", "test-rootfs.py",
    ]]
    return {relative: sha(read_input(relative, ARCHIVES.get(relative))[1]) for relative in paths}


def manifest_entries(specs):
    result = {"/": {"type": "directory", "mode": 0o755, "uid": 0, "gid": 0},
              "/lost+found": {"type": "directory", "mode": 0o700, "uid": 0, "gid": 0}}
    for name, item in specs.items():
        entry = {key: value for key, value in item.items() if key != "data"}
        entry.update(uid=0, gid=0)
        if "data" in item:
            entry.update(bytes=len(item["data"]), sha256=sha(item["data"]))
        result["/" + name] = entry
    return result


def build(output):
    output = bounded_path(output, HERE, exists=False)
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", str(output)):
        fail("Output path cannot contain debugfs command delimiters or whitespace")
    if not output.is_dir():
        fail("Output parent must already be a real directory")
    for name in ["build", "rootfs.img", "rootfs-manifest.json"]:
        if os.path.lexists(output / name):
            fail("Refusing existing output: " + str(output / name))
    specs, inputs = specifications()
    sources = source_inputs()
    _, image_data = read_input("outputs/rk3568-rcu-reset-20261004/Image", IMAGE_SHA)
    _, config = read_input("outputs/rk3568-rcu-reset-20261004/kernel.config", CONFIG_SHA)
    read_input(".deps/kernel/aiot-3568pq-rcu-reset/arch/arm64/boot/Image", IMAGE_SHA)
    _, live_config = read_input(".deps/kernel/aiot-3568pq-rcu-reset/.config", CONFIG_SHA)
    if config != live_config:
        fail("Kernel build configuration differs")
    kernel = ROOT / "third_party/linux-rk3588"
    if run(["git", "-C", str(kernel), "rev-parse", "HEAD"], text=True).stdout.strip() != COMMIT:
        fail("Wrong kernel source commit")
    if run(["git", "-C", str(kernel), "status", "--porcelain"], text=True).stdout:
        fail("Kernel source must be restored clean")
    build_dir = output / "build"
    build_dir.mkdir(mode=0o755)
    stage = build_dir / "stage"
    stage.mkdir(mode=0o755)
    for name, item in specs.items():
        path = stage / name
        if item["type"] == "directory":
            path.mkdir(mode=item["mode"])
            path.chmod(item["mode"])
        elif item["type"] == "file":
            with path.open("xb") as stream:
                stream.write(item["data"])
            path.chmod(item["mode"])
        else:
            path.symlink_to(item["target"])
    image = output / "rootfs.img"
    fd = os.open(image, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "wb") as stream:
        stream.truncate(SIZE)
    format_command = ["mkfs.ext4", "-F", "-q", "-b", "4096", "-m", "0", "-L", "rtctrl-net-root",
                      "-O", "^64bit,^metadata_csum", "-E", "lazy_itable_init=0,lazy_journal_init=0",
                      "-d", str(stage), str(image)]
    formatting = run(format_command, text=True)
    (build_dir / "format.log").write_text(formatting.stdout + formatting.stderr)
    entries = manifest_entries(specs)
    commands = []
    for name in entries:
        commands.append("set_inode_field " + name + " uid 0")
        commands.append("set_inode_field " + name + " gid 0")
    command_file = build_dir / "ownership.debugfs"
    command_file.write_text("\n".join(commands) + "\n")
    ownership = run(["debugfs", "-w", "-f", str(command_file), str(image)], text=True)
    (build_dir / "ownership.log").write_text(ownership.stdout + ownership.stderr)
    manifest = {
        "schema": 1, "phase": "source-network-rootfs", "image": {
            "file": "rootfs.img", "bytes": SIZE, "sha256": sha(image.read_bytes())},
        "kernel": {"release": RELEASE, "source_commit": COMMIT,
                   "image_sha256": sha(image_data), "config_sha256": sha(config)},
        "entries": entries, "inputs": inputs, "sources": sources,
        "binary_dependencies": {name: {"sha256": value, "role": "firmware_or_nvram_binary",
            "corresponding_source_obtained": False, "redistribution_permission_verified": False,
            "distribution_scope": "private_local_testing_only"} for name, value in FIRMWARE.items()},
        "policy": {"pid1_in_image": False, "autostart": False, "switch_root_tested": False,
                   "credentials_in_image": False, "tmp_must_be_bound_to_ram": True,
                   "manufacturer_android_libraries_included": False,
                   "physical_mcu_tool_included": False, "board_tested": False},
    }
    with (output / "rootfs-manifest.json").open("x") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    verification = subprocess.run(
        ["python3", str(HERE / "verify-rootfs.py"), "--output-dir", str(output)],
        capture_output=True, text=True,
    )
    if verification.returncode != 0:
        (build_dir / "verification-failure.log").write_text(verification.stdout + verification.stderr)
        fail("Fresh image verification failed: " + verification.stderr.strip())
    (build_dir / "verification.json").write_text(verification.stdout)
    print(verification.stdout, end="")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=HERE)
    args = parser.parse_args()
    try:
        build(args.output_dir)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, "ROOTFS_BUILD_REJECTED: " + str(error) + "\n")


if __name__ == "__main__":
    main()
