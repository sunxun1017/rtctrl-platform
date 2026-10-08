#!/usr/bin/env python3
"""Real PCM allocation/free/owner transfer, API allocator boundaries only."""
import argparse
import json
import re
import subprocess
from pathlib import Path
from source_utils import function,declaration,sha
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--source-dir",type=Path,required=True);p.add_argument("--label",required=True);a=p.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*",a.label):p.error("fresh red-vN / green-vN")
    out=HERE/("pcm-tests-memory-"+a.label);out.mkdir(exist_ok=False);candidate=a.source_dir/"sound/core/pcm_memory.c";source=(candidate if candidate.exists() else ROOT/"third_party/linux-rk3588/sound/core/pcm_memory.c").read_bytes();text=source.decode()
    h=(ROOT/"third_party/linux-rk3588/include/sound/memalloc.h").read_bytes();abi="\n".join(declaration(h.decode(),"struct",n) for n in ["snd_dma_device","snd_dma_buffer"])+"\n"
    (out/"dma-buffer-types.h").write_text(abi);(out/"memalloc-input.h").write_bytes(h)
    ph=a.source_dir/"include/sound/pcm.h";ph=(ph if ph.exists() else ROOT/"third_party/linux-rk3588/include/sound/pcm.h").read_bytes();setbuf=function(ph.decode(),"snd_pcm_set_runtime_buffer")
    names=["do_free_pages","do_alloc_pages","snd_pcm_lib_preallocate_dma_free","snd_pcm_lib_preallocate_free","snd_pcm_lib_free_pages","snd_pcm_lib_malloc_pages"]
    have="struct snd_pcm_dma_quarantine {" in text
    extra=""
    if have:
        names[0:0]=["snd_pcm_dma_quarantine_alloc","snd_pcm_dma_quarantine_free","snd_pcm_dma_quarantine_bytes","snd_pcm_dma_quarantine_check","snd_pcm_dma_quarantine"]
        extra="#define HAVE_QUARANTINE 1\n"+declaration(text,"struct","snd_pcm_dma_quarantine")+"\nstatic LIST_HEAD(pcm_dma_quarantine);\nstatic DEFINE_MUTEX(pcm_dma_quarantine_lock);\nstatic atomic_long_t pcm_dma_quarantine_bytes = ATOMIC_LONG_INIT(0);\n"
    bodies={n:function(text,n) for n in names};extracted=text[:text.index("#include")]+extra+setbuf+"\n\n"+"\n\n".join(bodies.values())+"\n"
    for n in ["test-pcm-memory-shim.h","test-pcm-memory-main.c","test-pcm-memory.py","source_utils.py"]:(out/n).write_bytes((HERE/n).read_bytes())
    (out/"source-input.c").write_bytes(source);(out/"pcm-header-input.h").write_bytes(ph);(out/"extracted.c").write_text(extracted);unit=out/"real-functions.c";unit.write_text('#include "test-pcm-memory-shim.h"\n'+extracted+'\n#include "test-pcm-memory-main.c"\n')
    result={"source_sha256":sha(source),"abi_sha256":sha(abi.encode()),"header_sha256":sha(ph),"extracted_sha256":sha(extracted.encode()),"unit_sha256":sha(unit.read_bytes()),"excerpts_sha256":{n:sha(b.encode()) for n,b in bodies.items()},"harness_sha256":{n:sha((out/n).read_bytes()) for n in ["test-pcm-memory-shim.h","test-pcm-memory-main.c","test-pcm-memory.py","source_utils.py"]},"runs":{}}
    failed=False
    def run(argv,stem):
        c=subprocess.run([str(x) for x in argv],capture_output=True,text=True,timeout=30);(out/(stem+".stdout")).write_text(c.stdout);(out/(stem+".stderr")).write_text(c.stderr);return c,{"returncode":c.returncode,"stdout_sha256":sha(c.stdout.encode()),"stderr_sha256":sha(c.stderr.encode()),"argv":[str(x) for x in argv]}
    for label,compiler,flags,launcher in [("host","gcc",[],[]),("host-sanitized","gcc",["-O1","-g","-fsanitize=address,undefined","-no-pie"],[]),("aarch64","aarch64-linux-gnu-gcc",["-static"],[ROOT/".deps/qemu-user/root/usr/bin/qemu-aarch64-static"])]:
        binary=out/("pcm-memory-"+label);c,rec=run([compiler,"-std=gnu11","-O2","-pthread","-Wall","-Wextra","-Werror","-Wno-unused-parameter",*flags,unit,"-o",binary],label+"-compile");record={"compile":rec}
        if c.returncode:failed=True
        else:
            c,rec=run([*launcher,binary],label)
            try:tests=json.loads(c.stdout)
            except ValueError:tests={"unavailable":True}
            record.update({"execution":rec,"binary_sha256":sha(binary.read_bytes()),"tests":tests});failed|=c.returncode!=0
        result["runs"][label]=record
    result["passed"]=not failed;(out/"result.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps({"result":str(out/"result.json"),"passed":not failed,"runs":{n:r.get("tests",r["compile"]) for n,r in result["runs"].items()}}));return int(failed)
if __name__=="__main__":raise SystemExit(main())
