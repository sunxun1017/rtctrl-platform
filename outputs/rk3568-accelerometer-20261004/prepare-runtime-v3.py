#!/usr/bin/env python3
"""Transfer RAM scripts using the existing shell printf, without extra applets."""
import hashlib
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", choices=["v3", "v4"], default="v3")
    args = parser.parse_args()
    hashes = {}
    for line in (HERE / "build/staging-v1/upload.sha256").read_text().splitlines():
        digest, name = line.split()
        hashes[name] = digest
    files = {}
    for name in ["linux-enumeration.sh", "linux-probe.sh", "linux-return-guard.sh"]:
        files[name] = (HERE / name).read_bytes()
        hashes[name] = hashlib.sha256(files[name]).hexdigest()
    files["upload.sha256"] = "".join(f"{digest}  {name}\n" for name, digest in hashes.items()).encode()
    steps = []
    for name, data in files.items():
        for offset in range(0, len(data), 96):
            encoded = "".join("\\0" + f"{value:03o}" for value in data[offset:offset + 96])
            append = ">" if offset == 0 else ">>"
            steps.append({"command": f"printf '%b' '{encoded}' {append} /tmp/accel/{name}", "wait": 0.05})
    steps.append({"command": "cd /tmp/accel && sha256sum -c upload.sha256 && echo ACCEL_RUNTIME_V3_HASHES_VERIFIED",
                  "wait": 1, "expect": r"(?m)^ACCEL_RUNTIME_V3_HASHES_VERIFIED\r?$"})
    with (HERE / ("linux-runtime-" + args.revision + "-upload.json")).open("x") as stream:
        json.dump(steps, stream, indent=2)
        stream.write("\n")
    manifest = "runtime-manifest.json" if args.revision == "v3" else "runtime-manifest-v4.json"
    with (HERE / manifest).open("x") as stream:
        json.dump({"files": hashes, "transport": "shell printf percent-b octal", "board_tested": False}, stream, indent=2)
        stream.write("\n")
    print("APPLET_FREE_RAM_RUNTIME_V3_PREPARED")


if __name__ == "__main__":
    main()
