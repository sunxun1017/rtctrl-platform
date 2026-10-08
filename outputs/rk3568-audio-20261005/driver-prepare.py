#!/usr/bin/env python3
"""Prepare a bounded RK817 registration fix without modifying locked kernel sources."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / "third_party/linux-rk3588"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
PATCH = ROOT / "platforms/rk3568/boards/aiot-3568pq/patches/0006-rk817-codec-error-propagation.patch"
SOURCE = "sound/soc/codecs/rk817_codec.c"
HEADER = "sound/soc/codecs/rk817_codec.h"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv):
    return subprocess.check_output(argv, text=True).strip()


def boundary(path):
    if path.is_symlink():
        raise ValueError("Refuse symlink output: " + str(path))
    for parent in path.parents:
        if parent == ROOT:
            break
        if parent.is_symlink():
            raise ValueError("Refuse symlink output parent: " + str(parent))
    else:
        raise ValueError("Output escaped repository")
    path.resolve().relative_to(ROOT)


def new_output(path):
    boundary(path)
    if path.exists():
        raise ValueError("Refuse existing output: " + str(path))


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Locked source pattern changed: " + repr(old))
    return text.replace(old, new)


def function(text, name):
    match = re.search(r"^static (?:int|void) " + re.escape(name) + r"\([^;]*?\)\s*\{", text, re.M)
    if not match:
        raise ValueError("Missing real function: " + name)
    offset = text.index("{", match.start()) + 1
    depth = 1
    while depth:
        depth += (text[offset] == "{") - (text[offset] == "}")
        offset += 1
    return text[match.start():offset]


def candidate(text):
    old = function(text, "rk817_reset")
    reset = replace(old, "\tstruct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(component);",
                    "\tstruct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(component);\n\tint ret;")
    reset, count = re.subn(r"^(\t+)snd_soc_component_write\(([^;]+)\);",
                          lambda match: match[1] + "ret = snd_soc_component_write(" + match[2] + ");\n" +
                          match[1] + "if (ret < 0)\n" + match[1] + "\treturn ret;", reset, flags=re.M)
    if count != 14:
        raise ValueError("Unexpected reset write count")
    text = replace(text, old, reset)
    old = function(text, "rk817_probe")
    probe = """static int rk817_probe(struct snd_soc_component *component)
{
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(component);
	unsigned int chip_name;
	unsigned int chip_ver;
	int ret;

	if (!rk817)
		return -EINVAL;

    /* The parent PMIC owns this map; the component only borrows it. */
	snd_soc_component_init_regmap(component, rk817->regmap);
	rk817->component = component;
	rk817->playback_path = OFF;
	rk817->capture_path = MIC_OFF;
	rk817->clk_capture = 0;
	rk817->clk_playback = 0;

	ret = regmap_read(rk817->regmap, RK817_PMIC_CHIP_NAME, &chip_name);
	if (ret < 0)
		goto err_detach_regmap;
	ret = regmap_read(rk817->regmap, RK817_PMIC_CHIP_VER, &chip_ver);
	if (ret < 0)
		goto err_detach_regmap;
	rk817->chip_ver = chip_ver & 0x0f;
	dev_info(component->dev, "%s: chip_name:0x%x, chip_ver:0x%x\\n",
		 __func__, chip_name, chip_ver);

	/* Hold this clock reference until remove, or undo it on probe failure. */
	ret = clk_prepare_enable(rk817->mclk);
	if (ret < 0)
		goto err_detach_regmap;
	ret = rk817_reset(component);
	if (ret < 0)
		goto err_disable_clock;

	mutex_init(&rk817->clk_lock);
	ret = snd_soc_add_component_controls(component, rk817_snd_path_controls,
					     ARRAY_SIZE(rk817_snd_path_controls));
	if (ret < 0)
		goto err_destroy_mutex;
	return 0;

err_destroy_mutex:
	mutex_destroy(&rk817->clk_lock);
err_disable_clock:
	clk_disable_unprepare(rk817->mclk);
err_detach_regmap:
    /* The PMIC also uses this map; detach without releasing its ownership. */
	component->regmap = NULL;
	rk817->component = NULL;
	return ret;
}"""
    text = replace(text, old, probe)
    old = function(text, "rk817_remove")
    remove = replace(old, "\tsnd_soc_component_exit_regmap(component);",
                     "\t/* The parent PMIC retains ownership of its regmap. */\n"
                     "\tcomponent->regmap = NULL;\n\trk817->component = NULL;")
    text = replace(text, old, remove)
    old = function(text, "rk817_codec_parse_dt_property")
    dt = old
    for name in ["hp", "spk"]:
        token = "\tif (!IS_ERR_OR_NULL(rk817->" + name + "_ctl_gpio)) {"
        guard = "\tif (IS_ERR(rk817->" + name + "_ctl_gpio)) {\n"
        guard += "\t\tret = PTR_ERR(rk817->" + name + "_ctl_gpio);\n"
        guard += "\t\trk817->" + name + "_ctl_gpio = NULL;\n\t\tgoto out_put_node;\n\t}\n"
        dt = replace(dt, token, guard + token)
    dt = replace(dt, "\treturn 0;\n}", "\tret = 0;\nout_put_node:\n\tof_node_put(node);\n\treturn ret;\n}")
    text = replace(text, old, dt)
    old = function(text, "rk817_platform_probe")
    platform = replace(old, "\t\tret = -ENXIO;", "\t\tret = PTR_ERR(rk817_codec_data->mclk);")
    platform = replace(platform, "err_:\n\n\treturn ret;", "err_:\n\tplatform_set_drvdata(pdev, NULL);\n\treturn ret;")
    begin = platform.index("\trk817_codec_data->regmap = devm_regmap_init_i2c(")
    end = platform.index("\n\tret = devm_snd_soc_register_component(", begin)
    platform = platform[:begin] + """	rk817_codec_data->mclk = devm_clk_get(&pdev->dev, "mclk");
	if (IS_ERR(rk817_codec_data->mclk)) {
		ret = PTR_ERR(rk817_codec_data->mclk);
		dev_err(&pdev->dev, "Unable to get mclk: %d\\n", ret);
		goto err_;
	}

    /* Borrow the MFD's original map; never create a second I2C lookup. */
    rk817_codec_data->regmap = rk817->regmap;
	if (IS_ERR(rk817_codec_data->regmap)) {
		ret = PTR_ERR(rk817_codec_data->regmap);
        goto err_;
    }
    if (!rk817_codec_data->regmap) {
        ret = -ENODEV;
        goto err_;
    }
""" + platform[end:]
    text = replace(text, old, platform)
    begin = text.index("static const struct reg_default rk817_reg_defaults[] = {")
    end = text.index("static int rk817_codec_ctl_gpio", begin)
    text = text[:begin] + text[end:]
    begin = text.index("static const struct regmap_config rk817_codec_regmap_config = {")
    end = text.index("static int rk817_platform_probe", begin)
    text = text[:begin] + text[end:]
    old = function(text, "rk817_set_dai_fmt")
    fmt = replace(old, "\tunsigned int i2s_mst = 0;", "\tunsigned int i2s_mst = 0;\n\tint ret;")
    fmt = replace(fmt, "\tsnd_soc_component_update_bits(component, RK817_CODEC_DI2S_CKM,",
                  "\tret = snd_soc_component_update_bits(component, RK817_CODEC_DI2S_CKM,")
    fmt = replace(fmt, "\treturn 0;\n}", "\treturn ret < 0 ? ret : 0;\n}")
    return replace(text, old, fmt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / ("driver-source-" + args.version)
    new_output(output)
    boundary(PATCH)
    if command(["git", "-C", str(KERNEL), "rev-parse", "HEAD"]) != COMMIT:
        raise ValueError("Unexpected kernel source commit")
    if command(["git", "-C", str(KERNEL), "status", "--porcelain"]):
        raise ValueError("Locked kernel source must be clean")
    before = (KERNEL / SOURCE).read_text()
    after = candidate(before)
    diff = "diff --git a/" + SOURCE + " b/" + SOURCE + "\n"
    diff += "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                      fromfile="a/" + SOURCE, tofile="b/" + SOURCE))
    generated = diff.encode()
    reused = PATCH.exists()
    if reused and (not PATCH.is_file() or PATCH.read_bytes() != generated):
        raise ValueError("Existing published patch differs; refuse overwrite")
    output.mkdir()
    for relative, data in [(SOURCE, after.encode()), (HEADER, (KERNEL / HEADER).read_bytes())]:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    if not reused:
        with PATCH.open("xb") as stream:
            stream.write(generated)
    record = {
        "source_commit": COMMIT, "source_clean": True,
        "sources": {relative: {"original_sha256": sha(KERNEL / relative),
                               "candidate_sha256": sha(output / relative)} for relative in [SOURCE, HEADER]},
        "patch_path": str(PATCH.relative_to(ROOT)), "patch_sha256": sha(PATCH),
        "existing_identical_patch_reused": reused, "generator_sha256": sha(Path(__file__)),
        "license": "GPL-2.0-or-later (unchanged upstream file license)",
        "bounded_scope": "DT errors/node refs, platform mclk errno, component read/reset/controls errors and cleanup, machine set_fmt",
        "default_paths": "Playback OFF / Capture MIC OFF; existing successful reset sequence unchanged",
        "regmap_ownership": "Parent PMIC owns its original map; codec never allocates or frees a map; component only detaches",
        "chip_identity_read": "PMIC RBTREE cache may supply chip name/version; not a fresh I2C identity claim",
        "board_tested": False, "runtime_pcm_paths_fixed": False, "unload_lifecycle_fixed": False,
        "unfixed_runtime_functions": ["rk817_restart_*_digital_clk", "rk817_codec_power_up",
                                      "rk817_codec_power_down", "rk817_playback_path_config",
                                      "rk817_capture_path_config", "rk817_hw_params", "rk817_digital_mute_dac",
                                      "rk817_digital_mute_adc", "rk817_suspend", "rk817_resume", "rk817_codec_shutdown"],
        "limitations": ["Reset failure can leave partially written hardware; resources are released, no rollback is claimed",
                        "PCM/path/mute/suspend/resume I/O propagation remains a separate implementation task",
                        "Read-only controls trial does not validate playback/capture or concurrent removal"]}
    (output / "driver-source-manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
