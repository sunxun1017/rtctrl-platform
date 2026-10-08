#!/usr/bin/env python3
"""Check pinned local Image symbols and emit limited I2C disassembly for review."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    image_path = ROOT / "outputs/rk3568-mcu-baseline-20261003/private/original-Image.bin"
    image = image_path.read_bytes()
    digest = hashlib.sha256(image).hexdigest()
    if digest != "54e75d6dbb03ab96ea938eb940fe64cab91f3f81a3e43a9e98d763980dd7779d":
        raise ValueError("Original Image fingerprint changed")
    helper = HERE / "build/inspect-v1/sensor-inspect"
    if hashlib.sha256(helper.read_bytes()).hexdigest() != "9b706bd7e7acb4b704b2838e004dd71c1c3ebc9ea2cda59dd64d9d82f768cdfb":
        raise ValueError("Standard helper fingerprint changed")
    indices = struct.unpack_from("<256H", image, 0x1726800)
    tokens = []
    for index in indices:
        start = 0x1726400 + index
        tokens.append(image[start:image.index(0, start)].decode("ascii"))
    count = struct.unpack_from("<Q", image, 0x158e600)[0]
    if count != 123800:
        raise ValueError("Unexpected symbol count")
    offsets = struct.unpack_from("<123800i", image, 0x1515600)
    expected = {"__i2c_transfer": 0x9845d8, "i2cdev_ioctl_rdwr.isra.1": 0x988bc8,
                "i2cdev_ioctl": 0x988e78, "rk3x_i2c_xfer": 0x98c390, "rk3x_i2c_irq": 0x98c098}
    position = 0x158e700
    found = {}
    for index in range(count):
        length = image[position]
        position += 1
        name = "".join(tokens[value] for value in image[position:position + length])[1:]
        position += length
        if name in expected:
            found[name] = offsets[index] & 0xffffffff
    if position != 0x17253aa or found != expected:
        raise ValueError("Locked symbol layout differs")
    ranges = {"rdwr": (0x988bc8, 0x988e78), "dispatch": (0x988e78, 0x9892d8),
              "core": (0x9845d8, 0x984c18), "prepare": (0x98b5d8, 0x98b728),
              "controller": (0x98bfd8, 0x98c800)}
    output = HERE / "private/android-abi-disassembly"
    if output.exists() or output.is_symlink():
        raise ValueError("Refusing existing disassembly output")
    output.mkdir()
    for name, (start, end) in ranges.items():
        result = subprocess.check_output(["aarch64-linux-gnu-objdump", "-D", "-b", "binary", "-m", "aarch64",
                                          f"--start-address={start}", f"--stop-address={end}", str(image_path)])
        (output / (name + ".txt")).write_bytes(result)
    print(json.dumps({"status": "OFFLINE_IMAGE_AND_I2C_SYMBOLS_VERIFIED", "original_image_sha256": digest,
                      "symbols": {name: hex(value) for name, value in found.items()},
                      "function_ranges": {name: [hex(v) for v in bounds] for name, bounds in ranges.items()},
                      "instruction_semantics_automatically_proven": False,
                      "board_io_performed": False}, indent=2))


if __name__ == "__main__":
    main()
