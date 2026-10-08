#!/usr/bin/env python3
"""Encode and round-trip actual BusyBox serial transfers before any board access."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    output = HERE / "closed-state-v2.json"
    manifest = HERE / "closed-state-manifest-v2.json"
    if output.exists() or manifest.exists():
        raise ValueError("Refusing existing evidence")
    qemu = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"
    busybox = ROOT / "outputs/rk3568-rng-network-20261004/build/busybox-module-options/v1/busybox"
    inputs = [("verify-clock-profile.sh", "/tmp/pcm-clock-profile.sh"),
              ("verify-closed-state.sh", "/tmp/pcm-closed-state.sh")]
    steps, hashes = [], {}
    with tempfile.TemporaryDirectory() as folder:
        for name, target in inputs:
            source = HERE / name
            data = source.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            hashes[name] = digest
            subprocess.run([str(qemu), str(busybox), "sh", "-n", str(source)], check=True)
            reconstructed = Path(folder) / name
            for index in range(0, len(data), 96):
                encoded = "".join("\\0" + format(byte, "03o") for byte in data[index:index + 96])
                redirect = ">" if index == 0 else ">>"
                command = "printf '%b' '" + encoded + "' " + redirect + " " + target
                if any(ord(char) < 32 or ord(char) > 126 for char in command):
                    raise ValueError("Serial command contains non-ASCII/control character")
                subprocess.run([str(qemu), str(busybox), "sh", "-c", command.replace(target, str(reconstructed))], check=True)
                steps.append({"command": command, "wait": 0.05})
            if reconstructed.read_bytes() != data:
                raise ValueError("Actual target printf round-trip failed")
            steps.append({"command": "sha256sum " + target, "wait": 1, "expect": digest + "  " + target})
    steps.append({"command": "sh /tmp/pcm-closed-state.sh", "wait": 10,
                  "expect": r"(?m)^PCM_CONFIGURATION_AND_CLOSED_STATE_VERIFIED_NO_START\r?$"})
    output.write_text(json.dumps(steps, indent=2) + "\n")
    manifest.write_text(json.dumps({"script_sha256": hashes, "exact_busybox_transfer_round_trip": True,
                                   "board_tested": False, "pcm_operations_repeated": False}, indent=2) + "\n")
    print(json.dumps(hashes))


if __name__ == "__main__":
    main()
