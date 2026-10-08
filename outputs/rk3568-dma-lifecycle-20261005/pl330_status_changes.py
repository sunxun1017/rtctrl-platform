"""New C3-only provider increment; older C1 frozen sources stay unchanged."""
from source_utils import function
def replace(text,old,new):
    if text.count(old)!=1:raise ValueError('expected one source occurrence: '+old[:80])
    return text.replace(old,new,1)
def provider_increment(text):
    text=replace(text,'#include <linux/dmaengine.h>','#include <linux/dmaengine.h>\n#include <linux/timer.h>')
    text=replace(text,'\trefcount_dec_and_test(&desc->refs);','\tif (WARN_ON(!refcount_dec_and_test(&desc->refs)))\n\t\treturn;')
    # Real translation-unit order differs from extracted test function order.
    point='static int __maybe_unused pl330_suspend(struct device *dev)'
    text=replace(text,point,'static bool pl330_controller_drained(struct pl330_dmac *pl330);\nstatic int pl330_controller_stop_proof(struct pl330_dmac *pl330);\n\n'+point)
    text=replace(text,'\tint lifecycle_error;', '\tint lifecycle_error;\n\tatomic_t owned_descs;\n\tbool stop_proven;\n\tu64 stop_reads;\n\tstruct timer_list reader_timer;')
    text=replace(text,'\tatomic_set(&pl330->producers, 0);','\tatomic_set(&pl330->producers, 0);\n\tatomic_set(&pl330->owned_descs, 0);\n\ttimer_setup(&pl330->reader_timer, pl330_reader_deadline, 0);')
    old=function(text,'pl330_error_locked')
    text=replace(text,old,replace(old,'\tif (!pl330->lifecycle_error)','\tpl330->stop_proven = false;\n\tif (!pl330->lifecycle_error)'))
    old=function(text,'_start')
    text=replace(text,old,replace(old,'\tint ret;','\tint ret;\n\n\tthrd->dmac->stop_proven = false;'))
    old=function(text,'_stop')
    # Every physical control action revokes cached proof; only checked process proof restores it.
    new=replace(old,'\tint ret;','\tint ret;\n\n\tthrd->dmac->stop_proven = false;')
    text=replace(text,old,new)
    old=function(text,'pl330_get_desc')
    text=replace(text,old,replace(old,'\tatomic_inc(&pch->prepared_descs);','\tatomic_inc(&pch->prepared_descs);\n\tatomic_inc(&pl330->owned_descs);'))
    old=function(text,'pl330_desc_release')
    text=replace(text,old,replace(old,'\tdma_descriptor_unmap(&desc->txd);','\tif (desc->owner_pch)\n\t\tatomic_dec(&pl330->owned_descs);\n\tdma_descriptor_unmap(&desc->txd);'))
    # called with controller lock and this checked invocation's successful PM lease held.
    capture='''static void pl330_capture_stop_locked(struct pl330_dmac *pl330)
{
	struct pl330_thread *thread;
	bool stopped = true;
	int i;

	for (i = 0; i <= pl330->pcfg.num_chan; i++) {
		thread = i == pl330->pcfg.num_chan ? pl330->manager : &pl330->channels[i];
		pl330->stop_reads++;
		if (_state(thread) != PL330_STATE_STOPPED)
			stopped = false;
	}
	pl330->stop_proven = stopped;
}

'''
    point='static int pl330_sync_channel(struct dma_chan *chan, bool reopen)'
    text=replace(text,point,capture+point)
    old=function(text,'pl330_sync_channel')
    text=replace(text,old,replace(old,'\tif (!ret)\n\t\tlist_splice_tail_init(&pch->retired_list, &reclaim);','\tif (!ret) {\n\t\tpl330_capture_stop_locked(pl330);\n\t\tlist_splice_tail_init(&pch->retired_list, &reclaim);\n\t}'))
    show='''/* Cached proof only: reading this attribute never powers or reads the DMAC. */
static ssize_t rk3568_lifecycle_state_show(struct device *dev,
			struct device_attribute *attr, char *buf)
{
	struct pl330_dmac *pl330 = dev_get_drvdata(dev);
	struct dma_pl330_chan *pch;
	unsigned long flags;
	unsigned int allocated = 0, leases = 0, software = 0, queued = 0;
	int error, usage, descriptors;
	u64 reads;
	bool stopped, ready;

	if (!spin_trylock_irqsave(&pl330->lock, flags))
		return -EAGAIN;
	list_for_each_entry(pch, &pl330->ddma.channels, chan.device_node) {
		allocated += READ_ONCE(pch->thread) != NULL;
		leases += READ_ONCE(pch->pm_ref_held);
		software += atomic_read(&pch->producers) + atomic_read(&pch->runners) +
			atomic_read(&pch->issuers) + atomic_read(&pch->operations) +
			atomic_read(&pch->preparations) + atomic_read(&pch->prepared_descs) +
			atomic_read(&pch->faults) + atomic_read(&pch->gc_users);
		queued += READ_ONCE(pch->tasklet_queued) + READ_ONCE(pch->gc_queued);
	}
	software += atomic_read(&pl330->producers) + atomic_read(&pl330->irq_users);
	queued += pl330->fault_tasklet_queued;
	error = pl330->lifecycle_error;
	usage = atomic_read(&dev->power.usage_count);
	descriptors = atomic_read(&pl330->owned_descs);
	stopped = pl330->stop_proven;
	reads = pl330->stop_reads;
	ready = pl330->ddma.device_synchronize_checked == pl330_synchronize_checked &&
		!error && !pl330->removing && !pl330->system_suspended &&
		stopped && reads && !usage && !leases && !software && !queued && !descriptors;
	spin_unlock_irqrestore(&pl330->lock, flags);
	return scnprintf(buf, PAGE_SIZE,
		"version=1 ready=%u error=%d stop_proven=%u stop_reads=%llu "
		"pm_usage=%d leases=%u software=%u queued=%u descriptors=%d allocated=%u\\n",
		ready, error, stopped, (unsigned long long)reads, usage, leases,
		software, queued, descriptors, allocated);
}
static DEVICE_ATTR_RO(rk3568_lifecycle_state);

static void pl330_reader_deadline(struct timer_list *timer)
{
	struct pl330_dmac *pl330 = from_timer(pl330, timer, reader_timer);

	pl330_failstop(pl330, "sysfs reader drain deadline");
}

static void pl330_reader_remove(struct pl330_dmac *pl330)
{
	/* kernfs drains active readers; bound that wait before devres can free us. */
	mod_timer(&pl330->reader_timer, jiffies + msecs_to_jiffies(500));
	device_remove_file(pl330->ddma.dev, &dev_attr_rk3568_lifecycle_state);
	del_timer_sync(&pl330->reader_timer);
}

'''
    point='static int\npl330_probe(struct amba_device *adev, const struct amba_id *id)'
    text=replace(text,point,show+point)
    text=replace(text,'\tret = dma_async_device_register_checked(pd, pl330_synchronize_checked);','\tret = device_create_file(&adev->dev, &dev_attr_rk3568_lifecycle_state);\n\tif (ret)\n\t\tgoto probe_err3;\n\tret = dma_async_device_register_checked(pd, pl330_synchronize_checked);')
    text=replace(text,'probe_err3:\n','probe_err3:\n\tpl330_reader_remove(pl330);\n')
    old=function(text,'pl330_remove')
    text=replace(text,old,replace(old,'\t/* Same core mutex as every client acquisition: no zero-snapshot race. */','\t/* sysfs deactivation drains active readers before any owner can be freed. */\n\tpl330_reader_remove(pl330);\n\t/* Same core mutex as every client acquisition: no zero-snapshot race. */'))
    return text

def pcm_status_increment(memory,pcm):
    memory=replace(memory,'#include <linux/moduleparam.h>','#include <linux/moduleparam.h>\n#include <linux/module.h>')
    old=function(memory,'snd_pcm_dma_quarantine')
    memory=replace(memory,old,replace(old,'\tget_device(device);','\t/* The permanent list lives in snd-pcm; an unsafe owner forbids module unload. */\n\t__module_get(THIS_MODULE);\n\tget_device(device);'))
    point='static int __init alsa_pcm_init(void)'
    show='''static ssize_t dma_quarantine_bytes_show(struct class *class,
			struct class_attribute *attr, char *buf)
{
	return scnprintf(buf, PAGE_SIZE, "%zu\\n", snd_pcm_dma_quarantine_bytes());
}
static CLASS_ATTR_RO(dma_quarantine_bytes);

'''
    pcm=replace(pcm,point,show+point)
    old=function(pcm,'alsa_pcm_init')
    pcm=replace(pcm,old,replace(old,'\tsnd_ctl_register_ioctl(snd_pcm_control_ioctl);','\tint ret = class_create_file(sound_class, &class_attr_dma_quarantine_bytes);\n\n\tif (ret)\n\t\treturn ret;\n\tsnd_ctl_register_ioctl(snd_pcm_control_ioctl);'))
    old=function(pcm,'alsa_pcm_exit')
    pcm=replace(pcm,old,replace(old,'\tsnd_ctl_unregister_ioctl(snd_pcm_control_ioctl);','\tclass_remove_file(sound_class, &class_attr_dma_quarantine_bytes);\n\tsnd_ctl_unregister_ioctl(snd_pcm_control_ioctl);'))
    return memory,pcm
