#!/usr/bin/env python3
"""Capture source/config/DT locks inside this output directory only."""
import json
import subprocess
from pathlib import Path
from source_utils import sha

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / "third_party/linux-rk3588"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
SOURCE = "sound/soc/rockchip/rockchip_i2s_tdm.c"
LOCKED = {
    KERNEL / SOURCE: "53de554206b13f13e480280b8f46366778c2837cdcba2cdb1417e0127be7ffda",
    ROOT / ".deps/kernel/aiot-3568pq-rcu-reset/.config": "1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912",
}
HEADERS = ["sound/soc/rockchip/rockchip_i2s_tdm.h", "include/sound/pcm.h",
           "include/sound/pcm_params.h", "include/uapi/sound/asound.h",
           "include/sound/soc-dai.h", "include/sound/soc-component.h",
           "include/sound/dmaengine_pcm.h", "include/linux/dmaengine.h"]


def main():
    output = HERE / "source-input-v1"
    if output.exists():
        raise ValueError("input directory exists")
    for argv, expected in [(["git", "-C", KERNEL, "rev-parse", "HEAD"], COMMIT),
                           (["git", "-C", KERNEL, "status", "--porcelain"], "")]:
        if subprocess.run(argv, check=True, capture_output=True, text=True).stdout.strip() != expected:
            raise ValueError("original kernel HEAD/clean gate rejected")
    records = {}
    data = {}
    for path, expected in LOCKED.items():
        raw = path.read_bytes()
        if sha(raw) != expected:
            raise ValueError("locked input rejected: " + str(path))
        relative = SOURCE if path == KERNEL / SOURCE else ".config"
        data[relative] = raw
        records[relative] = {"sha256": expected, "bytes": len(raw)}
    for relative in HEADERS:
        raw = (KERNEL / relative).read_bytes()
        if raw != subprocess.run(["git", "-C", KERNEL, "show", COMMIT + ":" + relative], check=True, capture_output=True).stdout:
            raise ValueError("header differs from commit")
        data[relative] = raw
        records[relative] = {"sha256": sha(raw), "bytes": len(raw)}
    output.mkdir()
    for relative, raw in data.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    result = {"kernel_commit": COMMIT, "files": records, "board_tested": False}
    (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
