#!/usr/bin/env python3
"""Extract the real PL330 + PCM/core/allocator/native chain in one translation unit."""
import argparse,json,re,subprocess
from pathlib import Path
from source_utils import function,declaration,sha
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];KERNEL=ROOT/'third_party/linux-rk3588'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-dir',type=Path,required=True);p.add_argument('--label',required=True);a=p.parse_args()
    if not re.fullmatch(r'(?:red|green)-v[1-9][0-9]*',a.label):p.error('fresh red/green-vN')
    out=HERE/('dma-pcm-open-tests-'+a.label);out.mkdir(exist_ok=False)
    paths=['drivers/dma/pl330.c','include/linux/dmaengine.h','sound/core/pcm_memory.c','sound/core/pcm_dmaengine.c','sound/soc/soc-generic-dmaengine-pcm.c','include/sound/pcm.h','include/sound/dmaengine_pcm.h','sound/core/pcm_native.c']
    sources={path:(a.source_dir/path).read_bytes() for path in paths}
    sources.update({path:(KERNEL/path).read_bytes() for path in ['drivers/dma/dmaengine.h','include/sound/memalloc.h','sound/core/memalloc.c','drivers/amba/bus.c','sound/soc/soc-link.c','include/sound/soc.h','include/sound/soc-component.h']})
    for path in ['sound/soc/soc-pcm.c','sound/soc/soc-component.c','sound/soc/soc-dai.c','drivers/dma/dmaengine.c']:sources[path]=(a.source_dir/path).read_bytes()
    for path,data in sources.items():(out/(path.replace('/','-')+'.input')).write_bytes(data)
    public=sources['include/linux/dmaengine.h'].decode();pl=sources['drivers/dma/pl330.c'].decode();memory=sources['sound/core/pcm_memory.c'].decode();engine=sources['sound/core/pcm_dmaengine.c'].decode()
    abi='\n'.join(declaration(public,kind,name) for kind,name in [('enum','dma_transfer_direction'),('enum','dma_slave_buswidth'),('struct','dma_slave_config'),('enum','dma_status'),('struct','dma_tx_state')])+'\n';(out/'dmaengine-types.h').write_text(abi)
    (out/'dma-flags.h').write_text(declaration(public,'enum','dma_ctrl_flags')+'\n')
    (out/'dmaengine-pcm-flags.h').write_text('\n'.join(line for line in sources['include/sound/dmaengine_pcm.h'].decode().splitlines() if line.startswith('#define SND_DMAENGINE_PCM_FLAG_'))+'\n')
    lines=sources['include/sound/soc.h'].decode().splitlines(True);macros=''
    for n in ['for_each_rtd_dais','for_each_rtd_components']:
        start=next(i for i,line in enumerate(lines) if line.startswith('#define '+n+'('));i=start
        while lines[i].rstrip().endswith('\\'):i+=1
        macros+=''.join(lines[start:i+1])
    (out/'asoc-iteration-macros.h').write_text(macros)
    allocator=sources['sound/core/memalloc.c'].decode();memalloc=sources['include/sound/memalloc.h'].decode()
    (out/'dma-buffer-types.h').write_text('\n'.join(declaration(memalloc,'struct',n) for n in ['snd_dma_device','snd_dma_buffer'])+'\n')
    memconstants='#define SNDRV_DMA_TYPE_UNKNOWN'+memalloc.split('#define SNDRV_DMA_TYPE_UNKNOWN',1)[1].split('/*\n * info for buffer allocation',1)[0];(out/'memalloc-constants.h').write_text(memconstants)
    (out/'pcm-trigger-constants.h').write_text('\n'.join(line for line in sources['include/sound/pcm.h'].decode().splitlines() if line.startswith('#define SNDRV_PCM_TRIGGER'))+'\n')
    # Names preserve the already tested dependency order, but bodies come from this source.
    names=list(json.loads((HERE/'pl330-start-tests-green-v1/result.json').read_text())['excerpts_sha256'])
    hardware=['pl330_error_locked','is_manager','_manager_ns','_emit_KILL','_emit_GO','_until_dmac_idle','_execute_DBGINSN','_state','pl330_wait_state','_stop','_trigger','_start']
    have_state='static ssize_t rk3568_lifecycle_state_show(' in pl
    if have_state:names.insert(names.index('pl330_sync_channel'),'pl330_capture_stop_locked');names.append('rk3568_lifecycle_state_show')
    if 'static void pl330_reader_remove(' in pl:
        names[names.index('pl330_remove'):names.index('pl330_remove')]=['pl330_reader_deadline','pl330_reader_remove','pl330_irqs_remove']
    names=hardware+[n for n in names if n not in hardware]
    if 'static int pl330_check_open(' in pl:names.append('pl330_check_open')
    bodies={'provider:'+n:function(pl,n) for n in names}
    privnames=['dma_cookie_init','dma_cookie_assign','dma_cookie_complete','dma_cookie_status','dma_set_residue','dmaengine_desc_get_callback','dmaengine_desc_callback_valid','dmaengine_desc_callback_invoke']
    api_names=['dma_async_is_complete','dma_submit_error','dmaengine_submit','dmaengine_prep_dma_cyclic','dma_async_issue_pending','dmaengine_resume','dmaengine_pause','dmaengine_terminate_async','dmaengine_synchronize','dmaengine_synchronize_checked','dmaengine_tx_status']
    if 'static inline int dmaengine_check_open(' in public:api_names.append('dmaengine_check_open')
    api={**{'api:'+n:function(public,n) for n in api_names},**{'private:'+n:function(sources['drivers/dma/dmaengine.h'].decode(),n) for n in privnames}}
    module=(KERNEL/'kernel/module.c').read_bytes();sources['kernel/module.c']=module;(out/'module-input.c').write_bytes(module)
    api['module:__module_get']=function(module.decode(),'__module_get')
    api.update({'core:'+n:function(sources['drivers/dma/dmaengine.c'].decode(),n) for n in ['dma_chan_put','dma_release_channel']})
    api['component:get_drvdata']=function(sources['include/sound/soc-component.h'].decode(),'snd_soc_component_get_drvdata')
    constants=[];lines=pl.splitlines(True);i=0
    wanted=re.compile(r'^#define (?:DS\b|DS_ST_|_CS\b|CS\(|INTEN\b|ES\b|INTCLR\b|FSM\b|FSC\b|DBG|DMAC_MODE_NS\b|PL330_STATE_|CMD_DMA(?:KILL|GO)\b|SZ_DMA(?:KILL|GO)\b|msecs_to_loops\(|UNTIL\(|CC_|_SA\b|SA\(|_DA\b|DA\()')
    while i<len(lines):
        if wanted.match(lines[i]):
            definition=lines[i]
            while lines[i].rstrip().endswith('\\'):i+=1;definition+=lines[i]
            constants.append(definition)
        i+=1
    (out/'pl330-constants.h').write_text(''.join(constants))
    core={}
    core['direction']=function(sources['include/sound/dmaengine_pcm.h'].decode(),'snd_pcm_substream_to_dma_direction');core['setbuf']=function(sources['include/sound/pcm.h'].decode(),'snd_pcm_set_runtime_buffer')
    core.update({'allocator:'+n:function(allocator,n) for n in ['snd_malloc_dev_pages','snd_free_dev_pages','snd_malloc_dev_iram','snd_free_dev_iram','snd_dma_alloc_pages','snd_dma_free_pages']})
    core.update({'memory:'+n:function(memory,n) for n in ['snd_pcm_dma_quarantine_alloc','snd_pcm_dma_quarantine_free','snd_pcm_dma_quarantine_bytes','snd_pcm_dma_quarantine_check','snd_pcm_dma_quarantine','do_free_pages','do_alloc_pages','snd_pcm_lib_preallocate_dma_free','snd_pcm_lib_preallocate_free','snd_pcm_lib_free_pages','snd_pcm_lib_malloc_pages']})
    core.update({'engine:'+n:function(engine,n) for n in ['substream_to_prtd','dmaengine_pcm_failstop','dmaengine_pcm_error','dmaengine_pcm_operation_begin','dmaengine_pcm_operation_end','snd_dmaengine_pcm_quiesce','dmaengine_pcm_dma_complete','dmaengine_pcm_prepare_and_submit','snd_dmaengine_pcm_trigger','snd_dmaengine_pcm_open','snd_dmaengine_pcm_close','snd_dmaengine_pcm_close_release_chan']})
    core['generic:quiesce']=function(sources['sound/soc/soc-generic-dmaengine-pcm.c'].decode(),'dmaengine_pcm_quiesce')
    core.update({'generic:'+n:function(sources['sound/soc/soc-generic-dmaengine-pcm.c'].decode(),n) for n in ['dmaengine_pcm_open','dmaengine_pcm_trigger','dmaengine_pcm_release_chan','snd_dmaengine_pcm_unregister']})
    for path,names in [('sound/soc/soc-component.c',['_soc_component_ret','snd_soc_pcm_component_trigger']),('sound/soc/soc-dai.c',['_soc_dai_ret','snd_soc_pcm_dai_trigger']),('sound/soc/soc-link.c',['_soc_link_ret','snd_soc_link_trigger']),('sound/soc/soc-pcm.c',['soc_pcm_trigger'])]:core.update({path+':'+n:function(sources[path].decode(),n) for n in names})
    cpu_path=ROOT/'outputs/rk3568-i2s-lifecycle-20261005/driver-source-v10/sound/soc/rockchip/rockchip_i2s_tdm.c';cpu=cpu_path.read_bytes()
    if sha(cpu)!='cbd19c1a8b128d442f6321ebb9ce1d51524633536282862b6c06fa76b4f77b59':raise ValueError('accepted CPU v10 changed')
    sources['cpu-v10/rockchip_i2s_tdm.c']=cpu;(out/'cpu-input.c').write_bytes(cpu);core['cpu:component_trigger']=function(cpu.decode(),'i2s_checked_component_trigger')
    if have_state:
        pcm=(a.source_dir/'sound/core/pcm.c').read_bytes();sources['sound/core/pcm.c']=pcm;(out/'pcm-input.c').write_bytes(pcm)
        core['pcm:show']=function(pcm.decode(),'dma_quarantine_bytes_show')
    native={n:function(sources['sound/core/pcm_native.c'].decode(),n) for n in ['snd_pcm_sync_stop','snd_pcm_hw_params','do_hw_free','snd_pcm_release_substream','snd_pcm_pre_start','snd_pcm_do_start']}
    memory_extra=declaration(memory,'struct','snd_pcm_dma_quarantine')+'\nstatic LIST_HEAD(pcm_dma_quarantine);\nstatic DEFINE_MUTEX(pcm_dma_quarantine_lock);\nstatic atomic_long_t pcm_dma_quarantine_bytes = ATOMIC_LONG_INIT(0);\n'
    declarations=memory_extra+declaration(engine,'struct','dmaengine_pcm_runtime_data')+'\n'
    extracted=declaration(pl,'struct','pl330_desc_block')+'\n'+'\n\n'.join([*api.values(),*bodies.values(),declarations,*core.values()]);native_extract='\n\n'.join(native.values())
    (out/'extracted.c').write_text(extracted);(out/'native-extracted.c').write_text(native_extract)
    names=['test-dma-pcm-open.py','test-dma-pcm-open-provider-shim.h','test-dma-pcm-open-runtime-shim.h','test-dma-pcm-open-mmio.h','test-dma-pcm-open-main.c','test-pcm-chain-runtime.h','test-pcm-chain-allocator.h','test-pcm-chain-native.h','test-pcm-chain-asoc.h','source_utils.py']
    for name in names:(out/name).write_bytes((HERE/name).read_bytes())
    unit=out/'real-functions.c';unit.write_text(('#define HAVE_READONLY_OPEN 1\n' if 'static int pl330_check_open(' in pl else '')+'#define HAVE_PCM_QUIESCE 1\n#define HAVE_ASOC_CHAIN 1\n'+('#define HAVE_READONLY_STATE 1\n' if have_state else '')+'#include "test-dma-pcm-open-provider-shim.h"\n#include "test-dma-pcm-open-runtime-shim.h"\n#include "test-dma-pcm-open-mmio.h"\n#include "test-pcm-chain-asoc.h"\n'+extracted+'\n#include "test-pcm-chain-native.h"\n'+native_extract+'\n#include "test-dma-pcm-open-main.c"\n')
    files={str(f.relative_to(out)):sha(f.read_bytes()) for f in out.rglob('*') if f.is_file()}
    result={'source_sha256':{path:sha(data) for path,data in sources.items()},'excerpts_sha256':{n:sha(b.encode()) for n,b in {**api,**bodies,**core,**{'native:'+n:b for n,b in native.items()}}.items()},'files_sha256':files,'board_tested':False,'boundary':'Shared real DMA APIs/provider/PCM/core allocator; fake kernel scheduling, PM, codegen leaf and MMIO register model, no AXI drain proof','runs':{}};failed=False
    for label,compiler,flags,launcher in [('host','gcc',[],[]),('host-sanitized','gcc',['-O1','-g','-fsanitize=address,undefined','-no-pie'],[]),('aarch64','aarch64-linux-gnu-gcc',['-static'],[ROOT/'.deps/qemu-user/root/usr/bin/qemu-aarch64-static'])]:
        def run(argv,stem):
            c=subprocess.run([str(x) for x in argv],capture_output=True,text=True,timeout=30);(out/(stem+'.stdout')).write_text(c.stdout);(out/(stem+'.stderr')).write_text(c.stderr)
            return c,{'argv':[str(x) for x in argv],'returncode':c.returncode,'stdout_sha256':sha(c.stdout.encode()),'stderr_sha256':sha(c.stderr.encode())}
        binary=out/label;c,rec=run([compiler,'-std=gnu11','-O2','-pthread','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unused-function','-Wno-unused-variable','-DCONFIG_NO_GKI=1',*flags,unit,'-o',binary],label+'-compile');record={'compile':rec}
        if c.returncode:failed=True
        else:
            c,rec=run([*launcher,binary],label)
            try:tests=json.loads(c.stdout)
            except ValueError:tests={'unavailable':True}
            record.update({'execution':rec,'binary_sha256':sha(binary.read_bytes()),'tests':tests});failed|=c.returncode!=0
        result['runs'][label]=record
    result['passed']=not failed;(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'result':str(out/'result.json'),'passed':not failed,'runs':{n:r.get('tests',r['compile']) for n,r in result['runs'].items()}}));return int(failed)
if __name__=='__main__':raise SystemExit(main())
