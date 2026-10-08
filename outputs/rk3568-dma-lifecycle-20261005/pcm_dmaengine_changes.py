#!/usr/bin/env python3
"""Checked DMA PCM process quiesce, ownership transfer and atomic trigger admission."""
from source_utils import function,replace

LIFECYCLE='''static __noreturn void dmaengine_pcm_failstop(const char *reason)
{
	/* Allocation/software ownership cannot be handed back on this path. */
	panic_timeout = 0;
	panic("DMA PCM lifecycle fail-stop: %s", reason);
}

static int dmaengine_pcm_error(struct dmaengine_pcm_runtime_data *prtd, int ret)
{
	unsigned long flags;

	if (!prtd->checked)
		return ret;
	spin_lock_irqsave(&prtd->lifecycle_lock, flags);
	if (ret < 0 && !prtd->first_error)
		prtd->first_error = ret;
	ret = prtd->first_error;
	spin_unlock_irqrestore(&prtd->lifecycle_lock, flags);
	return ret;
}

static int dmaengine_pcm_operation_begin(struct dmaengine_pcm_runtime_data *prtd,
					int cmd, bool stopping)
{
	unsigned long flags;
	int ret = 0;

	if (!prtd->checked)
		return 0;
	spin_lock_irqsave(&prtd->lifecycle_lock, flags);
	if (prtd->closing || prtd->quiescing)
		ret = prtd->first_error ? prtd->first_error : -EIO;
	else if (!stopping && (prtd->first_error || prtd->go_failed))
		ret = prtd->first_error ? prtd->first_error : -EIO;
	else if (cmd == SNDRV_PCM_TRIGGER_START && prtd->exposed)
		ret = -EBUSY;
	if (!ret)
		atomic_inc(&prtd->operations);
	spin_unlock_irqrestore(&prtd->lifecycle_lock, flags);
	return ret;
}

static void dmaengine_pcm_operation_end(struct dmaengine_pcm_runtime_data *prtd)
{
	if (prtd->checked) {
		atomic_dec(&prtd->operations);
		wake_up_all(&prtd->drain_wait);
	}
}

int snd_dmaengine_pcm_quiesce(struct snd_pcm_substream *substream)
{
	struct dmaengine_pcm_runtime_data *prtd = substream_to_prtd(substream);
	struct snd_pcm_runtime *runtime = substream->runtime;
	struct snd_dma_buffer *buffer;
	unsigned long flags;
	int ret, first;

	might_sleep();
	if (!prtd)
		return 0;
	if (!prtd->checked)
		return dmaengine_synchronize_checked(prtd->dma_chan);
	mutex_lock(&prtd->quiesce_mutex);
	spin_lock_irqsave(&prtd->lifecycle_lock, flags);
	prtd->quiescing = true;
	spin_unlock_irqrestore(&prtd->lifecycle_lock, flags);
	/* Atomic trigger callbacks never wait or acquire this process mutex. */
	if (!wait_event_timeout(prtd->drain_wait, !atomic_read(&prtd->operations),
				msecs_to_jiffies(500)))
		dmaengine_pcm_failstop("trigger admission drain deadline");
	/* A checked negative return means all old software callbacks are drained. */
	ret = dmaengine_synchronize_checked(prtd->dma_chan);
	first = dmaengine_pcm_error(prtd, ret);
	if (prtd->exposed) {
		buffer = runtime->dma_buffer_p;
		if (buffer != prtd->owner_buffer || !buffer ||
		    buffer->area != prtd->owner.area || buffer->addr != prtd->owner.addr ||
		    buffer->bytes != prtd->owner.bytes || buffer->dev.type != prtd->owner.dev.type ||
		    buffer->dev.dev != prtd->owner.dev.dev ||
		    buffer->private_data != prtd->owner.private_data ||
		    snd_pcm_dma_quarantine_check(substream, prtd->dma_chan->device->dev))
			dmaengine_pcm_failstop("exposed allocation owner changed");
		if (ret < 0 && snd_pcm_dma_quarantine(substream, prtd->quarantine,
						     prtd->dma_chan->device->dev))
			dmaengine_pcm_failstop("allocation ownership transfer failed");
		prtd->exposed = false;
		prtd->owner_buffer = NULL;
		memset(&prtd->owner, 0, sizeof(prtd->owner));
	}
	/* Void GO reported only DMA_ERROR; keep a later exact checked errno first. */
	if (!first && prtd->go_failed)
		first = dmaengine_pcm_error(prtd, -EIO);
	prtd->cookie = 0;
	spin_lock_irqsave(&prtd->lifecycle_lock, flags);
	if (!prtd->closing)
		prtd->quiescing = false;
	spin_unlock_irqrestore(&prtd->lifecycle_lock, flags);
	mutex_unlock(&prtd->quiesce_mutex);
	return first;
}
EXPORT_SYMBOL_GPL(snd_dmaengine_pcm_quiesce);

'''

TRIGGER='''int snd_dmaengine_pcm_trigger(struct snd_pcm_substream *substream, int cmd)
{
	struct dmaengine_pcm_runtime_data *prtd = substream_to_prtd(substream);
	struct snd_pcm_runtime *runtime = substream->runtime;
	unsigned long flags;
	bool stopping;
	int ret;

	switch (cmd) {
	case SNDRV_PCM_TRIGGER_START:
	case SNDRV_PCM_TRIGGER_STOP:
	case SNDRV_PCM_TRIGGER_RESUME:
	case SNDRV_PCM_TRIGGER_SUSPEND:
	case SNDRV_PCM_TRIGGER_PAUSE_PUSH:
	case SNDRV_PCM_TRIGGER_PAUSE_RELEASE:
		break;
	default:
		return -EINVAL;
	}
	stopping = cmd == SNDRV_PCM_TRIGGER_STOP ||
		(cmd == SNDRV_PCM_TRIGGER_SUSPEND && !(runtime->info & SNDRV_PCM_INFO_PAUSE));
	ret = dmaengine_pcm_operation_begin(prtd, cmd, stopping);
	if (ret)
		return ret;
	switch (cmd) {
	case SNDRV_PCM_TRIGGER_START:
		ret = dmaengine_pcm_prepare_and_submit(substream);
		if (ret)
			break;
		dma_async_issue_pending(prtd->dma_chan);
		if (prtd->checked && dmaengine_tx_status(prtd->dma_chan, prtd->cookie, NULL) == DMA_ERROR) {
			spin_lock_irqsave(&prtd->lifecycle_lock, flags);
			prtd->go_failed = true;
			spin_unlock_irqrestore(&prtd->lifecycle_lock, flags);
			dmaengine_pcm_operation_end(prtd);
			return -EIO;
		}
		break;
	case SNDRV_PCM_TRIGGER_RESUME:
	case SNDRV_PCM_TRIGGER_PAUSE_RELEASE:
		ret = dmaengine_resume(prtd->dma_chan);
		break;
	case SNDRV_PCM_TRIGGER_SUSPEND:
		if (runtime->info & SNDRV_PCM_INFO_PAUSE)
			ret = dmaengine_pause(prtd->dma_chan);
		else
			ret = dmaengine_terminate_async(prtd->dma_chan);
		break;
	case SNDRV_PCM_TRIGGER_PAUSE_PUSH:
		ret = dmaengine_pause(prtd->dma_chan);
		break;
	case SNDRV_PCM_TRIGGER_STOP:
		ret = dmaengine_terminate_async(prtd->dma_chan);
		break;
	default:
		ret = -EINVAL;
		break;
	}
	/* Validation/prep NULL has no exact I/O errno; checked obtains it later. */
	if (cmd == SNDRV_PCM_TRIGGER_START && ret < 0 && prtd->cookie >= 0) {
		dmaengine_pcm_operation_end(prtd);
		return ret;
	}
	ret = dmaengine_pcm_error(prtd, ret);
	dmaengine_pcm_operation_end(prtd);
	return ret;
}
'''

def dma_pcm(source,header,generic):
    source=replace(source,"#include <linux/slab.h>","#include <linux/slab.h>\n#include <linux/mutex.h>\n#include <linux/wait.h>\n#include <linux/kernel.h>")
    source=replace(source,"\tunsigned int pos;\n};",'''\tunsigned int pos;
	bool checked, exposed, quiescing, closing, go_failed;
	int first_error;
	spinlock_t lifecycle_lock;
	atomic_t operations;
	wait_queue_head_t drain_wait;
	struct mutex quiesce_mutex;
	struct snd_pcm_dma_quarantine *quarantine;
	struct snd_dma_buffer *owner_buffer;
	struct snd_dma_buffer owner;
};''')
    anchor=function(source,"dmaengine_pcm_dma_complete");source=replace(source,anchor,LIFECYCLE+anchor)
    old=function(source,"dmaengine_pcm_prepare_and_submit")
    new=replace(old,"\tunsigned long flags = DMA_CTRL_ACK;","\tunsigned long flags = DMA_CTRL_ACK, irqflags;\n\tint ret;")
    new=replace(new,"\tdirection = snd_pcm_substream_to_dma_direction(substream);",'''\tprtd->cookie = 0;
	if (prtd->checked) {
		ret = snd_pcm_dma_quarantine_check(substream, chan->device->dev);
		if (ret)
			return ret;
	}
	direction = snd_pcm_substream_to_dma_direction(substream);''')
    new=replace(new,"\tprtd->cookie = dmaengine_submit(desc);",'''\tprtd->cookie = dmaengine_submit(desc);
	ret = dma_submit_error(prtd->cookie);
	if (ret)
		return ret;
	if (prtd->checked) {
		spin_lock_irqsave(&prtd->lifecycle_lock, irqflags);
		prtd->owner_buffer = substream->runtime->dma_buffer_p;
		prtd->owner = *prtd->owner_buffer;
		prtd->exposed = true;
		spin_unlock_irqrestore(&prtd->lifecycle_lock, irqflags);
	}''')
    source=replace(source,old,new);source=replace(source,function(source,"snd_dmaengine_pcm_trigger"),TRIGGER)
    old=function(source,"snd_dmaengine_pcm_open")
    new=replace(old,"\tprtd->dma_chan = chan;",'''\tprtd->dma_chan = chan;
	prtd->checked = !!chan->device->device_synchronize_checked;
	spin_lock_init(&prtd->lifecycle_lock);
	atomic_set(&prtd->operations, 0);
	init_waitqueue_head(&prtd->drain_wait);
	mutex_init(&prtd->quiesce_mutex);
	if (prtd->checked) {
		prtd->quarantine = snd_pcm_dma_quarantine_alloc();
		if (!prtd->quarantine) {
			kfree(prtd);
			return -ENOMEM;
		}
	}''')
    new=replace(new,"\tsubstream->runtime->private_data = prtd;","\tsubstream->runtime->private_data = prtd;\n\tif (prtd->checked)\n\t\tsubstream->runtime->dma_quiesce = snd_dmaengine_pcm_quiesce;")
    source=replace(source,old,new)
    for name,releases in [("snd_dmaengine_pcm_close",False),("snd_dmaengine_pcm_close_release_chan",True)]:
        old=function(source,name)
        new=replace(old,"\tdmaengine_synchronize(prtd->dma_chan);",'''\tunsigned long flags;
	int ret;

	if (!prtd)
		return 0;
	if (prtd->checked) {
		spin_lock_irqsave(&prtd->lifecycle_lock, flags);
		prtd->closing = true;
		spin_unlock_irqrestore(&prtd->lifecycle_lock, flags);
	}
	ret = snd_dmaengine_pcm_quiesce(substream);''')
        if releases:new=replace(new,"\tdma_release_channel(prtd->dma_chan);","\tif (prtd->checked && ret < 0)\n\t\tdmaengine_pcm_failstop(\"channel owner cannot be released\");\n\tdma_release_channel(prtd->dma_chan);")
        new=replace(new,"\tkfree(prtd);","\tsubstream->runtime->dma_quiesce = NULL;\n\tsubstream->runtime->private_data = NULL;\n\tsnd_pcm_dma_quarantine_free(prtd->quarantine);\n\tkfree(prtd);")
        new=replace(new,"\treturn 0;\n}","\treturn ret;\n}")
        source=replace(source,old,new)
    header=replace(header,"int snd_dmaengine_pcm_close(struct snd_pcm_substream *substream);","int snd_dmaengine_pcm_close(struct snd_pcm_substream *substream);\nint snd_dmaengine_pcm_quiesce(struct snd_pcm_substream *substream);")
    anchor=function(generic,"dmaengine_pcm_trigger")
    generic=replace(generic,anchor,'''static int dmaengine_pcm_quiesce(struct snd_soc_component *component,
				 struct snd_pcm_substream *substream)
{
	return snd_dmaengine_pcm_quiesce(substream);
}

'''+anchor)
    # Both normal and process components must cover failed START without stop_operating.
    if generic.count("\t.trigger\t= dmaengine_pcm_trigger,")!=2:raise ValueError("two generic component ABI tables absent")
    generic=generic.replace("\t.trigger\t= dmaengine_pcm_trigger,","\t.prepare\t= dmaengine_pcm_quiesce,\n\t.hw_free\t= dmaengine_pcm_quiesce,\n\t.sync_stop\t= dmaengine_pcm_quiesce,\n\t.trigger\t= dmaengine_pcm_trigger,")
    return source,header,generic
