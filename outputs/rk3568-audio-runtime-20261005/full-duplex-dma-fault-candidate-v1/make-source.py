#!/usr/bin/env python3
"""Generate source-v1 from finite exact baseline; all edits stay private."""
import difflib
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE/'baseline'
OUT = HERE/'source-v5'
OUT.mkdir(exist_ok=True)
if any(OUT.iterdir()):
    raise ValueError('Fresh source directory required')

def replace(s,old,new):
    if s.count(old)!=1:
        raise ValueError('Exact replacement required: '+old[:80])
    return s.replace(old,new,1)

files={n:(BASE/n).read_text() for n in ['drivers/dma/pl330.c','sound/core/pcm_dmaengine.c',
    'sound/soc/soc-generic-dmaengine-pcm.c','include/sound/dmaengine_pcm.h']}
s=files['drivers/dma/pl330.c']
s=replace(s,'\t/* Lifecycle fields protected by lock; producers/runners are waitable. */\n\tu64 epoch;\n','\t/* Lifecycle fields protected by lock; producers/runners are waitable. */\n\tu64 epoch;\n\tu64 fault_notified_epoch;\n\tbool fault_notified;\n')
s=replace(s,'\tif (!pl330->lifecycle_error)\n\t\tpl330->lifecycle_error = error;','\tif (!pl330->lifecycle_error) {\n\t\tpl330->lifecycle_error = error;\n\t\t/* tasks is initialized before state becomes INIT. No PM/MMIO here. */\n\t\tif (pl330->state == INIT || pl330->state == DYING) {\n\t\t\tpl330->fault_tasklet_queued = true;\n\t\t\ttasklet_schedule(&pl330->tasks);\n\t\t}\n\t}')
s=replace(s,'static void pl330_dotask(struct tasklet_struct *t)\n', (HERE/'pl330-notify.inc').read_text()+'\nstatic void pl330_dotask(struct tasklet_struct *t)\n')
s=replace(s,'\tint i;\n\tatomic_inc(&pl330->producers);\n\n\tspin_lock_irqsave(&pl330->lock, flags);\n\tpl330->fault_tasklet_queued = false;','\tint i;\n\tatomic_inc(&pl330->producers);\n\n\tspin_lock_irqsave(&pl330->lock, flags);\n\tpl330->fault_tasklet_queued = false;\n\tspin_unlock_irqrestore(&pl330->lock, flags);\n\t/* PM failure/removal/reset early exits must not suppress borrowed faults. */\n\tpl330_fault_notify(pl330);\n\tspin_lock_irqsave(&pl330->lock, flags);')
files['drivers/dma/pl330.c']=s
s=files['sound/core/pcm_dmaengine.c']
s=replace(s,'\tint first_error;\n','\tint first_error;\n\tvoid (*error_sink)(struct snd_pcm_substream *, int, void *);\n\tvoid *error_sink_arg;\n')
s=replace(s,'static inline struct dmaengine_pcm_runtime_data *substream_to_prtd(','static int dmaengine_pcm_check_fault(struct snd_pcm_substream *substream);\nstatic void dmaengine_pcm_notify_fault(struct snd_pcm_substream *substream,\n\t\t\t\t      int error, bool stop_xrun);\n\nstatic inline struct dmaengine_pcm_runtime_data *substream_to_prtd(')
s=replace(s,'\tif (!prtd->checked)\n\t\treturn dmaengine_synchronize_checked(prtd->dma_chan);\n\tmutex_lock(&prtd->quiesce_mutex);','\tif (!prtd->checked)\n\t\treturn dmaengine_synchronize_checked(prtd->dma_chan);\n\t/* PREPARE/HW_FREE may have no descriptor; close CPU admission first. */\n\tdmaengine_pcm_check_fault(substream);\n\tmutex_lock(&prtd->quiesce_mutex);')
s=replace(s,'\tfirst = dmaengine_pcm_error(prtd, ret);','\tfirst = dmaengine_pcm_error(prtd, ret);\n\tif (ret < 0)\n\t\tdmaengine_pcm_notify_fault(substream, ret, false);')
s=replace(s,'static int dmaengine_pcm_prepare_and_submit(struct snd_pcm_substream *substream)\n',(HERE/'pcm-notify.inc').read_text()+'\nstatic int dmaengine_pcm_prepare_and_submit(struct snd_pcm_substream *substream)\n')
s=replace(s,'\tprtd->cookie = 0;\n\tif (prtd->checked) {','\tprtd->cookie = 0;\n\tret = dmaengine_pcm_check_fault(substream);\n\tif (ret)\n\t\treturn ret;\n\tif (prtd->checked) {')
s=replace(s,'\tdesc->callback = dmaengine_pcm_dma_complete;','\tif (prtd->checked)\n\t\tdesc->callback_result = dmaengine_pcm_dma_complete_result;\n\telse\n\t\tdesc->callback = dmaengine_pcm_dma_complete;')
s=replace(s,'\tif (!desc)\n\t\treturn -ENOMEM;','\tif (!desc) {\n\t\tret = dmaengine_pcm_check_fault(substream);\n\t\treturn ret ? ret : -ENOMEM;\n\t}')
s=replace(s,'\tret = dma_submit_error(prtd->cookie);\n\tif (ret)\n\t\treturn ret;','\tret = dma_submit_error(prtd->cookie);\n\tif (ret) {\n\t\tint exact = dmaengine_pcm_check_fault(substream);\n\n\t\treturn exact ? exact : ret;\n\t}')
s=replace(s,'\tret = dmaengine_pcm_operation_begin(prtd, cmd, stopping);','\tif (!stopping) {\n\t\tret = dmaengine_pcm_check_fault(substream);\n\t\tif (ret)\n\t\t\treturn ret;\n\t}\n\tret = dmaengine_pcm_operation_begin(prtd, cmd, stopping);')
s=replace(s,'\t\tdma_async_issue_pending(prtd->dma_chan);','\t\tret = dmaengine_pcm_check_fault(substream);\n\t\tif (ret)\n\t\t\tbreak;\n\t\tdma_async_issue_pending(prtd->dma_chan);\n\t\tret = dmaengine_pcm_check_fault(substream);\n\t\tif (ret)\n\t\t\tbreak;')
s=replace(s,'\t\t\tdmaengine_pcm_operation_end(prtd);\n\t\t\treturn -EIO;','\t\t\tret = dmaengine_pcm_check_fault(substream);\n\t\t\tif (!ret)\n\t\t\t\tdmaengine_pcm_notify_fault(substream, -EIO, false);\n\t\t\tdmaengine_pcm_operation_end(prtd);\n\t\t\treturn dmaengine_pcm_error(prtd, ret ? ret : -EIO);')
s=replace(s,'\treturn bytes_to_frames(substream->runtime, prtd->pos);','\tif (dmaengine_pcm_check_fault(substream))\n\t\treturn SNDRV_PCM_POS_XRUN;\n\treturn bytes_to_frames(substream->runtime, prtd->pos);')
s=replace(s,'\tdmaengine_tx_status(prtd->dma_chan, prtd->cookie, &state);','\tif (dmaengine_pcm_check_fault(substream))\n\t\treturn SNDRV_PCM_POS_XRUN;\n\tif (dmaengine_tx_status(prtd->dma_chan, prtd->cookie, &state) == DMA_ERROR && prtd->checked) {\n\t\tif (!dmaengine_pcm_check_fault(substream))\n\t\t\tdmaengine_pcm_notify_fault(substream, -EIO, false);\n\t\treturn SNDRV_PCM_POS_XRUN;\n\t}')
files['sound/core/pcm_dmaengine.c']=s
s=files['include/sound/dmaengine_pcm.h']
s=replace(s,'int snd_dmaengine_pcm_quiesce(struct snd_pcm_substream *substream);','int snd_dmaengine_pcm_quiesce(struct snd_pcm_substream *substream);\n/* Open-only binding; atomic sink invoked outside DMA/PCM lifecycle locks. */\nint snd_dmaengine_pcm_set_error_sink(struct snd_pcm_substream *substream,\n\tvoid (*sink)(struct snd_pcm_substream *, int, void *), void *arg);')
files['include/sound/dmaengine_pcm.h']=s
s=files['sound/soc/soc-generic-dmaengine-pcm.c']
sink='''static void dmaengine_pcm_cpu_fault(struct snd_pcm_substream *substream,
				   int first_error, void *arg)
{
	struct snd_soc_dai *cpu_dai = arg;

	/* CPU-only optional contract: atomic, no codec callbacks or sleeping. */
	cpu_dai->driver->ops->pcm_async_fault(cpu_dai, first_error);
}

'''
s=replace(s,'static int dmaengine_pcm_open(struct snd_soc_component *component,\n',sink+'static int dmaengine_pcm_open(struct snd_soc_component *component,\n')
s=replace(s,'\treturn snd_dmaengine_pcm_open(substream, chan);','''	ret = snd_dmaengine_pcm_open(substream, chan);
	if (!ret) {
		struct snd_soc_pcm_runtime *rtd = asoc_substream_to_rtd(substream);
		struct snd_soc_dai *cpu_dai;

		if (rtd->num_cpus == 1) {
			cpu_dai = asoc_rtd_to_cpu(rtd, 0);
			if (cpu_dai->driver->ops && cpu_dai->driver->ops->pcm_async_fault) {
				ret = snd_dmaengine_pcm_set_error_sink(substream,
							    dmaengine_pcm_cpu_fault, cpu_dai);
				if (ret)
					snd_dmaengine_pcm_close(substream);
			}
		}
	}
	return ret;''')
files['sound/soc/soc-generic-dmaengine-pcm.c']=s
manifest={}
patch=''
for name,text in files.items():
    p=OUT/name
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(text,encoding='utf-8',newline='\n')
    digest=hashlib.sha256(p.read_bytes()).hexdigest()
    manifest[name]={'bytes':p.stat().st_size,'sha256':digest}
    patch+=''.join(difflib.unified_diff((BASE/name).read_text().splitlines(True),text.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
(HERE/'source-manifest-v5.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8',newline='\n')
(HERE/'dma-fault-private-v5.patch').write_text(patch,encoding='utf-8',newline='\n')
print(json.dumps({'private_source_files':len(files),'patch_bytes':len(patch.encode()),'SDK_modified':False}))
