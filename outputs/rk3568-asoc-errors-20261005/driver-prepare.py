#!/usr/bin/env python3
"""Generate isolated ASoC/PCM errors fix, with all public board patches replayed."""
import argparse
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path
from importlib.machinery import SourceFileLoader

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / "third_party/linux-rk3588"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
SOC = "sound/soc/soc-pcm.c"
PCM = "sound/core/pcm_native.c"
SOURCES = {SOC: "1b64190aa7421d2195f174f2c5a6607cc72d868a56c5431591abbdb8619b3bfc",
           PCM: "dc1e6ac01a8532afce0155eaaf2cda1d65aa95c5414210fb54bb03c2577bd608"}
PATCH_DIR = ROOT / "platforms/rk3568/boards/aiot-3568pq/patches"
PATCH_NAME = "0010-asoc-prepare-free-errors.patch"
DEPENDENCIES = {
    "0001-arm64-cache-kasan-include.patch": "50fe5627b4fed8d765faf9210ab7ea5e5f74dcc7dd67cc2d4e3d2a3108c5619a",
    "0002-rk817-feedback-diagnostic.patch": "4354f6c9cb9de1d618f3b3e8838f39923d6c4e2bb9d851d92a8ee2e2a03df30b",
    "0003-printk-rcu-flush-context.patch": "b8ca5eb49e55dbc2cfdff55ab407d021d7cd8c094fd77372018bc859d9b712de",
    "0004-bcmdhd-out-of-tree-include.patch": "401657aecfad52d63bdf462c25f0deeed34ad23ee4da6dfd0d347b9e35338c1c",
    "0005-sensor-error-propagation.patch": "cff9f21c036173bc4465cf51ee414e77fc2456e8e0c15d84f0e74d414a64d184",
    "0006-rk817-codec-error-propagation.patch": "f501e5642d363b0c10431de053c19d8c1ae16060ddb35838d520de0f0d84bd81",
    "0007-rk817-pcm-configuration-errors.patch": "f74325e1a3df4eef99fbc7f47cbb0045e1d9b38b07745f30463fee811c57b80e",
    "0008-panel-simple-init-errors.patch": "d49469f53a3e7c310a1aec39baa9b0d86c5f48f2ae58d0d085d32b972f3df10f",
    "0009-rk817-mute-errors.patch": "4d7cb506387fea2d336cbb75fe81679ad72cb3121016ea2af949e176fbdfeb5c",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def command(argv):
    return subprocess.run([str(a) for a in argv], check=True, capture_output=True).stdout


def original_clean():
    if command(["git", "-C", KERNEL, "rev-parse", "HEAD"]).decode().strip() != COMMIT:
        raise ValueError("wrong kernel commit")
    if command(["git", "-C", KERNEL, "status", "--porcelain"]):
        raise ValueError("original kernel tree must be clean")


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError("expected one source occurrence: " + old[:100])
    return text.replace(old, new, 1)


def candidate(before):
    extractor = SourceFileLoader("asoc_extract", str(HERE / "test-asoc-functions.py")).load_module()
    text = before[SOC].decode()
    old = extractor.function(text, "soc_pcm_prepare")
    new = replace(old, "\tint i, ret = 0;", "\tint i, j, ret = 0;")
    new = replace(new, "\tfor_each_rtd_dais(rtd, i, dai)\n\t\tsnd_soc_dai_digital_mute(dai, 0, substream->stream);", """	for_each_rtd_dais(rtd, i, dai) {
		if (!soc_pcm_has_mute(dai, substream->stream))
			continue;
		ret = snd_soc_dai_digital_mute(dai, 0, substream->stream);
		if (ret < 0)
			goto err_mute;
	}
	ret = 0;
	goto out;

err_mute:
	/* Include the failing DAI: its callback may already have done I/O. */
	for_each_rtd_dais(rtd, j, dai) {
		if (j > i)
			break;
		if (soc_pcm_has_mute(dai, substream->stream))
			snd_soc_dai_digital_mute(dai, 1, substream->stream);
	}
	/* Pair this prepare's start without recursively taking pcm_mutex. */
	snd_soc_dapm_stream_event(rtd, substream->stream,
			SND_SOC_DAPM_STREAM_STOP);""")
    predicate = """/* Match the callback selection in snd_soc_dai_digital_mute(). */
static bool soc_pcm_has_mute(struct snd_soc_dai *dai, int stream)
{
	return dai->driver->ops && dai->driver->ops->mute_stream &&
		(stream == SNDRV_PCM_STREAM_PLAYBACK ||
		 !dai->driver->ops->no_capture_mute);
}

"""
    text = replace(text, old, predicate + new)
    old = extractor.function(text, "soc_pcm_hw_free")
    new = replace(old, "\tint i;", "\tint i, ret = 0;")
    new = replace(new, "\t\tif (active == 1)\n\t\t\tsnd_soc_dai_digital_mute(dai, 1, substream->stream);", """		if (active == 1 && soc_pcm_has_mute(dai, substream->stream)) {
			int err = snd_soc_dai_digital_mute(dai, 1, substream->stream);

			if (err < 0 && !ret)
				ret = err;
		}""")
    new = replace(new, "\treturn 0;", "\treturn ret;")
    text = replace(text, old, new)
    pcm = before[PCM].decode()
    old = extractor.function(pcm, "snd_pcm_do_prepare")
    new = replace(old, "\tif (err < 0)\n\t\treturn err;\n\treturn snd_pcm_do_reset(substream, state);", """	if (err >= 0)
		err = snd_pcm_do_reset(substream, state);
	if (err < 0)
		snd_pcm_set_state(substream, SNDRV_PCM_STATE_SETUP);
	return err;""")
    pcm = replace(pcm, old, new)
    return {SOC: text.encode(), PCM: pcm.encode()}


def replay(output, patches):
    targets = set(SOURCES)
    for name, data in patches.items():
        for relative in re.findall(r"^--- a/(.+)$", data.decode(), re.M):
            if Path(relative).is_absolute() or ".." in Path(relative).parts:
                raise ValueError("unsafe patch path")
            targets.add(relative)
    directory = output / "replay"
    for relative in sorted(targets):
        dest = directory / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(command(["git", "-C", KERNEL, "show", COMMIT + ":" + relative]))
    records = []
    snapshot = output / "patch-inputs"
    snapshot.mkdir()
    for name, data in patches.items():
        patch = snapshot / name
        patch.write_bytes(data)
        completed = subprocess.run(["patch", "--batch", "--forward", "--fuzz=0", "-p1", "-i", str(patch)],
                                   cwd=directory, check=True, capture_output=True, text=True)
        records.append({"patch": name, "sha256": sha(data), "stdout": completed.stdout})
    return directory, records


def prepare(version, publish=False, input_dir=KERNEL, patch_dir=PATCH_DIR, output_root=HERE):
    if not re.fullmatch(r"v[1-9][0-9]*", version):
        raise ValueError("version must be vN")
    output = output_root / ("driver-source-" + version)
    if output.exists():
        raise ValueError("refuse overwriting source output")
    original_clean()
    before = {relative: (input_dir / relative).read_bytes() for relative in SOURCES}
    for relative, data in before.items():
        if sha(data) != SOURCES[relative]:
            raise ValueError("source hash changed: " + relative)
    patches = {name: (patch_dir / name).read_bytes() for name in DEPENDENCIES}
    for name, data in patches.items():
        if sha(data) != DEPENDENCIES[name]:
            raise ValueError("dependency patch hash changed: " + name)
    after = candidate(before)
    patch = ""
    for relative in SOURCES:
        patch += "diff --git a/" + relative + " b/" + relative + "\n"
        patch += "".join(difflib.unified_diff(before[relative].decode().splitlines(True), after[relative].decode().splitlines(True),
                                             fromfile="a/" + relative, tofile="b/" + relative))
    data = patch.encode()
    public = patch_dir / PATCH_NAME
    if publish and public.exists() and public.read_bytes() != data:
        raise ValueError("refuse replacing different public patch")
    output.mkdir()
    for relative in SOURCES:
        for directory, contents in [(output, after[relative]), (output / "source-inputs", before[relative])]:
            dest = directory / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(contents)
    preview = output / PATCH_NAME
    preview.write_bytes(data)
    replay_dir, records = replay(output, {**patches, PATCH_NAME: data})
    for relative in SOURCES:
        if (replay_dir / relative).read_bytes() != after[relative]:
            raise ValueError("full public patch replay differs: " + relative)
    # These frozen candidates must survive the full board patch sequence too.
    for relative, expected in {
        "sound/soc/codecs/rk817_codec.c": "72e59ced7af3bc570bafb516459c55a073f80613fb0a9ff1b6192cfa3f7cbc64",
        "drivers/gpu/drm/panel/panel-simple.c": "894f460c36d0da16104fdadccb56d03fc2df51462241fb93dc2bf254ca759ab5",
    }.items():
        if sha((replay_dir / relative).read_bytes()) != expected:
            raise ValueError("frozen earlier candidate differs: " + relative)
    original_clean()
    if publish:
        if public.exists():
            if public.read_bytes() != data:
                raise ValueError("public patch changed before publication")
        else:
            with public.open("xb") as handle:
                handle.write(data)
    manifest = {"kernel_commit": COMMIT, "original_tree_clean": True, "board_tested": False,
                "production_build_completed": False, "source_sha256_before": SOURCES,
                "source_sha256": {relative: sha(contents) for relative, contents in after.items()},
                "patch_sha256": sha(data), "public_patch": str(public), "published": publish,
                "generator_sha256": sha(Path(__file__).read_bytes()),
                "extractor_sha256": sha((HERE / "test-asoc-functions.py").read_bytes()),
                "full_board_patch_replay": records,
                "replay_files_sha256": {str(p.relative_to(replay_dir)): sha(p.read_bytes())
                                        for p in sorted(replay_dir.rglob("*")) if p.is_file()}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return output, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    output, manifest = prepare(args.version, args.publish)
    print(json.dumps({"output": str(output), "source_sha256": manifest["source_sha256"],
                      "patch_sha256": manifest["patch_sha256"], "published": args.publish}))


if __name__ == "__main__":
    main()
