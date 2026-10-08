#!/usr/bin/env python3
"""Actual kernfs active/drain and module unload helpers, single attribute leaf fixture."""
import argparse,json,re,subprocess
from pathlib import Path
from source_utils import function,sha
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];KERNEL=ROOT/'third_party/linux-rk3588'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-dir',type=Path,required=True);p.add_argument('--label',required=True);a=p.parse_args()
    if not re.fullmatch(r'(?:red|green)-v[1-9][0-9]*',a.label):p.error('fresh label')
    out=HERE/('core-lifecycle-tests-'+a.label);out.mkdir(exist_ok=False)
    specs={'fs/kernfs/dir.c':['kernfs_get_active','kernfs_put_active','kernfs_drain','__kernfs_remove','kernfs_remove_by_name_ns'],'fs/sysfs/file.c':['sysfs_remove_file_ns'],'include/linux/sysfs.h':['sysfs_remove_file'],'drivers/base/core.c':['device_remove_file'],'drivers/base/class.c':['class_remove_file_ns'],'kernel/module.c':['__module_get','try_release_module_ref','try_stop_module']}
    sources={path:(KERNEL/path).read_bytes() for path in [*specs,'fs/kernfs/kernfs-internal.h','include/linux/module.h','sound/core/Makefile']}
    source=(a.source_dir/'drivers/dma/pl330.c').read_bytes();sources['drivers/dma/pl330.c']=source
    core={path+':'+n:function(sources[path].decode(),n) for path,names in specs.items() for n in names}
    have='static void pl330_reader_remove(' in source.decode()
    if have:core.update({'provider:'+n:function(source.decode(),n) for n in ['pl330_failstop','pl330_reader_deadline','pl330_reader_remove']})
    constants=''
    for symbol,path in [('KN_DEACTIVATED_BIAS','fs/kernfs/kernfs-internal.h'),('MODULE_REF_BASE','kernel/module.c')]:
        constants+=next(line for line in sources[path].decode().splitlines() if line.startswith('#define '+symbol))+'\n'
    constants+='#define KERNFS_ACTIVATED 0x0010\n#define MODULE_STATE_GOING 2\n' # ABI enum values audited below against headers.
    header=(KERNEL/'include/linux/kernfs.h').read_bytes();sources['include/linux/kernfs.h']=header
    if 'KERNFS_ACTIVATED\t= 0x0010' not in header.decode():raise ValueError('activated enum changed')
    (out/'constants.h').write_text(constants)
    for path,data in sources.items():(out/(path.replace('/','-')+'.input')).write_bytes(data)
    excerpts='\n\n'.join(core.values());(out/'extracted.c').write_text(excerpts)
    names=['test-core-lifecycle.py','test-core-lifecycle-shim.h','test-core-lifecycle-main.c','source_utils.py']
    for n in names:(out/n).write_bytes((HERE/n).read_bytes())
    unit=out/'real-functions.c'
    unit.write_text(('#define HAVE_PROVIDER_READER_TIMER 1\n' if have else '')+'#include "test-core-lifecycle-shim.h"\n'+excerpts+'\n#include "test-core-lifecycle-main.c"\n')
    # Production ordering/ABI audit accompanies API behavior, rather than fake devres freeing.
    remove=function(source.decode(),'pl330_remove');probe=function(source.decode(),'pl330_probe')
    if have:
        if remove.index('pl330_reader_remove')>remove.index('pl330_free_chan_resources'):raise ValueError('reader protection after destruction')
        if probe.index('device_create_file')>probe.index('dma_async_device_register_checked'):raise ValueError('late publication')
    result={'source_sha256':{path:sha(data) for path,data in sources.items()},'excerpts_sha256':{n:sha(b.encode()) for n,b in core.items()},'publication_before_dma_register':have,'reader_deactivate_before_free':have,'board_tested':False,'boundary':'Actual kernfs active/get/put/remove/drain and module helpers; single leaf traversal, pthread wait/timer primitives; ordinary module unload only','files_sha256':{str(f.relative_to(out)):sha(f.read_bytes()) for f in out.rglob('*') if f.is_file()},'runs':{}};failed=False
    for label,compiler,flags,launcher in [('host','gcc',[],[]),('host-sanitized','gcc',['-O1','-g','-fsanitize=address,undefined','-no-pie'],[]),('aarch64','aarch64-linux-gnu-gcc',['-static'],[ROOT/'.deps/qemu-user/root/usr/bin/qemu-aarch64-static'])]:
        def run(argv,stem):
            c=subprocess.run([str(x) for x in argv],capture_output=True,text=True,timeout=30);(out/(stem+'.stdout')).write_text(c.stdout);(out/(stem+'.stderr')).write_text(c.stderr)
            return c,{'argv':[str(x) for x in argv],'returncode':c.returncode,'stdout_sha256':sha(c.stdout.encode()),'stderr_sha256':sha(c.stderr.encode())}
        binary=out/label;c,rec=run([compiler,'-std=gnu11','-O2','-pthread','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unused-function',*flags,unit,'-o',binary],label+'-compile');record={'compile':rec}
        if c.returncode:failed=True
        else:
            c,rec=run([*launcher,binary],label)
            try:tests=json.loads(c.stdout)
            except ValueError:tests={'unavailable':True}
            record.update({'execution':rec,'binary_sha256':sha(binary.read_bytes()),'tests':tests});failed|=c.returncode!=0
        result['runs'][label]=record
    result['passed']=not failed;(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'result':str(out/'result.json'),'passed':not failed,'runs':{n:r.get('tests',r['compile']) for n,r in result['runs'].items()}}));return int(failed)
if __name__=='__main__':raise SystemExit(main())
