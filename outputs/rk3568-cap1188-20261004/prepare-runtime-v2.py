#!/usr/bin/env python3
"""Update one RAM script for the observed minimal BusyBox ls layout, with SHA readback."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    original = json.loads((HERE / "runtime-manifest.json").read_text())
    files = {"linux-identity.sh": (HERE / "linux-identity.sh").read_bytes()}
    hashes = dict(original["files"])
    hashes["linux-identity.sh"] = hashlib.sha256(files["linux-identity.sh"]).hexdigest()
    files["upload.sha256"] = "".join(f"{sha}  {name}\n" for name, sha in hashes.items()).encode()
    steps = []
    for name, data in files.items():
        for offset in range(0, len(data), 96):
            encoded = "".join("\\0" + f"{b:03o}" for b in data[offset:offset + 96])
            steps.append({"command": f"printf '%b' '{encoded}' {'>' if offset == 0 else '>>'} /tmp/cap1188/{name}", "wait": 0.05})
    steps.append({"command": "cd /tmp/cap1188 && sha256sum -c upload.sha256 && echo CAP_RUNTIME_V2_HASHES_VERIFIED",
                  "expect": r"(?m)^CAP_RUNTIME_V2_HASHES_VERIFIED\r?$", "wait": 1})
    manifest = {**original, "files": hashes, "reason": "Observed BusyBox ls lacks owner/group columns; no prior identity attempt",
                "initial_staging_unchanged": True, "transport": "RAM-only octal printf with full readback SHA"}
    for name, value in [("linux-runtime-v2-upload.json", steps), ("runtime-manifest-v2.json", manifest)]:
        with (HERE / name).open("x") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
    print("CAP_RUNTIME_V2_PREPARED")


if __name__ == "__main__":
    main()
