#!/usr/bin/env python3
"""Generate and replay a minimal panel lifecycle patch from a locked MIT source."""
import argparse
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / "third_party/linux-rk3588"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
SOURCE = "drivers/gpu/drm/panel/panel-simple.c"
BASE_SHA = "a3bcbd7ae35f1f3d86a60d0cd39d77d4626d97310d05a4566a2b7d6428a2b93e"
PATCH = ROOT / "platforms/rk3568/boards/aiot-3568pq/patches/0008-panel-simple-init-errors.patch"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError("expected one occurrence: " + old[:100])
    return text.replace(old, new, 1)


def function(text, name):
    match = re.search(r"^(?:static )?int " + name + r"\([^;]*?\)\s*\{", text, re.M)
    if not match:
        raise ValueError("missing function: " + name)
    depth = 0
    for index in range(text.index("{", match.start()), len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[match.start():index + 1]
    raise ValueError("unclosed function: " + name)


def candidate(text):
    text = replace(text, "\tbool enabled;\n", "\tbool enabled;\n\t/* Shutdown failed: do not acquire another supply reference. */\n\tbool lifecycle_fault;\n")
    old = function(text, "panel_simple_xfer_dsi_cmd_seq")
    new = replace(old, "\t\tif (err < 0)\n\t\t\tdev_err(dev, \"failed to write dcs cmd: %d\\n\", err);",
                  "\t\t/* Some hosts return packet size rather than payload length. */\n"
                  "\t\tif (err < 0) {\n\t\t\tdev_err(dev, \"failed to write dcs cmd: %d\\n\", err);\n"
                  "\t\t\treturn err;\n\t\t}")
    text = replace(text, old, new)

    text = replace(text, function(text, "panel_simple_regulator_enable"), """static int panel_simple_regulator_enable(struct panel_simple *p)
{
	int err;

	if (p->power_invert) {
		err = regulator_is_enabled(p->supply);
		if (err < 0)
			return err;
		if (err > 0)
			return regulator_disable(p->supply);
	} else {
		return regulator_enable(p->supply);
	}

	return 0;
}""")
    text = replace(text, function(text, "panel_simple_regulator_disable"), """static int panel_simple_regulator_disable(struct panel_simple *p)
{
	int err;

	if (p->power_invert) {
		err = regulator_is_enabled(p->supply);
		if (err < 0)
			return err;
		if (!err)
			return regulator_enable(p->supply);
	} else {
		return regulator_disable(p->supply);
	}

	return 0;
}""")
    old = function(text, "panel_simple_loader_protect")
    new = replace(old, "\terr = panel_simple_regulator_enable(p);", "\tif (p->lifecycle_fault)\n\t\treturn -EIO;\n\n\terr = panel_simple_regulator_enable(p);")
    text = replace(text, old, new)

    text = replace(text, function(text, "panel_simple_unprepare"), """static int panel_simple_unprepare(struct drm_panel *panel)
{
	struct panel_simple *p = to_panel_simple(panel);
	int err = 0;
	int ret;

	if (p->lifecycle_fault)
		return -EIO;
	if (!p->prepared)
		return 0;

	if (p->desc->exit_seq) {
		if (p->desc->cmd_type == CMD_TYPE_SPI)
			err = panel_simple_xfer_spi_cmd_seq(p, p->desc->exit_seq);
		else if (p->dsi)
			err = panel_simple_xfer_dsi_cmd_seq(p, p->desc->exit_seq);
		if (err)
			dev_err(panel->dev, "failed to send exit cmds seq: %d\\n", err);
	}

	/* Attempt every independent shutdown action, preserving the first error. */
	ret = gpiod_direction_output(p->reset_gpio, 1);
	if (ret) {
		p->lifecycle_fault = true;
		if (!err)
			err = ret;
	}
	ret = gpiod_direction_output(p->enable_gpio, 0);
	if (ret) {
		p->lifecycle_fault = true;
		if (!err)
			err = ret;
	}
	ret = panel_simple_regulator_disable(p);
	if (ret) {
		p->lifecycle_fault = true;
		if (!err)
			err = ret;
	}

	if (p->desc->delay.unprepare)
		usleep_range(p->desc->delay.unprepare * 1000, p->desc->delay.unprepare * 1000 + 100);

	/* Not ready for enable; an error does not establish that power is off. */
	p->prepared = false;
	p->enabled = false;

	return err;
}""")

    old = function(text, "panel_simple_prepare")
    new = replace(old, "\tint err;", "\tint err;\n\tint ret;")
    new = replace(new, "\tif (p->prepared)", "\tif (p->lifecycle_fault)\n\t\treturn -EIO;\n\tif (p->prepared)")
    new = replace(new, "\tgpiod_direction_output(p->enable_gpio, 1);", "\terr = gpiod_direction_output(p->enable_gpio, 1);\n\tif (err)\n\t\tgoto poweroff;")
    new = replace(new, "\t\t\tif (err)\n\t\t\t\treturn err;", "\t\t\tif (err)\n\t\t\t\tgoto poweroff;")
    new = replace(new, "\t\t\treturn err;\n\t\t}\n\t}\n\n\tgpiod_direction_output(p->reset_gpio, 1);",
                  "\t\t\tgoto poweroff;\n\t\t}\n\t}\n\n\terr = gpiod_direction_output(p->reset_gpio, 1);\n\tif (err)\n\t\tgoto poweroff;")
    new = replace(new, "\tgpiod_direction_output(p->reset_gpio, 0);", "\terr = gpiod_direction_output(p->reset_gpio, 0);\n\tif (err)\n\t\tgoto poweroff;")
    start = new.index("\tif (p->desc->init_seq) {")
    end = new.index("\n\tp->prepared = true;", start)
    new = new[:start] + """	if (p->desc->init_seq) {
		if (p->desc->cmd_type == CMD_TYPE_SPI)
			err = panel_simple_xfer_spi_cmd_seq(p, p->desc->init_seq);
		else if (p->dsi)
			err = panel_simple_xfer_dsi_cmd_seq(p, p->desc->init_seq);
		if (err) {
			dev_err(panel->dev, "failed to send init cmds seq: %d\\n", err);
			goto poweroff;
		}
	}
""" + new[end:]
    new = replace(new, "\tp->prepared = true;", """	p->prepared = true;
	if (p->desc->init_seq &&
	    (p->desc->cmd_type == CMD_TYPE_SPI || p->dsi))
		dev_info(panel->dev, "panel initialization sequence completed (%u commands)\\n",
			 p->desc->init_seq->cmd_cnt);""")
    new = replace(new, "\treturn 0;\n}", """	return 0;

poweroff:
	/* Rollback is best effort; never hide the prepare error. */
	ret = gpiod_direction_output(p->reset_gpio, 1);
	if (ret) {
		p->lifecycle_fault = true;
		dev_err(panel->dev, "failed to assert reset on rollback: %d\\n", ret);
	}
	ret = gpiod_direction_output(p->enable_gpio, 0);
	if (ret) {
		p->lifecycle_fault = true;
		dev_err(panel->dev, "failed to disable GPIO on rollback: %d\\n", ret);
	}
	ret = panel_simple_regulator_disable(p);
	if (ret) {
		p->lifecycle_fault = true;
		dev_err(panel->dev, "failed to disable supply on rollback: %d\\n", ret);
	}

	return err;
}""")
    text = replace(text, old, new)
    old = function(text, "panel_simple_enable")
    new = replace(old, "\tif (p->enabled)", "\tif (p->lifecycle_fault)\n\t\treturn -EIO;\n\tif (!p->prepared)\n\t\treturn -EINVAL;\n\tif (p->enabled)")
    return replace(text, old, new)


def command(argv):
    return subprocess.run(argv, check=True, capture_output=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--supersedes-patch-sha256")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / ("panel-source-" + args.version)
    if output.exists():
        raise ValueError("refuse overwriting source output")
    if command(["git", "-C", str(KERNEL), "rev-parse", "HEAD"]).decode().strip() != COMMIT:
        raise ValueError("wrong source commit")
    raw = command(["git", "-C", str(KERNEL), "show", COMMIT + ":" + SOURCE])
    if sha(raw) != BASE_SHA or (KERNEL / SOURCE).read_bytes() != raw:
        raise ValueError("locked source bytes changed")
    before = raw.decode()
    after = candidate(before)
    patch = "diff --git a/" + SOURCE + " b/" + SOURCE + "\n"
    patch += "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                          fromfile="a/" + SOURCE, tofile="b/" + SOURCE))
    output.mkdir()
    target = output / SOURCE
    target.parent.mkdir(parents=True)
    target.write_bytes(after.encode())
    preview = output / PATCH.name
    preview.write_bytes(patch.encode())
    replay = output / "replay"
    original = replay / SOURCE
    original.parent.mkdir(parents=True)
    original.write_bytes(raw)
    replay_result = subprocess.run(["patch", "--batch", "--forward", "--fuzz=0", "-p1", "-i", str(preview)],
                                   cwd=replay, check=True, capture_output=True, text=True)
    if original.read_bytes() != after.encode():
        raise ValueError("public patch replay differs from generated source")
    if args.publish:
        if PATCH.exists() and PATCH.read_bytes() != patch.encode():
            if args.supersedes_patch_sha256 != sha(PATCH.read_bytes()):
                raise ValueError("replacing a public patch requires its exact superseded SHA")
            PATCH.write_bytes(patch.encode())
        elif not PATCH.exists():
            PATCH.write_bytes(patch.encode())
    manifest = {"source_commit": COMMIT, "base_sha256": BASE_SHA,
                "source_sha256": sha(target.read_bytes()), "patch_sha256": sha(patch.encode()),
                "patch_path": str(PATCH), "published": args.publish,
                "patch_requires": [], "replay_byte_identical": True,
                "replay_command": ["patch", "--batch", "--forward", "--fuzz=0", "-p1", "-i", str(preview)],
                "replay_stdout": replay_result.stdout,
                "license": "Original MIT notice retained byte for byte; no relicensing",
                "supersedes_patch_sha256": args.supersedes_patch_sha256,
                "rejected_prior_candidates": "panel-source-v1/v2 enforce a wrong payload return length; their fake-API green results are superseded by the real-host red regression",
                "fix_scope": "DSI first negative errno; prepare GPIO/init/HPD rollback; unprepare independent cleanup; regulator status/disable errno; preparation and sticky fault gates; success milestone after complete initialization",
                "dsi_positive_return_policy": "Preserve host-specific success. Locked DW host returns packet size (short=4, long=4+payload); no generic short-write inference is made.",
                "success_milestone": "panel initialization sequence completed (%u commands); means all init API calls accepted, not physical panel acknowledgement or electrical validation",
                "lifecycle_fault_policy": "Failed GPIO/supply rollback or shutdown latches EIO for subsequent prepare/enable/unprepare/loader protection with no further I/O. No automatic reset or retry. Reprobe/reboot requires external hardware recovery, not a promise of restored state.",
                "board_tested": False,
                "unfixed": ["DSI host/bridge prepare return handling", "DRM core/backlight shutdown return handling",
                            "payload parser and malformed DSC/PPS data", "probe/remove and concurrent lifecycle",
                            "hardware power/reset timing and physical brightness",
                            "power_invert hardware ownership and all other panel boards"]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output), "source_sha256": manifest["source_sha256"],
                      "patch_sha256": manifest["patch_sha256"], "published": args.publish}))


if __name__ == "__main__":
    main()
