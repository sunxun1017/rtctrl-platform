#!/usr/bin/env python3
"""Preserve cache v1, upload corrected PID1 checks to RAM only."""
import base64
import hashlib
import json
from pathlib import Path
import shlex

HERE = Path(__file__).resolve().parent


def main():
    steps = []
    hashes = {}
    for line in (HERE / "build/staging-v1/upload.sha256").read_text().splitlines():
        digest, name = line.split()
        hashes[name] = digest
    for name in ["linux-enumeration.sh", "linux-probe.sh", "linux-return-guard.sh"]:
        hashes[name] = hashlib.sha256((HERE / name).read_bytes()).hexdigest()
    checksum = "".join(f"{digest}  {name}\n" for name, digest in hashes.items()).encode()
    files = {name: (HERE / name).read_bytes() for name in ["linux-enumeration.sh", "linux-probe.sh", "linux-return-guard.sh"]}
    files["upload.sha256"] = checksum
    for name, data in files.items():
        encoded = base64.b64encode(data).decode()
        for index in range(0, len(encoded), 512):
            append = ">" if index == 0 else ">>"
            steps.append({"command": f"printf '%s' '{encoded[index:index + 512]}' {append} /tmp/accel/{name}.b64", "wait": 0.05})
        steps.append({"command": f"base64 -d /tmp/accel/{name}.b64 > /tmp/accel/{name}", "wait": 0.1})
    steps.append({"command": "cd /tmp/accel && sha256sum -c upload.sha256 && echo ACCEL_RUNTIME_V2_HASHES_VERIFIED", "wait": 1,
                  "expect": r"(?m)^ACCEL_RUNTIME_V2_HASHES_VERIFIED\r?$"})
    path = HERE / "linux-runtime-v2-upload.json"
    with path.open("x") as stream:
        json.dump(steps, stream, indent=2)
        stream.write("\n")
    path = HERE / "linux-stage-v3.json"
    with path.open("x") as stream:
        json.dump([{"command": "sh -c " + shlex.quote((HERE / "linux-stage.sh").read_text()), "wait": 5,
                    "expect": r"(?m)^ACCEL_INPUTS_IN_RAM_CACHE_RELEASED\r?$"}], stream, indent=2)
        stream.write("\n")
    print(json.dumps({"status": "RAM_ONLY_RUNTIME_V2_PREPARED", "files": hashes}, indent=2))


if __name__ == "__main__":
    main()
