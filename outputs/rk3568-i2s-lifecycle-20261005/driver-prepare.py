#!/usr/bin/env python3
"""Generate immutable review-only I2S candidates, never publish or mutate kernel."""
import argparse
import difflib
import json
import re
from pathlib import Path
from source_utils import sha
from i2s_changes import parameters
from i2s_lifecycle_changes import trigger
from i2s_irq_changes import irq_lifecycle
from i2s_pm_changes import pm_lifecycle
from i2s_status_changes import status_and_profile

HERE = Path(__file__).resolve().parent
SOURCE = "sound/soc/rockchip/rockchip_i2s_tdm.c"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--stage", choices=["params", "trigger", "irq", "pm"], default="params")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / ("driver-source-" + args.version)
    if output.exists():
        raise ValueError("candidate exists")
    original = (HERE / "source-input-v1" / SOURCE).read_bytes()
    if sha(original) != "53de554206b13f13e480280b8f46366778c2837cdcba2cdb1417e0127be7ffda":
        raise ValueError("original I2S lock rejected")
    text = parameters(original.decode())
    if args.stage in ["trigger", "irq", "pm"]:
        text = trigger(text)
    if args.stage in ["irq", "pm"]:
        text = irq_lifecycle(text)
    if args.stage == "pm":
        text = pm_lifecycle(text)
        text = status_and_profile(text)
    patch = "diff --git a/" + SOURCE + " b/" + SOURCE + "\n"
    patch += "".join(difflib.unified_diff(original.decode().splitlines(True), text.splitlines(True), fromfile="a/" + SOURCE, tofile="b/" + SOURCE))
    output.mkdir()
    target = output / SOURCE
    target.parent.mkdir(parents=True)
    target.write_text(text)
    (output / ("parameters-review.patch" if args.stage == "params" else "i2s-lifecycle-review.patch")).write_text(patch)
    generators = ["driver-prepare.py", "i2s_changes.py", "i2s_lifecycle_changes.py", "i2s_irq_changes.py", "i2s_pm_changes.py", "i2s_status_changes.py", "source_utils.py"]
    for name in generators:
        (output / name).write_bytes((HERE / name).read_bytes())
    manifest = {"kernel_commit": "9f9e9d18574d0914c0d192a90c3babfe1fd63c95", "source_sha256": sha(text.encode()), "original_sha256": sha(original), "patch_sha256": sha(patch.encode()),
                "generator_sha256": {n: sha((HERE / n).read_bytes()) for n in generators},
                "published": False, "deployable": False, "board_tested": False, "stage": args.stage + ("; checked locked profile enabled by probe" if args.stage == "pm" else "; checked flag not yet enabled by probe"),
                "remaining": ["probe/config/profile failure tests", "independent review and C3 combined lifecycle", "full Image and hardware acceptance"] if args.stage == "pm" else ["remaining lifecycle stages", "independent review and C3 combined lifecycle", "full Image and hardware acceptance"],
                "full_duplex_supported": False}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
