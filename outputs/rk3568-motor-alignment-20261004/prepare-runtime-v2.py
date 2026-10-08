#!/usr/bin/env python3
"""Prepare auditable RAM-only script uploads and corrected return checks."""
import hashlib
import json
from pathlib import Path
import shlex

HERE = Path(__file__).resolve().parent


def write(name, steps):
    with (HERE / name).open("x") as stream:
        json.dump(steps, stream, indent=2)
        stream.write("\n")


uploads = []
for name in ["linux-module-options-v2.sh", "linux-module-cleanup-v2.sh", "linux-return-guard.sh"]:
    data = (HERE / name).read_bytes()
    command = ("sh -c " + shlex.quote("set -eu\n"
               + "test ! -e /tmp/" + name + "\n"
               + "test ! -L /tmp/" + name + "\nset -C\n"
               + "printf %s " + shlex.quote(data.decode()) + " > /tmp/" + name + "\n"))
    uploads.append({"command": command, "wait": 3})
    digest = hashlib.sha256(data).hexdigest()
    uploads.append({"command": "sha256sum /tmp/" + name, "expect": digest, "wait": 1})
write("linux-runtime-v2-upload.json", uploads)
for name, marker, wait in [
    ("linux-module-options-v2", "REAL_BUSYBOX_MODULE_OPTIONS_DELIVERED", 8),
    ("linux-module-cleanup-v2", "MODULE_CONFIG_AND_FIRMWARE_PATH_RELEASED", 5),
]:
    write(name + ".json", [{"command": "sh /tmp/" + name + ".sh", "wait": wait,
                           "expect": r"(?m)^" + marker + r"\r?$"}])
write("return-android-v2.json", [
    {"command": "sh /tmp/linux-return-guard.sh", "expect": r"(?m)^RAM_ONLY_RESOURCES_RELEASED\r?$", "wait": 2},
    {"command": "dmesg", "wait": 2},
    {"command": "echo b > /proc/sysrq-trigger", "wait": 40},
])
print("CORRECTED_RAM_RUNTIME_V2_SESSIONS_READY")
