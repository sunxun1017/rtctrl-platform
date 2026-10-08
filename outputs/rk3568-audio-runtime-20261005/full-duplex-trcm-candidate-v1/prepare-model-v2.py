#!/usr/bin/env python3
"""Reuses frozen finite params model, extracts CPU and native slices byte-exact."""
import argparse, hashlib, importlib.util, json, re, shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[2]
PARAMS=HERE.parent/'full-duplex-params-candidate-v1'; BASE=PARAMS/'model-v6'
CPU='sound/soc/rockchip/rockchip_i2s_tdm.c'; NATIVE='sound/core/pcm_native.c'
def sha(b):return hashlib.sha256(b).hexdigest()
spec=importlib.util.spec_from_file_location('extractor',PARAMS/'make-candidate.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
function,one=h.function,h.one
def declaration(text,name):
    start=text.index('struct '+name+' {');return text[start:text.index('\n};',start)+4]
def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--candidate',action='store_true');args=p.parse_args()
    old_b=(BASE/'input-manifest.json').read_bytes()
    if sha(old_b)!='1d724f4514139356943fa912fc736fd93c6a5b72675161ded3795766aeddf5f2':raise ValueError('Frozen params model drift')
    old=json.loads(old_b)
    if {f.relative_to(BASE).as_posix():sha(f.read_bytes()) for f in BASE.rglob('*') if f.is_file() and f.name!='input-manifest.json'}!=old['model_files_sha256']:raise ValueError('Frozen params bytes drift')
    original=(PARAMS/'source-v4'/CPU).read_text();text=original
    cpath=HERE/'source-v2'/CPU
    sb=(HERE/'source-manifest-v2.json').read_bytes();sm=json.loads(sb)
    if sha(sb)!='42d646ce5c5240e9023ca71abd8a8fb3e94e36bece80004a691cda5cee55566d':raise ValueError('Reviewed CPU drift')
    if args.candidate:text=cpath.read_text()
    out=HERE/args.model;shutil.copytree(BASE,out)
    (out/'parent-input-manifest.json').write_bytes(old_b)
    bodies=dict(old['production_bodies']);units={}
    for key,item in bodies.items():
        rel,name=key.split(':',1)
        if rel!=CPU:continue
        before=function(original,name)
        if sha(before.encode())!=item['sha256']:raise ValueError('Lexical inherited identity '+name)
        unit=item['unit'];units.setdefault(unit,(out/unit).read_text())
        after=function(text,name);units[unit]=one(units[unit],before,after)
        item=dict(item);item['sha256']=sha(after.encode());bodies[key]=item
    for unit,data in units.items():(out/unit).write_text(data)
    names=['i2s_checked_isr','i2s_checked_runtime_suspend']
    if args.candidate:names += [name for name in sm['changed_bodies'] if name.startswith('i2s_trcm_') or name=='i2s_checked_all_stop_locked']
    added=[];prototypes=[]
    for name in names:
        key=CPU+':'+name
        if key in bodies:continue
        body=function(text,name);added.append(body);prototypes.append(body[:body.index('{')].strip()+';')
        bodies[key]={'source_kind':'private','sha256':sha(body.encode()),'unit':'actual-trcm-functions.c'}
    (out/'actual-trcm-functions.c').write_text('\n\n'.join(added)+'\n')
    native=(ROOT/'.deps/kernel-source/aiot-3568pq-audio-v4'/NATIVE).read_text()
    native_names=['snd_pcm_action_single','snd_pcm_action','snd_pcm_action_lock_irq','snd_pcm_pre_start',
        'snd_pcm_do_start','snd_pcm_undo_start','snd_pcm_post_start','snd_pcm_start_lock_irq']
    nb=[]
    for name in native_names:
        body=function(native,name);nb.append(body);prototypes.append(body[:body.index('{')].strip()+';')
        bodies[NATIVE+':'+name]={'source_kind':'actual_SOURCE','sha256':sha(body.encode()),'unit':'actual-native-start.c'}
    reg_start=native.index('static const struct action_ops snd_pcm_action_start = {')
    reg=native[reg_start:native.index('\n};',reg_start)+4]
    # Preserve real definition order: registration precedes the wrapper referencing it.
    nb.insert(-1,reg)
    (out/'actual-native-start.c').write_text('\n\n'.join(nb)+'\n')
    (out/'actual-trcm-prototypes.h').write_text('\n'.join(prototypes)+'\n')
    (out/'actual-native-types.h').write_text(declaration(native,'action_ops')+'\n')
    if args.candidate:
        types=(out/'actual-cpu-types.h').read_text();types=one(types,declaration(types,'rk_i2s_tdm_dev'),declaration(text,'rk_i2s_tdm_dev'));(out/'actual-cpu-types.h').write_text(types)
    glue=(out/'model-glue.h').read_text()
    glue=one(glue,'void (*hw_params_fault)(struct snd_soc_dai *, int);','void (*hw_params_fault)(struct snd_soc_dai *, int);\n    void (*pcm_async_fault)(struct snd_soc_dai *, int); /* finite new optional ops shape, product header owned by root */')
    glue=one(glue,'struct snd_pcm_runtime { struct { unsigned int info, rates, channels_min, channels_max, rate_min, rate_max; uint64_t formats; } hw; };', '''struct snd_pcm_runtime {
    struct { unsigned int info, rates, channels_min, channels_max, rate_min, rate_max; uint64_t formats; } hw;
    struct snd_pcm_mmap_status *status; struct snd_pcm_substream *trigger_master;
    bool trigger_tstamp_latched; unsigned long hw_ptr_jiffies, hw_ptr_buffer_jiffies;
    unsigned long buffer_size, rate, silence_size;
};''');(out/'model-glue.h').write_text(glue)
    shim=(out/'test-params-shim.h').read_text()
    shim=one(shim,'bool pm_held; bool component_opened; };','bool pm_held; bool component_opened; const struct snd_pcm_ops *ops; };')
    shim=one(shim,'struct snd_pcm_runtime;','struct snd_pcm_ops { int (*trigger)(struct snd_pcm_substream *, int); };\nstruct snd_pcm_runtime;')
    # The forward struct tag must precede the finite ops shape.
    shim=one(shim,'struct snd_pcm_ops {','struct snd_pcm_substream;\nstruct snd_pcm_ops {');(out/'test-params-shim.h').write_text(shim)
    (out/'trcm-api.h').write_bytes((HERE/'trcm-api.h').read_bytes())
    unit=(out/'unit.c').read_text();unit=one(unit,'#define CANDIDATE 1','#define CANDIDATE 1\n#define TRCM_CANDIDATE '+str(int(args.candidate)))
    unit=one(unit,'#include "params-api.h"','#include "params-api.h"\n#include "actual-native-types.h"\n#include "trcm-api.h"\n#include "actual-trcm-prototypes.h"')
    unit=one(unit,'#include "test-caller-chain.c"','#include "actual-trcm-functions.c"\n#include "actual-native-start.c"\n#include "test-caller-chain.c"')
    unit=one(unit,'#include "test-shared-params.c"','#define main inherited_params_main_not_executed\n#include "test-shared-params.c"\n#undef main\n#include "test-trcm.c"')
    (out/'unit.c').write_text(unit)
    caller=(out/'test-caller-chain.c').read_text()
    caller=one(caller,'    if (function == (void *)i2s_checked_trigger) {','    if (function == (void *)i2s_checked_trigger'+(' || function == (void *)i2s_trcm_trigger' if args.candidate else '')+') {')
    caller=one(caller,'    (void)caller;\n\n    if (function == (void *)i2s_shared_begin)', '    (void)caller;\n    trcm_native_cut(function);\n\n    if (function == (void *)i2s_shared_begin)')
    caller=one(caller,'        dma_running[ss->stream] = true;','        dma_running[ss->stream] = true;\n        trcm_GO_cut(ss);')
    if args.candidate:caller=one(caller,'\t.hw_params_fault = i2s_shared_fault,\n};','\t.hw_params_fault = i2s_shared_fault,\n\t.pcm_async_fault = i2s_trcm_async_fault,\n};')
    (out/'test-caller-chain.c').write_text(caller)
    (out/'test-trcm.c').write_bytes((HERE/'test-trcm.c').read_bytes())
    (out/'prepare-snapshot.py').write_bytes(Path(__file__).read_bytes())
    source_paths={rel:str((PARAMS/'source-v4'/rel).relative_to(ROOT)) for rel in old['source_locks']}
    if args.candidate:source_paths[CPU]=str(cpath.relative_to(ROOT))
    result={**old,'scope':'PRIVATE_CPU_TRCM_C3_AND_NATIVE_START_SLICE_NOT_KERNEL_OR_BOARD',
        'candidate':args.candidate,'production_bodies':bodies,'source_paths':source_paths,
        'source_locks':{rel:sha((ROOT/path).read_bytes()) for rel,path in source_paths.items()},
        'CPU_manifest_sha256':sha(sb),'parent_source_manifest_sha256':old['source_manifest_sha256'],
        'native_whole_outer_executed':False,'native_slice_body_count':len(native_names),
        'native_profile':'unlinked atomic, stream lock/group/XRUN/timestamp APIs modelled, actual action/do/post bodies executed',
        'native_registration_sha256':sha(reg.encode()),'PL330_async_fanout_integrated':False}
    result['model_files_sha256']={f.relative_to(out).as_posix():sha(f.read_bytes()) for f in out.rglob('*') if f.is_file() and f.name!='input-manifest.json'}
    (out/'input-manifest.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'manifest_sha256':sha((out/'input-manifest.json').read_bytes()),'available_bodies':len(bodies),'compiler_executed':False}))
if __name__=='__main__':main()
