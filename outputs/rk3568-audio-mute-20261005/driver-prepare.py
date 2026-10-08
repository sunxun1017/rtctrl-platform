#!/usr/bin/env python3
"""Generate isolated RK817 mute fix and verify full public 0006+0007+0009 replay."""
import argparse
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / "outputs/rk3568-audio-runtime-20261005/driver-source-v1"
KERNEL = ROOT / "third_party/linux-rk3588"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
SOURCE = "sound/soc/codecs/rk817_codec.c"
HEADER = "sound/soc/codecs/rk817_codec.h"
BASE_SHA = "797d9d74c81dba2ed6f306c011446882eaed1bdf7b8d1ffc7321de73676e86b6"
PATCH_DIR = ROOT / "platforms/rk3568/boards/aiot-3568pq/patches"
PREVIOUS = [PATCH_DIR / "0006-rk817-codec-error-propagation.patch", PATCH_DIR / "0007-rk817-pcm-configuration-errors.patch"]
PATCH = PATCH_DIR / "0009-rk817-mute-errors.patch"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError("expected one occurrence: " + old[:100])
    return text.replace(old, new, 1)


def function(text, name):
    match = re.search(r"^static int " + name + r"\([^;]*?\)\s*\{", text, re.M)
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
    text = replace(text, "\tbool resume_path;", "\tbool resume_path;\n\t/* First mute I/O error; cached success does not establish recovery. */\n\tint mute_io_error;")
    old = function(text, "rk817_digital_mute_dac")
    new = replace(old, "\tDBG(\"%s %d\\n\", __func__, mute);", """	int ret;

	/* Reject the direction before GPIO or register operations. */
	if (stream != SNDRV_PCM_STREAM_PLAYBACK)
		return -EINVAL;
	if (rk817->playback_path == OFF)
		mute = 1;
	if (!mute && rk817->mute_io_error)
		return rk817->mute_io_error;

	DBG("%s %d\\n", __func__, mute);""")
    start = new.index("\t\tsnd_soc_component_update_bits(component,")
    end = new.index("\t} else {", start)
    new = new[:start] + """		ret = snd_soc_component_update_bits(component,
					    RK817_CODEC_DDAC_MUTE_MIXCTL,
					    DACMT_ENABLE, DACMT_ENABLE);
		if (ret < 0) {
			if (!rk817->mute_io_error)
				rk817->mute_io_error = ret;
		} else {
			ret = rk817_restart_dac_digital_clk(component);
			if (ret < 0 && !rk817->mute_io_error)
				rk817->mute_io_error = ret;
		}
		/* Disable RX even if mute or clock restart failed. */
		ret = snd_soc_component_update_bits(component, RK817_CODEC_DTOP_DIGEN_CLKE,
					    I2SRX_EN_MASK, I2SRX_DIS);
		if (ret < 0 && !rk817->mute_io_error)
			rk817->mute_io_error = ret;
""" + new[end:]
    start = new.index("\t} else {")
    prefix, suffix = new[:start], new[start:]
    pattern = r"^(\t+)snd_soc_component_(write|update_bits)\((.*?);"
    def checked(match):
        indent, name, arguments = match.groups()
        return (indent + "ret = snd_soc_component_" + name + "(" + arguments + ";\n" +
                indent + "if (ret < 0)\n" + indent + "\tgoto err_mute;")
    suffix = re.sub(pattern, checked, suffix, flags=re.M | re.S)
    new = prefix + suffix
    new = replace(new, "\treturn 0;\n}", """	return rk817->mute_io_error;

err_mute:
	if (!rk817->mute_io_error)
		rk817->mute_io_error = ret;
	/* One bounded checked mute attempt; cleanup cannot erase the first error. */
	rk817_digital_mute_dac(dai, 1, stream);
	return rk817->mute_io_error;
}""")
    text = replace(text, old, new)
    text = replace(text, function(text, "rk817_digital_mute_adc"), """static int rk817_digital_mute_adc(struct snd_soc_dai *dai, int mute, int stream)
{
	struct snd_soc_component *component = dai->component;
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(component);
	int ret;

	if (stream != SNDRV_PCM_STREAM_CAPTURE)
		return -EINVAL;
	if (rk817->capture_path == MIC_OFF)
		mute = 1;
	if (!mute && rk817->mute_io_error)
		return rk817->mute_io_error;

	ret = snd_soc_component_update_bits(component, RK817_CODEC_DTOP_DIGEN_CLKE,
					    I2STX_EN_MASK, mute ? I2STX_DIS : I2STX_EN);
	if (ret < 0) {
		if (!rk817->mute_io_error)
			rk817->mute_io_error = ret;
		if (!mute)
			rk817_digital_mute_adc(dai, 1, stream);
	}

	return rk817->mute_io_error;
}""")
    old = function(text, "rk817_digital_mute")
    new = replace(old, "\telse\n\t\treturn rk817_digital_mute_adc(dai, mute, stream);", "\tif (stream == SNDRV_PCM_STREAM_CAPTURE)\n\t\treturn rk817_digital_mute_adc(dai, mute, stream);\n\treturn -EINVAL;")
    return replace(text, old, new)


def command(argv):
    return subprocess.run([str(arg) for arg in argv], check=True, capture_output=True).stdout


def replay(output, patches, before):
    replay_dir = output / "replay"
    for relative in [SOURCE, HEADER]:
        path = replay_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(command(["git", "-C", KERNEL, "show", COMMIT + ":" + relative]))
    records = []
    for patch in patches:
        completed = subprocess.run(["patch", "--batch", "--forward", "--fuzz=0", "-p1", "-i", str(patch)],
                                   cwd=replay_dir, check=True, capture_output=True, text=True)
        records.append({"patch": patch.name, "sha256": sha(patch.read_bytes()), "stdout": completed.stdout})
        if patch == PREVIOUS[-1] and (replay_dir / SOURCE).read_bytes() != before:
            raise ValueError("public 0006+0007 differs from the locked runtime candidate")
    return replay_dir, records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / ("driver-source-" + args.version)
    if output.exists():
        raise ValueError("refuse overwriting source output")
    before = (BASE / SOURCE).read_bytes()
    if sha(before) != BASE_SHA:
        raise ValueError("runtime candidate source changed")
    if command(["git", "-C", KERNEL, "rev-parse", "HEAD"]).decode().strip() != COMMIT:
        raise ValueError("wrong kernel commit")
    if command(["git", "-C", KERNEL, "status", "--porcelain"]):
        raise ValueError("original kernel tree must be clean")
    after = candidate(before.decode()).encode()
    patch = "diff --git a/" + SOURCE + " b/" + SOURCE + "\n"
    patch += "".join(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True),
                                          fromfile="a/" + SOURCE, tofile="b/" + SOURCE))
    output.mkdir()
    for relative, data in [(SOURCE, after), (HEADER, (BASE / HEADER).read_bytes())]:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    preview = output / PATCH.name
    preview.write_bytes(patch.encode())
    replay_dir, records = replay(output, [*PREVIOUS, preview], before)
    for relative in [SOURCE, HEADER]:
        if (replay_dir / relative).read_bytes() != (output / relative).read_bytes():
            raise ValueError("full patch replay differs from candidate: " + relative)
    if command(["git", "-C", KERNEL, "status", "--porcelain"]):
        raise ValueError("original kernel tree changed during generation")
    if args.publish:
        if PATCH.exists() and PATCH.read_bytes() != patch.encode():
            raise ValueError("refuse replacing a different public patch")
        if not PATCH.exists():
            PATCH.write_bytes(patch.encode())
    manifest = {"source_commit": COMMIT, "base_sha256": BASE_SHA,
                "sources": {relative: sha((output / relative).read_bytes()) for relative in [SOURCE, HEADER]},
                "source_sha256": sha(after), "patch_sha256": sha(patch.encode()),
                "patch_requires": [path.name for path in PREVIOUS], "patch_path": str(PATCH),
                "published": args.publish, "full_patch_replay_byte_identical": True, "replay": records,
                "original_tree_clean_before_after": True, "shared_regmap_cache_policy_changed": False,
                "fix_scope": "three mute callbacks plus sticky instance first-error field",
                "io_failure_policy": "Stop unmute at first negative errno, latch it, attempt one same-direction checked mute. Mute remains best effort and always returns the latched first errno after any prior fault; cached 0/1 success does not clear it.",
                "gpio_limit": "gpiod_set_value has no error return; output-off requests are not electrical proof",
                "board_tested": False, "production_module_built": False, "start_dma_authorized": False,
                "unfixed": ["ASoC callers ignoring mute errno", "PCM PREPARE reentry/state handling",
                            "DMA start/stop synchronization and progress", "arbitrary runtime path switching",
                            "shared PMIC cache recovery", "resume/shutdown/remove/concurrent lifecycle"]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output), "source_sha256": sha(after),
                      "patch_sha256": sha(patch.encode()), "published": args.publish}))


if __name__ == "__main__":
    main()
