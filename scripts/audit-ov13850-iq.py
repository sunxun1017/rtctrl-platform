#!/usr/bin/env python3
"""Read-only comparison of vendor IQ inputs; does not generate calibrated IQ."""
import argparse
import hashlib
import json
from pathlib import Path


def describe(value, prefix=""):
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            result.update(describe(child, f"{prefix}.{key}" if prefix else key))
    elif isinstance(value, list):
        result[prefix] = "list"
        if value:
            result.update(describe(value[0], prefix + "[]"))
    else:
        result[prefix] = type(value).__name__
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.sdk_root / "external/camera_engine_rkaiq/rkaiq/iqfiles"
    paths = [root / "isp21/ov13850_ZC-OV13850R2A-V1_Largan-50064B31.json",
             root / "isp35/common/imx335_ATKMC_V1_3.json"]
    docs = []
    for path in paths:
        raw = path.read_bytes()
        docs.append(json.loads(raw))
        print(f"input: {path}\nsha256: {hashlib.sha256(raw).hexdigest()}")
    old, new = [describe(d["sensor_calib"]) for d in docs]
    print("\nSensor schema additions in ISP35 reference:")
    for key in sorted(new.keys() - old.keys()):
        print(f"  {key}: {new[key]}")
    print("\nSensor schema type changes:")
    for key in sorted(old.keys() & new.keys()):
        if old[key] != new[key]:
            print(f"  {key}: {old[key]} -> {new[key]}")
    print("\nOV13850 sensor parameters (reference, not board calibration):")
    for key in ("resolution", "Gain2Reg", "Time2Reg", "CISExpUpdate"):
        print(key, json.dumps(docs[0]["sensor_calib"][key], ensure_ascii=False))
    print("\nOV13850-named files in ISP35:")
    matches = sorted((root / "isp35").rglob("*ov13850*"))
    print("\n".join(map(str, matches)) or "NONE")
    print("\nDo not deploy the IMX335 reference or copy ISP21 blocks blindly.")


if __name__ == "__main__":
    main()
