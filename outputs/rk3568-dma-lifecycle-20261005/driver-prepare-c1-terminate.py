#!/usr/bin/env python3
"""Count the public terminate admission before its unlocked PM boundary."""
import difflib,json,subprocess
from pathlib import Path
from source_utils import function,replace,sha
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
KERNEL=ROOT/"third_party/linux-rk3588"
PUBLIC='''static int pl330_terminate_all(struct dma_chan *chan)
{
	struct dma_pl330_chan *pch = to_pchan(chan);
	unsigned long flags;
	int ret;

	/* Public IRQ/callback-safe admission precedes any unlocked PM access.
	 * Close the epoch here so checked/free cannot pass this admitted operation.
	 * Repeated termination behind cutoff does not publish another old operation.
	 */
	spin_lock_irqsave(&pch->lock, flags);
	if (pch->quiescing || !pch->thread) {
		ret = READ_ONCE(pch->dmac->lifecycle_error);
		spin_unlock_irqrestore(&pch->lock, flags);
		return ret;
	}
	atomic_inc(&pch->operations);
	pch->quiescing = true;
	pch->epoch++;
	spin_unlock_irqrestore(&pch->lock, flags);
	ret = pl330_terminate_channel(chan);
	atomic_dec(&pch->operations);
	wake_up_all(&pch->drain_wait);
	return ret;
}
'''

def main():
    old=HERE/"driver-source-v16";out=HERE/"driver-source-v17"
    if out.exists():raise ValueError("fresh output required")
    receipt=(HERE/"C1-review-v3/receipt.json").read_bytes()
    if sha(receipt)!="8b3306e3f529a3ad9d834a4cf7ee1a5cb50f05159de0f9f675d64ba71716b890":raise ValueError("parent receipt drift")
    r=json.loads(receipt);manifest=json.loads((old/"manifest.json").read_text())
    for argv,wanted in [(["git","-C",KERNEL,"rev-parse","HEAD"],manifest["kernel_commit"]),(["git","-C",KERNEL,"status","--porcelain"],"")]:
        if subprocess.run(argv,check=True,capture_output=True,text=True).stdout.strip()!=wanted:raise ValueError("original lock/clean rejected")
    paths=["drivers/dma/pl330.c","include/linux/dmaengine.h","drivers/dma/dmaengine.c"];after={}
    for path in paths:
        data=(old/path).read_bytes()
        if sha(data)!=r["files_sha256"][str((old/path).relative_to(HERE))]:raise ValueError("parent candidate drift")
        after[path]=data
    source=after[paths[0]].decode();oldbody=function(source,"pl330_terminate_all")
    private=replace(oldbody,"static int pl330_terminate_all(","static int pl330_terminate_channel(")
    source=replace(source,oldbody,private+"\n\n"+PUBLIC)
    oldsync=function(source,"pl330_sync_channel")
    newsync=replace(oldsync,"\tpl330_terminate_all(chan);","\t/* Private cutoff is not an operation that would wait for itself. */\n\tpl330_terminate_channel(chan);")
    after[paths[0]]=replace(source,oldsync,newsync).encode();out.mkdir();patch=""
    for path,data in after.items():
        dst=out/path;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(data)
        patch+="diff --git a/"+path+" b/"+path+"\n"+"".join(difflib.unified_diff((KERNEL/path).read_text().splitlines(True),data.decode().splitlines(True),fromfile="a/"+path,tofile="b/"+path))
    (out/"C1-ownership-review.patch").write_text(patch)
    manifest.update({"parent_candidate":"driver-source-v16","parent_receipt_sha256":sha(receipt),"source_sha256":sha(after[paths[0]]),"patch_sha256":sha(patch.encode()),"generator_sha256":{n:sha((HERE/n).read_bytes()) for n in ["driver-prepare-c1-terminate.py","source_utils.py"]}})
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n");print(json.dumps({"output":str(out),**manifest}))
if __name__=="__main__":main()
