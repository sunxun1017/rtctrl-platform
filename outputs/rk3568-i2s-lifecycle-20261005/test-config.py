#!/usr/bin/env python3
"""Real probe initial-register block, SoC init, profile and readonly state."""
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
        parser.error("invalid label")
    raw = (args.source_dir / SOURCE).read_bytes()
    source = raw.decode()
    output = HERE / ("config-tests-" + args.label)
    output.mkdir(exist_ok=False)
    declarations = "\n".join(declaration(source, "struct", n) for n in ["txrx_config", "rk_i2s_soc_data", "rk_i2s_tdm_dev"])
    dma_header = (HERE / "source-input-v1/include/sound/dmaengine_pcm.h").read_text()
    abi = declaration(dma_header, "struct", "snd_dmaengine_dai_dma_data")
    bodies = {"common_soc_init": function(source, "common_soc_init")}
    checked = "static int i2s_checked_initial_config(" in source
    if checked:
        for name in ["i2s_checked_profile", "i2s_checked_initial_config", "rk3568_lifecycle_state_show"]:
            bodies[name] = function(source, name)
    probe = function(source, "rockchip_i2s_tdm_probe")
    start = probe.index("\tdev_set_drvdata(&pdev->dev, i2s_tdm);") + len("\tdev_set_drvdata(&pdev->dev, i2s_tdm);")
    end = probe.index("\n\n\t/*\n\t * CLK_ALWAYS_ON", start)
    block = probe[start:end]
    configs = re.search(r"^static const struct txrx_config rk3568_txrx_config\[\].*?\n\};", source, re.M | re.S).group()
    soc = re.search(r"^static const struct rk_i2s_soc_data rk3568_i2s_soc_data = \{.*?\n\};", source, re.M | re.S).group()
    actual = ("#define HAVE_CONFIG_CHECKED 1\n" if checked else "") + "\n" + declarations + "\n" + "\n\n".join(bodies.values()) + "\n" + configs + "\n" + soc + "\n"
    actual += 'static int real_probe_initial_block(struct platform_device *pdev, struct rk_i2s_tdm_dev *i2s_tdm)\n{\n struct resource *res = pdev->resource;\n int ret __attribute__((unused));\n' + block + '\n return 0;\n}\n'
    for name in ["test-config.py", "test-config-shim.h", "test-config-main.c", "test-lifecycle-shim.h", "source_utils.py"]:
        (output / name).write_bytes((HERE / name).read_bytes())
    (output / "source-input.c").write_bytes(raw)
    (output / "actual-abi.h").write_text(abi)
    (output / "extracted.c").write_text(actual)
    (output / "rockchip_i2s_tdm.h").write_bytes((HERE / "source-input-v1/sound/soc/rockchip/rockchip_i2s_tdm.h").read_bytes())
    unit = output / "real-functions.c"
    unit.write_text('#include "test-config-shim.h"\n#include "actual-abi.h"\n' + actual + '\n#include "test-config-main.c"\n')
    result = {"source_sha256": sha(raw), "probe_block_sha256": sha(block.encode()), "functions_sha256": {n: sha(b.encode()) for n, b in bodies.items()}, "files_sha256": {p.name: sha(p.read_bytes()) for p in output.iterdir() if p.is_file()}, "board_tested": False,
              "boundary": "Byte-exact initial configuration block from production probe and real SoC/profile/state functions. Not full devres/ALSA registration probe simulation. OF/resource/regmap/sysfs APIs modeled.", "runs": {}}
    failed = False
    def run(argv, label):
        c = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=30)
        (output / (label + ".stdout")).write_text(c.stdout)
        (output / (label + ".stderr")).write_text(c.stderr)
        return c, {"argv": [str(a) for a in argv], "exit_code": c.returncode, "stdout_sha256": sha(c.stdout.encode()), "stderr_sha256": sha(c.stderr.encode())}
    for label, compiler, flags, launcher in [("host", "gcc", [], []), ("host-sanitized", "gcc", ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"], []), ("aarch64", "aarch64-linux-gnu-gcc", ["-static"], [ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"])]:
        binary = output / ("config-" + label)
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
