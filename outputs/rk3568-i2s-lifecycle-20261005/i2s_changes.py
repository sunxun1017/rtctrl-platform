"""Review-only current-board additions; untouched legacy paths retain their text."""
from source_utils import replace


ERROR_HELPERS = r'''
/* Protected by lock; never cleared by STOP, HW_FREE, close or PM retry. */
static int i2s_checked_error_locked(struct rk_i2s_tdm_dev *i2s_tdm, int ret)
{
	if (ret < 0 && !i2s_tdm->runtime_error)
		i2s_tdm->runtime_error = ret;
	return ret;
}

static int i2s_checked_gate_locked(struct rk_i2s_tdm_dev *i2s_tdm)
{
	if (i2s_tdm->runtime_error)
		return i2s_tdm->runtime_error;
	if (i2s_tdm->shutting_down)
		return -ESHUTDOWN;
	if (i2s_tdm->configuring || i2s_tdm->started)
		return -EBUSY;
	return 0;
}
'''

FORMAT_HELPER = r'''
static int i2s_checked_set_fmt(struct rk_i2s_tdm_dev *i2s_tdm,
			       struct device *dev, unsigned int fmt)
{
	unsigned long flags;
	int ret, put_ret;

	/* This checked board path is the locked ordinary I2S master profile. */
	if (fmt != (SND_SOC_DAIFMT_CBS_CFS | SND_SOC_DAIFMT_NB_NF |
		    SND_SOC_DAIFMT_I2S))
		return -EINVAL;
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	ret = i2s_checked_gate_locked(i2s_tdm);
	if (!ret)
		i2s_tdm->configuring = true;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	if (ret)
		return ret;

	ret = pm_runtime_get_sync(dev);
	if (ret < 0) {
		pm_runtime_put_noidle(dev);
		goto out;
	}
	ret = regmap_update_bits(i2s_tdm->regmap, I2S_CKR,
				 I2S_CKR_MSS_MASK, I2S_CKR_MSS_MASTER);
	if (ret)
		goto put;
	ret = regmap_update_bits(i2s_tdm->regmap, I2S_CKR,
				 I2S_CKR_CKP_MASK | I2S_CKR_TLP_MASK |
				 I2S_CKR_RLP_MASK, I2S_CKR_CKP_NORMAL |
				 I2S_CKR_TLP_NORMAL | I2S_CKR_RLP_NORMAL);
	if (ret)
		goto put;
	ret = regmap_update_bits(i2s_tdm->regmap, I2S_TXCR,
				 I2S_TXCR_IBM_MASK | I2S_TXCR_TFS_MASK |
				 I2S_TXCR_PBM_MASK, I2S_TXCR_IBM_NORMAL);
	if (ret)
		goto put;
	ret = regmap_update_bits(i2s_tdm->regmap, I2S_RXCR,
				 I2S_RXCR_IBM_MASK | I2S_RXCR_TFS_MASK |
				 I2S_RXCR_PBM_MASK, I2S_RXCR_IBM_NORMAL);
	if (!ret)
		i2s_tdm->is_master_mode = true;
put:
	put_ret = pm_runtime_put(dev);
	if (!ret && put_ret < 0)
		ret = put_ret;
out:
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	if (!ret && i2s_tdm->runtime_error)
		ret = i2s_tdm->runtime_error;
	i2s_checked_error_locked(i2s_tdm, ret);
	i2s_tdm->configuring = false;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}
'''

PARAM_HELPERS = r'''
static int i2s_checked_params_dirty(struct snd_pcm_substream *substream,
				  struct rk_i2s_tdm_dev *i2s_tdm,
				  unsigned int div_bclk,
				  unsigned int div_lrck,
				  unsigned int fmt, bool *dirty)
{
	unsigned int val;
	int ret;

	*dirty = false;
	ret = regmap_read(i2s_tdm->regmap, I2S_CLKDIV, &val);
	if (ret)
		return ret;
	*dirty |= (((val & I2S_CLKDIV_TXM_MASK) >> I2S_CLKDIV_TXM_SHIFT) + 1 != div_bclk);
	ret = regmap_read(i2s_tdm->regmap, I2S_CKR, &val);
	if (ret)
		return ret;
	*dirty |= (((val & I2S_CKR_TSD_MASK) >> I2S_CKR_TSD_SHIFT) + 1 != div_lrck);
	ret = regmap_read(i2s_tdm->regmap,
			  substream->stream == SNDRV_PCM_STREAM_PLAYBACK ?
			  I2S_TXCR : I2S_RXCR, &val);
	if (ret)
		return ret;
	*dirty |= ((val & (I2S_TXCR_VDW_MASK | I2S_TXCR_CSR_MASK)) != fmt);
	return 0;
}

static int i2s_checked_params_trcm(struct snd_pcm_substream *substream,
				 struct rk_i2s_tdm_dev *i2s_tdm,
				 unsigned int div_bclk,
				 unsigned int div_lrck, unsigned int fmt)
{
	int ret;

	ret = regmap_update_bits(i2s_tdm->regmap, I2S_CLKDIV,
				 I2S_CLKDIV_TXM_MASK | I2S_CLKDIV_RXM_MASK,
				 I2S_CLKDIV_TXM(div_bclk) | I2S_CLKDIV_RXM(div_bclk));
	if (ret)
		return ret;
	ret = regmap_update_bits(i2s_tdm->regmap, I2S_CKR,
				 I2S_CKR_TSD_MASK | I2S_CKR_RSD_MASK,
				 I2S_CKR_TSD(div_lrck) | I2S_CKR_RSD(div_lrck));
	if (ret)
		return ret;
	return regmap_update_bits(i2s_tdm->regmap,
				  substream->stream == SNDRV_PCM_STREAM_PLAYBACK ?
				  I2S_TXCR : I2S_RXCR,
				  I2S_TXCR_VDW_MASK | I2S_TXCR_CSR_MASK, fmt);
}

static int i2s_checked_hw_params(struct snd_pcm_substream *substream,
			       struct snd_pcm_hw_params *params,
			       struct snd_soc_dai *dai)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	struct snd_dmaengine_dai_dma_data *dma_data;
	struct clk *mclk;
	unsigned int fmt, div_bclk, div_lrck;
	unsigned int channels = params_channels(params);
	u64 lrck_rate, bclk_rate;
	unsigned long flags;
	bool dirty;
	int ret;

	if (substream->stream != SNDRV_PCM_STREAM_PLAYBACK &&
	    substream->stream != SNDRV_PCM_STREAM_CAPTURE)
		return -EINVAL;
	if (!params_rate(params) || !i2s_tdm->lrck_ratio ||
	    (channels != 2 && channels != 4 && channels != 6 && channels != 8))
		return -EINVAL;
	switch (params_format(params)) {
	case SNDRV_PCM_FORMAT_S8:
		fmt = I2S_TXCR_VDW(8);
		break;
	case SNDRV_PCM_FORMAT_S16_LE:
		fmt = I2S_TXCR_VDW(16);
		break;
	case SNDRV_PCM_FORMAT_S20_3LE:
		fmt = I2S_TXCR_VDW(20);
		break;
	case SNDRV_PCM_FORMAT_S24_LE:
		fmt = I2S_TXCR_VDW(24);
		break;
	case SNDRV_PCM_FORMAT_S32_LE:
	case SNDRV_PCM_FORMAT_IEC958_SUBFRAME_LE:
		fmt = I2S_TXCR_VDW(32);
		break;
	default:
		return -EINVAL;
	}
	lrck_rate = (u64)params_rate(params) * i2s_tdm->lrck_ratio;
	bclk_rate = lrck_rate * i2s_tdm->bclk_fs;
	if (!bclk_rate || bclk_rate > 0xffffffffULL || lrck_rate > 0xffffffffULL)
		return -EINVAL;

	/* Admission spans sleeping clock operations without holding spinlock. */
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	ret = i2s_checked_gate_locked(i2s_tdm);
	if (!ret)
		i2s_tdm->configuring = true;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	if (ret)
		return ret;
	ret = rockchip_i2s_tdm_set_mclk(i2s_tdm, substream, &mclk);
	if (ret)
		goto out;
	div_bclk = DIV_ROUND_CLOSEST(clk_get_rate(mclk), (unsigned int)bclk_rate);
	div_lrck = (unsigned int)(bclk_rate / lrck_rate);
	if (!div_bclk || div_bclk > 256 || !div_lrck || div_lrck > 256) {
		ret = -EINVAL;
		goto out;
	}
	ret = rockchip_i2s_tdm_params_channels(substream, params, dai);
	if (ret < 0)
		goto out;
	fmt |= ret;
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	if (i2s_tdm->runtime_error)
		ret = i2s_tdm->runtime_error;
	else if (i2s_tdm->shutting_down)
		ret = -ESHUTDOWN;
	else
		ret = i2s_checked_params_dirty(substream, i2s_tdm, div_bclk, div_lrck, fmt, &dirty);
	if (!ret && dirty)
		ret = i2s_checked_params_trcm(substream, i2s_tdm, div_bclk, div_lrck, fmt);
	if (!ret) {
		dma_data = snd_soc_dai_get_dma_data(dai, substream);
		dma_data->maxburst = MAXBURST_PER_FIFO * channels / 2;
	}
	i2s_checked_error_locked(i2s_tdm, ret);
	i2s_tdm->configuring = false;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
out:
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	i2s_checked_error_locked(i2s_tdm, ret);
	i2s_tdm->configuring = false;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}
'''


def parameters(source):
    source = replace(source, "\tbool is_master_mode;", "\t/* Only the locked RK3568 I2S1 ordinary master path opts in. */\n\tbool checked_lifecycle;\n\tbool configuring;\n\tbool shutting_down;\n\tunsigned int started;\n\tint runtime_error;\n\tbool is_master_mode;")
    source = replace(source, "static inline struct rk_i2s_tdm_dev *to_info", ERROR_HELPERS + "\nstatic inline struct rk_i2s_tdm_dev *to_info")
    source = replace(source, "static int rockchip_i2s_tdm_set_fmt(", FORMAT_HELPER + "\nstatic int rockchip_i2s_tdm_set_fmt(")
    source = replace(source, "\tbool is_tdm = i2s_tdm->tdm_mode;\n\n\tpm_runtime_get_sync", "\tbool is_tdm = i2s_tdm->tdm_mode;\n\n\tif (i2s_tdm->checked_lifecycle)\n\t\treturn i2s_checked_set_fmt(i2s_tdm, cpu_dai->dev, fmt);\n\n\tpm_runtime_get_sync")
    source = replace(source, "\tregmap_read(i2s_tdm->regmap, reg_fmt, &fmt);", "\tret = regmap_read(i2s_tdm->regmap, reg_fmt, &fmt);\n\tif (i2s_tdm->checked_lifecycle && ret < 0)\n\t\treturn ret;")
    source = replace(source, "static int rockchip_i2s_tdm_hw_params(", PARAM_HELPERS + "\nstatic int rockchip_i2s_tdm_hw_params(")
    source = replace(source, "\tunsigned int mclk_rate, bclk_rate, lrck_rate, div_bclk = 4, div_lrck = 64;", "\tunsigned int mclk_rate, bclk_rate, lrck_rate, div_bclk = 4, div_lrck = 64;\n\n\tif (i2s_tdm->checked_lifecycle)\n\t\treturn i2s_checked_hw_params(substream, params, dai);")
    return source
