#!/usr/bin/env python3
"""Real debugfs publication function: checked profile must publish no old reader."""
import argparse,json,re,subprocess
from pathlib import Path
from source_utils import function,sha
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--source-dir",type=Path,required=True);p.add_argument("--label",required=True);a=p.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*",a.label):p.error("fresh label")
    out=HERE/("pl330-debugfs-tests-"+a.label);out.mkdir(exist_ok=False)
    source=(a.source_dir/"drivers/dma/pl330.c").read_bytes();body=function(source.decode(),"init_pl330_debugfs")
    probe=function(source.decode(),"pl330_probe")
    if probe.index("dma_async_device_register_checked(")>probe.index("init_pl330_debugfs("):raise ValueError("checked callback must be registered before debugfs admission")
    unit=out/"real-functions.c"
    shim='''/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <stdio.h>
#include <sys/stat.h>
struct device { int value; };
struct dma_device { struct device *dev; int (*device_synchronize_checked)(void *); };
struct pl330_dmac { struct dma_device ddma; };
static int published;
static const int pl330_debugfs_fops;
static const char *dev_name(struct device *dev) { (void)dev; return "dma"; }
static void *debugfs_create_file(const char *name,int mode,void *parent,void *owner,const void *fops)
{ (void)name;(void)mode;(void)parent;(void)owner;(void)fops;published++;return 0; }
static int checked(void *arg) { (void)arg;return 0; }
'''
    main='''
int main(void) {
 struct device dev={0};struct pl330_dmac d={.ddma={.dev=&dev,.device_synchronize_checked=checked}};
 int passed=0;init_pl330_debugfs(&d);if(published==0)passed++;
 published=0;d.ddma.device_synchronize_checked=0;init_pl330_debugfs(&d);if(published==1)passed++;
 printf("{\\"total\\":2,\\"passed\\":%d,\\"failed\\":%d}\\n",passed,2-passed);return passed==2?0:1;
}
'''
    unit.write_text(shim+body+main);(out/"source-input.c").write_bytes(source);(out/"extracted.c").write_text(body);(out/"probe-excerpt.c").write_text(probe);(out/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    result={"source_sha256":sha(source),"extracted_sha256":sha(body.encode()),"unit_sha256":sha(unit.read_bytes()),"probe_sha256":sha(probe.encode()),"runs":{}};failed=False
    def run(argv,stem):
        c=subprocess.run([str(x) for x in argv],capture_output=True,text=True,timeout=30);(out/(stem+".stdout")).write_text(c.stdout);(out/(stem+".stderr")).write_text(c.stderr)
        return c,{"returncode":c.returncode,"stdout_sha256":sha(c.stdout.encode()),"stderr_sha256":sha(c.stderr.encode()),"argv":[str(x) for x in argv]}
    for label,compiler,flags,launcher in [("host","gcc",[],[]),("host-sanitized","gcc",["-O1","-g","-fsanitize=address,undefined","-no-pie"],[]),("aarch64","aarch64-linux-gnu-gcc",["-static"],[ROOT/".deps/qemu-user/root/usr/bin/qemu-aarch64-static"])]:
        binary=out/("debugfs-"+label);c,rec=run([compiler,"-std=gnu11","-O2","-Wall","-Wextra","-Werror",*flags,unit,"-o",binary],label+"-compile");record={"compile":rec}
        if c.returncode:failed=True
        else:
            c,rec=run([*launcher,binary],label);record.update({"execution":rec,"binary_sha256":sha(binary.read_bytes()),"tests":json.loads(c.stdout)});failed|=c.returncode!=0
        result["runs"][label]=record
    result["passed"]=not failed;(out/"result.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps({"result":str(out/"result.json"),"passed":not failed,"runs":{n:r.get("tests",r["compile"]) for n,r in result["runs"].items()}}));return int(failed)
if __name__=="__main__":raise SystemExit(main())
