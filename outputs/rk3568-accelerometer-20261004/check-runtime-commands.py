#!/usr/bin/env python3
"""Check the declared Linux script dependencies against the exact RAM BusyBox."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    busybox = ROOT / "outputs/rk3568-rng-network-20261004/build/busybox-module-options/v1/busybox"
    if hashlib.sha256(busybox.read_bytes()).hexdigest() != "514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1":
        raise ValueError("RAM BusyBox fingerprint changed")
    qemu = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"
    applets = subprocess.check_output([str(qemu), str(busybox), "--list"], text=True).splitlines()
    required = {"cat", "grep", "readlink", "hexdump", "sha256sum", "uname", "ls", "mkdir", "mount", "umount",
                "cp", "chmod", "insmod", "touch", "dmesg", "losetup", "printf", "sh"}
    if required - set(applets):
        raise ValueError("Unsupported dependencies: " + repr(required - set(applets)))
    scripts = list(HERE.glob("linux-*.sh"))
    for script in scripts:
        if "id -u" in script.read_text() or "base64 " in script.read_text():
            raise ValueError("Unsupported command retained: " + str(script))
        subprocess.run([str(qemu), str(busybox), "sh", "-n", str(script)], check=True)
    print(json.dumps({"status": "EXACT_RAM_BUSYBOX_DEPENDENCIES_AND_SYNTAX_VERIFIED", "applets": len(applets),
                      "required": sorted(required), "script_sha256": {
                          script.name: hashlib.sha256(script.read_bytes()).hexdigest() for script in scripts},
                      "declared_dependencies_not_a_full_shell_static_analyzer": True}, indent=2))


if __name__ == "__main__":
    main()
