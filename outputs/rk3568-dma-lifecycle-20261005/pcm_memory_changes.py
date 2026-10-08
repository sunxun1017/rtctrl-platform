#!/usr/bin/env python3
"""Protected-runtime guard and true core allocation ownership quarantine."""
from source_utils import function,replace

QUARANTINE='''/* Permanent owners never retain a runtime, substream, PCM or card pointer. */
struct snd_pcm_dma_quarantine {
	struct list_head node;
	struct snd_dma_buffer saved;
	struct snd_dma_buffer *buffer;
	struct device *device;
	bool consumed;
};

static LIST_HEAD(pcm_dma_quarantine);
static DEFINE_MUTEX(pcm_dma_quarantine_lock);
static atomic_long_t pcm_dma_quarantine_bytes = ATOMIC_LONG_INIT(0);

struct snd_pcm_dma_quarantine *snd_pcm_dma_quarantine_alloc(void)
{
	struct snd_pcm_dma_quarantine *token;

	token = kzalloc(sizeof(*token), GFP_KERNEL);
	if (token)
		INIT_LIST_HEAD(&token->node);
	return token;
}
EXPORT_SYMBOL_GPL(snd_pcm_dma_quarantine_alloc);

void snd_pcm_dma_quarantine_free(struct snd_pcm_dma_quarantine *token)
{
	/* A consumed token and its allocation remain core-owned until power cycle. */
	if (token && !token->consumed)
		kfree(token);
}
EXPORT_SYMBOL_GPL(snd_pcm_dma_quarantine_free);

size_t snd_pcm_dma_quarantine_bytes(void)
{
	return atomic_long_read(&pcm_dma_quarantine_bytes);
}
EXPORT_SYMBOL_GPL(snd_pcm_dma_quarantine_bytes);

int snd_pcm_dma_quarantine_check(struct snd_pcm_substream *substream,
			       struct device *device)
{
	struct snd_pcm_runtime *runtime = substream->runtime;
	struct snd_dma_buffer *buffer;

	if (!runtime || !device)
		return -EOPNOTSUPP;
	buffer = runtime->dma_buffer_p;
	if (!buffer || !buffer->area || !buffer->bytes ||
	    buffer->dev.type != SNDRV_DMA_TYPE_DEV || buffer->private_data ||
	    buffer->dev.dev != device || device_iommu_mapped(device) ||
	    runtime->dma_area != buffer->area || runtime->dma_addr != buffer->addr ||
	    !runtime->dma_bytes || runtime->dma_bytes > buffer->bytes)
		return -EOPNOTSUPP;
	return 0;
}
EXPORT_SYMBOL_GPL(snd_pcm_dma_quarantine_check);

int snd_pcm_dma_quarantine(struct snd_pcm_substream *substream,
			   struct snd_pcm_dma_quarantine *token, struct device *device)
{
	struct snd_dma_buffer *buffer;
	struct snd_card *card = substream->pcm->card;

	if (!token || token->consumed)
		return -EINVAL;
	if (snd_pcm_dma_quarantine_check(substream, device))
		return -EOPNOTSUPP;
	buffer = substream->runtime->dma_buffer_p;
	mutex_lock(&card->memory_mutex);
	/* Refuse ownership transfer before any old owner/accounting mutation. */
	if (card->total_pcm_alloc_bytes < buffer->bytes) {
		mutex_unlock(&card->memory_mutex);
		return -EIO;
	}
	get_device(device);
	token->device = device;
	mutex_lock(&pcm_dma_quarantine_lock);
	if (buffer == &substream->dma_buffer) {
		token->saved = *buffer;
		token->buffer = &token->saved;
		/* The embedded old owner must not free or account this allocation again. */
		memset(buffer, 0, sizeof(*buffer));
	} else {
		/* Dynamic metadata itself transfers; no kfree and no copy dangling owner. */
		token->buffer = buffer;
	}
	card->total_pcm_alloc_bytes -= token->buffer->bytes;
	atomic_long_add(token->buffer->bytes, &pcm_dma_quarantine_bytes);
	snd_pcm_set_runtime_buffer(substream, NULL);
	token->consumed = true;
	list_add_tail(&token->node, &pcm_dma_quarantine);
	mutex_unlock(&pcm_dma_quarantine_lock);
	mutex_unlock(&card->memory_mutex);
	return 0;
}
EXPORT_SYMBOL_GPL(snd_pcm_dma_quarantine);

'''


def memory_ownership(source,header):
    source=replace(source,"#include <linux/slab.h>", "#include <linux/slab.h>\n#include <linux/device.h>\n#include <linux/atomic.h>")
    anchor=function(source,"do_free_pages");source=replace(source,anchor,QUARANTINE+anchor)
    old=function(source,"snd_pcm_lib_malloc_pages")
    new=replace(old,"\tstruct snd_dma_buffer *dmab = NULL;", "\tstruct snd_dma_buffer *dmab = NULL;\n\tint err;")
    new=replace(new,"\tif (snd_BUG_ON(substream->dma_buffer.dev.type ==", '''	/* Process context, before resize can release an old exposed allocation. */
	if (substream->runtime->dma_quiesce) {
		err = substream->runtime->dma_quiesce(substream);
		if (err < 0)
			return err;
	}
	if (snd_BUG_ON(substream->dma_buffer.dev.type ==''')
    source=replace(source,old,new)
    old=function(source,"snd_pcm_lib_free_pages")
    new=replace(old,"\tstruct snd_pcm_runtime *runtime;", "\tstruct snd_pcm_runtime *runtime;\n\tint err;")
    new=replace(new,"\truntime = substream->runtime;", "\truntime = substream->runtime;\n\terr = runtime->dma_quiesce ? runtime->dma_quiesce(substream) : 0;")
    new=replace(new,"\tif (runtime->dma_area == NULL)\n\t\treturn 0;", "\tif (runtime->dma_area == NULL)\n\t\treturn err;")
    new=replace(new,"\treturn 0;", "\treturn err;")
    source=replace(source,old,new)
    # Runtime creation is the actual kzalloc in snd_pcm_attach_substream.
    start=header.index("struct snd_pcm_runtime {");end=header.index("\n};",start)
    before=header[start:end]
    after=replace(before,"\tvoid *private_data;", "\tvoid *private_data;\n\t/* BSP checked DMA PCM only; allocator guards run in process context. */\n\tint (*dma_quiesce)(struct snd_pcm_substream *substream);")
    header=header[:start]+after+header[end:]
    api='''
struct snd_pcm_dma_quarantine;
struct snd_pcm_dma_quarantine *snd_pcm_dma_quarantine_alloc(void);
void snd_pcm_dma_quarantine_free(struct snd_pcm_dma_quarantine *token);
size_t snd_pcm_dma_quarantine_bytes(void);
int snd_pcm_dma_quarantine_check(struct snd_pcm_substream *substream, struct device *device);
int snd_pcm_dma_quarantine(struct snd_pcm_substream *substream,
		struct snd_pcm_dma_quarantine *token, struct device *device);
'''
    header=replace(header,"int snd_pcm_lib_malloc_pages(struct snd_pcm_substream *substream, size_t size);", "int snd_pcm_lib_malloc_pages(struct snd_pcm_substream *substream, size_t size);"+api)
    return source,header
