static void i2s_trcm_async_fault(struct snd_soc_dai *dai, int first_errno)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	unsigned long flags;

	spin_lock_irqsave(&i2s_tdm->lock, flags);
	i2s_checked_error_locked(i2s_tdm, first_errno < 0 ? first_errno : -EIO);
	/* The sink may observe a PM transition or a retained late callback. A RAM
	 * latch cannot manufacture MMIO ownership or a STOP proof in that state.
	 */
	if (!i2s_tdm->hclk_enabled || !i2s_tdm->mclks_enabled || i2s_tdm->power_transition) {
		if (i2s_tdm->transport_live || i2s_tdm->started || i2s_tdm->starting)
			i2s_tdm->stop_proven = false;
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		return;
	}
	i2s_trcm_joint_locked(i2s_tdm, first_errno < 0 ? first_errno : -EIO);
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
}
