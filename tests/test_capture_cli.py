#!/usr/bin/env python3
"""Exercise the shared frame consumer through a real hardware-free backend."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

executable = sys.argv[1]
with tempfile.TemporaryDirectory() as directory:
    output = Path(directory) / "frame.gray"
    run = subprocess.run([executable, str(output)], text=True, capture_output=True, timeout=10)
    assert run.returncode == 0, run.stderr
    assert "frames=70 corrupt=0 dropped=0 status=ok" in run.stderr
    assert output.read_bytes() == bytes([1]) * (64 * 48)
    metadata = json.loads(Path(str(output) + ".json").read_text())
    assert metadata["schema_version"] == 2
    assert (metadata["width"], metadata["height"], metadata["pixel_format"]) == (64, 48, 1)
    assert metadata["timestamp_monotonic"] == 0
    assert metadata["planes"] == [{"stride": 64, "size": 64 * 48}]
    failure = subprocess.run([executable, directory], text=True, capture_output=True, timeout=10)
    assert failure.returncode == 1, failure.stderr
print("Shared capture consumer saves portable metadata and handles output errors")
