#!/usr/bin/env python3
"""Read the actual completed v4 vmlinux identity without modifying the ELF."""
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "build/live-image-v4-id"
VMLINUX = ROOT / ".deps/kernel/aiot-3568pq-audio-v4/vmlinux"
IMAGE = HERE / "build/integration-v4/Image"
IMAGE_SHA = "48b9958d36e2b4821235520360530faac38c9f2dae072c2a2602dbda7e048595"
MANIFEST_SHA = "8df525843cac41fd0e272351bc41d0e573c25570cfed7e60f1990b9fe97aa33a"


def ordinary(path):
    if not path.is_relative_to(ROOT) or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Nonordinary input")
    for ancestor in path.parents:
        if not stat.S_ISDIR(ancestor.lstat().st_mode):
            raise ValueError("Nonordinary ancestry")
        if ancestor == ROOT:
            break


def sha(path):
    ordinary(path)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write(name, value):
    (OUT / name).write_bytes((json.dumps(value, indent=2) + "\n").encode())


def main():
    manifest_path = IMAGE.parent / "manifest.json"
    if sha(manifest_path) != MANIFEST_SHA or sha(IMAGE) != IMAGE_SHA:
        raise ValueError("Completed Image differs from actual root build")
    manifest = json.loads(manifest_path.read_bytes())
    if manifest["build_exit_code"] != 0 or manifest["battery_algorithm_enabled"] or manifest["duplex_START_gates_relaxed"]:
        raise ValueError("Completed restricted Image required")
    before = sha(VMLINUX)
    if OUT.exists() or OUT.is_symlink():
        raise ValueError("Fresh identity output required")
    OUT.mkdir()
    argv = ["aarch64-linux-gnu-readelf", "-x", ".notes", str(VMLINUX)]
    result = subprocess.run(argv, capture_output=True)
    (OUT / "readelf-notes.stdout").write_bytes(result.stdout)
    (OUT / "readelf-notes.stderr").write_bytes(result.stderr)
    write("readelf-notes.command.json", {"argv": argv, "exit": result.returncode,
                                        "stdout_sha256": sha(OUT / "readelf-notes.stdout"),
                                        "stderr_sha256": sha(OUT / "readelf-notes.stderr")})
    if result.returncode or result.stderr:
        raise ValueError("Readelf failed; evidence retained")
    words = []
    for line in result.stdout.decode("ascii").splitlines():
        match = re.match(r"\s+0x[0-9a-f]+\s+(.*)", line)
        if match:
            for word in match.group(1).split()[:4]:
                if not re.fullmatch("[0-9a-f]{8}", word):
                    break
                words.append(word)
    notes = bytes.fromhex("".join(words))
    if len(notes) != 60 or notes[:16].hex() != "040000001400000003000000474e5500":
        raise ValueError("Unexpected actual notes layout")
    if notes[36:].hex() != "0600000001000000000100004c696e757800000000000000" or notes[16:36] == b"\0" * 20:
        raise ValueError("Unexpected actual note metadata")
    if sha(VMLINUX) != before or sha(IMAGE) != IMAGE_SHA or sha(manifest_path) != MANIFEST_SHA:
        raise ValueError("Identity inputs changed")
    (OUT / "kernel.notes").write_bytes(notes)
    record = {"image_sha256": IMAGE_SHA, "image_manifest_sha256": MANIFEST_SHA,
              "vmlinux_sha256_before_and_after": before, "notes_bytes": len(notes),
              "notes_sha256": sha(OUT / "kernel.notes"), "notes_hex": notes.hex(),
              "gnu_build_id": notes[16:36].hex(), "tool_sha256": sha(Path(__file__)),
              "readelf_stdout_sha256": sha(OUT / "readelf-notes.stdout"),
              "scope": "Build identity for fresh /sys/kernel/notes; not a full live RAM Image hash",
              "board_verified": False}
    write("identity.json", record)
    print(json.dumps(record))


if __name__ == "__main__":
    main()
