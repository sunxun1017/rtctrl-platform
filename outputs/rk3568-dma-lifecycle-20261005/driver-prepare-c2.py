#!/usr/bin/env python3
"""Generate fresh C2 candidates on immutable C1 review source and frozen B."""
import argparse
import difflib
import json
import re
import subprocess
from pathlib import Path
from source_utils import sha,function
from pcm_memory_changes import memory_ownership
from pcm_dmaengine_changes import dma_pcm
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
KERNEL=ROOT/"third_party/linux-rk3588"
COMMIT="9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
C1=HERE/"driver-source-v17"
C1_RECEIPT_SHA="486c294feacafb737853d01230e0ae1feb9668be2a4f63f6f151458831b89702"

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--version",required=True);a=parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*",a.version):parser.error("fresh vN")
    output=HERE/("driver-source-c2-"+a.version)
    if output.exists():raise ValueError("candidate exists")
    if sha((HERE/"C1-review-v4/receipt.json").read_bytes())!=C1_RECEIPT_SHA:raise ValueError("C1 receipt drift")
    receipt=json.loads((HERE/"C1-review-v4/receipt.json").read_text())
    for argv,wanted in [(["git","-C",KERNEL,"rev-parse","HEAD"],COMMIT),(["git","-C",KERNEL,"status","--porcelain"],"")]:
        if subprocess.run(argv,check=True,capture_output=True,text=True).stdout.strip()!=wanted:raise ValueError("kernel lock/clean rejected")
    paths=["drivers/dma/pl330.c","include/linux/dmaengine.h","drivers/dma/dmaengine.c","sound/core/pcm_memory.c","include/sound/pcm.h","sound/core/pcm_dmaengine.c","sound/soc/soc-generic-dmaengine-pcm.c","include/sound/dmaengine_pcm.h"]
    before={path:(KERNEL/path).read_bytes() for path in paths};after=dict(before)
    for path in paths[:3]:
        data=(C1/path).read_bytes()
        if sha(data)!=receipt["files_sha256"][str((C1/path).relative_to(HERE))]:raise ValueError("C1 production bytes drift")
        after[path]=data
    after["sound/core/pcm_memory.c"],after["include/sound/pcm.h"]=map(str.encode,memory_ownership(before["sound/core/pcm_memory.c"].decode(),before["include/sound/pcm.h"].decode()))
    after["sound/core/pcm_dmaengine.c"],after["include/sound/dmaengine_pcm.h"],after["sound/soc/soc-generic-dmaengine-pcm.c"]=map(str.encode,dma_pcm(before["sound/core/pcm_dmaengine.c"].decode(),before["include/sound/dmaengine_pcm.h"].decode(),before["sound/soc/soc-generic-dmaengine-pcm.c"].decode()))
    attach_source=(KERNEL/"sound/core/pcm.c").read_bytes();attach=function(attach_source.decode(),"snd_pcm_attach_substream")
    if "runtime = kzalloc(sizeof(*runtime), GFP_KERNEL);" not in attach:raise ValueError("runtime zero-init proof absent")
    output.mkdir();patch=""
    for path,data in after.items():
        target=output/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        if data!=before[path]:patch+="diff --git a/"+path+" b/"+path+"\n"+"".join(difflib.unified_diff(before[path].decode().splitlines(True),data.decode().splitlines(True),fromfile="a/"+path,tofile="b/"+path))
    (output/"C2-allocation-review.patch").write_text(patch);(output/"runtime-init-input.c").write_bytes(attach_source);(output/"runtime-init-excerpt.c").write_text(attach)
    manifest={"kernel_commit":COMMIT,"published":False,"deployable":False,"phase":"C2 process guard registration and allocation ownership candidate; C3 and production compile incomplete","c1_receipt_sha256":C1_RECEIPT_SHA,"patch_sha256":sha(patch.encode()),"before_sha256":{p:sha(b) for p,b in before.items()},"source_sha256":{p:sha(b) for p,b in after.items()},"runtime_init_source_sha256":sha(attach_source),"runtime_init_excerpt_sha256":sha(attach.encode()),"generator_sha256":{n:sha((HERE/n).read_bytes()) for n in ["driver-prepare-c2.py","pcm_memory_changes.py","pcm_dmaengine_changes.py","source_utils.py"]}}
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n");print(json.dumps({"output":str(output),**manifest}))
if __name__=="__main__":main()
