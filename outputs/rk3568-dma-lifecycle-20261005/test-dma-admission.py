#!/usr/bin/env python3
"""Compile locked real DMA core registry/get with API boundaries only."""
import argparse
import json
import re
import subprocess
from pathlib import Path
from source_utils import function,sha
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--source-dir",type=Path,required=True);parser.add_argument("--label",required=True);args=parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*",args.label):parser.error("fresh red-vN / green-vN required")
    output=HERE/("dma-admission-tests-"+args.label);output.mkdir(exist_ok=False)
    candidate=args.source_dir/"drivers/dma/dmaengine.c";source=(candidate if candidate.exists() else ROOT/"third_party/linux-rk3588/drivers/dma/dmaengine.c").read_bytes();text=source.decode()
    have="int dmaengine_device_quiesce(" in text
    names=["balance_ref_count","dma_chan_get"]
    if have:names.extend(["dmaengine_device_quiesce","__dma_async_device_register"])
    names.append("dma_async_device_register")
    if have:names.append("dma_async_device_register_checked")
    bodies={n:function(text,n) for n in names}
    extracted=("#define HAVE_ADMISSION 1\n" if have else "")+"\n\n".join(bodies.values())+"\n"
    unit=output/"real-functions.c";unit.write_text('#include "test-dma-admission-shim.h"\n'+extracted+'\n#include "test-dma-admission-main.c"\n')
    for n in ["test-dma-admission-shim.h","test-dma-admission-main.c","test-dma-admission.py","source_utils.py"]:(output/n).write_bytes((HERE/n).read_bytes())
    (output/"source-input.c").write_bytes(source);(output/"extracted.c").write_text(extracted)
    result={"source_sha256":sha(source),"extracted_sha256":sha(extracted.encode()),"unit_sha256":sha(unit.read_bytes()),"excerpts_sha256":{n:sha(b.encode()) for n,b in bodies.items()},"harness_sha256":{n:sha((output/n).read_bytes()) for n in ["test-dma-admission-shim.h","test-dma-admission-main.c","test-dma-admission.py","source_utils.py"]},"runs":{}}
    failed=False
    def run(argv,stem):
        r=subprocess.run([str(x) for x in argv],capture_output=True,text=True,timeout=30);(output/(stem+".stdout")).write_text(r.stdout);(output/(stem+".stderr")).write_text(r.stderr)
        return r,{"returncode":r.returncode,"stdout_sha256":sha(r.stdout.encode()),"stderr_sha256":sha(r.stderr.encode()),"argv":[str(x) for x in argv]}
    for label,compiler,flags,launcher in [("host","gcc",[],[]),("host-sanitized","gcc",["-O1","-g","-fsanitize=address,undefined","-no-pie"],[]),("aarch64","aarch64-linux-gnu-gcc",["-static"],[ROOT/".deps/qemu-user/root/usr/bin/qemu-aarch64-static"])]:
        binary=output/("dma-core-"+label);c,rec=run([compiler,"-std=gnu11","-O2","-pthread","-Wall","-Wextra","-Werror","-Wno-unused-parameter",*flags,unit,"-o",binary],label+"-compile");record={"compile":rec}
        if c.returncode:failed=True
        else:
            c,rec=run([*launcher,binary],label);record.update({"execution":rec,"binary_sha256":sha(binary.read_bytes()),"tests":json.loads(c.stdout)});failed|=c.returncode!=0
        result["runs"][label]=record
    result["passed"]=not failed;(output/"result.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps({"result":str(output/"result.json"),"passed":not failed,"runs":{n:r.get("tests",r["compile"]) for n,r in result["runs"].items()}}));return int(failed)
if __name__=="__main__":raise SystemExit(main())
