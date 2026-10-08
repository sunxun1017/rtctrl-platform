/* SPDX-License-Identifier: GPL-2.0-or-later */
typedef int dma_cookie_t;
typedef uint32_t u32;
#include "dmaengine-types.h"
#define SNDRV_PCM_STREAM_PLAYBACK 0
#define SNDRV_PCM_STREAM_CAPTURE 1
#include "pcm-trigger-constants.h"
#define SNDRV_PCM_INFO_PAUSE 1
#define SNDRV_PCM_HW_PARAM_PERIODS 0
#define DMA_CTRL_ACK 1
#define DMA_PREP_INTERRUPT 2
struct dma_chan;
struct dma_async_tx_descriptor {void (*callback)(void *);void *callback_param;dma_cookie_t (*tx_submit)(struct dma_async_tx_descriptor *);};
struct dma_device {
 struct device *dev;
 int (*device_synchronize_checked)(struct dma_chan *);
 void (*device_synchronize)(struct dma_chan *);
 int (*device_resume)(struct dma_chan *),(*device_pause)(struct dma_chan *),(*device_terminate_all)(struct dma_chan *);
 void (*device_issue_pending)(struct dma_chan *);
 enum dma_status (*device_tx_status)(struct dma_chan *,dma_cookie_t,struct dma_tx_state *);
 struct dma_async_tx_descriptor *(*device_prep_dma_cyclic)(struct dma_chan *,dma_addr_t,size_t,size_t,enum dma_transfer_direction,unsigned long);
};
struct dma_chan {struct dma_device *device;};
static atomic_int checked_calls;
static int void_sync_calls,prep_calls,submit_calls,issue_calls,status_calls,pause_calls,resume_calls,terminate_calls,release_calls,period_calls;
static int checked_error,submit_cookie,pause_error,resume_error,terminate_error,constraint_error;
static bool prep_null,go_error;
static struct dma_async_tx_descriptor desc;
static _Thread_local bool pause_prep;
static void dma_boundary_pause(void);
static int fake_checked(struct dma_chan *chan){(void)chan;checked_calls++;might_sleep();return checked_error;}
static void fake_synchronize(struct dma_chan *chan){(void)chan;void_sync_calls++;might_sleep();}
static struct dma_async_tx_descriptor *fake_prep(struct dma_chan *chan,dma_addr_t addr,size_t len,size_t period,enum dma_transfer_direction direction,unsigned long flags){(void)chan;(void)addr;(void)len;(void)period;(void)direction;(void)flags;prep_calls++;if(pause_prep){pause_prep=false;dma_boundary_pause();}return prep_null?NULL:&desc;}
static dma_cookie_t fake_submit(struct dma_async_tx_descriptor *tx){(void)tx;submit_calls++;return submit_cookie;}
static void fake_issue(struct dma_chan *chan){(void)chan;issue_calls++;}
static enum dma_status fake_status(struct dma_chan *chan,dma_cookie_t cookie,struct dma_tx_state *state){(void)chan;(void)cookie;(void)state;status_calls++;return go_error?DMA_ERROR:DMA_IN_PROGRESS;}
static int fake_pause(struct dma_chan *chan){(void)chan;pause_calls++;return pause_error;}
static int fake_resume(struct dma_chan *chan){(void)chan;resume_calls++;return resume_error;}
static int fake_terminate(struct dma_chan *chan){(void)chan;terminate_calls++;return terminate_error;}
static inline void dma_release_channel(struct dma_chan *chan){(void)chan;release_calls++;}
static inline size_t snd_pcm_lib_buffer_bytes(struct snd_pcm_substream *s){return s->runtime->dma_bytes;}
static inline size_t snd_pcm_lib_period_bytes(struct snd_pcm_substream *s){return s->runtime->dma_bytes/2;}
static inline int snd_pcm_hw_constraint_integer(struct snd_pcm_runtime *r,int p){(void)r;(void)p;return constraint_error;}
static inline void snd_pcm_stream_lock_irq(struct snd_pcm_substream *s){(void)s;spin_depth++;}
static inline void snd_pcm_stream_unlock_irq(struct snd_pcm_substream *s){(void)s;spin_depth--;}
static inline void snd_pcm_period_elapsed(struct snd_pcm_substream *s){(void)s;period_calls++;}
struct snd_soc_component_driver;
struct snd_soc_component {int value;const struct snd_soc_component_driver *driver;struct device *dev;const char *name;int id;};
int snd_dmaengine_pcm_quiesce(struct snd_pcm_substream *substream);
