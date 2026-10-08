#!/usr/bin/env python3
"""Real I2S parameter callbacks and locked header excerpts, three execution modes."""
import argparse
import json
import re
import subprocess
from pathlib import Path
from source_utils import declaration, function, sha

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = "sound/soc/rockchip/rockchip_i2s_tdm.c"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", args.label):
        parser.error("label must be red-vN or green-vN")
    output = HERE / ("params-tests-" + args.label)
    output.mkdir(exist_ok=False)
    raw = (args.source_dir / SOURCE).read_bytes()
    source = raw.decode()
    inputs = HERE / "source-input-v1"
    headers = {p: (inputs / p).read_text() for p in ["include/sound/pcm.h", "include/sound/pcm_params.h", "include/sound/soc-dai.h", "include/sound/dmaengine_pcm.h", "include/uapi/sound/asound.h"]}
    abi = declaration(headers["include/sound/dmaengine_pcm.h"], "struct", "snd_dmaengine_dai_dma_data") + "\n"
    abi += declaration(headers["include/sound/soc-dai.h"], "struct", "snd_soc_dai") + "\n"
    abi += function(headers["include/sound/soc-dai.h"], "snd_soc_dai_get_drvdata") + "\n"
    abi += function(headers["include/sound/soc-dai.h"], "snd_soc_dai_get_dma_data") + "\n"
    for header, names in [("include/sound/pcm.h", ["hw_param_mask_c", "hw_param_interval_c", "params_channels", "params_rate"]), ("include/sound/pcm_params.h", ["snd_mask_min", "params_format"])]:
        abi += "\n".join(function(headers[header], n) for n in names) + "\n"
    asoc = (ROOT / "third_party/linux-rk3588/include/uapi/sound/asoc.h").read_bytes()
    defines = "".join(line for line in asoc.decode().splitlines(True) if line.startswith("#define SND_SOC_DAI_FORMAT_"))
    defines += "".join(line for line in headers["include/sound/soc-dai.h"].splitlines(True) if line.startswith("#define SND_SOC_DAIFMT_"))
    declarations = "\n".join(declaration(source, "struct", n) for n in ["txrx_config", "rk_i2s_soc_data", "rk_i2s_tdm_dev"])
    names = ["to_info", "rockchip_i2s_tdm_mclk_reparent", "rockchip_i2s_tdm_set_mclk", "rockchip_i2s_tdm_params_channels", "is_params_dirty", "rockchip_i2s_tdm_params_trcm", "rockchip_i2s_tdm_set_fmt", "rockchip_i2s_tdm_hw_params", "rockchip_i2s_tdm_set_sysclk", "rockchip_dai_tdm_slot"]
    if "static int i2s_checked_error_locked(" in source:
        names = ["i2s_checked_error_locked", "i2s_checked_gate_locked", "i2s_checked_params_dirty", "i2s_checked_params_trcm", "i2s_checked_set_fmt", "to_info", "rockchip_i2s_tdm_mclk_reparent", "rockchip_i2s_tdm_set_mclk", "rockchip_i2s_tdm_params_channels", "i2s_checked_hw_params", "is_params_dirty", "rockchip_i2s_tdm_params_trcm", "rockchip_i2s_tdm_set_fmt", "rockchip_i2s_tdm_hw_params", "rockchip_i2s_tdm_set_sysclk", "rockchip_dai_tdm_slot"]
    bodies = {name: function(source, name) for name in names}
    extracted = ("#define HAVE_CHECKED 1\n" if "checked_lifecycle;" in declarations else "") + declarations + "\n" + "\n\n".join(bodies.values()) + "\n"
    for name in ["test-params.py", "test-params-shim.h", "test-params-main.c", "source_utils.py"]:
        (output / name).write_bytes((HERE / name).read_bytes())
    (output / "source-input.c").write_bytes(raw)
    (output / "rockchip_i2s_tdm.h").write_bytes((inputs / "sound/soc/rockchip/rockchip_i2s_tdm.h").read_bytes())
    (output / "asound.h").write_bytes((inputs / "include/uapi/sound/asound.h").read_bytes())
    (output / "asoc-input.h").write_bytes(asoc)
    (output / "actual-abi.h").write_text(abi)
    (output / "actual-formats.h").write_text(defines)
    (output / "extracted.c").write_text(extracted)
    unit = output / "real-functions.c"
    unit.write_text('#include "test-params-shim.h"\n#include "actual-abi.h"\n' + extracted + '\n#include "test-params-main.c"\n')
    result = {"source_sha256": sha(raw), "extracted_sha256": sha(extracted.encode()), "functions_sha256": {n: sha(b.encode()) for n, b in bodies.items()}, "abi_sha256": sha(abi.encode()), "files_sha256": {p.name: sha(p.read_bytes()) for p in output.iterdir() if p.is_file()}, "board_tested": False,
              "boundary": "Actual device/DAI/DMA-data/UAPI declarations and callback bodies. device, PCM substream and IRQ/clock/regmap/spinlock APIs are explicit models, not full kernel ABI or hardware.", "runs": {}}
    failed = False
    def run(argv, label):
        c = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=30)
        (output / (label + ".stdout")).write_text(c.stdout)
        (output / (label + ".stderr")).write_text(c.stderr)
        return c, {"argv": [str(a) for a in argv], "exit_code": c.returncode, "stdout_sha256": sha(c.stdout.encode()), "stderr_sha256": sha(c.stderr.encode())}
    for label, compiler, flags, launcher in [("host", "gcc", [], []), ("host-sanitized", "gcc", ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"], []), ("aarch64", "aarch64-linux-gnu-gcc", ["-static"], [ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"])]:
        binary = output / ("params-" + label)
        c, compile_record = run([compiler, "-std=gnu11", "-O0", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-Wno-unused-function", "-pthread", *flags, unit, "-o", binary], label + "-compile")
        record = {"compile": compile_record, "compiler_version": subprocess.run([compiler, "--version"], check=True, capture_output=True, text=True).stdout.splitlines()[0]}
        if c.returncode:
            failed = True
        else:
            c, executed = run([*launcher, binary], label)
            record.update({"execution": executed, "binary_sha256": sha(binary.read_bytes()), "tests": json.loads(c.stdout)})
            failed |= c.returncode != 0
        result["runs"][label] = record
    result["passed"] = not failed
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"result": str(output / "result.json"), "runs": {n: r.get("tests", r["compile"]) for n, r in result["runs"].items()}, "passed": not failed}))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
