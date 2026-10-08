#!/usr/bin/env python3
"""Reuse the accepted finite caller model with byte-extracted private bodies."""
import argparse, hashlib, importlib.util, json, re, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
BASE = HERE.parent/'full-duplex-params-baseline-v1/model-v2'
spec = importlib.util.spec_from_file_location('private_source_helpers', HERE/'make-candidate.py')
helpers = importlib.util.module_from_spec(spec); spec.loader.exec_module(helpers)
function, one, sha = helpers.function, helpers.one, helpers.sha
LABELS = {'cpu': 'sound/soc/rockchip/rockchip_i2s_tdm.c', 'codec': 'sound/soc/codecs/rk817_codec.c',
 'simple': 'sound/soc/generic/simple-card-utils.c', 'pcm': 'sound/soc/soc-pcm.c',
 'dai': 'sound/soc/soc-dai.c', 'component': 'sound/soc/soc-component.c',
 'link': 'sound/soc/soc-link.c', 'compress': 'sound/soc/soc-compress.c',
 'soc-header': 'include/sound/soc.h', 'component-header': 'include/sound/soc-component.h'}
def declaration(text, kind, name):
    m = re.search(r'^'+kind+r'\s+'+name+r'\s*\{', text, re.M)
    if not m: raise ValueError('Missing type '+name)
    return text[m.start():text.index('\n};', m.end())+4]
def registration(text, name):
    m = re.search(r'^static const struct snd_soc_dai_ops '+name+r' = \{', text, re.M)
    return text[m.start():text.index('\n};', m.end())+4]
def main():
    old_bytes = (BASE/'input-manifest.json').read_bytes()
    if sha(old_bytes) != '3c17ce462a8e5b64bf0214e7348f2a5189a32c7de12ae815ecd1a120d9a2b362': raise ValueError('Old model manifest drift')
    old = json.loads(old_bytes)
    actual = {p.relative_to(BASE).as_posix(): sha(p.read_bytes()) for p in BASE.rglob('*') if p.is_file() and p.name != 'input-manifest.json'}
    if actual != old['model_files_sha256']: raise ValueError('Old exact model inputs drift')
    source_manifest_bytes = (HERE/'source-manifest-v4.json').read_bytes()
    if sha(source_manifest_bytes) != '889c0e25655b29bbda10061b6f0ac569741b892a20cd0316695498442be8037c': raise ValueError('Private source revision drift')
    sm = json.loads(source_manifest_bytes)
    sources = {}
    for rel, item in sm['files'].items():
        p = HERE/'source-v4'/rel
        if p.is_symlink() or sha(p.read_bytes()) != item['candidate_sha256']: raise ValueError('Private source drift')
        sources[rel] = p.read_text()
    parser=argparse.ArgumentParser(); parser.add_argument('--model',required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'model-v[2-9][0-9]*',args.model): raise ValueError('Fresh versioned model, preserve failed v1')
    out = HERE/args.model
    shutil.copytree(BASE, out)
    (out/'baseline-input-manifest.json').write_bytes(old_bytes)
    unit = (out/'unit.c').read_text()
    extra = (out/'actual-params-functions.c').read_text()
    body_map = {}
    # Replace only bodies which are actually available in the inherited compilation units.
    for key, digest in old['inherited_production_functions_sha256'].items():
        label, name = key.split(':', 1); rel = LABELS[label]
        if rel in sources:
            before = function((HERE/'inputs-v1'/rel).read_text(), name)
            # Older lexical convention may omit a newline in return-type prefix.
            if sha(before.encode()) != digest:
                matches = [x for x in re.finditer(r'^[A-Za-z_][A-Za-z_0-9 \t*]*\b'+name+r'\([^;{}]*?\)\s*\{', (HERE/'inputs-v1'/rel).read_text(), re.M)]
                if not matches: raise ValueError('Inherited lexical prefix '+key)
                t=(HERE/'inputs-v1'/rel).read_text(); m=matches[0]; end=t.index('{',m.start()); depth=0
                for i in range(end,len(t)):
                    depth+=(t[i]=='{')-(t[i]=='}')
                    if not depth: before=t[m.start():i+1]; break
            after = function(sources[rel], name)
            # Same lexical old prefix when only return prefix is split.
            if before != after and after.endswith(before) and sha(before.encode()) == digest:
                after = before
            unit = one(unit, before, after)
            body_map[rel+':'+name] = {'sha256': sha(after.encode()), 'unit': 'unit.c', 'source_kind': 'private'}
        else:
            body_map[rel+':'+name] = {'sha256': digest, 'unit': 'unit.c', 'source_kind': 'actual_SOURCE'}
    added_order = []
    for key, digest in old['added_production_functions_sha256'].items():
        leaf, name = key.split(':', 1)
        rel = next((r for r in sources if Path(r).name == leaf), None)
        before = function((BASE/'production-source-inputs'/leaf).read_text(), name)
        if sha(before.encode()) != digest: raise ValueError('Extra old body drift '+name)
        after = function(sources[rel],name) if rel else before
        extra = one(extra, before, after)
        origin = rel or next((r for r in LABELS.values() if Path(r).name == leaf), None)
        origin = origin or {'soc-dai.h':'include/sound/soc-dai.h', 'soc-generic-dmaengine-pcm.c':'sound/soc/soc-generic-dmaengine-pcm.c'}[leaf]
        body_map[origin+':'+name] = {'sha256': sha(after.encode()), 'unit': 'actual-params-functions.c', 'source_kind': 'private' if origin in sources else 'actual_SOURCE'}
        added_order.append(origin+':'+name)
    (out/'actual-params-functions.c').write_text(extra)
    new_bodies = []
    declarations = []
    for key, item in sm['changed_functions'].items():
        if key in body_map: continue
        rel,name=key.split(':',1)
        if name in ['rk817_platform_probe','rockchip_i2s_tdm_probe','rk817_codec_parse_dt_property']: continue
        body = function(sources[rel],name)
        target = 'actual-shared-header.h' if rel.endswith('.h') else 'actual-shared-functions.c'
        body_map[key] = {'sha256':sha(body.encode()),'unit':target,'source_kind':'private'}
        if target.endswith('.c'):
            new_bodies.append(body)
            declarations.append(body[:body.index('{')].strip()+';')
    # Actual dependencies of the new callbacks/runtime init; no success stubs.
    for label,name in [('simple','asoc_simple_init_dai'), ('codec','rk817_set_dai_fmt')]:
        body=function(sources[LABELS[label]], name)
        new_bodies.append(body); declarations.append(body[:body.index('{')].strip()+';')
        body_map[LABELS[label]+':'+name]={'sha256':sha(body.encode()),'unit':'actual-shared-functions.c','source_kind':'private'}
    header_bodies = [function(sources['include/sound/soc-dai.h'], k.split(':')[1]) for k,v in body_map.items() if v['unit']=='actual-shared-header.h']
    (out/'actual-shared-state.h').write_text(declaration(sources['include/sound/soc-dai.h'], 'struct', 'snd_soc_dai_params_state')+'\n')
    (out/'actual-shared-header.h').write_text('\n\n'.join(header_bodies)+'\n')
    (out/'actual-shared-functions.c').write_text('\n\n'.join(new_bodies)+'\n')
    (out/'actual-shared-prototypes.h').write_text('\n'.join(declarations)+'\n')
    cpu_types=(out/'actual-cpu-types.h').read_text()
    cpu_types=one(cpu_types,declaration(cpu_types,'struct','rk_i2s_tdm_dev'),declaration(sources[LABELS['cpu']],'struct','rk_i2s_tdm_dev'))
    (out/'actual-cpu-types.h').write_text(cpu_types)
    glue=(out/'model-glue.h').read_text()
    glue=one(glue,'void (*hw_free)(struct snd_pcm_substream *, struct snd_soc_dai *);','int (*hw_free)(struct snd_pcm_substream *, struct snd_soc_dai *);')
    glue=one(glue,'void (*hw_free)(struct snd_pcm_substream *);','int (*hw_free)(struct snd_pcm_substream *);')
    glue=one(glue,'    bool no_capture_mute;', '''    bool no_capture_mute;
    int (*prepare)(struct snd_pcm_substream *, struct snd_soc_dai *);
    int (*set_fmt)(struct snd_soc_dai *, unsigned int);
    int (*set_tdm_slot)(struct snd_soc_dai *, unsigned int, unsigned int, int, int);
    int (*hw_params_begin)(struct snd_pcm_substream *, struct snd_pcm_hw_params *, struct snd_soc_dai *, u64 *);
    int (*hw_params_commit)(struct snd_pcm_substream *, struct snd_soc_dai *, u64);
    void (*hw_params_abort)(struct snd_pcm_substream *, struct snd_soc_dai *, u64, int, bool);
    int (*hw_params_reuse)(struct snd_pcm_substream *, struct snd_soc_dai *);
    int (*hw_params_free_check)(struct snd_pcm_substream *, struct snd_soc_dai *);
    void (*hw_params_fault)(struct snd_soc_dai *, int);''')
    glue=one(glue,'int pcm_subclass;','int pcm_subclass, num_links, num_rtd;')
    glue=one(glue,'struct rk817_codec_priv { unsigned int stereo_sysclk, chip_ver; bool pdmdata_out_enable; };', '''/* Finite field shape only, not kernel layout/ABI evidence. */
struct rk817_codec_priv { unsigned int stereo_sysclk, chip_ver, shared_dai_fmt;
    bool pdmdata_out_enable, adc_for_loopback, shared_params_enabled;
    int params_error; pthread_mutex_t params_lock;
    struct snd_soc_dai_params_state shared_params;
    struct snd_pcm_substream *shared_open[2]; };''')
    glue=one(glue,'static void model_mutex_unlock(pthread_mutex_t *lock);', '#define mutex_lock(lock) pthread_mutex_lock(lock)\nstatic void model_mutex_unlock(pthread_mutex_t *lock);')
    (out/'model-glue.h').write_text(glue)
    unit=one(unit,'#include "actual-cpu-types.h"','#include "actual-shared-state.h"\n#include "actual-cpu-types.h"')
    unit=one(unit,'#include "params-api.h"','#include "params-api.h"\n#include "actual-shared-header.h"\n#include "actual-shared-prototypes.h"')
    unit=one(unit,'#include "actual-params-functions.c"','#include "actual-params-functions.c"\n#include "actual-shared-functions.c"')
    unit=one(unit,'#include "test-params-caller.c"','#include "test-shared-params.c"')
    (out/'unit.c').write_text(unit)
    # Model API state remains an explicit boundary, including error return injection.
    events=(out/'params-events.h').read_text()
    events=one(events,'#include <string.h>','#include <string.h>\n#include <pthread.h>\nstatic pthread_mutex_t params_event_lock = PTHREAD_MUTEX_INITIALIZER;')
    events=one(events,'static unsigned int codec_registers[2048]', '''static bool params_inject_commit_error, params_inject_codec_release;
static bool params_inject_commit_busy;
static int params_commit_window_result;
static unsigned int params_codec_fail_at;
static int params_mute_error, params_component_free_error, params_link_free_error;
static unsigned int codec_registers[2048]''')
    events=one(events,'    if (params_event_count == 1024)', '    pthread_mutex_lock(&params_event_lock);\n    if (params_event_count == 1024)')
    events=one(events,'    params_events[params_event_count++] = (struct params_event){name, value, result};','    params_events[params_event_count++] = (struct params_event){name, value, result};\n    pthread_mutex_unlock(&params_event_lock);')
    events=one(events,'    params_inject_cpu_clock = params_inject_slave_config = params_inject_start_error = false;', '''    params_inject_cpu_clock = params_inject_slave_config = params_inject_start_error = false;
    params_inject_commit_error = params_inject_codec_release = false;
    params_inject_commit_busy = false; params_commit_window_result = 999;
    params_codec_fail_at = 0; params_mute_error = params_component_free_error = params_link_free_error = 0;''')
    events=one(events,'    for (unsigned int i = 0; i < params_event_count; i++)\n        printf("PARAM_EVENT',
        '    printf("PARAM_CASE %s %u\\n", case_name, params_event_count);\n    for (unsigned int i = 0; i < params_event_count; i++)\n        printf("PARAM_EVENT')
    (out/'params-events.h').write_text(events)
    api=(out/'params-api.h').read_text()
    api=one(api,'    params_note("CODEC_WRITE", reg, 0);\n    return 0;', '''    int ret = params_codec_fail_at == codec_io_calls ? -EREMOTEIO : 0;
    params_note("CODEC_WRITE", reg, ret);
    return ret;''')
    api=one(api,'return mute == 1 ? 0 : -ENOTSUPP;', 'return mute == 1 ? params_mute_error : -ENOTSUPP;')
    api += '''\n/* Optional callback API error fixtures; not PL330 or machine production bodies. */
static int params_component_free_api(struct snd_soc_component *c, struct snd_pcm_substream *ss)
{ params_note("COMPONENT_FREE_API", c->model_id, params_component_free_error); (void)ss; return params_component_free_error; }
static int params_link_free_api(struct snd_pcm_substream *ss)
{ params_note("LINK_FREE_API", ss->stream, params_link_free_error); return params_link_free_error; }
static int params_codec_release_api(struct snd_pcm_substream *ss, struct snd_soc_dai *dai)
{ if (params_inject_codec_release) return -ENXIO; return rk817_shared_free(ss, dai); }
'''
    # The only extra real declaration needed by the API passthrough above.
    api=one(api,'#include "rk817_codec.h"','#include "rk817_codec.h"\n#define RK817_HIFI 0\n#define RK817_VOICE 1\nstatic int rk817_shared_free(struct snd_pcm_substream *, struct snd_soc_dai *);')
    api += '\nstatic int snd_soc_dai_set_tdm_slot(struct snd_soc_dai *dai, unsigned int tx_mask, unsigned int rx_mask, int slots, int slot_width)\n{ return dai->driver->ops->set_tdm_slot ? dai->driver->ops->set_tdm_slot(dai, tx_mask, rx_mask, slots, slot_width) : -ENOTSUPP; }\n'
    (out/'params-api.h').write_text(api)
    caller=(out/'test-caller-chain.c').read_text()
    cpu_ops=registration(sources[LABELS['cpu']], 'rockchip_i2s_tdm_shared_ops').replace('rockchip_i2s_tdm_shared_ops','checked_cpu_ops')
    codec_ops=registration(sources[LABELS['codec']], 'rk817_shared_dai_ops').replace('rk817_shared_dai_ops','checked_codec_ops').replace('rk817_digital_mute','params_codec_mute_api')
    caller=one(caller,'static struct snd_soc_dai_driver cpu_driver', cpu_ops+'\n'+codec_ops+'\nstatic struct snd_soc_dai_driver cpu_driver')
    caller=one(caller,'    if (function == (void *)rk817_hw_params) { params_phase = 2;', '    if (function == (void *)rk817_shared_hw_params) { params_phase = 2;')
    caller=one(caller,'    if (function == (void *)i2s_checked_hw_params) { params_phase = 3;', '    if (function == (void *)i2s_shared_hw_params) { params_phase = 3;')
    caller=one(caller,'    if (function == (void *)asoc_simple_hw_params) { params_phase = 1; params_note("MACHINE_BEGIN", 0, 0); }', '''
    if (function == (void *)i2s_shared_begin) params_note("CPU_RESERVE", 0, 0);
    if (function == (void *)rk817_shared_begin) params_note("CODEC_RESERVE", 0, 0);
    if (function == (void *)rk817_shared_commit) params_note("CODEC_COMMIT", 0, 0);
    if (function == (void *)i2s_shared_commit) {
        params_note("CPU_COMMIT", 0, 0);
        if (params_inject_commit_busy) info.power_transition = true;
        if (params_inject_commit_error) {
            params_inject_commit_error = false;
            pthread_mutex_lock(&info.lock);
            i2s_checked_error_locked(&info, -EREMOTEIO);
            pthread_mutex_unlock(&info.lock);
            params_note("INJECT_CPU_FAULT_BEFORE_COMMIT", 0, -EREMOTEIO);
        }
    }
    if (function == (void *)asoc_simple_hw_params) { params_phase = 1; params_note("MACHINE_BEGIN", 0, 0); }''')
    # Exit instrumentation uses the new callback entrypoints, not unused default bodies.
    caller=caller.replace('if (function == (void *)rk817_hw_params) params_note("CODEC_END"', 'if (function == (void *)rk817_shared_hw_params) params_note("CODEC_END"')
    caller=caller.replace('if (function == (void *)i2s_checked_hw_params) params_note("CPU_END"', 'if (function == (void *)i2s_shared_hw_params) params_note("CPU_END"')
    caller=one(caller,'    if (function == (void *)asoc_simple_hw_params) params_note("MACHINE_END", 0, 0);', '''    if (function == (void *)i2s_shared_commit && params_inject_commit_busy) {
        params_inject_commit_busy = false;
        info.power_transition = false; /* Test only the still-owned reservation gate. */
        params_commit_window_result = soc_pcm_trigger(&substreams[0], SNDRV_PCM_TRIGGER_START);
        params_note("START_DURING_CPU_COMMIT_ERROR_WINDOW", 0, params_commit_window_result);
    }
    if (function == (void *)asoc_simple_hw_params) params_note("MACHINE_END", 0, 0);''')
    caller=one(caller,'        pthread_mutex_destroy(&card.pcm_mutex);','        pthread_mutex_destroy(&card.pcm_mutex);\n        pthread_mutex_destroy(&codec_info.params_lock);')
    caller=one(caller,'    memset(&info, 0, sizeof(info));','    memset(&info, 0, sizeof(info));\n    memset(&codec_info, 0, sizeof(codec_info));')
    caller=one(caller,'    pthread_mutex_init(&card.pcm_mutex, NULL);','    pthread_mutex_init(&card.pcm_mutex, NULL);\n    pthread_mutex_init(&codec_info.params_lock, NULL);\n    cpu_driver.ops = &checked_cpu_ops; codec_driver.ops = &checked_codec_ops;\n    card.num_links = card.num_rtd = 1;')
    caller=one(caller,'    info.checked_lifecycle = info.is_master_mode = true;', '''    info.checked_lifecycle = info.is_master_mode = true;
    info.shared_params_enabled = codec_info.shared_params_enabled = true;
    info.shared_dai_fmt = codec_info.shared_dai_fmt = SND_SOC_DAIFMT_CBS_CFS | SND_SOC_DAIFMT_NB_NF | SND_SOC_DAIFMT_I2S;
    codec_info.chip_ver = 5; codec_dai.id = RK817_HIFI;''')
    caller=one(caller,'static bool configure_both(void)\n{', 'static bool configure_both(void)\n{')
    old_config=function(caller,'configure_both')
    caller=one(caller,old_config,'''static bool configure_both(void)
{
    for (int stream = 0; stream < 2; stream++)
        if (soc_pcm_hw_params(&substreams[stream], &params)) return false;
    for (int stream = 0; stream < 2; stream++)
        if (i2s_checked_prepare(&substreams[stream], &cpu_dai)) return false;
    return !info.started && info.stop_proven && !info.runtime_error;
}''')
    caller=one(caller,'.hw_params = dmaengine_pcm_hw_params, .trigger = platform_trigger', '.hw_params = dmaengine_pcm_hw_params, .hw_free = params_component_free_api, .trigger = platform_trigger')
    caller=one(caller,'.trigger = i2s_checked_component_trigger, .open = component_open', '.trigger = i2s_checked_component_trigger, .hw_free = params_component_free_api, .open = component_open')
    caller=one(caller,'codec_component_ops = {.open = component_open', 'codec_component_ops = {.hw_free = params_component_free_api, .open = component_open')
    caller=one(caller,'link_ops = {.hw_params = asoc_simple_hw_params', 'link_ops = {.hw_free = params_link_free_api, .hw_params = asoc_simple_hw_params')
    (out/'test-caller-chain.c').write_text(caller)
    test=(HERE/'test-shared-params.c').read_text()
    test=one(test,'    int ret = soc_pcm_hw_free(&substreams[0]);\n    int expected = kind', '''    struct snd_soc_dai_ops release_fixture = checked_codec_ops;
    if (kind == 0) { release_fixture.hw_free = params_codec_release_api; codec_driver.ops = &release_fixture; }
    int ret = soc_pcm_hw_free(&substreams[0]);
    codec_driver.ops = &checked_codec_ops;
    int expected = kind''')
    (out/'test-shared-params.c').write_text(test)
    # Inputs are explicitly ordinary, finite, and do not pretend the five private copies are Image inputs.
    manifest = {'scope':'PRIVATE_PARAMS_CANDIDATE_MODEL_NOT_KERNEL_HARDWARE_OR_ABI',
        'baseline_manifest_sha256':sha(old_bytes), 'source_manifest_sha256':sha(source_manifest_bytes),
        'source_version':'source-v4','production_bodies':body_map,
        'Image_source_inventory_sha256':'bb2fb1a0c548bb2de8e683ebd6540f3cb75ddb5815af3df7cf2f8a1d918d0cd3',
        'model_registration':'Synthetic explicit checked CPU/hifi profile; real per-probe code is copied/audited but not executed. Codec mute is an API boundary; one late-release case substitutes an errno-only callback, other frees invoke actual production body. Three optional component frees and machine free are API error fixtures.',
        'probe_executed':False,'Kbuild_executed':False,'board_tested':False,
        'remaining_reds':['sequential_first_0_second_normal_START','sequential_first_1_second_normal_START','concurrent_two_normal_START_commit_both','hypothetical_dual_joint_STOP_reaches_global_proof']}
    manifest['design_amendment_sha256']=sha((HERE/'INTERFACE-AMENDMENT-v4.md').read_bytes())
    native=HERE.parents[2]/'.deps/kernel-source/aiot-3568pq-audio-v4/sound/core/pcm_native.c'
    native_bytes=native.read_bytes(); native_lines=native_bytes.decode().splitlines()
    selected=[{'line':i+1,'text':line} for i,line in enumerate(native_lines) if 'ops->hw_free' in line or 'ops->hw_params' in line]
    manifest['native_outer_boundary']={'actual_file':'sound/core/pcm_native.c','bytes':len(native_bytes),'sha256':sha(native_bytes),
        'git_mode':'100755' if native.stat().st_mode & 0o111 else '100644',
        'callback_reference_lines':selected,'full_native_body_executed':False,
        'test_scope':'Explicit native error cleanup API boundary invokes real soc_pcm_hw_free, not native whole state machine'}
    manifest['source_locks']={rel:item['candidate_sha256'] for rel,item in sm['files'].items()}
    (out/'prepare-snapshot-current.py').write_bytes(Path(__file__).read_bytes())
    manifest['model_files_sha256']={p.relative_to(out).as_posix():sha(p.read_bytes()) for p in out.rglob('*') if p.is_file() and p.name!='input-manifest.json'}
    (out/'input-manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'available_actual_body_identities':len(body_map),'manifest_sha256':sha((out/'input-manifest.json').read_bytes()),'model_executed':False}))
if __name__=='__main__': main()
