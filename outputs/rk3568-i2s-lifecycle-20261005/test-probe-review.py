#!/usr/bin/env python3
"""Run complete real probe, actual descriptors, reverse devres and PM nesting."""
import argparse
import json
import re
import subprocess
from pathlib import Path
from source_utils import declaration, function, sha

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = "sound/soc/rockchip/rockchip_i2s_tdm.c"


def table(source, name):
    return re.search(r"^static const struct [^\n]+ " + name + r"(?:\[\])?\s*=\s*\{.*?^\};", source, re.M | re.S).group()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", args.label):
        parser.error("invalid label")
    output = HERE / ("probe-review-tests-" + args.label)
    output.mkdir(exist_ok=False)
    raw = (args.source_dir / SOURCE).read_bytes()
    source = raw.decode()
    declarations = "\n".join(declaration(source, "struct", n) for n in ["txrx_config", "rk_i2s_soc_data", "rk_i2s_tdm_dev"])
    inputs = HERE / "source-input-v1"
    dai = (inputs / "include/sound/soc-dai.h").read_text()
    dma = (inputs / "include/sound/dmaengine_pcm.h").read_text()
    abi = declaration(dma, "struct", "snd_dmaengine_dai_dma_data") + "\n" + declaration(dai, "struct", "snd_soc_dai") + "\n" + function(dai, "snd_soc_dai_get_drvdata") + "\n"
    names = ["to_info", "i2s_checked_error_locked", "i2s_checked_gate_locked", "i2s_checked_first_error", "i2s_checked_clear_locked", "i2s_checked_irq_locked", "i2s_checked_dma_locked", "i2s_checked_stop_locked", "i2s_checked_start_locked", "i2s_checked_trigger", "i2s_checked_failstop", "i2s_checked_runtime_suspend", "i2s_checked_runtime_resume", "i2s_checked_quiesce", "i2s_checked_probe_clock_release", "rockchip_i2s_tdm_pinctrl_select_clk_state", "i2s_tdm_runtime_suspend", "i2s_tdm_runtime_resume", "i2s_checked_set_fmt", "i2s_checked_prepare", "i2s_checked_component_trigger", "rockchip_i2s_tdm_startup", "rockchip_i2s_tdm_shutdown", "i2s_checked_isr", "common_soc_init", "i2s_checked_profile", "i2s_checked_initial_config", "rk3568_lifecycle_state_show", "rockchip_i2s_tdm_loopback_get", "rockchip_i2s_tdm_loopback_put", "rockchip_i2s_tdm_dai_probe", "rockchip_i2s_tdm_dai_prepare", "rockchip_i2s_tdm_probe", "rockchip_i2s_tdm_remove", "rockchip_i2s_tdm_platform_shutdown"]
    bodies = {n: function(source, n) for n in names}
    tables = {name: table(source, name) for name in ["rockchip_i2s_tdm_snd_controls", "rockchip_i2s_tdm_component", "rk3568_txrx_config", "rk3568_i2s_soc_data"]}
    if "rockchip_i2s_tdm_checked_component" in source:
        tables["rockchip_i2s_tdm_checked_component"] = table(source, "rockchip_i2s_tdm_checked_component")
    actual = declarations + "\n" + "\n\n".join(bodies.values()) + "\n" + "\n\n".join(tables.values()) + "\n"
    # Complete probe is declared first, but defined after actual descriptors.
    before_probe = "\n\n".join(b for n, b in bodies.items() if n != "rockchip_i2s_tdm_probe")
    unit = '#include "probe-review-shim.h"\n#include "actual-abi.h"\n' + declarations + '\n#include "probe-review-adapter.h"\n' + before_probe + "\n" + "\n\n".join(tables.values()) + "\n" + bodies["rockchip_i2s_tdm_probe"] + '\n#include "probe-review-main.c"\n'
    for name in ["test-probe-review.py", "probe-review-shim.h", "probe-review-adapter.h", "probe-review-main.c", "source_utils.py"]:
        (output / name).write_bytes((HERE / name).read_bytes())
    (output / "baseline-lifecycle-shim.h").write_bytes((HERE / "test-lifecycle-shim.h").read_bytes())
    (output / "source-input.c").write_bytes(raw)
    (output / "actual-abi.h").write_text(abi)
    (output / "extracted.c").write_text(actual)
    (output / "real-functions.c").write_text(unit)
    (output / "rockchip_i2s_tdm.h").write_bytes((inputs / "sound/soc/rockchip/rockchip_i2s_tdm.h").read_bytes())
    record = {"source_sha256": sha(raw), "functions_sha256": {n: sha(b.encode()) for n, b in bodies.items()}, "tables_sha256": {n: sha(t.encode()) for n, t in tables.items()}, "files_sha256": {p.name: sha(p.read_bytes()) for p in output.iterdir() if p.is_file()}, "boundary": "Whole production probe/remove/PM/startup/ISR/descriptor bodies; OF, ALSA registration, CCF consumer handles, devres reverse order and serialized/asynchronous PM-core APIs are explicit models, not full-kernel/hardware/C3 acceptance", "board_tested": False, "runs": {}}
    failed = False
    def run(argv, label):
        result = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=40)
        (output / (label + ".stdout")).write_text(result.stdout)
        (output / (label + ".stderr")).write_text(result.stderr)
        return result, {"argv": [str(a) for a in argv], "exit_code": result.returncode, "stdout_sha256": sha(result.stdout.encode()), "stderr_sha256": sha(result.stderr.encode())}
    for mode, compiler, flags, launcher in [("host", "gcc", [], []), ("host-sanitized", "gcc", ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"], []), ("aarch64", "aarch64-linux-gnu-gcc", ["-static"], [ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"])]:
        binary = output / ("probe-" + mode)
        built, compiled = run([compiler, "-std=gnu11", "-O0", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-Wno-unused-function", "-Wno-unused-variable", "-Wno-sign-compare", "-Wno-type-limits", "-Wno-pointer-sign", "-pthread", *flags, output / "real-functions.c", "-o", binary], mode + "-compile")
        item = {"compile": compiled, "cases": {}}
        if built.returncode:
            failed = True
        else:
            item["binary_sha256"] = sha(binary.read_bytes())
            for case in ["partial", "late-fault", "ready", "controls", "nested", "nested-errors", "irq-exit", "pm-exit"]:
                executed, receipt = run([*launcher, binary, case], mode + "-" + case)
                try:
                    receipt["tests"] = json.loads(executed.stdout)
                except json.JSONDecodeError:
                    receipt["tests"] = None
                failed |= executed.returncode != 0
                item["cases"][case] = receipt
        record["runs"][mode] = item
    record["passed"] = not failed
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"result": str(output / "result.json"), "passed": record["passed"], "runs": {m: {"compile": r["compile"]["exit_code"], "cases": {n: {"exit": c["exit_code"], "tests": c["tests"]} for n, c in r["cases"].items()}} for m, r in record["runs"].items()}}))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
