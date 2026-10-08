#!/usr/bin/env python3
"""Compile verbatim locked panel-simple functions against test-only I/O boundaries."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FUNCTIONS = [
    "to_panel_simple", "panel_simple_xfer_dsi_cmd_seq", "panel_simple_xfer_spi_cmd_seq",
    "panel_simple_regulator_enable", "panel_simple_regulator_disable",
    "panel_simple_loader_protect", "panel_simple_disable", "panel_simple_unprepare",
    "panel_simple_get_hpd_gpio", "panel_simple_prepare", "panel_simple_enable",
]
KERNEL = ROOT / "third_party/linux-rk3588"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
DSI_SOURCE = "drivers/gpu/drm/drm_mipi_dsi.c"
HOST_SOURCE = "drivers/gpu/drm/bridge/synopsys/dw-mipi-dsi.c"
DSI_HEADER = "include/drm/drm_mipi_dsi.h"
DISPLAY_HEADER = "include/video/mipi_display.h"
BOARD_DTS = ROOT / "platforms/rk3568/boards/aiot-3568pq/bsp/rk3568-aiot-3568pq-display.dts"
DSI_FUNCTIONS = ["mipi_dsi_packet_format_is_short", "mipi_dsi_packet_format_is_long",
                 "mipi_dsi_create_packet", "mipi_dsi_device_transfer", "mipi_dsi_generic_write",
                 "mipi_dsi_dcs_write_buffer", "mipi_dsi_compression_mode", "mipi_dsi_picture_parameter_set"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def balanced(text, opening):
    depth = 0
    for position in range(opening, len(text)):
        if text[position] == "{":
            depth += 1
        elif text[position] == "}":
            depth -= 1
            if depth == 0:
                return position + 1
    raise ValueError("unclosed declaration")


def extract(text):
    blocks = [text[:text.index("#include")]]  # Retain the source MIT notice.
    for kind, name in [("enum", "panel_simple_cmd_type"), ("struct", "panel_cmd_header"),
                       ("struct", "panel_cmd_desc"), ("struct", "panel_cmd_seq"),
                       ("struct", "panel_desc"), ("struct", "panel_simple")]:
        match = re.search(r"^" + kind + " " + name + r"\s*\{", text, re.M)
        end = text.index(";", balanced(text, text.index("{", match.start()))) + 1
        blocks.append(text[match.start():end])
    for name in FUNCTIONS:
        match = re.search(r"^(?:static (?:inline )?)?(?:int|struct panel_simple \*)\s*" +
                          name + r"\([^;]*?\)\s*\{", text, re.M)
        if not match:
            raise ValueError("function not found: " + name)
        end = balanced(text, text.index("{", match.start()))
        blocks.append(text[match.start():end])
    return "\n\n".join(blocks) + "\n"


def declaration(text, kind, name):
    match = re.search(r"^" + kind + " " + name + r"\s*\{", text, re.M)
    end = text.index(";", balanced(text, text.index("{", match.start()))) + 1
    return text[match.start():end]


def body(text, name):
    match = re.search(r"^(?:static (?:inline )?)?(?:bool|int|ssize_t|struct dw_mipi_dsi \*)\s*" +
                      name + r"\([^;]*?\)\s*\{", text, re.M)
    if not match:
        raise ValueError("function not found: " + name)
    return text[match.start():balanced(text, text.index("{", match.start()))]


def actual_dsi_chain():
    for source in [DSI_SOURCE, HOST_SOURCE, DSI_HEADER, DISPLAY_HEADER]:
        locked = subprocess.run(["git", "-C", str(KERNEL), "show", COMMIT + ":" + source],
                                check=True, capture_output=True).stdout
        if locked != (KERNEL / source).read_bytes():
            raise ValueError("DSI dependency bytes differ from locked commit: " + source)
    header = (KERNEL / DSI_HEADER).read_text()
    dsi = (KERNEL / DSI_SOURCE).read_text()
    host = (KERNEL / HOST_SOURCE).read_text()
    blocks = [header[:header.index("#ifndef")]]
    blocks.append(declaration(header, "enum", "mipi_dsi_pixel_format"))
    for name in ["mipi_dsi_msg", "mipi_dsi_packet", "mipi_dsi_host_ops", "mipi_dsi_host", "mipi_dsi_device"]:
        blocks.append(declaration(header, "struct", name))
    blocks.append("struct dw_mipi_dsi { struct mipi_dsi_host dsi_host; struct dw_mipi_dsi *slave; struct device *dev; };")
    blocks.append(dsi[:dsi.index("#include")])
    blocks.extend(body(dsi, name) for name in DSI_FUNCTIONS)
    blocks.append(host[:host.index("#include")])
    blocks.append(body(host, "host_to_dsi"))
    blocks.append(body(host, "dw_mipi_dsi_host_transfer"))
    return "\n\n".join(blocks) + "\n"


def board_sequence():
    text = BOARD_DTS.read_text()
    match = re.search(r"panel-init-sequence\s*=\s*\[([^]]+)\]", text)
    data = bytes(int(token, 16) for token in match.group(1).split())
    commands = []
    position = 0
    while position < len(data):
        kind, delay, length = data[position:position + 3]
        if position + 3 + length > len(data):
            raise ValueError("incomplete board command")
        commands.append((kind, delay, length, position + 3))
        position += 3 + length
    if len(data) != 898 or len(commands) != 180:
        raise ValueError("board sequence changed: review the new fixture expectations")
    generated = "static u8 board_init_bytes[] = {" + ",".join(hex(value) for value in data) + "};\n"
    generated += "static struct panel_cmd_desc board_cmds[] = {\n"
    for kind, delay, length, offset in commands:
        generated += "    {{%d,%d,%d}, &board_init_bytes[%d]},\n" % (kind, delay, length, offset)
    generated += "};\nstatic struct panel_cmd_seq board_seq = {board_cmds, 180};\n"
    return data, generated


def run(command, output, label):
    result = subprocess.run([str(part) for part in command], capture_output=True, text=True)
    (output / (label + ".stdout")).write_text(result.stdout)
    (output / (label + ".stderr")).write_text(result.stderr)
    return {"command": [str(part) for part in command], "returncode": result.returncode,
            "stdout_sha256": sha(result.stdout.encode()), "stderr_sha256": sha(result.stderr.encode())}, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    raw = args.source.read_bytes()
    selected = extract(raw.decode())
    (output / "extracted.c").write_text(selected)
    for name in ["test-panel-shim.h", "test-panel-main.c", "test-panel-functions.py"]:
        (output / name).write_bytes((HERE / name).read_bytes())
    (output / "mipi_display.h").write_bytes((KERNEL / DISPLAY_HEADER).read_bytes())
    chain = actual_dsi_chain()
    board_bytes, fixture = board_sequence()
    (output / "dsi-chain.c").write_text(chain)
    combined = '#include "' + str(output / "test-panel-shim.h") + '"\n'
    combined += '#include "' + str(output / "mipi_display.h") + '"\n' + chain + selected
    combined += "\n" + fixture
    combined += '\n#include "' + str(output / "test-panel-main.c") + '"\n'
    translation = output / "test.c"
    translation.write_text(combined)
    result = {"source": str(args.source.resolve()), "source_sha256": sha(raw),
              "extracted_sha256": sha(selected.encode()), "functions": FUNCTIONS,
              "harness_sha256": {name: sha((HERE / name).read_bytes()) for name in
                                 ["test-panel-shim.h", "test-panel-main.c", "test-panel-functions.py"]},
              "dsi_chain": {"functions": DSI_FUNCTIONS + ["host_to_dsi", "dw_mipi_dsi_host_transfer"],
                            "source_commit": COMMIT,
                            "extracted_sha256": sha(chain.encode()),
                            "inputs_sha256": {name: sha((KERNEL / name).read_bytes()) for name in
                                               [DSI_SOURCE, HOST_SOURCE, DSI_HEADER, DISPLAY_HEADER]}},
              "board_fixture": {"dts": str(BOARD_DTS), "dts_sha256": sha(BOARD_DTS.read_bytes()),
                                "init_sequence_sha256": sha(board_bytes), "bytes": 898, "commands": 180},
              "boundary": "Verbatim panel and DSI API/packet/host-transfer functions. Fake only FIFO write/read/config and regulator/GPIO/delay/allocation boundaries. No MMIO, physical timing, DRM core/backlight or concurrent lifecycle validation. Generated DSI excerpts retain upstream GPL notices; panel source retains MIT notice.",
              "runs": {}}
    versions = {}
    for tool in ["gcc", "aarch64-linux-gnu-gcc", ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"]:
        completed = subprocess.run([str(tool), "--version"], check=True, capture_output=True, text=True)
        versions[str(tool)] = completed.stdout.splitlines()[0]
    result["tool_versions"] = versions
    failed = False
    for label, compiler, flags, launcher in [
        ("host", "gcc", [], []),
        ("host-sanitized", "gcc", ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"], []),
        ("aarch64", "aarch64-linux-gnu-gcc", ["-static"],
         [ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"]),
    ]:
        binary = output / ("test-" + label)
        compile_command = [compiler, "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
                           "-Wno-unused-parameter", "-Wno-sign-compare", *flags, translation, "-o", binary]
        build, completed = run(compile_command, output, label + "-compile")
        record = {"compile": build}
        if completed.returncode:
            failed = True
        else:
            execution, completed = run([*launcher, binary], output, label)
            record.update({"execution": execution, "binary_sha256": sha(binary.read_bytes())})
            try:
                record["tests"] = json.loads(completed.stdout)
            except json.JSONDecodeError as error:
                record["parse_error"] = str(error)
                failed = True
            elf = subprocess.run(["readelf", "-h", "-l", str(binary)], check=True, capture_output=True, text=True)
            (output / (label + ".elf.txt")).write_text(elf.stdout)
            record["elf_sha256"] = sha(elf.stdout.encode())
            if label == "aarch64":
                if "AArch64" not in elf.stdout or "INTERP" in elf.stdout:
                    raise ValueError("expected a static AArch64 executable")
                record["static_aarch64_confirmed"] = True
            failed |= completed.returncode != 0
        result["runs"][label] = record
    result["passed"] = not failed
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(output), "passed": not failed,
                      "tests": {key: {field: value.get("tests", {}).get(field) for field in
                                      ["total", "passed", "failed"]} for key, value in result["runs"].items()}}))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
