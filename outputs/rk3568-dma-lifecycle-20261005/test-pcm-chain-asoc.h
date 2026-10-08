/* SPDX-License-Identifier: GPL-2.0-or-later */
#define ENOTSUPP 524
#define EPROBE_DEFER 517
#define dev_err(...) ((void)0)
struct snd_soc_component_driver {int (*trigger)(struct snd_soc_component *,struct snd_pcm_substream *,int);};
struct snd_soc_dai;
struct snd_soc_dai_ops {int (*trigger)(struct snd_pcm_substream *,int,struct snd_soc_dai *);};
struct snd_soc_dai_driver {const struct snd_soc_dai_ops *ops;};
struct snd_soc_dai {const struct snd_soc_dai_driver *driver;struct device *dev;const char *name;int id;};
struct snd_soc_ops {int (*trigger)(struct snd_pcm_substream *,int);};
struct snd_soc_dai_link {const struct snd_soc_ops *ops;const char *name;};
struct snd_soc_pcm_runtime {struct device *dev;struct snd_soc_dai_link *dai_link;struct snd_soc_component **components;struct snd_soc_dai **dais;int num_components,num_cpus,num_codecs;};
#include "asoc-iteration-macros.h"
#define asoc_substream_to_rtd(s) ((struct snd_soc_pcm_runtime *)(s)->private_data)
#define soc_component_ret(c,r) _soc_component_ret(c,__func__,r)
#define soc_dai_ret(d,r) _soc_dai_ret(d,__func__,r)
#define soc_link_ret(rtd,r) _soc_link_ret(rtd,__func__,r)
