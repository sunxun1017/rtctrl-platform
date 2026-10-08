"""Current-board single-direction trigger chain; no sleeping work under lock."""
from source_utils import replace


TRIGGER_HELPERS = r'''
static int i2s_checked_first_error(int first, int next)
{
	return first ? first : next;
}

static int i2s_checked_clear_locked(struct rk_i2s_tdm_dev *i2s_tdm)
{
	unsigned int clr = I2S_CLR_TXC | I2S_CLR_RXC;
	unsigned int val;
	int ret;

	ret = regmap_write_bits(i2s_tdm->regmap, I2S_CLR, clr, clr);
	if (ret)
		return ret;
	ret = regmap_read_poll_timeout_atomic(i2s_tdm->regmap, I2S_CLR, val,
					      !(val & clr), 10, 100);
	if (ret != -ETIMEDOUT)
		return ret;
	ret = regmap_write_bits(i2s_tdm->regmap, I2S_CLR, clr, clr);
	if (ret)
		return ret;
	/* RK3568 has no mapped sync reset here; no reset can certify clear. */
	return regmap_read_poll_timeout_atomic(i2s_tdm->regmap, I2S_CLR, val,
					       !(val & clr), 10, 100);
}

static int i2s_checked_irq_locked(struct rk_i2s_tdm_dev *i2s_tdm,
				  int stream, bool en)
{
	unsigned int ack, mask, value;
	int ret, next;

	if (stream == SNDRV_PCM_STREAM_PLAYBACK) {
		ack = I2S_INTCR_TXUIC;
		mask = I2S_INTCR_TXUIE_MASK;
		value = I2S_INTCR_TXUIE(en);
	} else {
		ack = I2S_INTCR_RXOIC;
		mask = I2S_INTCR_RXOIE_MASK;
		value = I2S_INTCR_RXOIE(en);
	}
	if (en) {
		ret = regmap_write_bits(i2s_tdm->regmap, I2S_INTCR, ack, ack);
		if (ret)
			return ret;
		return regmap_write_bits(i2s_tdm->regmap, I2S_INTCR, mask, value);
	}
	/* Disable and acknowledge independently, even after the first failure. */
	ret = regmap_write_bits(i2s_tdm->regmap, I2S_INTCR, mask, 0);
	next = regmap_write_bits(i2s_tdm->regmap, I2S_INTCR, ack, ack);
	return i2s_checked_first_error(ret, next);
}

static int i2s_checked_dma_locked(struct rk_i2s_tdm_dev *i2s_tdm,
				  int stream, bool en)
{
	unsigned int mask, value;
	int ret = 0, next;

	if (!en)
		ret = i2s_checked_irq_locked(i2s_tdm, stream, false);
	if (stream == SNDRV_PCM_STREAM_PLAYBACK) {
		mask = I2S_DMACR_TDE_MASK;
		value = I2S_DMACR_TDE(en);
	} else {
		mask = I2S_DMACR_RDE_MASK;
		value = I2S_DMACR_RDE(en);
	}
	next = regmap_write_bits(i2s_tdm->regmap, I2S_DMACR, mask, value);
	ret = i2s_checked_first_error(ret, next);
	if (en && !ret) {
		if (stream == SNDRV_PCM_STREAM_PLAYBACK)
			udelay(1);
		ret = i2s_checked_irq_locked(i2s_tdm, stream, true);
	}
	return ret;
}

static int i2s_checked_stop_locked(struct rk_i2s_tdm_dev *i2s_tdm,
				   int stream, bool force)
{
	unsigned int bit = BIT(stream);
	int ret, next;

	if (!(i2s_tdm->started & bit) && !force)
		return 0;
	if (i2s_tdm->started & ~bit)
		return -EBUSY;
	ret = i2s_checked_dma_locked(i2s_tdm, stream, false);
	/* FLAT cache is updated before failed MMIO. Always force the STOP write. */
	next = regmap_write_bits(i2s_tdm->regmap, I2S_XFER,
				 I2S_XFER_TXS_MASK | I2S_XFER_RXS_MASK,
				 I2S_XFER_TXS_STOP | I2S_XFER_RXS_STOP);
	ret = i2s_checked_first_error(ret, next);
	udelay(150);
	next = i2s_checked_clear_locked(i2s_tdm);
	ret = i2s_checked_first_error(ret, next);
	if (!ret) {
		i2s_tdm->started &= ~bit;
		i2s_tdm->stop_proven = true;
	} else {
		i2s_tdm->stop_proven = false;
	}
	i2s_checked_error_locked(i2s_tdm, ret);
	return ret;
}

static int i2s_checked_start_locked(struct rk_i2s_tdm_dev *i2s_tdm, int stream)
{
	unsigned int bit = BIT(stream);
	int ret;

	if (i2s_tdm->runtime_error)
		return i2s_tdm->runtime_error;
	if (i2s_tdm->shutting_down)
		return -ESHUTDOWN;
	if (i2s_tdm->configuring)
		return -EBUSY;
	if (i2s_tdm->started & bit)
		return 0;
	if (i2s_tdm->started)
		return -EBUSY;
	i2s_tdm->stop_proven = false;
	ret = i2s_checked_dma_locked(i2s_tdm, stream, true);
	if (!ret)
		ret = regmap_write_bits(i2s_tdm->regmap, I2S_XFER,
					 I2S_XFER_TXS_MASK | I2S_XFER_RXS_MASK,
					 I2S_XFER_TXS_START | I2S_XFER_RXS_START);
	if (ret) {
		i2s_checked_error_locked(i2s_tdm, ret);
		/* Keep the START errno; STOP still attempts every independent stage. */
		i2s_checked_stop_locked(i2s_tdm, stream, true);
		return ret;
	}
	i2s_tdm->started = bit;
	return 0;
}

static int i2s_checked_trigger(struct rk_i2s_tdm_dev *i2s_tdm, int stream, int cmd)
{
	unsigned long flags;
	int ret;

	if (stream != SNDRV_PCM_STREAM_PLAYBACK && stream != SNDRV_PCM_STREAM_CAPTURE)
		return -EINVAL;
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	switch (cmd) {
	case SNDRV_PCM_TRIGGER_START:
	case SNDRV_PCM_TRIGGER_RESUME:
	case SNDRV_PCM_TRIGGER_PAUSE_RELEASE:
		ret = i2s_checked_start_locked(i2s_tdm, stream);
		break;
	case SNDRV_PCM_TRIGGER_STOP:
	case SNDRV_PCM_TRIGGER_SUSPEND:
	case SNDRV_PCM_TRIGGER_PAUSE_PUSH:
		ret = i2s_checked_stop_locked(i2s_tdm, stream, false);
		break;
	default:
		ret = -EINVAL;
		break;
	}
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}
'''


def trigger(source):
    source = replace(source, "\tbool configuring;", "\tbool configuring;\n\tbool stop_proven;")
    source = replace(source, "static inline struct rk_i2s_tdm_dev *to_info", TRIGGER_HELPERS + "\nstatic inline struct rk_i2s_tdm_dev *to_info")
    source = replace(source, "\tint ret = 0;\n\n\tswitch (cmd) {", "\tint ret = 0;\n\n\tif (i2s_tdm->checked_lifecycle)\n\t\treturn i2s_checked_trigger(i2s_tdm, substream->stream, cmd);\n\n\tswitch (cmd) {")
    return source
