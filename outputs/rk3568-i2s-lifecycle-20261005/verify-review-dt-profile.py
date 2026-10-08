#!/usr/bin/env python3
"""Validate actual locked DT cells and rerun the real profile on their values."""
import json
import argparse
import re
import struct
import subprocess
from pathlib import Path
from source_utils import sha

HERE = Path(__file__).resolve().parent
TARGET = HERE / 'review-regression-v1'
ROOT = HERE.parents[1]
DTB = ROOT / "outputs/rk3568-audio-20261005/build/staging-v1/audio.dtb"
EXPECTED = "9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478"


def parse(data):
    magic, length, blocks, strings, reserve, version, last, cpu, strings_len, blocks_len = struct.unpack_from(">10I", data)
    if magic != 0xd00dfeed or length != len(data) or version < 17:
        raise ValueError("invalid flattened DT")
    names = data[strings:strings + strings_len]
    cursor = blocks
    nodes, stack = {}, []
    while cursor < blocks + blocks_len:
        token, = struct.unpack_from(">I", data, cursor)
        cursor += 4
        if token == 1:
            end = data.index(b"\0", cursor)
            stack.append(data[cursor:end].decode())
            cursor = (end + 4) & ~3
            nodes["/" + "/".join(p for p in stack if p)] = {}
        elif token == 2:
            stack.pop()
        elif token == 3:
            size, offset = struct.unpack_from(">II", data, cursor)
            cursor += 8
            name = names[offset:names.index(b"\0", offset)].decode()
            nodes["/" + "/".join(p for p in stack if p)][name] = data[cursor:cursor + size]
            cursor = (cursor + size + 3) & ~3
        elif token == 4:
            pass
        elif token == 9:
            return nodes
        else:
            raise ValueError("bad DT token")
    raise ValueError("unterminated DT")


def cells(value):
    if len(value) % 4:
        raise ValueError("unaligned DT cells")
    return list(struct.unpack(">" + "I" * (len(value) // 4), value))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--config-result-dir", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / ("actual-dt-review-profile-" + args.version)
    output.mkdir(exist_ok=False)
    raw = DTB.read_bytes()
    if sha(raw) != EXPECTED:
        raise ValueError("locked audio DT differs")
    nodes = parse(raw)
    node = nodes["/i2s@fe410000"]
    reg = cells(node["reg"])
    trcm = cells(node["rockchip,clk-trcm"])
    if node["compatible"] != b"rockchip,rk3568-i2s-tdm\0" or reg != [0, 0xfe410000, 0, 0x1000] or trcm != [1] or node["status"] != b"okay\0":
        raise ValueError("actual CPU profile differs")
    excluded = ["rockchip,always-on", "rockchip,hdmi-path", "rockchip,mclk-calibrate", "rockchip,io-multiplex", "rockchip,tdm-multi-lanes", "rockchip,no-dmaengine", "rockchip,digital-loopback", "rockchip,i2s-tx-route", "rockchip,i2s-rx-route"]
    if any(name in node for name in excluded):
        raise ValueError("actual DT contains an excluded feature")
    if "rockchip,bclk-fs" in node and cells(node["rockchip,bclk-fs"]) != [64]:
        raise ValueError("actual BCLK profile differs")
    if node["pinctrl-names"] != b"default\0" or cells(node["interrupts"]) != [0, 0x35, 4]:
        raise ValueError("actual pinctrl/IRQ differs")
    phandle = cells(node["phandle"])[0]
    cards = [(path, props) for path, props in nodes.items() if props.get("compatible") == b"simple-audio-card\0" and cells(nodes.get(path + "/simple-audio-card,cpu", {}).get("sound-dai", b"")) == [phandle]]
    if len(cards) != 1:
        raise ValueError("card routing differs")
    card_path, card = cards[0]
    if card.get("simple-audio-card,format") != b"i2s\0" or cells(card["simple-audio-card,mclk-fs"]) != [256]:
        raise ValueError("actual audio format/MCLK differs")
    checked = args.config_result_dir.resolve()
    if checked.parent != TARGET:
        raise ValueError("config receipt is outside owned output")
    result = json.loads((checked / "result.json").read_text())
    if not result["passed"]:
        raise ValueError("real profile test must pass first")
    # The original fixture is read, replaced with actual DT cell values and
    # recompiled with byte-identical real C functions from the passing run.
    for name in ["real-functions.c", "actual-abi.h", "test-config-shim.h", "test-lifecycle-shim.h", "rockchip_i2s_tdm.h"]:
        (output / name).write_bytes((checked / name).read_bytes())
    original = (checked / "test-config-main.c").read_text()
    rewritten = original.replace("resource.start = 0xfe410000;", "resource.start = " + hex(reg[1]) + ";").replace("resource.end = resource.start + 0xfff;", "resource.end = resource.start + " + hex(reg[3] - 1) + ";").replace('node.compatible = "rockchip,rk3568-i2s-tdm";', "node.compatible = " + json.dumps(node["compatible"].rstrip(b"\0").decode()) + ";").replace("node.trcm = 1;", "node.trcm = " + str(trcm[0]) + ";")
    (output / "test-config-main.c").write_text(rewritten)
    (output / "audio.dtb").write_bytes(raw)
    unit, binary = output / "real-functions.c", output / "actual-profile-host"
    argv = ["gcc", "-std=gnu11", "-O0", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-Wno-unused-function", "-pthread", str(unit), "-o", str(binary)]
    built = subprocess.run(argv, capture_output=True, text=True)
    (output / "compile.stdout").write_text(built.stdout)
    (output / "compile.stderr").write_text(built.stderr)
    if built.returncode:
        raise ValueError("actual-DT real profile compile failed")
    executed = subprocess.run([str(binary)], capture_output=True, text=True)
    (output / "run.stdout").write_text(executed.stdout)
    (output / "run.stderr").write_text(executed.stderr)
    record = {"audio_dtb_sha256": EXPECTED, "candidate_source_sha256": result["source_sha256"], "real_probe_block_sha256": result["probe_block_sha256"], "functions_sha256": result["functions_sha256"], "actual_node": "/i2s@fe410000", "reg": reg, "trcm": trcm[0], "bclk_fs": cells(node["rockchip,bclk-fs"])[0] if "rockchip,bclk-fs" in node else "driver default 64", "absent_features": excluded, "pinctrl": "default only", "card": card_path, "format": "i2s", "mclk_fs": 256, "initial_test_receipt_sha256": sha((checked / "result.json").read_bytes()), "argv": argv, "compile_exit_code": built.returncode, "run_exit_code": executed.returncode, "tests": json.loads(executed.stdout), "binary_sha256": sha(binary.read_bytes()), "files_sha256": {p.name: sha(p.read_bytes()) for p in output.iterdir() if p.is_file()}, "board_tested": False, "boundary": "Actual locked DT data drives real profile/config/state functions; full devres/ALSA registration probe and electrical hardware remain untested"}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"result": str(output / "result.json"), "tests": record["tests"], "exit_code": executed.returncode}))
    return executed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
