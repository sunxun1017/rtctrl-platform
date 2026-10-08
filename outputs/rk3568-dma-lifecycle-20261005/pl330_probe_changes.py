"""Probe/IRQ publication and complete storage ownership increment on rejected v5."""
from source_utils import function

def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('expected exact probe source anchor: ' + old[:90])
    return text.replace(old, new, 1)

def apply(text):
    text = replace(text, '\tstruct list_head desc_pool;', '\tstruct list_head desc_pool;\n\tstruct list_head desc_blocks;')
    text = replace(text, '\tbool removing;', '\tbool removing;\n\tbool irq_ready;\n\tunsigned int irqs_registered;')
    point = function(text, 'is_manager')
    # Blocks remain owned by the controller even while descriptors leave its pool.
    block = '''struct pl330_desc_block {
	struct list_head node;
	struct dma_pl330_desc *descs;
};

'''
    text = replace(text, point, block + 'static void __noreturn pl330_failstop(struct pl330_dmac *pl330,\n\t\t\t\t\t const char *reason);\n\n' + point)
    old = function(text, 'add_desc')
    new = old.replace('static int add_desc(struct list_head *pool, spinlock_t *lock,',
                      'static int add_desc(struct pl330_dmac *pl330,\n\t\t    struct list_head *pool, spinlock_t *lock,', 1)
    new = replace(new, '\tstruct dma_pl330_desc *desc;', '\tstruct dma_pl330_desc *desc;\n\tstruct pl330_desc_block *block;')
    new = replace(new, '\tdesc = kcalloc(count, sizeof(*desc), flg);\n\tif (!desc)\n\t\treturn 0;', '''	block = kzalloc(sizeof(*block), flg);
	if (!block)
		return 0;
	desc = kcalloc(count, sizeof(*desc), flg);
	if (!desc) {
		kfree(block);
		return 0;
	}
	block->descs = desc;
	/* A preparation lease protects this publication until checkout finishes. */
	spin_lock_irqsave(&pl330->pool_lock, flags);
	list_add_tail(&block->node, &pl330->desc_blocks);
	spin_unlock_irqrestore(&pl330->pool_lock, flags);''')
    text = replace(text, old, new)
    text = replace(text, 'add_desc(&pool, &lock, GFP_ATOMIC, 1)', 'add_desc(pl330, &pool, &lock, GFP_ATOMIC, 1)')
    text = replace(text, 'add_desc(&pl330->desc_pool, &pl330->pool_lock,', 'add_desc(pl330, &pl330->desc_pool, &pl330->pool_lock,')
    old = function(text, 'pl330_del')
    new = replace(old, '{\n\tpl330->state', '{\n\tstruct pl330_desc_block *block, *next;\n\tLIST_HEAD(blocks);\n\tunsigned long flags;\n\n\tif (atomic_read(&pl330->owned_descs))\n\t\tpl330_failstop(pl330, "destroy has a descriptor owner");\n\tpl330->state')
    new = replace(new, '\t\tpl330->mcode_bus, DMA_ATTR_PRIVILEGED);', '''		pl330->mcode_bus, DMA_ATTR_PRIVILEGED);
	/* All clients and software/hardware owners have been drained by the caller. */
	spin_lock_irqsave(&pl330->pool_lock, flags);
	INIT_LIST_HEAD(&pl330->desc_pool);
	list_splice_tail_init(&pl330->desc_blocks, &blocks);
	spin_unlock_irqrestore(&pl330->pool_lock, flags);
	list_for_each_entry_safe(block, next, &blocks, node) {
		list_del(&block->node);
		kfree(block->descs);
		kfree(block);
	}
	kfree(pl330->peripherals);
	pl330->peripherals = NULL;''')
    text = replace(text, old, new)
    old = function(text, 'pl330_irq_handler')
    new = replace(old, '\tif (READ_ONCE(pl330->removing)', '\tif (!READ_ONCE(pl330->irq_ready) || READ_ONCE(pl330->removing)')
    text = replace(text, old, new)
    old = function(text, 'pl330_add')
    new = replace(old, '\tspin_lock_init(&pl330->lock);\n\n\tINIT_LIST_HEAD(&pl330->req_done);\n\n', '')
    text = replace(text, old, new)
    # The one preallocated timer bounds a publication join; no owner is freed in it.
    text = replace(text, 'pl330_failstop(pl330, "sysfs reader drain deadline");', 'pl330_failstop(pl330, "sysfs or IRQ publication drain deadline");')
    helper = '''/* Admission is already closed; the owner remains alive through free_irq's join. */
static void pl330_irqs_remove(struct pl330_dmac *pl330)
{
	struct amba_device *adev = to_amba_device(pl330->ddma.dev);

	mod_timer(&pl330->reader_timer, jiffies + msecs_to_jiffies(500));
	while (pl330->irqs_registered) {
		unsigned int index = --pl330->irqs_registered;

		devm_free_irq(&adev->dev, adev->irq[index], pl330);
	}
	del_timer_sync(&pl330->reader_timer);
}

/* Probe still owns its successful temporary PM lease and AMBA's original lease. */
static void pl330_probe_cleanup(struct pl330_dmac *pl330, bool registered)
{
	struct dma_pl330_chan *pch, *next;
	unsigned long flags;
	int i;

	pl330_reader_remove(pl330);
	if (registered && dmaengine_device_quiesce(&pl330->ddma))
		pl330_failstop(pl330, "failed probe has a live published client");
	spin_lock_irqsave(&pl330->lock, flags);
	pl330->irq_ready = false;
	pl330->removing = true;
	pl330->state = DYING;
	for (i = 0; i < pl330->pcfg.num_chan; i++)
		pl330->channels[i].accept_callbacks = false;
	spin_unlock_irqrestore(&pl330->lock, flags);
	list_for_each_entry(pch, &pl330->ddma.channels, chan.device_node) {
		if (pch->thread)
			pl330_free_chan_resources(&pch->chan);
		else if (atomic_read(&pch->prepared_descs) || !pl330_software_drained(pch))
			pl330_failstop(pl330, "failed probe has a software descriptor owner");
	}
	pl330_irqs_remove(pl330);
	if (!wait_event_timeout(pl330->drain_wait, pl330_controller_drained(pl330),
				msecs_to_jiffies(500)))
		pl330_failstop(pl330, "failed probe controller software deadline");
	if (pl330_controller_stop_proof(pl330))
		pl330_failstop(pl330, "failed probe manager or channel stop proof");
	tasklet_kill(&pl330->tasks);
	if (registered) {
		mod_timer(&pl330->reader_timer, jiffies + msecs_to_jiffies(500));
		dma_async_device_unregister(&pl330->ddma);
		del_timer_sync(&pl330->reader_timer);
	}
	list_for_each_entry_safe(pch, next, &pl330->ddma.channels, chan.device_node)
		list_del(&pch->chan.device_node);
	pl330_del(pl330);
}

'''
    point = 'static int\npl330_probe(struct amba_device *adev, const struct amba_id *id)'
    text = replace(text, point, helper + point)
    old = function(text, 'pl330_probe')
    new = replace(old, '\tstruct dma_pl330_chan *pch, *_p;', '\tstruct dma_pl330_chan *pch;\n\tunsigned long flags;')
    new = replace(new, '\tinit_waitqueue_head(&pl330->drain_wait);', '''	init_waitqueue_head(&pl330->drain_wait);
	atomic_set(&pl330->irq_users, 0);
	spin_lock_init(&pl330->lock);
	INIT_LIST_HEAD(&pl330->req_done);
	INIT_LIST_HEAD(&pl330->desc_pool);
	INIT_LIST_HEAD(&pl330->desc_blocks);
	spin_lock_init(&pl330->pool_lock);
	INIT_LIST_HEAD(&pl330->ddma.channels);''')
    new = replace(new, '\t\treturn dev_err_probe(&adev->dev, PTR_ERR(pl330->rstc_ocp),\n\t\t\t\t     "Failed to get OCP reset!\\n");', '\t\tret = dev_err_probe(&adev->dev, PTR_ERR(pl330->rstc_ocp),\n\t\t\t\t    "Failed to get OCP reset!\\n");\n\t\tpl330->rstc_ocp = NULL;\n\t\tgoto probe_err_reset;')
    new = replace(new, '\t\t\tdev_err(&adev->dev, "Couldn\'t deassert the device from OCP reset!\\n");\n\t\t\treturn ret;', '\t\t\tdev_err(&adev->dev, "Couldn\'t deassert the device from OCP reset!\\n");\n\t\t\tgoto probe_err_reset;')
    start = new.index('\tfor (i = 0; i < AMBA_NR_IRQS; i++) {')
    end = new.index('\n\tpcfg = &pl330->pcfg;', start)
    irq_request = new[start:end]
    irq_request = replace(irq_request, '\t\t\tif (ret)\n\t\t\t\treturn ret;', '\t\t\tif (ret)\n\t\t\t\tgoto probe_err3;\n\t\t\tpl330->irqs_registered++;')
    new = new[:start] + '''	/* Own a successful local lease before the first controller MMIO. */
	ret = pm_runtime_get_sync(&adev->dev);
	if (ret < 0) {
		pm_runtime_put_noidle(&adev->dev);
		goto probe_err_reset;
	}
''' + new[end:]
    new = replace(new, '\tret = pl330_add(pl330);\n\tif (ret)\n\t\treturn ret;', '\tret = pl330_add(pl330);\n\tif (ret)\n\t\tgoto probe_err_pm;')
    new = replace(new, '\tINIT_LIST_HEAD(&pl330->desc_pool);\n\tspin_lock_init(&pl330->pool_lock);\n\n\t/* Create', '\t/* Create')
    new = replace(new, '\tINIT_LIST_HEAD(&pd->channels);\n\n', '')
    new = replace(new, '\t\tgoto probe_err2;', '\t\tgoto probe_err3;')
    point = '\tret = device_create_file(&adev->dev, &dev_attr_rk3568_lifecycle_state);'
    new = replace(new, point, '''	ret = dma_set_max_seg_size(&adev->dev, 1900800);
	if (ret)
		goto probe_err3;
	/* Mask/clear pending level events and prove every hardware thread first. */
	if (pl330_controller_stop_proof(pl330))
		pl330_failstop(pl330, "initial probe manager or channel stop proof");
	spin_lock_irqsave(&pl330->lock, flags);
	pl330->irq_ready = true;
	spin_unlock_irqrestore(&pl330->lock, flags);
''' + irq_request + '''
	spin_lock_irqsave(&pl330->lock, flags);
	ret = pl330->lifecycle_error;
	spin_unlock_irqrestore(&pl330->lock, flags);
	if (ret)
		pl330_failstop(pl330, "pending probe IRQ fault before DMA publication");
''' + point)
    new = replace(new, '\t\t\t"unable to register DMA to the generic DT DMA helpers\\n");\n\t\t}', '\t\t\t"unable to register DMA to the generic DT DMA helpers\\n");\n\t\t\tgoto probe_err_registered;\n\t\t}')
    start = new.index('\n\t/*\n\t * This is the limit for transfers')
    end = new.index('\n\tinit_pl330_debugfs(pl330);', start)
    new = new[:start] + '\n' + new[end:]
    new = replace(new, '\tpm_runtime_mark_last_busy(&adev->dev);\n\tpm_runtime_put_autosuspend(&adev->dev);', '\tpm_runtime_put_noidle(&adev->dev); /* local probe lease */\n\tpm_runtime_mark_last_busy(&adev->dev);\n\tpm_runtime_put_autosuspend(&adev->dev); /* AMBA probe lease */')
    start = new.index('probe_err3:\n')
    new = new[:start] + '''probe_err_registered:
	pl330_probe_cleanup(pl330, true);
	goto probe_err_pm;
probe_err3:
	pl330_probe_cleanup(pl330, false);
probe_err_pm:
	pm_runtime_put_noidle(&adev->dev);
probe_err_reset:
	if (pl330->rstc_ocp)
		reset_control_assert(pl330->rstc_ocp);
	if (pl330->rstc)
		reset_control_assert(pl330->rstc);
	return ret;
}'''
    text = replace(text, old, new)
    old = function(text, 'pl330_remove')
    new = replace(old, '\tpl330->removing = true;', '\tpl330->irq_ready = false;\n\tpl330->removing = true;')
    new = replace(new, '\tfor (i = 0; i < AMBA_NR_IRQS; i++)\n\t\tif (adev->irq[i])\n\t\t\tdevm_free_irq(&adev->dev, adev->irq[i], pl330);', '\tpl330_irqs_remove(pl330);')
    new = replace(new, '\tdma_async_device_unregister(&pl330->ddma);', '\tmod_timer(&pl330->reader_timer, jiffies + msecs_to_jiffies(500));\n\tdma_async_device_unregister(&pl330->ddma);\n\tdel_timer_sync(&pl330->reader_timer);')
    text = replace(text, old, new)
    return text
