#!/usr/bin/env python3
"""Compile verbatim locked ASoC/PCM chains with callback and kernel API boundaries."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / "third_party/linux-rk3588"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
SOC = "sound/soc/soc-pcm.c"
PCM = "sound/core/pcm_native.c"
DAI = "sound/soc/soc-dai.c"
DH = "include/sound/soc-dai.h"
PH = "include/sound/pcm.h"
SH = "include/sound/soc.h"
QEMU = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def locked(relative):
    return subprocess.run(["git", "-C", KERNEL, "show", COMMIT + ":" + relative],
                          check=True, capture_output=True).stdout


def function(source, name):
    match = re.search(r"^(?:[A-Za-z_][A-Za-z_0-9 \t*]*[ \t*])?" + name + r"\([^;{}]*?\)\s*\{", source, re.M)
    if not match:
        raise ValueError("missing function " + name)
    start = match.start()
    # Kernel places a pointer/unsigned return type on its own preceding line.
    if source[start:match.end()].lstrip().startswith(name + "("):
        start = source.rfind("\n", 0, start - 1) + 1
    depth = 0
    for i in range(source.index("{", match.start()), len(source)):
        depth += (source[i] == "{") - (source[i] == "}")
        if depth == 0:
            return source[start:i + 1]
    raise ValueError("unclosed function " + name)


def macro(source, name):
    match = re.search(r"^#define " + name + r"\b[^\n]*(?:\n[^\n]*)?", source, re.M)
    if not match:
        raise ValueError("missing macro " + name)
    lines = source[match.start():].splitlines(True)
    result = []
    for line in lines:
        result.append(line)
        if not line.rstrip().endswith("\\"):
            break
    return "".join(result).rstrip()


def declaration(source, name):
    return re.search(r"^(?:static const )?struct " + name + r"\s*(?:=\s*)?\{.*?^\};",
                     source, re.M | re.S).group()


def run(argv, output, name):
    result = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=45)
    (output / (name + ".stdout")).write_text(result.stdout)
    (output / (name + ".stderr")).write_text(result.stderr)
    return result, {"argv": [str(a) for a in argv], "returncode": result.returncode,
                    "stdout_sha256": sha(result.stdout.encode()), "stderr_sha256": sha(result.stderr.encode())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", args.label):
        parser.error("label must be red-vN or green-vN")
    output = HERE / ("asoc-tests-" + args.label)
    output.mkdir(exist_ok=False)
    sources = {relative: ((args.source_dir / relative).read_bytes() if relative in [SOC, PCM]
                          else locked(relative)) for relative in [SOC, PCM, DAI, DH, PH, SH]}
    records = []
    parts = []
    for relative, data in sources.items():
        dest = output / "source-inputs" / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    texts = {relative: data.decode() for relative, data in sources.items()}

    def add(relative, name, kind="function"):
        text = {"function": function, "macro": macro, "declaration": declaration}[kind](texts[relative], name)
        parts.append(text)
        records.append({"file": relative, "name": name, "kind": kind, "sha256": sha(text.encode())})

    for relative in [SOC, PCM, DAI]:
        parts.append(texts[relative][:texts[relative].index("#include")])
    for relative, name in [(PH, "snd_pcm_substream_chip"), (PH, "for_each_pcm_streams"),
                           (SH, "asoc_substream_to_rtd"), (SH, "for_each_rtd_dais")]:
        add(relative, name, "macro")
    for relative, names in [
        (DH, ["snd_soc_dai_get_pcm_stream", "snd_soc_dai_stream_active"]),
        (PH, ["snd_pcm_stream_linked", "snd_pcm_running", "snd_pcm_playback_avail", "snd_pcm_playback_data"]),
        (DAI, ["_soc_dai_ret", "snd_soc_dai_digital_mute", "snd_soc_pcm_dai_prepare",
               "snd_soc_dai_active", "snd_soc_dai_stream_valid", "snd_soc_dai_hw_free"]),
    ]:
        for name in names:
            add(relative, name)
    parts.append("#define soc_dai_ret(dai, ret) _soc_dai_ret(dai, __func__, ret)")
    # The macro is needed above its real consumers.
    index = next(i for i, text in enumerate(parts) if text.startswith("int snd_soc_dai_digital_mute"))
    parts.insert(index, parts.pop())
    if "static bool soc_pcm_has_mute(" in texts[SOC]:
        add(SOC, "soc_pcm_has_mute")
    for name in ["soc_pcm_prepare", "soc_pcm_hw_free"]:
        add(SOC, name)
    for name in ["snd_pcm_ops_ioctl", "snd_pcm_set_state", "snd_pcm_sync_stop", "do_hw_free", "snd_pcm_hw_free",
                 "snd_pcm_trigger_tstamp"]:
        add(PCM, name)
    add(PCM, "action_ops", "declaration")
    for name in ["snd_pcm_action_group", "snd_pcm_action_single", "snd_pcm_action", "snd_pcm_action_nonatomic",
                 "snd_pcm_pre_start", "snd_pcm_do_start", "snd_pcm_undo_start", "snd_pcm_post_start"]:
        add(PCM, name)
    add(PCM, "action_ops snd_pcm_action_start", "declaration")
    add(PCM, "snd_pcm_start")
    for name in ["snd_pcm_do_reset", "snd_pcm_pre_prepare", "snd_pcm_do_prepare", "snd_pcm_post_prepare"]:
        add(PCM, name)
    add(PCM, "action_ops snd_pcm_action_prepare", "declaration")
    add(PCM, "snd_pcm_prepare")
    extracted = "\n\n".join(parts) + "\n"
    for name in ["test-asoc-shim.h", "test-asoc-main.c", "test-asoc-functions.py"]:
        (output / name).write_bytes((HERE / name).read_bytes())
    (output / "extracted.c").write_text(extracted)
    unit = output / "real-functions.c"
    unit.write_text('#include "test-asoc-shim.h"\n' + extracted + '\n#include "test-asoc-main.c"\n')
    result = {"kernel_commit": COMMIT, "source_dir": str(args.source_dir.resolve()),
              "source_sha256": {relative: sha(data) for relative, data in sources.items()},
              "excerpts": records, "extracted_sha256": sha(extracted.encode()),
              "unit_sha256": sha(unit.read_bytes()),
              "harness_sha256": {name: sha((output / name).read_bytes()) for name in
                                 ["test-asoc-shim.h", "test-asoc-main.c", "test-asoc-functions.py"]},
              "board_tested": False, "linked_pcm_tested": False,
              "boundary": "Verbatim ASoC/DAI/PCM prepare, hw_free, state, single-action/START chain; fake callbacks, DAPM events, locks/group references, buffer/QoS and timing. No codec/DMA/electrical or linked-PCM transaction validation.", "runs": {}}
    failed = False
    for label, compiler, flags, launcher in [
        ("host", "gcc", [], []),
        ("host-sanitized", "gcc", ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"], []),
        ("aarch64", "aarch64-linux-gnu-gcc", ["-static"], [QEMU]),
    ]:
        binary = output / ("asoc-" + label)
        completed, compiled = run([compiler, "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                                   *flags, unit, "-o", binary], output, label + "-compile")
        record = {"compile": compiled,
                  "compiler_version": subprocess.run([compiler, "--version"], check=True, capture_output=True, text=True).stdout.splitlines()[0]}
        if completed.returncode:
            failed = True
        else:
            completed, execution = run([*launcher, binary], output, label)
            record.update({"execution": execution, "binary_sha256": sha(binary.read_bytes())})
            record["tests"] = json.loads(completed.stdout)
            failed |= completed.returncode != 0
            elf = subprocess.run(["readelf", "-h", "-l", binary], check=True, capture_output=True).stdout
            (output / (label + ".elf.txt")).write_bytes(elf)
            record["elf_sha256"] = sha(elf)
        result["runs"][label] = record
    result["passed"] = not failed
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"result": str(output / "result.json"), "passed": not failed,
                      "runs": {k: v.get("tests", v["compile"]) for k, v in result["runs"].items()}}))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
