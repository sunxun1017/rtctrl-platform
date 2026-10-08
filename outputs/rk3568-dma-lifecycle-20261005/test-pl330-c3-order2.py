#!/usr/bin/env python3
"""Extract real PL330 queue/runner functions and run deterministic pthread barriers."""
import argparse
import json
import re
import subprocess
from pathlib import Path
from source_utils import function, declaration, sha

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SOURCE="drivers/dma/pl330.c"
NAMES=["to_pchan","to_desc","pl330_tx_submit","_init_desc","add_desc","pluck_desc","pl330_get_desc",
       "fill_queue","dma_pl330_rqcb","pl330_tasklet","pl330_terminate_all","pl330_issue_pending"]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir",type=Path,required=True)
    parser.add_argument("--label",required=True)
    args=parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*",args.label):parser.error("label must be red-vN / green-vN")
    output=HERE/("pl330-c3-order2-tests-"+args.label);output.mkdir(exist_ok=False)
    source=args.source_dir/SOURCE;data=source.read_bytes();text=data.decode()
    names=list(NAMES)
    names[names.index("fill_queue"):names.index("fill_queue")]=["_queue_full","_manager_ns","_prepare_ccr","pl330_submit_req"]
    names[names.index("pl330_tasklet"):names.index("pl330_tasklet")]=["pl330_dotask","pl330_update"]
    names.extend(["pl330_dma_slave_map_dir","pl330_unprep_slave_fifo","pl330_prep_slave_fifo","fixup_burst_len","pl330_config_write","fill_px","pl330_prep_dma_cyclic","pl330_prep_slave_sg"])
    names.extend(["pl330_irq_handler","pl330_get_current_xferred_count","pl330_pause","pl330_tx_status"])
    if "static int pl330_operation_begin(" in text:
        names[names.index("pl330_pause"):names.index("pl330_pause")]=["pl330_operation_begin","pl330_operation_end"]
    have_gc="static void pl330_gc_work(" in text
    have_lifecycle="static void pl330_run(" in text
    if have_lifecycle:
        names[2:2]=[*( ["pl330_error_locked"] if "static void pl330_error_locked(" in text else []),*( ["pl330_pm_error_locked"] if "static void pl330_pm_error_locked(" in text else []),"pl330_desc_get","pl330_desc_put","pl330_desc_release","__pl330_giveback_desc","pl330_schedule_locked"]
        names.insert(names.index("pl330_tasklet"),"pl330_run")
        if have_gc:names.insert(names.index("pl330_run"),"pl330_gc_schedule_locked")
    if "static bool pl330_prep_begin(" in text:
        names[names.index("pl330_prep_dma_cyclic"):names.index("pl330_prep_dma_cyclic")]=[*( ["pl330_fifo_config_same"] if "static bool pl330_fifo_config_same(" in text else []),"pl330_prep_begin","pl330_prep_end"]
    checked_api="static int pl330_synchronize_checked(" in text
    if checked_api:
        names.extend(["pl330_failstop","pl330_software_drained_locked","pl330_software_drained","pl330_synchronize_checked","pl330_synchronize"])
    if "static int pl330_sync_channel(" in text:
        names.insert(names.index("pl330_synchronize_checked"),"pl330_sync_channel")
        if "static void pl330_capture_stop_locked(" in text:names.insert(names.index("pl330_sync_channel"),"pl330_capture_stop_locked")
    if have_gc:names.insert(names.index("pl330_sync_channel"),"pl330_gc_work")
    names.extend(["_chan_ns","_alloc_event","_free_event","pl330_request_channel","pl330_release_channel","pl330_alloc_chan_resources","pl330_free_chan_resources"])
    names.append("pl330_wait_state")
    if "static bool pl330_controller_drained(" in text:names.extend(["pl330_controller_drained","pl330_controller_stop_proof"])
    if "static void pl330_reader_remove(" in text:names.extend(["pl330_reader_deadline","pl330_reader_remove","pl330_irqs_remove"])
    names.extend(["dmac_free_threads","pl330_del","pl330_remove","pl330_suspend","pl330_resume"])
    if "static int pl330_terminate_channel(" in text:names.insert(names.index("pl330_terminate_all"),"pl330_terminate_channel")
    names.insert(names.index("pl330_dotask"),"_start")
    bodies={name:function(text,name) for name in names}
    api_source=(ROOT/"third_party/linux-rk3588/drivers/dma/dmaengine.h").read_bytes()
    api_bodies={name:function(api_source.decode(),name) for name in ["dma_cookie_init","dma_cookie_assign","dma_cookie_complete","dma_cookie_status","dma_set_residue",
                                                                 "dmaengine_desc_get_callback","dmaengine_desc_callback_valid","dmaengine_desc_callback_invoke"]}
    candidate_api=args.source_dir/"include/linux/dmaengine.h"
    public_api=(candidate_api if candidate_api.exists() else ROOT/"third_party/linux-rk3588/include/linux/dmaengine.h").read_bytes()
    public_helpers={name:function(public_api.decode(),name) for name in ["dma_async_is_complete","dmaengine_synchronize"]}
    if checked_api:public_helpers["dmaengine_synchronize_checked"]=function(public_api.decode(),"dmaengine_synchronize_checked")
    declarations={name:declaration(public_api.decode(),kind,name) for kind,name in [("enum","dma_transfer_direction"),("enum","dma_slave_buswidth"),("struct","dma_slave_config"),("enum","dma_status"),("struct","dma_tx_state")]}
    abi="\n\n".join(declarations.values())+"\n"
    (output/"dmaengine-types.h").write_text(abi)
    (output/"dmaengine-public-input.h").write_bytes(public_api)
    register_names={"FSM","FSC","ES","INTEN","INTCLR","_SA","SA(n)","_DA","DA(n)"}
    constants="\n".join(line for line in text.splitlines() if line.startswith("#define CC_") or line.startswith("#define DMAC_MODE_NS") or line.startswith("#define PL330_STATE_") or (line.startswith("#define ") and line.split()[1] in register_names))+"\n"
    (output/"pl330-constants.h").write_text(constants)
    bus_source=(ROOT/"third_party/linux-rk3588/drivers/amba/bus.c").read_bytes()
    shutdown=function(bus_source.decode(),"amba_shutdown")
    extracted=text[:text.index("#include")]+("#define HAVE_LIFECYCLE 1\n" if have_lifecycle else "")+("#define HAVE_CHECKED_API 1\n" if checked_api else "")+("#define HAVE_GC 1\n" if have_gc else "")+"\n\n".join([*public_helpers.values(),*api_bodies.values(),*bodies.values(),shutdown])+"\n"
    (output/"amba-input.c").write_bytes(bus_source)
    for name in ["test-pl330-c3-order2-shim.h","test-pl330-c3-order2-main.c","test-pl330-c3-order2.py","source_utils.py"]:
        (output/name).write_bytes((HERE/name).read_bytes())
    extracted=declaration(text,'struct','pl330_desc_block')+'\n'+extracted
    (output/"source-input.c").write_bytes(data);(output/"extracted.c").write_text(extracted)
    (output/"dmaengine-input.h").write_bytes(api_source)
    unit=output/"real-functions.c";unit.write_text('#include "test-pl330-c3-order2-shim.h"\n'+extracted+'\n#include "test-pl330-c3-order2-main.c"\n')
    result={"source":str(source.resolve()),"source_sha256":sha(data),"extracted_sha256":sha(extracted.encode()),
            "excerpts_sha256":{name:sha(body.encode()) for name,body in bodies.items()},
            "dmaengine_source_sha256":sha(api_source),"dmaengine_excerpts_sha256":{name:sha(body.encode()) for name,body in api_bodies.items()},
            "dmaengine_public_source_sha256":sha(public_api),"declarations_sha256":{name:sha(body.encode()) for name,body in declarations.items()},
            "public_helpers_sha256":{name:sha(body.encode()) for name,body in public_helpers.items()},
            "abi_sha256":sha(abi.encode()),"constants_sha256":sha(constants.encode()),
            "unit_sha256":sha(unit.read_bytes()),"board_tested":False,
            "amba_source_sha256":sha(bus_source),"amba_shutdown_sha256":sha(shutdown.encode()),
            "harness_sha256":{name:sha((output/name).read_bytes()) for name in
                              ["test-pl330-c3-order2-shim.h","test-pl330-c3-order2-main.c","test-pl330-c3-order2.py","source_utils.py"]},"runs":{}}
    failed=False
    def run(argv,stem):
        try:c=subprocess.run([str(a) for a in argv],capture_output=True,text=True,timeout=30)
        except subprocess.TimeoutExpired as e:
            def decoded(v):return v.decode(errors="replace") if isinstance(v,bytes) else v or ""
            c=subprocess.CompletedProcess(argv,124,decoded(e.stdout),decoded(e.stderr)+"\nTEST DEADLINE EXCEEDED\n")
        (output/(stem+".stdout")).write_text(c.stdout);(output/(stem+".stderr")).write_text(c.stderr)
        return c,{"argv":[str(a) for a in argv],"returncode":c.returncode,"stdout_sha256":sha(c.stdout.encode()),"stderr_sha256":sha(c.stderr.encode())}
    for label,compiler,flags,launcher in [
        ("host","gcc",[],[]),
        ("host-sanitized","gcc",["-O1","-g","-fsanitize=address,undefined","-fno-omit-frame-pointer","-no-pie"],[]),
        ("aarch64","aarch64-linux-gnu-gcc",["-static"],[ROOT/".deps/qemu-user/root/usr/bin/qemu-aarch64-static"]),
    ]:
        binary=output/("pl330-"+label)
        c,compile_record=run([compiler,"-std=gnu11","-O2","-pthread","-Wall","-Wextra","-Werror","-Wno-unused-parameter","-DCONFIG_NO_GKI=1",*flags,unit,"-o",binary],label+"-compile")
        record={"compile":compile_record,"compiler_version":subprocess.run([compiler,"--version"],check=True,capture_output=True,text=True).stdout.splitlines()[0]}
        if c.returncode:failed=True
        else:
            c,execution=run([*launcher,binary],label)
            try:tests=json.loads(c.stdout)
            except ValueError:tests={"unavailable":"execution produced no valid JSON report"};failed=True
            record.update({"execution":execution,"binary_sha256":sha(binary.read_bytes()),"tests":tests})
            failed|=c.returncode!=0
        result["runs"][label]=record
    result["passed"]=not failed;(output/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"result":str(output/"result.json"),"runs":{name:r.get("tests",r["compile"]) for name,r in result["runs"].items()},"passed":not failed}))
    return int(failed)


if __name__=="__main__":raise SystemExit(main())
