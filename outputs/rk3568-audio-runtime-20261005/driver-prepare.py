#!/usr/bin/env python3
"""Add fail-stop PCM configuration to the verified registration patch."""
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / "outputs/rk3568-audio-20261005"
BASE = OLD / "driver-source-v5"
SOURCE = "sound/soc/codecs/rk817_codec.c"
HEADER = "sound/soc/codecs/rk817_codec.h"
BASE_SHA = "210104c9c6014a50d3486398d081e760e08f3e7fb84fe19cde2119993131bed7"
PATCH = ROOT / "platforms/rk3568/boards/aiot-3568pq/patches/0007-rk817-pcm-configuration-errors.patch"
spec = importlib.util.spec_from_file_location("probe_fix", OLD / "driver-prepare.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def checked_calls(body):
    pattern = r"^(\t+)(snd_soc_component_(?:write|update_bits)|rk817_restart_[a-z_]+)\((.*?);"
    def change(match):
        indent, name, arguments = match.groups()
        return (indent + "ret = " + name + "(" + arguments + ";\n" + indent +
                "if (ret < 0)\n" + indent + "\treturn ret;")
    return re.sub(pattern, change, body, flags=re.M | re.S)

def candidate(text):
    names = ["rk817_restart_dac_digital_clk", "rk817_restart_dac_digital_clk_and_apll",
             "rk817_restart_adc_digital_clk", "rk817_restart_adc_digital_clk_and_apll"]
    for name in names:
        old = helper.function(text, name)
        body = old.replace("{\n", "{\n\tint ret;\n\n", 1)
        text = helper.replace(text, old, checked_calls(body))
    old = helper.function(text, "rk817_hw_params")
    body = old
    start = body.index("\tif (rk817->chip_ver <= 0x4)")
    end = body.index("\n\tswitch (rate)", start)
    chip = body[start:end]
    body = body[:start] + body[end:]
    start = body.index("\tswitch (params_format(params))")
    end = body.index("\n\treturn 0;", start)
    body = body[:start] + """\tret = snd_soc_component_write(component, RK817_CODEC_DI2S_RXCR2, rx_width);
\tif (ret < 0)
\t\treturn ret;
\tret = snd_soc_component_write(component, RK817_CODEC_DI2S_TXCR2, tx_width);
\treturn ret < 0 ? ret : 0;
}"""
    body = helper.replace(body, "\tunsigned char dtop_digen_sr_lmt0;", """\tunsigned char dtop_digen_sr_lmt0;
\tunsigned int rx_width;
\tunsigned int tx_width;
\tint ret;""")
    position = body.index("\tDBG(")
    body = body[:position] + """\t/* Reject unsupported parameters before any codec register operation. */
\tif (substream->stream != SNDRV_PCM_STREAM_PLAYBACK &&
\t    substream->stream != SNDRV_PCM_STREAM_CAPTURE)
\t\treturn -EINVAL;
\tswitch (params_format(params)) {
\tcase SNDRV_PCM_FORMAT_S16_LE:
\t\trx_width = VDW_RX_16BITS;
\t\ttx_width = VDW_TX_16BITS;
\t\tbreak;
\tcase SNDRV_PCM_FORMAT_S24_LE:
\tcase SNDRV_PCM_FORMAT_S32_LE:
\t\trx_width = VDW_RX_24BITS;
\t\ttx_width = VDW_TX_24BITS;
\t\tbreak;
\tdefault:
\t\treturn -EINVAL;
\t}

""" + body[position:]
    position = body.index("\n\t/**")
    body = body[:position] + "\n" + chip + "\n" + body[position:]
    # Give conditional helper calls braces before appending error checks.
    body = helper.replace(body,
                          "\t\tif (substream->stream == SNDRV_PCM_STREAM_PLAYBACK)\n"
                          "\t\t\trk817_restart_dac_digital_clk_and_apll(component);\n"
                          "\t\telse\n\t\t\trk817_restart_adc_digital_clk_and_apll(component);",
                          "\t\tif (substream->stream == SNDRV_PCM_STREAM_PLAYBACK) {\n"
                          "\t\t\trk817_restart_dac_digital_clk_and_apll(component);\n"
                          "\t\t} else {\n\t\t\trk817_restart_adc_digital_clk_and_apll(component);\n\t\t}")
    body = checked_calls(body)
    text = helper.replace(text, old, body)
    return helper.replace(text, "\t\t\tSNDRV_PCM_FMTBIT_S20_3LE |\\\n", "")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / ("driver-source-" + args.version)
    helper.new_output(output)
    if sha(BASE / SOURCE) != BASE_SHA:
        raise ValueError("Verified registration candidate changed")
    if helper.command(["git", "-C", str(helper.KERNEL), "rev-parse", "HEAD"]) != helper.COMMIT:
        raise ValueError("Wrong locked kernel")
    if helper.command(["git", "-C", str(helper.KERNEL), "status", "--porcelain"]):
        raise ValueError("Locked kernel must be clean")
    before = (BASE / SOURCE).read_text()
    after = candidate(before)
    patch = "diff --git a/" + SOURCE + " b/" + SOURCE + "\n"
    patch += "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                          fromfile="a/" + SOURCE, tofile="b/" + SOURCE))
    if PATCH.exists() and PATCH.read_bytes() != patch.encode():
        raise ValueError("Refuse replacing existing different public patch")
    output.mkdir()
    for relative, data in [(SOURCE, after.encode()), (HEADER, (BASE / HEADER).read_bytes())]:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if not PATCH.exists():
        with PATCH.open("xb") as stream:
            stream.write(patch.encode())
    manifest = {"source_commit": helper.COMMIT, "base_sha256": BASE_SHA,
                "sources": {relative: sha(output / relative) for relative in [SOURCE, HEADER]},
                "patch_sha256": sha(PATCH), "patch_requires": "0006-rk817-codec-error-propagation.patch",
                "fix_scope": "hw_params validation and first errno, four restart callbacks, remove unimplemented S20_3LE claim",
                "io_failure_policy": "stop at first error; partial hardware and parent regcache state unknown; no automatic retry",
                "shared_regmap_cache_mode_changed": False, "board_tested": False,
                "unfixed": ["path controls", "mute return handling in ASoC core", "suspend/resume", "concurrent remove"]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output), "source_sha256": sha(output / SOURCE), "patch_sha256": sha(PATCH)}))

if __name__ == "__main__":
    main()
