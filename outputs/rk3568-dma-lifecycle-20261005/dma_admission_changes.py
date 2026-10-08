#!/usr/bin/env python3
"""DMA registry initializes BSP fields and serializes final provider admission."""
from source_utils import function,replace

QUIESCE='''/* Provider remove only: success closes all future core client acquisitions. */
int dmaengine_device_quiesce(struct dma_device *device)
{
	struct dma_chan *chan;
	int ret = 0;

	mutex_lock(&dma_list_mutex);
	list_for_each_entry(chan, &device->channels, device_node) {
		if (chan->client_count) {
			ret = -EBUSY;
			break;
		}
	}
	if (!ret)
		device->lifecycle_closing = true;
	mutex_unlock(&dma_list_mutex);
	return ret;
}
EXPORT_SYMBOL_GPL(dmaengine_device_quiesce);

'''


def admission(source,header,core):
    # Explicit initialization occurs inside registration before any publication.
    header=replace(header,"\tint (*device_synchronize_checked)(struct dma_chan *chan);", "\tint (*device_synchronize_checked)(struct dma_chan *chan);\n\t/* BSP terminal provider removal gate; protected by DMA core mutex. */\n\tbool lifecycle_closing;")
    header=replace(header,"int dma_async_device_register(struct dma_device *device);", '''int dma_async_device_register(struct dma_device *device);
int dma_async_device_register_checked(struct dma_device *device,
		int (*checked)(struct dma_chan *chan));
/* Terminal provider remove admission; no successful re-registration before unregister. */
int dmaengine_device_quiesce(struct dma_device *device);''')
    old=function(core,"dma_chan_get")
    new=replace(old,"\t/* The channel is already in use, update client count */", '''	lockdep_assert_held(&dma_list_mutex);
	/* ESHUTDOWN avoids the ENODEV/module-removal list deletion path. */
	if (chan->device->lifecycle_closing)
		return -ESHUTDOWN;

	/* The channel is already in use, update client count */''')
    core=replace(core,old,QUIESCE+new)
    old=function(core,"dma_async_device_register")
    new=replace(old,"int dma_async_device_register(struct dma_device *device)", "static int __dma_async_device_register(struct dma_device *device,\n\t\tint (*checked)(struct dma_chan *chan))")
    new=replace(new,"\t/* validate device routines */", '''	/* Initialize new fields for every provider, including nonzero allocations. */
	device->lifecycle_closing = false;
	device->device_synchronize_checked = checked;

	/* validate device routines */''')
    core=replace(core,old,new+'''

int dma_async_device_register(struct dma_device *device)
{
	return __dma_async_device_register(device, NULL);
}

int dma_async_device_register_checked(struct dma_device *device,
		int (*checked)(struct dma_chan *chan))
{
	if (!checked)
		return -EINVAL;
	return __dma_async_device_register(device, checked);
}
EXPORT_SYMBOL_GPL(dma_async_device_register_checked);''')
    source=replace(source,"ret = dma_async_device_register(pd);", "ret = dma_async_device_register_checked(pd, pl330_synchronize_checked);")
    # Registry is now the single initialization/publish boundary.
    source=replace(source,"\n\tpd->device_synchronize_checked = pl330_synchronize_checked;", "")
    return source,header,core
