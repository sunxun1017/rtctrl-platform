/* SPDX-License-Identifier: GPL-2.0-or-later */
#define SNDRV_PCM_STATE_OPEN 0
#define SNDRV_PCM_STATE_SETUP 1
#define SNDRV_PCM_STATE_PREPARED 2
#define SNDRV_PCM_STATE_RUNNING 3
#define SNDRV_PCM_INFO_NO_PERIOD_WAKEUP 4
#define SNDRV_PCM_HW_PARAMS_NO_PERIOD_WAKEUP 4
#define SNDRV_PCM_INFO_MMAP 8
#define SNDRV_PCM_TSTAMP_NONE 0
static int native_hw_params_calls,native_detach_calls,buffer_lock;
static int native_hw_params_callback(struct snd_pcm_substream *s,struct snd_pcm_hw_params *p){(void)s;(void)p;native_hw_params_calls++;return 0;}
static int native_sync_callback(struct snd_pcm_substream *s){
#ifdef HAVE_PCM_QUIESCE
 return dmaengine_pcm_quiesce(NULL,s);
#else
 dmaengine_synchronize(substream_to_prtd(s)->dma_chan);return 0;
#endif
}
static int native_free_callback(struct snd_pcm_substream *s){return native_sync_callback(s);}
static int native_close_callback(struct snd_pcm_substream *s){return snd_dmaengine_pcm_close(s);}
static int native_trigger_callback(struct snd_pcm_substream *s,int cmd){
#ifdef HAVE_ASOC_CHAIN
 return soc_pcm_trigger(s,cmd);
#else
 return snd_dmaengine_pcm_trigger(s,cmd);
#endif
}
static inline bool snd_pcm_playback_data(struct snd_pcm_substream *s){(void)s;return true;}
static int snd_pcm_buffer_access_lock(struct snd_pcm_runtime *r){(void)r;if(buffer_lock)abort();buffer_lock++;return 0;}
static void snd_pcm_buffer_access_unlock(struct snd_pcm_runtime *r){(void)r;buffer_lock--;}
static bool is_oss_stream(struct snd_pcm_substream *s){(void)s;return false;}
static int snd_pcm_hw_refine(struct snd_pcm_substream *s,struct snd_pcm_hw_params *p){(void)s;(void)p;return 0;}
static int snd_pcm_hw_params_choose(struct snd_pcm_substream *s,struct snd_pcm_hw_params *p){(void)s;(void)p;return 0;}
static int fixup_unreferenced_params(struct snd_pcm_substream *s,struct snd_pcm_hw_params *p){(void)s;(void)p;return 0;}
static size_t params_buffer_bytes(struct snd_pcm_hw_params *p){return p->bytes;}
#define params_access(p) 0
#define params_format(p) 0
#define params_subformat(p) 0
#define params_channels(p) 2
#define params_rate(p) 48000
#define params_period_size(p) ((p)->bytes/8)
#define params_periods(p) 2
#define params_buffer_size(p) ((p)->bytes/4)
static int snd_pcm_format_physical_width(int format){(void)format;return 16;}
static void snd_pcm_timer_resolution_change(struct snd_pcm_substream *s){(void)s;}
static void snd_pcm_set_state(struct snd_pcm_substream *s,int state){s->runtime->status->state=state;}
static bool cpu_latency_qos_request_active(int *req){(void)req;return false;}
static void cpu_latency_qos_remove_request(int *req){(void)req;}
static void cpu_latency_qos_add_request(int *req,int value){(void)req;(void)value;}
static int period_to_usecs(struct snd_pcm_runtime *runtime){(void)runtime;return -1;}
static void synchronize_irq(int irq){(void)irq;}
static void snd_pcm_drop(struct snd_pcm_substream *s){snd_dmaengine_pcm_trigger(s,SNDRV_PCM_TRIGGER_STOP);}
static void snd_pcm_detach_substream(struct snd_pcm_substream *s){native_detach_calls++;if(s->runtime->dma_quiesce || s->runtime->private_data)warnings++;}
