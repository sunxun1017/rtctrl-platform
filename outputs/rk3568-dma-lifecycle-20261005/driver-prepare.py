#!/usr/bin/env python3
"""Generate review-only C stage source copies; never mutate original kernel."""
import argparse
import difflib
import json
import re
import subprocess
from pathlib import Path
from source_utils import sha
from pl330_changes import ownership
from pl330_hardware_changes import bounded_hardware
from pl330_sync_changes import synchronization
from pl330_io_changes import powered_io
from pl330_release_changes import channel_release
from dma_admission_changes import admission
from pl330_device_changes import device_release
from pl330_gc_changes import idle_reclaim

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
KERNEL=ROOT/"third_party/linux-rk3588"
COMMIT="9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
SOURCE="drivers/dma/pl330.c"
SOURCE_SHA="8fa1c9f54d7ef9bdd6ce2fedf356144db31f5e1d1f1005e3a0365b1f8b0e5627"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version",required=True)
    args=parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*",args.version):parser.error("version must be vN")
    output=HERE/("driver-source-"+args.version)
    if output.exists():raise ValueError("refuse overwriting candidate")
    for argv,expected in [(["git","-C",KERNEL,"rev-parse","HEAD"],COMMIT),(["git","-C",KERNEL,"status","--porcelain"],"")]:
        if subprocess.run(argv,check=True,capture_output=True,text=True).stdout.strip()!=expected:raise ValueError("original kernel lock/clean gate rejected")
    before=(KERNEL/SOURCE).read_bytes()
    if sha(before)!=SOURCE_SHA:raise ValueError("original PL330 SHA rejected")
    header_path="include/linux/dmaengine.h"
    before_header=(KERNEL/header_path).read_bytes()
    if before_header!=subprocess.run(["git","-C",KERNEL,"show",COMMIT+":"+header_path],check=True,capture_output=True).stdout:raise ValueError("original DMA header bytes rejected")
    after_text,after_header=synchronization(bounded_hardware(ownership(before.decode())),before_header.decode())
    after_text=channel_release(powered_io(after_text))
    core_path="drivers/dma/dmaengine.c"
    before_core=(KERNEL/core_path).read_bytes()
    if before_core!=subprocess.run(["git","-C",KERNEL,"show",COMMIT+":"+core_path],check=True,capture_output=True).stdout:raise ValueError("original DMA core bytes rejected")
    after_text,after_header,after_core=admission(after_text,after_header,before_core.decode())
    after_text=idle_reclaim(device_release(after_text))
    after=after_text.encode();after_header=after_header.encode()
    output.mkdir();target=output/SOURCE;target.parent.mkdir(parents=True);target.write_bytes(after)
    (output/"source-input.c").write_bytes(before)
    target_header=output/header_path;target_header.parent.mkdir(parents=True);target_header.write_bytes(after_header)
    (output/"header-input.h").write_bytes(before_header)
    (output/core_path).write_text(after_core);(output/"core-input.c").write_bytes(before_core)
    patch="diff --git a/"+SOURCE+" b/"+SOURCE+"\n"+"".join(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile="a/"+SOURCE,tofile="b/"+SOURCE))
    patch+="diff --git a/"+header_path+" b/"+header_path+"\n"+"".join(difflib.unified_diff(before_header.decode().splitlines(True),after_header.decode().splitlines(True),fromfile="a/"+header_path,tofile="b/"+header_path))
    patch+="diff --git a/"+core_path+" b/"+core_path+"\n"+"".join(difflib.unified_diff(before_core.decode().splitlines(True),after_core.splitlines(True),fromfile="a/"+core_path,tofile="b/"+core_path))
    (output/"C1-ownership-review.patch").write_text(patch)
    manifest={"kernel_commit":COMMIT,"source_sha256_before":sha(before),"source_sha256":sha(after),"patch_sha256":sha(patch.encode()),
              "published":False,"deployable":False,"phase":"C1b software/hardware proof candidate; production compile, PCM quarantine and trigger rollback incomplete",
              "header_sha256_before":sha(before_header),"header_sha256":sha(after_header),
              "core_sha256_before":sha(before_core),"core_sha256":sha(after_core.encode()),
              "remaining":["full provider production compile","PCM coherent allocation quarantine","ASoC START rollback and STOP cleanup"],
              "generator_sha256":{name:sha((HERE/name).read_bytes()) for name in ["driver-prepare.py","pl330_changes.py","pl330_hardware_changes.py","pl330_sync_changes.py","pl330_io_changes.py","pl330_release_changes.py","dma_admission_changes.py","pl330_device_changes.py","pl330_gc_changes.py","source_utils.py"]}}
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(json.dumps({"output":str(output),**manifest}))


if __name__=="__main__":main()
