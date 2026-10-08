#!/usr/bin/env python3
"""Apply independently reproduced review fixes to immutable v8, offline only."""
import argparse
import difflib
import json
import re
from pathlib import Path
from source_utils import function, replace, sha

HERE = Path(__file__).resolve().parent
SOURCE = "sound/soc/rockchip/rockchip_i2s_tdm.c"
V8_SHA = "33bd1208d379be53be8232cab11fe908f2d3096b94e66fc59d76a143c86cb3d0"


def scoped(source, name, old, new):
    original = function(source, name)
    return replace(source, original, replace(original, old, new))


def revision(source):
    source = scoped(source, "i2s_checked_gate_locked", "i2s_tdm->configuring || i2s_tdm->started", "i2s_tdm->configuring || i2s_tdm->power_transition || i2s_tdm->started")
    for name in ["rockchip_i2s_tdm_startup", "i2s_checked_prepare"]:
        source = scoped(source, name, "\t\tret = i2s_checked_gate_locked(i2s_tdm);" if name == "rockchip_i2s_tdm_startup" else "\tret = i2s_checked_gate_locked(i2s_tdm);", ("\t\tret = i2s_checked_gate_locked(i2s_tdm);\n\t\tif (!ret && !READ_ONCE(i2s_tdm->ready))\n\t\t\tret = -EAGAIN;" if name == "rockchip_i2s_tdm_startup" else "\tret = i2s_checked_gate_locked(i2s_tdm);\n\tif (!ret && !READ_ONCE(i2s_tdm->ready))\n\t\tret = -EAGAIN;"))
    source = scoped(source, "i2s_checked_component_trigger", "\t\telse if (i2s_tdm->configuring ||", "\t\telse if (!READ_ONCE(i2s_tdm->ready))\n\t\t\tret = -EAGAIN;\n\t\telse if (i2s_tdm->configuring || i2s_tdm->power_transition ||")
    source = scoped(source, "i2s_checked_start_locked", "\tif (i2s_tdm->configuring)\n\t\treturn -EBUSY;", "\tif (!READ_ONCE(i2s_tdm->ready))\n\t\treturn -EAGAIN;\n\tif (i2s_tdm->configuring || i2s_tdm->power_transition)\n\t\treturn -EBUSY;")
    source = scoped(source, "i2s_checked_quiesce", "\t\ti2s_tdm->shutting_down = true;", "\t\tWRITE_ONCE(i2s_tdm->ready, false);\n\t\ti2s_tdm->shutting_down = true;")
    source = scoped(source, "i2s_checked_runtime_resume", "\ti2s_tdm->irq_live = !stopping;", "\t/* A concurrent process teardown may have revoked the gate while resuming. */\n\ti2s_tdm->irq_live = !i2s_tdm->shutting_down;")
    original = function(source, "i2s_checked_probe_clock_release")
    changed = r'''static void i2s_checked_probe_clock_release(void *data)
{
	struct rk_i2s_tdm_dev *i2s_tdm = data;
	unsigned long flags;
	int ret;

	/* IRQ/component devres are gone; all clock consumer handles are still alive. */
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	WRITE_ONCE(i2s_tdm->ready, false);
	i2s_tdm->shutting_down = true;
	i2s_tdm->irq_live = false;
	ret = READ_ONCE(i2s_tdm->substreams[0]) || READ_ONCE(i2s_tdm->substreams[1]) ||
		i2s_tdm->started || i2s_tdm->configuring ? -EBUSY : 0;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	if (ret)
		i2s_checked_failstop(i2s_tdm, "probe cleanup", ret);
	/* PM disable drains pending/running PM callbacks before consumer release. */
	pm_runtime_disable(i2s_tdm->dev);
	if (i2s_tdm->mclks_enabled && !i2s_tdm->stop_proven)
		i2s_checked_failstop(i2s_tdm, "probe cleanup stop unproved", -EIO);
	if (i2s_tdm->mclks_enabled) {
		clk_disable_unprepare(i2s_tdm->mclk_tx);
		clk_disable_unprepare(i2s_tdm->mclk_rx);
		i2s_tdm->mclks_enabled = false;
	}
	if (i2s_tdm->hclk_enabled) {
		clk_disable_unprepare(i2s_tdm->hclk);
		i2s_tdm->hclk_enabled = false;
	}
}'''
    source = replace(source, original, changed)
    component = re.search(r"^static const struct snd_soc_component_driver rockchip_i2s_tdm_component = \{.*?^\};", source, re.M | re.S).group()
    source = replace(source, component, component + r'''

/* The checked single-direction profile exposes only readonly lifecycle state. */
static const struct snd_soc_component_driver rockchip_i2s_tdm_checked_component = {
	.name = DRV_NAME,
	.trigger = i2s_checked_component_trigger,
};''')
    original = function(source, "rockchip_i2s_tdm_probe")
    old = '''	ret = clk_prepare_enable(i2s_tdm->hclk);
	if (ret)
		return ret;

	if (i2s_tdm->checked_lifecycle) {
		i2s_tdm->hclk_enabled = true;
		ret = devm_add_action_or_reset(&pdev->dev, i2s_checked_probe_clock_release, i2s_tdm);
		if (ret)
			return ret;
	}
'''
    new = '''	if (!i2s_tdm->checked_lifecycle) {
		ret = clk_prepare_enable(i2s_tdm->hclk);
		if (ret)
			return ret;
	}
'''
    changed = replace(original, old, new)
    marker = '''	i2s_tdm->mclk_rx = devm_clk_get(&pdev->dev, "mclk_rx");
	if (IS_ERR(i2s_tdm->mclk_rx))
		return PTR_ERR(i2s_tdm->mclk_rx);'''
    changed = replace(changed, marker, marker + r'''

	if (i2s_tdm->checked_lifecycle) {
		/* Reverse devres order: action precedes clk_put for all three handles. */
		ret = devm_add_action_or_reset(&pdev->dev, i2s_checked_probe_clock_release, i2s_tdm);
		if (ret)
			return ret;
		ret = clk_prepare_enable(i2s_tdm->hclk);
		if (ret)
			return ret;
		i2s_tdm->hclk_enabled = true;
	}''')
    changed = replace(changed, "\t\t\t\t\t      &rockchip_i2s_tdm_component,", "\t\t\t\t\t      i2s_tdm->checked_lifecycle ?\n\t\t\t\t\t      &rockchip_i2s_tdm_checked_component :\n\t\t\t\t\t      &rockchip_i2s_tdm_component,")
    changed = replace(changed, "err_suspend:\n\tif (!pm_runtime_status_suspended", "err_suspend:\n\tif (i2s_tdm->checked_lifecycle) {\n\t\t/* Preserve registration errno; prove exit before any devres release. */\n\t\ti2s_checked_quiesce(i2s_tdm, \"probe late failure\");\n\t\treturn ret;\n\t}\n\tif (!pm_runtime_status_suspended")
    source = replace(source, original, changed)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"v(?:9|[1-9][0-9]+)", args.version):
        parser.error("review candidate must be v9 or later")
    output = HERE / ("driver-source-" + args.version)
    if output.exists():
        raise ValueError("candidate exists")
    baseline = (HERE / "driver-source-v8" / SOURCE).read_bytes()
    if sha(baseline) != V8_SHA:
        raise ValueError("frozen v8 changed")
    text = revision(baseline.decode())
    original = (HERE / "source-input-v1" / SOURCE).read_bytes()
    patch = "diff --git a/" + SOURCE + " b/" + SOURCE + "\n"
    patch += "".join(difflib.unified_diff(original.decode().splitlines(True), text.splitlines(True), fromfile="a/" + SOURCE, tofile="b/" + SOURCE))
    output.mkdir()
    target = output / SOURCE
    target.parent.mkdir(parents=True)
    target.write_text(text)
    (output / "i2s-lifecycle-review.patch").write_text(patch)
    (output / "driver-review-revision.py").write_bytes(Path(__file__).read_bytes())
    (output / "source_utils.py").write_bytes((HERE / "source_utils.py").read_bytes())
    manifest = {"kernel_commit": "9f9e9d18574d0914c0d192a90c3babfe1fd63c95", "source_sha256": sha(text.encode()), "original_sha256": sha(original), "patch_sha256": sha(patch.encode()), "review_baseline_sha256": V8_SHA, "published": False, "deployable": False, "board_tested": False, "full_duplex_supported": False, "audio_start_allowed": False, "remaining": ["independent review", "C3/DMA combined lifecycle", "full built-in Image and hardware acceptance"]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
