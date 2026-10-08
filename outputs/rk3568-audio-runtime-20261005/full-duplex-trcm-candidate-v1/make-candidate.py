#!/usr/bin/env python3
"""Private CPU-only candidate; never writes accepted source/SDK."""
import argparse, difflib, hashlib, importlib.util, json, re
from pathlib import Path
HERE = Path(__file__).resolve().parent
PARAMS = HERE.parent/'full-duplex-params-candidate-v1'
REL = 'sound/soc/rockchip/rockchip_i2s_tdm.c'
SHA = '399a672728c41a5ed3900b6186021babaf9a1d3aac4dafbfcd4f72277d5fafe0'
def sha(b): return hashlib.sha256(b).hexdigest()
spec=importlib.util.spec_from_file_location('lexical',PARAMS/'make-candidate.py')
lex=importlib.util.module_from_spec(spec);spec.loader.exec_module(lex)
function,one=lex.function,lex.one
def main():
    p=argparse.ArgumentParser();p.add_argument('--version',type=int,required=True);args=p.parse_args()
    before=(PARAMS/'source-v4'/REL).read_bytes()
    if sha(before)!=SHA: raise ValueError('Accepted CPU drift')
    out=HERE/f'source-v{args.version}'/REL;out.parent.mkdir(parents=True,exist_ok=False)
    text=before.decode()
    text=one(text,'unsigned int shared_dai_fmt, shared_prepared;', '''unsigned int shared_dai_fmt, shared_prepared;
	/* Per-direction C3 reservation; epoch revoke never claims GO borrow drained. */
	unsigned int starting, starting_valid, quiet_proven;
	u64 trcm_epoch, trcm_ticket_epoch[2];
	struct snd_pcm_substream *trcm_ticket[2], *trcm_active[2];
	bool transport_live;''')
    text=one(text,'static int i2s_checked_first_error(int first, int next);', '''static int i2s_checked_first_error(int first, int next);
static int i2s_checked_all_stop_locked(struct rk_i2s_tdm_dev *i2s_tdm);
static int i2s_trcm_joint_locked(struct rk_i2s_tdm_dev *i2s_tdm, int first);''')
    anchor=function(text,'i2s_checked_stop_locked')
    # function() excludes forward declarations and returns the definition.
    text=one(text,anchor,(HERE/'trcm-functions.inc').read_text()+'\n'+anchor)
    text=one(text,'if (ret < 0 && !i2s_tdm->runtime_error)\n\t\ti2s_tdm->runtime_error = ret;', '''if (ret < 0 && !i2s_tdm->runtime_error) {
		i2s_tdm->runtime_error = ret;
		if (i2s_tdm->shared_params_enabled) {
			i2s_tdm->starting_valid = 0;
			if (i2s_tdm->trcm_epoch != ~(u64)0)
				i2s_tdm->trcm_epoch++;
		}
	}''')
    # The old gate is also used by params, format/startup and must include pending GO.
    text=one(text,'i2s_tdm->power_transition || i2s_tdm->started)\n\t\treturn -EBUSY;', 'i2s_tdm->power_transition || i2s_tdm->started || i2s_tdm->starting)\n\t\treturn -EBUSY;')
    text=one(text,'i2s_tdm->started || !i2s_tdm->stop_proven)\n\t\tret = -EBUSY;', 'i2s_tdm->started || i2s_tdm->starting || !i2s_tdm->stop_proven)\n\t\tret = -EBUSY;')
    text=text.replace('ret = i2s_tdm->configuring || i2s_tdm->started ||','ret = i2s_tdm->configuring || i2s_tdm->started || i2s_tdm->starting ||')
    text=text.replace('i2s_tdm->started || i2s_tdm->configuring ? -EBUSY : 0;', 'i2s_tdm->started || i2s_tdm->starting || i2s_tdm->configuring ? -EBUSY : 0;')
    # Runtime-resume/quiesce use a genuine joint helper for the managed profile.
    block='''ret = i2s_checked_stop_locked(i2s_tdm, SNDRV_PCM_STREAM_PLAYBACK, true);
		next = i2s_checked_stop_locked(i2s_tdm, SNDRV_PCM_STREAM_CAPTURE, true);
		ret = i2s_checked_first_error(ret, next);'''
    if text.count(block)!=2: raise ValueError('Global pair count')
    text=text.replace(block,'ret = i2s_checked_all_stop_locked(i2s_tdm);')
    block='''next = i2s_checked_stop_locked(i2s_tdm, SNDRV_PCM_STREAM_PLAYBACK, true);
	proved = !next;
	next = i2s_checked_stop_locked(i2s_tdm, SNDRV_PCM_STREAM_CAPTURE, true);
	proved = proved && !next;'''
    text=one(text,block,'next = i2s_checked_all_stop_locked(i2s_tdm);\n\tproved = !next && !i2s_tdm->starting;')
    old=function(text,'i2s_checked_quiesce');new=old.replace('int ret, next;', 'int ret;');text=one(text,old,new)
    text=one(text,'if (i2s_tdm->configuring || p->pending || (i2s_tdm->started & BIT(ss->stream)))', 'if (i2s_tdm->configuring || p->pending || ((i2s_tdm->started | i2s_tdm->starting) & BIT(ss->stream)))')
    text=one(text,'if (i2s_tdm->configuring || (i2s_tdm->started & BIT(ss->stream)))', 'if (i2s_tdm->configuring || ((i2s_tdm->started | i2s_tdm->starting) & BIT(ss->stream)))')
    # Pure format validation is safe only outside an outstanding transport ticket.
    old=function(text,'i2s_shared_set_fmt');new=old.replace('spin_lock_irqsave(&i2s_tdm->lock, flags);', '''spin_lock_irqsave(&i2s_tdm->lock, flags);
	if (i2s_tdm->starting) {
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		return -EBUSY;
	}''',1);text=one(text,old,new)
    text=one(text,'if (i2s_tdm->checked_lifecycle)\n\t\treturn i2s_checked_trigger(i2s_tdm, substream->stream, cmd);', '''if (i2s_tdm->checked_lifecycle) {
		if (i2s_tdm->shared_params_enabled)
			return i2s_trcm_trigger(i2s_tdm, substream, cmd);
		return i2s_checked_trigger(i2s_tdm, substream->stream, cmd);
	}''')
    for name,file in [('i2s_checked_prepare','prepare.inc'),('i2s_checked_component_trigger','component.inc'),
                      ('rockchip_i2s_tdm_shutdown','shutdown.inc')]:
        text=one(text,function(text,name),(HERE/file).read_text().rstrip())
    old=function(text,'i2s_checked_isr')
    new=one(old,'irqreturn_t result = IRQ_NONE;', 'irqreturn_t result = IRQ_NONE;\n\n\tif (i2s_tdm->shared_params_enabled)\n\t\treturn i2s_trcm_isr(i2s_tdm);')
    text=one(text,old,(HERE/'isr.inc').read_text()+'\n'+new)
    async_body=(HERE/'async-fault.inc').read_text()
    text=one(text,'static const struct snd_soc_dai_ops rockchip_i2s_tdm_shared_ops = {',async_body+'\nstatic const struct snd_soc_dai_ops rockchip_i2s_tdm_shared_ops = {')
    old='\t.hw_params_fault = i2s_shared_fault,\n};'
    text=one(text,old,'\t.hw_params_fault = i2s_shared_fault,\n\t.pcm_async_fault = i2s_trcm_async_fault,\n};')
    out.write_text(text)
    identities={}
    names=set(re.findall(r'^static (?:inline )?(?:int|void|irqreturn_t)\s+(\w+)\([^;]*?\)\s*\{', text,re.M))
    for name in names:
        body=function(text,name)
        try:old=function(before.decode(),name)
        except ValueError:old=None
        if body!=old: identities[name]={'sha256':sha(body.encode()),'previous_sha256':sha(old.encode()) if old else None}
    patch=''.join(difflib.unified_diff(before.decode().splitlines(True),text.splitlines(True),fromfile='a/'+REL,tofile='b/'+REL))
    (HERE/f'cpu-trcm-private-v{args.version}.patch').write_text(patch)
    manifest={'scope':'PRIVATE_CPU_ONLY_NOT_IMAGE_OR_BOARD','baseline_CPU_sha256':SHA,'source_path':out.relative_to(HERE).as_posix(),
        'source_sha256':sha(out.read_bytes()),'changed_bodies':identities,'patch_sha256':sha(patch.encode()),
        'new_optional_ops_header_required':'void (*pcm_async_fault)(struct snd_soc_dai *, int)',
        'header_product_compiled':False,'Kbuild_executed':False,'board_tested':False,'duplex_START_authorized':False}
    (HERE/f'source-manifest-v{args.version}.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'source_sha256':manifest['source_sha256'],'changed_bodies':len(identities),'manifest_sha256':sha((HERE/f'source-manifest-v{args.version}.json').read_bytes())}))
if __name__=='__main__': main()
