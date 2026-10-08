#!/usr/bin/env python3
"""Actual DMA PCM + allocator + native HW_PARAMS/release chain, kernel API boundaries."""
import argparse,json,re,subprocess
from pathlib import Path
from source_utils import function,declaration,sha
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--source-dir",type=Path,required=True);p.add_argument("--label",required=True);a=p.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*",a.label):p.error("fresh label")
    out=HERE/("trigger-tests-"+a.label);out.mkdir(exist_ok=False)
    def read(path):
        candidate=a.source_dir/path
        return (candidate if candidate.exists() else ROOT/"third_party/linux-rk3588"/path).read_bytes()
    paths=["sound/core/pcm_memory.c","sound/core/pcm_dmaengine.c","sound/soc/soc-generic-dmaengine-pcm.c","include/sound/pcm.h","include/sound/dmaengine_pcm.h","include/linux/dmaengine.h"]
    sources={path:read(path) for path in paths};memory=sources[paths[0]].decode();engine=sources[paths[1]].decode();generic=sources[paths[2]].decode()
    for path in ["sound/soc/soc-pcm.c","sound/soc/soc-component.c","sound/soc/soc-dai.c","sound/soc/soc-link.c"]:
        if path=="sound/soc/soc-pcm.c" and not (a.source_dir/path).exists():sources[path]=(ROOT/"outputs/rk3568-asoc-errors-20261005/driver-source-v2"/path).read_bytes()
        else:sources[path]=read(path)
    soc_header=(ROOT/"third_party/linux-rk3588/include/sound/soc.h").read_bytes();(out/"soc-header-input.h").write_bytes(soc_header)
    lines=soc_header.decode().splitlines(True);macros=""
    for n in ["for_each_rtd_dais","for_each_rtd_components"]:
        start=next(i for i,line in enumerate(lines) if line.startswith("#define "+n+"("));i=start
        while lines[i].rstrip().endswith("\\"):i+=1
        macros+="".join(lines[start:i+1])
    (out/"asoc-iteration-macros.h").write_text(macros)
    constants="\n".join(line for line in sources["include/sound/pcm.h"].decode().splitlines() if line.startswith("#define SNDRV_PCM_TRIGGER"))+"\n";(out/"pcm-trigger-constants.h").write_text(constants)
    memalloc=(ROOT/"third_party/linux-rk3588/include/sound/memalloc.h").read_bytes();abi="\n".join(declaration(memalloc.decode(),"struct",n) for n in ["snd_dma_device","snd_dma_buffer"])+"\n";(out/"dma-buffer-types.h").write_text(abi);(out/"memalloc-input.h").write_bytes(memalloc)
    memconstants=memalloc.decode().split("#define SNDRV_DMA_TYPE_UNKNOWN",1)[1].split("/*\n * info for buffer allocation",1)[0];memconstants="#define SNDRV_DMA_TYPE_UNKNOWN"+memconstants;(out/"memalloc-constants.h").write_text(memconstants)
    allocator=(ROOT/"third_party/linux-rk3588/sound/core/memalloc.c").read_bytes();(out/"allocator-input.c").write_bytes(allocator)
    public=sources[paths[-1]].decode();dmaabi="\n".join(declaration(public,"enum",n) for n in ["dma_status","dma_transfer_direction"])+"\n"+declaration(public,"struct","dma_tx_state")+"\n";(out/"dmaengine-types.h").write_text(dmaabi)
    public_names=["dma_submit_error","dmaengine_submit","dmaengine_prep_dma_cyclic","dma_async_issue_pending","dmaengine_resume","dmaengine_pause","dmaengine_terminate_async","dmaengine_synchronize","dmaengine_synchronize_checked","dmaengine_tx_status"]
    excerpts={"dmaapi:"+n:function(public,n) for n in public_names}
    excerpts["direction"]=function(sources["include/sound/dmaengine_pcm.h"].decode(),"snd_pcm_substream_to_dma_direction")
    excerpts["setbuf"]=function(sources["include/sound/pcm.h"].decode(),"snd_pcm_set_runtime_buffer")
    excerpts.update({"allocator:"+n:function(allocator.decode(),n) for n in ["snd_malloc_dev_pages","snd_free_dev_pages","snd_malloc_dev_iram","snd_free_dev_iram","snd_dma_alloc_pages","snd_dma_free_pages"]})
    memory_names=["snd_pcm_dma_quarantine_alloc","snd_pcm_dma_quarantine_free","snd_pcm_dma_quarantine_bytes","snd_pcm_dma_quarantine_check","snd_pcm_dma_quarantine","do_free_pages","do_alloc_pages","snd_pcm_lib_preallocate_dma_free","snd_pcm_lib_preallocate_free","snd_pcm_lib_free_pages","snd_pcm_lib_malloc_pages"]
    memory_extra=declaration(memory,"struct","snd_pcm_dma_quarantine")+"\nstatic LIST_HEAD(pcm_dma_quarantine);\nstatic DEFINE_MUTEX(pcm_dma_quarantine_lock);\nstatic atomic_long_t pcm_dma_quarantine_bytes = ATOMIC_LONG_INIT(0);\n"
    excerpts.update({"memory:"+n:function(memory,n) for n in memory_names})
    engine_names=["substream_to_prtd"]
    have="int snd_dmaengine_pcm_quiesce(" in engine
    if have:engine_names.extend(["dmaengine_pcm_failstop","dmaengine_pcm_error","dmaengine_pcm_operation_begin","dmaengine_pcm_operation_end","snd_dmaengine_pcm_quiesce"])
    engine_names.extend(["dmaengine_pcm_dma_complete","dmaengine_pcm_prepare_and_submit","snd_dmaengine_pcm_trigger","snd_dmaengine_pcm_open","snd_dmaengine_pcm_close","snd_dmaengine_pcm_close_release_chan"])
    excerpts.update({"engine:"+n:function(engine,n) for n in engine_names})
    if have:excerpts["component:quiesce"]=function(generic,"dmaengine_pcm_quiesce")
    excerpts["generic:trigger"]=function(generic,"dmaengine_pcm_trigger")
    for path,names in [("sound/soc/soc-component.c",["_soc_component_ret","snd_soc_pcm_component_trigger"]),("sound/soc/soc-dai.c",["_soc_dai_ret","snd_soc_pcm_dai_trigger"]),("sound/soc/soc-link.c",["_soc_link_ret","snd_soc_link_trigger"]),("sound/soc/soc-pcm.c",["soc_pcm_trigger"])]:
        excerpts.update({path+":"+n:function(sources[path].decode(),n) for n in names})
    # Real core managed allocation and close ordering; B source is frozen.
    native=(ROOT/"outputs/rk3568-asoc-errors-20261005/driver-source-v2/sound/core/pcm_native.c").read_bytes();native_names=["snd_pcm_sync_stop","snd_pcm_hw_params","do_hw_free","snd_pcm_release_substream","snd_pcm_pre_start","snd_pcm_do_start"]
    native_excerpts={"native:"+n:function(native.decode(),n) for n in native_names}
    attach=(ROOT/"third_party/linux-rk3588/sound/core/pcm.c").read_bytes();init_excerpt=function(attach.decode(),"snd_pcm_attach_substream")
    if "runtime = kzalloc(sizeof(*runtime), GFP_KERNEL);" not in init_excerpt:raise ValueError("real runtime zero-init absent")
    (out/"runtime-init-source.c").write_bytes(attach);(out/"runtime-init-excerpt.c").write_text(init_excerpt)
    for path,data in sources.items():(out/(path.replace("/","-")+".input")).write_bytes(data)
    (out/"native-input.c").write_bytes(native)
    names=["test-asoc-trigger.py","test-pcm-chain-asoc.h","test-asoc-trigger-main.c","test-pcm-chain-shim.h","test-pcm-chain-atomic.h","test-pcm-chain-runtime.h","test-pcm-chain-dma.h","test-pcm-chain-native.h","test-pcm-chain-allocator.h","test-pcm-chain-main.c","source_utils.py"]
    for name in names:(out/name).write_bytes((HERE/name).read_bytes())
    prefix=memory[:memory.index("#include")]+"#define HAVE_ASOC_CHAIN 1\n"+("#define HAVE_PCM_QUIESCE 1\n" if have else "")
    prtd=declaration(engine,"struct","dmaengine_pcm_runtime_data")
    extracted=prefix+memory_extra+prtd+"\n"+"\n\n".join(excerpts.values())
    native_extract="\n\n".join(native_excerpts.values())
    (out/"extracted.c").write_text(extracted);(out/"native-extracted.c").write_text(native_extract)
    unit=out/"real-functions.c";unit.write_text('#include "test-pcm-chain-shim.h"\n#include "test-pcm-chain-dma.h"\n#include "test-pcm-chain-asoc.h"\n'+extracted+'\n#include "test-pcm-chain-native.h"\n'+native_extract+'\n#include "test-pcm-chain-main.c"\n')
    result={"source_sha256":{path:sha(data) for path,data in sources.items()},"native_sha256":sha(native),"memalloc_sha256":sha(memalloc),"dma_buffer_abi_sha256":sha(abi.encode()),"dma_abi_sha256":sha(dmaabi.encode()),"extracted_sha256":sha(extracted.encode()),"native_extracted_sha256":sha(native_extract.encode()),"unit_sha256":sha(unit.read_bytes()),"excerpts_sha256":{n:sha(body.encode()) for n,body in {**excerpts,**native_excerpts}.items()},"harness_sha256":{n:sha((out/n).read_bytes()) for n in names},"runs":{}};failed=False
    def run(argv,stem):
        c=subprocess.run([str(x) for x in argv],capture_output=True,text=True,timeout=30);(out/(stem+".stdout")).write_text(c.stdout);(out/(stem+".stderr")).write_text(c.stderr)
        return c,{"returncode":c.returncode,"stdout_sha256":sha(c.stdout.encode()),"stderr_sha256":sha(c.stderr.encode()),"argv":[str(x) for x in argv]}
    for label,compiler,flags,launcher in [("host","gcc",[],[]),("host-sanitized","gcc",["-O1","-g","-fsanitize=address,undefined","-no-pie"],[]),("aarch64","aarch64-linux-gnu-gcc",["-static"],[ROOT/".deps/qemu-user/root/usr/bin/qemu-aarch64-static"])]:
        binary=out/("pcm-chain-"+label);c,rec=run([compiler,"-std=gnu11","-O2","-pthread","-Wall","-Wextra","-Werror","-Wno-unused-parameter",*flags,unit,"-o",binary],label+"-compile");record={"compile":rec}
        if c.returncode:failed=True
        else:
            c,rec=run([*launcher,binary],label)
            try:tests=json.loads(c.stdout)
            except ValueError:tests={"unavailable":True}
            record.update({"execution":rec,"binary_sha256":sha(binary.read_bytes()),"tests":tests});failed|=c.returncode!=0
        result["runs"][label]=record
    result["trigger_constants_sha256"]=sha(constants.encode());result["allocator_source_sha256"]=sha(allocator);result["allocator_constants_sha256"]=sha(memconstants.encode());result["soc_header_sha256"]=sha(soc_header);result["iteration_macros_sha256"]=sha(macros.encode())
    result["passed"]=not failed;(out/"result.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps({"result":str(out/"result.json"),"passed":not failed,"runs":{n:r.get("tests",r["compile"]) for n,r in result["runs"].items()}}));return int(failed)
if __name__=="__main__":raise SystemExit(main())
