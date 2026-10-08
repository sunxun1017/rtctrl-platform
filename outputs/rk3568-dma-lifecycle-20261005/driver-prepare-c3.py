#!/usr/bin/env python3
"""C3 increment on frozen B, C2 allocation source and latest reviewed C1 source."""
import argparse,difflib,json,re,subprocess
from pathlib import Path
from source_utils import sha
from asoc_trigger_changes import asoc_trigger
from pl330_status_changes import provider_increment,pcm_status_increment
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
KERNEL=ROOT/"third_party/linux-rk3588"
COMMIT="9f9e9d18574d0914c0d192a90c3babfe1fd63c95"

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--version",required=True);a=p.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*",a.version):p.error("fresh vN")
    out=HERE/("driver-source-c3-"+a.version)
    if out.exists():raise ValueError("fresh candidate required")
    for argv,wanted in [(["git","-C",KERNEL,"rev-parse","HEAD"],COMMIT),(["git","-C",KERNEL,"status","--porcelain"],"")]:
        if subprocess.run(argv,check=True,capture_output=True,text=True).stdout.strip()!=wanted:raise ValueError("locked original rejected")
    c2=HERE/"driver-source-c2-v3";c2manifest=json.loads((c2/"manifest.json").read_text());before={};after={}
    for path,wanted in c2manifest["source_sha256"].items():
        data=(c2/path).read_bytes()
        if sha(data)!=wanted:raise ValueError("C2 source drift")
        before[path]=(KERNEL/path).read_bytes();after[path]=data
    c1=HERE/"driver-source-v18";receipt=(HERE/"C1-review-v5/receipt.json").read_bytes()
    if sha(receipt)!="adf2ee8f327d9ab5f2021ce3a43a792360d15b50ac8f801b159b9f5fb65fc908":raise ValueError("C1 receipt drift")
    c1manifest=json.loads((c1/"manifest.json").read_text())
    for path,field in [("drivers/dma/pl330.c","source_sha256"),("include/linux/dmaengine.h","header_sha256"),("drivers/dma/dmaengine.c","core_sha256")]:
        data=(c1/path).read_bytes()
        if sha(data)!=c1manifest[field]:raise ValueError("C1 source drift")
        after[path]=data
    b=ROOT/"outputs/rk3568-asoc-errors-20261005/driver-source-v2"
    for path,wanted in [("sound/soc/soc-pcm.c","0da4f2816f293dc782fa83260f9d59735553064836fc333edc8c70556361d1b0"),("sound/core/pcm_native.c","bc34db0aabe8b523172403a4095afeac5544434e15a05884ca99f6b77d48c47d")]:
        data=(b/path).read_bytes()
        if sha(data)!=wanted:raise ValueError("B source lock drift")
        before[path]=after[path]=data
    for path in ["sound/soc/soc-component.c","sound/soc/soc-dai.c"]:before[path]=after[path]=(KERNEL/path).read_bytes()
    names=["sound/soc/soc-pcm.c","sound/soc/soc-component.c","sound/soc/soc-dai.c"]
    changed=asoc_trigger(*[after[path].decode() for path in names])
    for path,text in zip(names,changed):after[path]=text.encode()
    after["drivers/dma/pl330.c"]=provider_increment(after["drivers/dma/pl330.c"].decode()).encode()
    pcm_path="sound/core/pcm.c";before[pcm_path]=(KERNEL/pcm_path).read_bytes()
    memory,pcm=pcm_status_increment(after["sound/core/pcm_memory.c"].decode(),before[pcm_path].decode())
    after["sound/core/pcm_memory.c"]=memory.encode();after[pcm_path]=pcm.encode()
    out.mkdir();patch=""
    for path,data in after.items():
        target=out/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        if data!=before[path]:patch+="diff --git a/"+path+" b/"+path+"\n"+"".join(difflib.unified_diff(before[path].decode().splitlines(True),data.decode().splitlines(True),fromfile="a/"+path,tofile="b/"+path))
    (out/"C3-lifecycle-review.patch").write_text(patch)
    manifest={"kernel_commit":COMMIT,"published":False,"deployable":False,"production_compiled":False,"board_tested":False,"c1_receipt_sha256":sha(receipt),"c2_manifest_sha256":sha((c2/"manifest.json").read_bytes()),"phase":"C3 group rollback candidate; full public replay, provider+PCM chain and readonly state final review pending","source_sha256":{path:sha(data) for path,data in after.items()},"before_sha256":{path:sha(data) for path,data in before.items()},"patch_sha256":sha(patch.encode()),"generator_sha256":{name:sha((HERE/name).read_bytes()) for name in ["driver-prepare-c3.py","asoc_trigger_changes.py","pl330_status_changes.py","source_utils.py"]}}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n");print(json.dumps({"output":str(out),**manifest}))
if __name__=="__main__":main()
