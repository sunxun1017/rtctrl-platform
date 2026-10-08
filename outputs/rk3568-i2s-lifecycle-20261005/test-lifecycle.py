#!/usr/bin/env python3
"""Extract real I2S trigger/helper chains and run forced-write/ownership faults."""
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
    parser.add_argument("--suite", choices=["lifecycle", "irq", "pm"], default="lifecycle")
    args = parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", args.label):
        parser.error("invalid label")
    output = HERE / (args.suite + "-tests-" + args.label)
    output.mkdir(exist_ok=False)
    raw = (args.source_dir / SOURCE).read_bytes()
    source = raw.decode()
    inputs = HERE / "source-input-v1"
    dai_header = (inputs / "include/sound/soc-dai.h").read_text()
    dma_header = (inputs / "include/sound/dmaengine_pcm.h").read_text()
    abi = declaration(dma_header, "struct", "snd_dmaengine_dai_dma_data") + "\n" + declaration(dai_header, "struct", "snd_soc_dai") + "\n" + function(dai_header, "snd_soc_dai_get_drvdata") + "\n"
    declarations = "\n".join(declaration(source, "struct", n) for n in ["txrx_config", "rk_i2s_soc_data", "rk_i2s_tdm_dev"])
    names = ["to_info", "rockchip_i2s_tdm_reset_assert", "rockchip_i2s_tdm_reset_deassert", "rockchip_i2s_tdm_sync_reset", "rockchip_i2s_tdm_reset", "rockchip_i2s_tdm_clear", "to_ch_num", "rockchip_i2s_tdm_tx_fifo_padding", "rockchip_i2s_tdm_fifo_xrun_detect", "rockchip_i2s_tdm_dma_ctrl", "rockchip_i2s_tdm_xfer_start", "rockchip_i2s_tdm_xfer_stop", "rockchip_i2s_tdm_xfer_trcm_start", "rockchip_i2s_tdm_xfer_trcm_stop", "rockchip_i2s_tdm_start", "rockchip_i2s_tdm_stop", "rockchip_i2s_tdm_trigger"]
    checked = "static int i2s_checked_trigger(" in source
    if checked:
        names = ["i2s_checked_error_locked", "i2s_checked_gate_locked", "i2s_checked_first_error", "i2s_checked_clear_locked", "i2s_checked_irq_locked", "i2s_checked_dma_locked", "i2s_checked_stop_locked", "i2s_checked_start_locked", "i2s_checked_trigger", *names]
    irq_checked = "static irqreturn_t i2s_checked_isr(" in source
    if args.suite == "irq":
        if irq_checked:
            names += ["i2s_checked_prepare", "i2s_checked_component_trigger", "i2s_checked_isr"]
        names += ["rockchip_i2s_tdm_startup", "rockchip_i2s_tdm_shutdown", "rockchip_i2s_tdm_isr"]
    pm_checked = "static int i2s_checked_runtime_suspend(" in source
    if args.suite == "pm":
        if pm_checked:
            names += ["i2s_checked_failstop", "i2s_checked_runtime_suspend", "i2s_checked_runtime_resume", "i2s_checked_quiesce", "i2s_checked_probe_clock_release"]
        names += ["rockchip_i2s_tdm_pinctrl_select_clk_state", "i2s_tdm_runtime_suspend", "i2s_tdm_runtime_resume", "rockchip_i2s_tdm_remove", "rockchip_i2s_tdm_platform_shutdown", "rockchip_i2s_tdm_suspend", "rockchip_i2s_tdm_resume"]
    bodies = {n: function(source, n) for n in names}
    extracted = ("#define HAVE_READBACK 1\n" if "void __iomem *regs;" in declarations else "") + ("#define HAVE_CHECKED_PM 1\n" if pm_checked else "") + ("#define HAVE_CHECKED_IRQ 1\n" if irq_checked else "") + ("#define HAVE_CHECKED_TRIGGER 1\n" if checked else "") + ("#define HAVE_CHECKED_FIELDS 1\n" if "checked_lifecycle;" in declarations else "") + declarations + "\n" + "\n\n".join(bodies.values()) + "\n"
    main_file = {"irq": "test-irq-main.c", "pm": "test-pm-main.c"}.get(args.suite, "test-lifecycle-main.c")
    for name in ["test-lifecycle.py", "test-lifecycle-shim.h", main_file, "source_utils.py"]:
        (output / name).write_bytes((HERE / name).read_bytes())
    (output / "source-input.c").write_bytes(raw)
    (output / "actual-abi.h").write_text(abi)
    (output / "extracted.c").write_text(extracted)
    (output / "rockchip_i2s_tdm.h").write_bytes((inputs / "sound/soc/rockchip/rockchip_i2s_tdm.h").read_bytes())
    unit = output / "real-functions.c"
    unit.write_text('#include "test-lifecycle-shim.h"\n#include "actual-abi.h"\n' + extracted + '\n#include "' + main_file + '"\n')
    result = {"source_sha256": sha(raw), "extracted_sha256": sha(extracted.encode()), "functions_sha256": {n: sha(b.encode()) for n, b in bodies.items()}, "files_sha256": {p.name: sha(p.read_bytes()) for p in output.iterdir() if p.is_file()}, "board_tested": False, "boundary": "Actual trigger and helper bodies; regmap cache-before-write/forced MMIO, clocks, spinlock and FIFO poll are boundary models; no hardware or full-duplex acceptance", "runs": {}}
    failed = False
    def run(argv, label):
        c = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=30)
        (output / (label + ".stdout")).write_text(c.stdout)
        (output / (label + ".stderr")).write_text(c.stderr)
        return c, {"argv": [str(a) for a in argv], "exit_code": c.returncode, "stdout_sha256": sha(c.stdout.encode()), "stderr_sha256": sha(c.stderr.encode())}
    for label, compiler, flags, launcher in [("host", "gcc", [], []), ("host-sanitized", "gcc", ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"], []), ("aarch64", "aarch64-linux-gnu-gcc", ["-static"], [ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"])]:
        binary = output / ("lifecycle-" + label)
        c, compile_record = run([compiler, "-std=gnu11", "-O0", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-Wno-unused-function", "-pthread", *flags, unit, "-o", binary], label + "-compile")
        record = {"compile": compile_record}
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
