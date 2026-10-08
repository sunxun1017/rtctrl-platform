#!/usr/bin/env python3
"""Real PL330 debug/state/control functions, with register and clock boundaries."""
import argparse
import json
import re
import subprocess
from pathlib import Path
from source_utils import function, sha

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SOURCE="drivers/dma/pl330.c"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir",type=Path,required=True)
    parser.add_argument("--label",required=True)
    args=parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*",args.label):parser.error("label must be red-vN / green-vN")
    output=HERE/("pl330-hw-tests-"+args.label);output.mkdir(exist_ok=False)
    data=(args.source_dir/SOURCE).read_bytes();source=data.decode()
    checked="static int pl330_wait_state(" in source
    names=["is_manager","_manager_ns","_emit_KILL","_emit_GO","_until_dmac_idle","_execute_DBGINSN","_state"]
    if "static void pl330_error_locked(" in source:names.insert(0,"pl330_error_locked")
    if checked:names.append("pl330_wait_state")
    names.extend(["_stop","_trigger","_start"])
    bodies={name:function(source,name) for name in names}
    defines=[];lines=source.splitlines(True);i=0
    wanted=re.compile(r"^#define (?:DS\b|DS_ST_|_CS\b|CS\(|INTEN\b|ES\b|INTCLR\b|FSM\b|FSC\b|DBG|DMAC_MODE_NS\b|PL330_STATE_|CMD_DMA(?:KILL|GO)\b|SZ_DMA(?:KILL|GO)\b|msecs_to_loops\(|UNTIL\()")
    while i<len(lines):
        if wanted.match(lines[i]):
            definition=lines[i]
            while lines[i].rstrip().endswith("\\"):
                i+=1;definition+=lines[i]
            defines.append(definition)
        i+=1
    constants="".join(defines)
    extracted=source[:source.index("#include")]+("#define HAVE_CHECKED_HW 1\n" if checked else "")+("#define HAVE_ERROR_HELPER 1\n" if "pl330_error_locked" in names else "")+"\n\n".join(bodies.values())+"\n"
    for name in ["test-pl330-hardware.py","test-pl330-hw-shim.h","test-pl330-hw-main.c","source_utils.py"]:
        (output/name).write_bytes((HERE/name).read_bytes())
    (output/"source-input.c").write_bytes(data);(output/"constants.h").write_text(constants);(output/"extracted.c").write_text(extracted)
    unit=output/"real-functions.c";unit.write_text('#include "test-pl330-hw-shim.h"\n'+extracted+'\n#include "test-pl330-hw-main.c"\n')
    result={"source_sha256":sha(data),"extracted_sha256":sha(extracted.encode()),"constants_sha256":sha(constants.encode()),
            "excerpts_sha256":{n:sha(b.encode()) for n,b in bodies.items()},"unit_sha256":sha(unit.read_bytes()),
            "harness_sha256":{n:sha((output/n).read_bytes()) for n in ["test-pl330-hardware.py","test-pl330-hw-shim.h","test-pl330-hw-main.c","source_utils.py"]},
            "board_tested":False,"boundary":"MMIO register model and deterministic monotonic clock; emergency loop escape records old unbounded waits", "runs":{}}
    failed=False
    def run(argv,stem):
        completed=subprocess.run([str(a) for a in argv],capture_output=True,text=True,timeout=30)
        (output/(stem+".stdout")).write_text(completed.stdout);(output/(stem+".stderr")).write_text(completed.stderr)
        return completed,{"argv":[str(a) for a in argv],"returncode":completed.returncode,"stdout_sha256":sha(completed.stdout.encode()),"stderr_sha256":sha(completed.stderr.encode())}
    for label,compiler,flags,launcher in [("host","gcc",[],[]),("host-sanitized","gcc",["-O1","-g","-fsanitize=address,undefined","-fno-omit-frame-pointer","-no-pie"],[]),("aarch64","aarch64-linux-gnu-gcc",["-static"],[ROOT/".deps/qemu-user/root/usr/bin/qemu-aarch64-static"])]:
        binary=output/("hardware-"+label)
        c,compile_record=run([compiler,"-std=gnu11","-O2","-Wall","-Wextra","-Werror","-Wno-unused-parameter",*flags,unit,"-o",binary],label+"-compile")
        record={"compile":compile_record,"compiler_version":subprocess.run([compiler,"--version"],check=True,capture_output=True,text=True).stdout.splitlines()[0]}
        if c.returncode:failed=True
        else:
            c,execution=run([*launcher,binary],label);record.update({"execution":execution,"binary_sha256":sha(binary.read_bytes()),"tests":json.loads(c.stdout)})
            failed|=c.returncode!=0
        result["runs"][label]=record
    result["passed"]=not failed;(output/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"result":str(output/"result.json"),"runs":{n:r.get("tests",r["compile"]) for n,r in result["runs"].items()},"passed":not failed}))
    return int(failed)


if __name__=="__main__":raise SystemExit(main())
