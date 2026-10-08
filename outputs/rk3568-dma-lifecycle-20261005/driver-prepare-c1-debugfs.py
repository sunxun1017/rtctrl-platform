#!/usr/bin/env python3
"""Increment frozen C1 without changing any frozen generator or evidence."""
import difflib,json,subprocess
from pathlib import Path
from source_utils import function,replace,sha
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
KERNEL=ROOT/"third_party/linux-rk3588"
COMMIT="9f9e9d18574d0914c0d192a90c3babfe1fd63c95"

def main():
    old=HERE/"driver-source-v15";out=HERE/"driver-source-v16"
    if out.exists():raise ValueError("fresh output required")
    receipt=(HERE/"C1-review-v2/receipt.json").read_bytes()
    if sha(receipt)!="9f7a85667dd343199923630f0b2a6e014a11a964a6fd2e057db55a763ae211f9":raise ValueError("frozen receipt drift")
    r=json.loads(receipt)
    for argv,wanted in [(["git","-C",KERNEL,"rev-parse","HEAD"],COMMIT),(["git","-C",KERNEL,"status","--porcelain"],"")]:
        if subprocess.run(argv,check=True,capture_output=True,text=True).stdout.strip()!=wanted:raise ValueError("original lock/clean rejected")
    files=["drivers/dma/pl330.c","include/linux/dmaengine.h","drivers/dma/dmaengine.c"];after={}
    for path in files:
        data=(old/path).read_bytes()
        if sha(data)!=r["files_sha256"][str((old/path).relative_to(HERE))]:raise ValueError("frozen candidate drift")
        after[path]=data
    source=after[files[0]].decode();body=function(source,"init_pl330_debugfs")
    new=replace(body,"\tdebugfs_create_file(",'''\t/* This checked profile does not publish the old unowned debugfs reader.
\t * Its raw controller/channel pointers cannot outlive destructive removal.
\t */
\tif (pl330->ddma.device_synchronize_checked)
\t\treturn;
\tdebugfs_create_file(''')
    after[files[0]]=replace(source,body,new).encode();out.mkdir();patch=""
    for path,data in after.items():
        dst=out/path;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(data)
        patch+="diff --git a/"+path+" b/"+path+"\n"+"".join(difflib.unified_diff((KERNEL/path).read_text().splitlines(True),data.decode().splitlines(True),fromfile="a/"+path,tofile="b/"+path))
    (out/"C1-ownership-review.patch").write_text(patch);manifest=json.loads((old/"manifest.json").read_text())
    manifest.update({"parent_candidate":"driver-source-v15","parent_receipt_sha256":sha(receipt),"source_sha256":sha(after[files[0]]),"header_sha256":sha(after[files[1]]),"core_sha256":sha(after[files[2]]),"patch_sha256":sha(patch.encode()),"published":False,"deployable":False,"debugfs_checked_profile_published":False,"generator_sha256":{n:sha((HERE/n).read_bytes()) for n in ["driver-prepare-c1-debugfs.py","source_utils.py"]}})
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n");print(json.dumps({"output":str(out),**manifest}))
if __name__=="__main__":main()
