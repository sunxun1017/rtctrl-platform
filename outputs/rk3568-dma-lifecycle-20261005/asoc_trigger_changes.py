#!/usr/bin/env python3
"""Actual group-prefix rollback and first-error cleanup without changing public ABI."""
from source_utils import function,replace

def group_function(kind):
    if kind=="component":
        plural="components";member="component";membertype="snd_soc_component";callback="component->driver->trigger";invoke="component->driver->trigger(component, substream, cmd)";stop="component->driver->trigger(component, substream, SNDRV_PCM_TRIGGER_STOP)";has="component->driver->trigger";retwrap="soc_component_ret"
    else:
        plural="dais";member="dai";membertype="snd_soc_dai";callback="dai->driver->ops->trigger";invoke="dai->driver->ops->trigger(substream, cmd, dai)";stop="dai->driver->ops->trigger(substream, SNDRV_PCM_TRIGGER_STOP, dai)";has="dai->driver->ops && dai->driver->ops->trigger";retwrap="soc_dai_ret"
    return f'''int snd_soc_pcm_{kind}_trigger(struct snd_pcm_substream *substream,
				  int cmd)
{{
	struct snd_soc_pcm_runtime *rtd = asoc_substream_to_rtd(substream);
	struct {membertype} *{member};
	bool starting = cmd == SNDRV_PCM_TRIGGER_START ||
		cmd == SNDRV_PCM_TRIGGER_RESUME || cmd == SNDRV_PCM_TRIGGER_PAUSE_RELEASE;
	bool stopping = cmd == SNDRV_PCM_TRIGGER_STOP ||
		cmd == SNDRV_PCM_TRIGGER_SUSPEND || cmd == SNDRV_PCM_TRIGGER_PAUSE_PUSH;
	int i, j, ret, first = 0;

	for_each_rtd_{plural}(rtd, i, {member}) {{
		if (!({has}))
			continue;
		ret = {invoke};
		if (ret >= 0)
			continue;
		if (!first)
			first = {retwrap}({member}, ret);
		if (starting)
			goto rollback;
		if (!stopping)
			return first;
	}}
	return first;

rollback:
	/* The failed member may have partially executed; later members are untouched.
	 * STOP carries this substream so each callback keeps its own direction owner.
	 */
	for (j = i; j >= 0; j--) {{
		{member} = rtd->{plural}[j];
		if ({has})
			{stop};
	}}
	return first;
}}
'''

PIPELINE='''static int soc_pcm_trigger(struct snd_pcm_substream *substream, int cmd)
{
	int ret, next;

	switch (cmd) {
	case SNDRV_PCM_TRIGGER_START:
	case SNDRV_PCM_TRIGGER_RESUME:
	case SNDRV_PCM_TRIGGER_PAUSE_RELEASE:
		ret = snd_soc_link_trigger(substream, cmd);
		if (ret < 0)
			goto stop_link;
		ret = snd_soc_pcm_component_trigger(substream, cmd);
		if (ret < 0)
			goto stop_link;
		ret = snd_soc_pcm_dai_trigger(substream, cmd);
		if (ret >= 0)
			return ret;
		/* The failed group already rolled back only its attempted prefix. */
		snd_soc_pcm_component_trigger(substream, SNDRV_PCM_TRIGGER_STOP);
stop_link:
		snd_soc_link_trigger(substream, SNDRV_PCM_TRIGGER_STOP);
		return ret;
	case SNDRV_PCM_TRIGGER_STOP:
	case SNDRV_PCM_TRIGGER_SUSPEND:
	case SNDRV_PCM_TRIGGER_PAUSE_PUSH:
		ret = snd_soc_pcm_dai_trigger(substream, cmd);
		next = snd_soc_pcm_component_trigger(substream, cmd);
		if (ret >= 0 && next < 0)
			ret = next;
		next = snd_soc_link_trigger(substream, cmd);
		if (ret >= 0 && next < 0)
			ret = next;
		return ret;
	default:
		return -EINVAL;
	}
}
'''

def asoc_trigger(pcm,component,dai):
    pcm=replace(pcm,function(pcm,"soc_pcm_trigger"),PIPELINE)
    component=replace(component,function(component,"snd_soc_pcm_component_trigger"),group_function("component"))
    dai=replace(dai,function(dai,"snd_soc_pcm_dai_trigger"),group_function("dai"))
    return pcm,component,dai
