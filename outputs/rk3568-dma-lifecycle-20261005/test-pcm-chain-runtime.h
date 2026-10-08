/* SPDX-License-Identifier: GPL-2.0-or-later */
typedef unsigned long snd_pcm_uframes_t;
typedef int snd_pcm_state_t;
struct snd_pcm_mmap_status {int state;};
struct snd_pcm_mmap_control {snd_pcm_uframes_t avail_min;};
struct snd_pcm_runtime {
 unsigned char *dma_area;dma_addr_t dma_addr;size_t dma_bytes;struct snd_dma_buffer *dma_buffer_p;
 int (*dma_quiesce)(struct snd_pcm_substream *);void *private_data;bool stop_operating;
 bool no_period_wakeup,buffer_changed;
 bool trigger_tstamp_latched;struct snd_pcm_substream *trigger_master;
 struct snd_pcm_mmap_status *status;struct snd_pcm_mmap_control *control;
 unsigned int info,access,format,subformat,channels,rate,periods,rate_num,rate_den,sample_bits,frame_bits,byte_align,min_align,tstamp_mode,period_step;
 snd_pcm_uframes_t period_size,buffer_size,start_threshold,stop_threshold,silence_threshold,silence_size,boundary;
};
struct snd_pcm_hw_params {unsigned int rmask,info,flags,rate_num,rate_den;size_t bytes;};
struct snd_pcm_ops {int (*hw_params)(struct snd_pcm_substream *,struct snd_pcm_hw_params *);int (*hw_free)(struct snd_pcm_substream *);int (*close)(struct snd_pcm_substream *);int (*sync_stop)(struct snd_pcm_substream *);int (*trigger)(struct snd_pcm_substream *,int);void *copy_user;};
