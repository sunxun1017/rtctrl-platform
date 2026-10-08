#!/usr/bin/env python3
"""Record refused WFE/invalid hardware START in the controller sticky errno."""
import difflib,json,subprocess
from pathlib import Path
from source_utils import function,replace,sha
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
KERNEL=ROOT/"third_party/linux-rk3588"

def main():
    old=HERE/"driver-source-v17";out=HERE/"driver-source-v18"
    if out.exists():raise ValueError("fresh output required")
    receipt=(HERE/"C1-review-v4/receipt.json").read_bytes()
    if sha(receipt)!="486c294feacafb737853d01230e0ae1feb9668be2a4f63f6f151458831b89702":raise ValueError("frozen receipt drift")
    r=json.loads(receipt);manifest=json.loads((old/"manifest.json").read_text())
    for argv,wanted in [(["git","-C",KERNEL,"rev-parse","HEAD"],manifest["kernel_commit"]),(["git","-C",KERNEL,"status","--porcelain"],"")]:
        if subprocess.run(argv,check=True,capture_output=True,text=True).stdout.strip()!=wanted:raise ValueError("original lock/clean rejected")
    paths=["drivers/dma/pl330.c","include/linux/dmaengine.h","drivers/dma/dmaengine.c"];after={}
    for path in paths:
        data=(old/path).read_bytes()
        if sha(data)!=r["files_sha256"][str((old/path).relative_to(HERE))]:raise ValueError("frozen candidate drift")
        after[path]=data
    source=after[paths[0]].decode();body=function(source,"_start")
    new=replace(body,"\tcase PL330_STATE_WFE:\n\tdefault:\n\t\treturn false;",'''\tcase PL330_STATE_WFE:
	default:
		/* Every execution producer must expose an actual START refusal. */
		pl330_error_locked(thrd->dmac, -EIO);
		return false;''')
    after[paths[0]]=replace(source,body,new).encode();out.mkdir();patch=""
    for path,data in after.items():
        dst=out/path;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(data)
        patch+="diff --git a/"+path+" b/"+path+"\n"+"".join(difflib.unified_diff((KERNEL/path).read_text().splitlines(True),data.decode().splitlines(True),fromfile="a/"+path,tofile="b/"+path))
    (out/"C1-ownership-review.patch").write_text(patch)
    manifest.update({"parent_candidate":"driver-source-v17","parent_receipt_sha256":sha(receipt),"source_sha256":sha(after[paths[0]]),"patch_sha256":sha(patch.encode()),"generator_sha256":{n:sha((HERE/n).read_bytes()) for n in ["driver-prepare-c1-start.py","source_utils.py"]}})
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n");print(json.dumps({"output":str(out),**manifest}))
if __name__=="__main__":main()
