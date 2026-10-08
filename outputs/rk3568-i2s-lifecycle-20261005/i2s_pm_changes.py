"""Clock references, process IRQ drain and conservative void destruction."""
from source_utils import function, replace


PROTOTYPES = r'''
static int i2s_checked_error_locked(struct rk_i2s_tdm_dev *i2s_tdm, int ret);
static int i2s_checked_stop_locked(struct rk_i2s_tdm_dev *i2s_tdm, int stream, bool force);
static int i2s_checked_first_error(int first, int next);
static int rockchip_i2s_tdm_pinctrl_select_clk_state(struct device *dev);

static void i2s_checked_failstop(struct rk_i2s_tdm_dev *i2s_tdm,
			       const char *operation, int ret)
{
	/* Returning from remove does not preserve devres. Never warm reboot. */
	WRITE_ONCE(panic_timeout, 0);
	panic("%s: %s unsafe CPU I2S destruction (%d)", DRV_NAME, operation, ret);
}

static int i2s_checked_runtime_suspend(struct rk_i2s_tdm_dev *i2s_tdm)
{
	unsigned long flags;
	int ret = 0;

	spin_lock_irqsave(&i2s_tdm->lock, flags);
	if (i2s_tdm->runtime_error && !i2s_tdm->shutting_down)
		ret = i2s_tdm->runtime_error;
	else if (i2s_tdm->configuring || i2s_tdm->started || !i2s_tdm->stop_proven)
		ret = -EBUSY;
	if (!ret)
		i2s_tdm->irq_live = false;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	if (ret)
		return ret;
	if (i2s_tdm->irq > 0)
		synchronize_irq(i2s_tdm->irq);
	regcache_cache_only(i2s_tdm->regmap, true);
	if (i2s_tdm->mclks_enabled) {
		clk_disable_unprepare(i2s_tdm->mclk_tx);
		clk_disable_unprepare(i2s_tdm->mclk_rx);
		i2s_tdm->mclks_enabled = false;
	}
	ret = pinctrl_pm_select_idle_state(i2s_tdm->dev);
	if (ret) {
		spin_lock_irqsave(&i2s_tdm->lock, flags);
		i2s_checked_error_locked(i2s_tdm, ret);
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	}
	return ret;
}

static int i2s_checked_runtime_resume(struct rk_i2s_tdm_dev *i2s_tdm)
{
	unsigned long flags;
	bool stopping;
	int ret, next;

	spin_lock_irqsave(&i2s_tdm->lock, flags);
	stopping = i2s_tdm->shutting_down;
	ret = i2s_tdm->runtime_error;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	if (ret && !stopping)
		return ret;
	if (i2s_tdm->mclks_enabled)
		return 0;
	ret = rockchip_i2s_tdm_pinctrl_select_clk_state(i2s_tdm->dev);
	if (ret)
		goto error;
	ret = clk_prepare_enable(i2s_tdm->mclk_tx);
	if (ret)
		goto error;
	ret = clk_prepare_enable(i2s_tdm->mclk_rx);
	if (ret)
		goto disable_tx;
	regcache_cache_only(i2s_tdm->regmap, false);
	/* Destruction may only issue forced STOP, never replay cached START bits. */
	if (!stopping) {
		regcache_mark_dirty(i2s_tdm->regmap);
		ret = regcache_sync(i2s_tdm->regmap);
		if (ret)
			goto cache_error;
		spin_lock_irqsave(&i2s_tdm->lock, flags);
		if (!i2s_tdm->stop_proven) {
			ret = i2s_checked_stop_locked(i2s_tdm, SNDRV_PCM_STREAM_PLAYBACK, true);
			next = i2s_checked_stop_locked(i2s_tdm, SNDRV_PCM_STREAM_CAPTURE, true);
			ret = i2s_checked_first_error(ret, next);
			i2s_tdm->stop_proven = !ret;
		}
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		if (ret)
			goto cache_error;
	}
	i2s_tdm->mclks_enabled = true;
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	i2s_tdm->irq_live = !stopping;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return 0;
cache_error:
	regcache_cache_only(i2s_tdm->regmap, true);
	clk_disable_unprepare(i2s_tdm->mclk_rx);
disable_tx:
	clk_disable_unprepare(i2s_tdm->mclk_tx);
error:
	regcache_cache_only(i2s_tdm->regmap, true);
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	i2s_tdm->irq_live = false;
	i2s_checked_error_locked(i2s_tdm, ret);
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}

static void i2s_checked_quiesce(struct rk_i2s_tdm_dev *i2s_tdm,
			      const char *operation)
{
	unsigned long flags;
	int ret, next;

	spin_lock_irqsave(&i2s_tdm->lock, flags);
	/* No cross-ALSA ownership exists here; devres cannot destroy open owners. */
	ret = i2s_tdm->configuring || i2s_tdm->started ||
		READ_ONCE(i2s_tdm->substreams[SNDRV_PCM_STREAM_PLAYBACK]) ||
		READ_ONCE(i2s_tdm->substreams[SNDRV_PCM_STREAM_CAPTURE]) ? -EBUSY : 0;
	if (!ret) {
		i2s_tdm->shutting_down = true;
		i2s_tdm->irq_live = false;
	}
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	if (ret)
		i2s_checked_failstop(i2s_tdm, operation, ret);
	if (i2s_tdm->irq > 0)
		synchronize_irq(i2s_tdm->irq);
	ret = pm_runtime_get_sync(i2s_tdm->dev);
	if (ret < 0) {
		pm_runtime_put_noidle(i2s_tdm->dev);
		i2s_checked_failstop(i2s_tdm, operation, ret);
	}
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	ret = i2s_checked_stop_locked(i2s_tdm, SNDRV_PCM_STREAM_PLAYBACK, true);
	next = i2s_checked_stop_locked(i2s_tdm, SNDRV_PCM_STREAM_CAPTURE, true);
	ret = i2s_checked_first_error(ret, next);
	i2s_tdm->stop_proven = !ret;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	if (ret)
		i2s_checked_failstop(i2s_tdm, operation, ret);
	pm_runtime_put_noidle(i2s_tdm->dev);
	pm_runtime_disable(i2s_tdm->dev);
	ret = i2s_checked_runtime_suspend(i2s_tdm);
	if (ret)
		i2s_checked_failstop(i2s_tdm, operation, ret);
	if (i2s_tdm->hclk_enabled) {
		clk_disable_unprepare(i2s_tdm->hclk);
		i2s_tdm->hclk_enabled = false;
	}
}

static void i2s_checked_probe_clock_release(void *data)
{
	struct rk_i2s_tdm_dev *i2s_tdm = data;

	/* IRQ and component devres, registered later, are already destroyed. */
	if (READ_ONCE(i2s_tdm->substreams[0]) || READ_ONCE(i2s_tdm->substreams[1]) ||
	    i2s_tdm->started || i2s_tdm->configuring)
		i2s_checked_failstop(i2s_tdm, "probe cleanup", -EBUSY);
	if (i2s_tdm->mclks_enabled && !i2s_tdm->stop_proven)
		i2s_checked_failstop(i2s_tdm, "probe cleanup stop unproved", -EIO);
	/* Probe may fail after PM/component registration: block late callbacks. */
	pm_runtime_disable(i2s_tdm->dev);
	if (i2s_tdm->mclks_enabled) {
		clk_disable_unprepare(i2s_tdm->mclk_tx);
		clk_disable_unprepare(i2s_tdm->mclk_rx);
		i2s_tdm->mclks_enabled = false;
	}
	if (i2s_tdm->hclk_enabled) {
		clk_disable_unprepare(i2s_tdm->hclk);
		i2s_tdm->hclk_enabled = false;
	}
}
'''


def pm_lifecycle(source):
    source = replace(source, "\tbool mclks_enabled;", "\tbool mclks_enabled;\n\tbool hclk_enabled;")
    source = replace(source, "static int i2s_tdm_runtime_suspend(", PROTOTYPES + "\nstatic int i2s_tdm_runtime_suspend(")
    source = replace(source, "\tregcache_cache_only(i2s_tdm->regmap, true);\n\n\tclk_disable_unprepare", "\tif (i2s_tdm->checked_lifecycle)\n\t\treturn i2s_checked_runtime_suspend(i2s_tdm);\n\n\tregcache_cache_only(i2s_tdm->regmap, true);\n\n\tclk_disable_unprepare")
    source = replace(source, "\tpinctrl_select_state(i2s_tdm->pinctrl, i2s_tdm->clk_state);\n\n\treturn 0;", "\tif (i2s_tdm->checked_lifecycle)\n\t\treturn pinctrl_select_state(i2s_tdm->pinctrl, i2s_tdm->clk_state);\n\tpinctrl_select_state(i2s_tdm->pinctrl, i2s_tdm->clk_state);\n\n\treturn 0;")
    source = replace(source, "\t/*\n\t * pinctrl default state is invoked by ASoC framework", "\tif (i2s_tdm->checked_lifecycle)\n\t\treturn i2s_checked_runtime_resume(i2s_tdm);\n\n\t/*\n\t * pinctrl default state is invoked by ASoC framework")
    source = replace(source, "\ti2s_tdm->lrck_ratio = 1;", r'''	i2s_tdm->lrck_ratio = 1;
	/* Exact locked board/profile scope. Other controllers retain legacy paths. */
	res = platform_get_resource(pdev, IORESOURCE_MEM, 0);
	if (res && res->start == 0xfe410000 &&
	    of_device_is_compatible(node, "rockchip,rk3568-i2s-tdm") &&
	    !of_property_read_u32(node, "rockchip,clk-trcm", &val) && val == 1 &&
	    !of_property_read_bool(node, "rockchip,always-on") &&
	    !of_property_read_bool(node, "rockchip,hdmi-path") &&
	    !of_property_read_bool(node, "rockchip,mclk-calibrate") &&
	    !of_property_read_bool(node, "rockchip,io-multiplex") &&
	    !of_property_read_bool(node, "rockchip,tdm-multi-lanes") &&
	    !of_property_read_bool(node, "rockchip,no-dmaengine") &&
	    !of_property_read_bool(node, "rockchip,digital-loopback") &&
	    !of_find_property(node, "rockchip,i2s-tx-route", NULL) &&
	    !of_find_property(node, "rockchip,i2s-rx-route", NULL))
		i2s_tdm->checked_lifecycle = true;''')
    source = replace(source, "\ti2s_tdm->mclk_tx = devm_clk_get(&pdev->dev, \"mclk_tx\");", r'''	if (i2s_tdm->checked_lifecycle) {
		i2s_tdm->hclk_enabled = true;
		ret = devm_add_action_or_reset(&pdev->dev, i2s_checked_probe_clock_release, i2s_tdm);
		if (ret)
			return ret;
	}

	i2s_tdm->mclk_tx = devm_clk_get(&pdev->dev, "mclk_tx");''')
    source = replace(source, "\tif (irq > 0) {\n\t\tret = devm_request_irq", "\tif (irq > 0) {\n\t\ti2s_tdm->irq = irq;\n\t\tret = devm_request_irq")
    source = replace(source, "\tpm_runtime_disable(&pdev->dev);\n\tif (!pm_runtime_status_suspended", "\tif (i2s_tdm->checked_lifecycle) {\n\t\ti2s_checked_quiesce(i2s_tdm, \"remove\");\n\t\treturn 0;\n\t}\n\n\tpm_runtime_disable(&pdev->dev);\n\tif (!pm_runtime_status_suspended")
    source = replace(source, "\tpm_runtime_get_sync(i2s_tdm->dev);\n\trockchip_i2s_tdm_stop", "\tif (i2s_tdm->checked_lifecycle) {\n\t\ti2s_checked_quiesce(i2s_tdm, \"platform shutdown\");\n\t\treturn;\n\t}\n\n\tpm_runtime_get_sync(i2s_tdm->dev);\n\trockchip_i2s_tdm_stop")
    source = replace(source, "\tregcache_mark_dirty(i2s_tdm->regmap);\n\n\treturn 0;", "\tif (i2s_tdm->checked_lifecycle)\n\t\treturn pm_runtime_force_suspend(dev);\n\n\tregcache_mark_dirty(i2s_tdm->regmap);\n\n\treturn 0;")
    original = function(source, "rockchip_i2s_tdm_resume")
    changed = replace(original, "\tret = pm_runtime_get_sync(dev);\n\tif (ret < 0)", "\tif (i2s_tdm->checked_lifecycle)\n\t\treturn pm_runtime_force_resume(dev);\n\n\tret = pm_runtime_get_sync(dev);\n\tif (ret < 0)")
    source = replace(source, original, changed)
    original = function(source, "rockchip_i2s_tdm_set_sysclk")
    changed = replace(original, "\t/* Put set mclk rate", r'''	unsigned long flags;
	int ret;

	if (i2s_tdm->checked_lifecycle) {
		if ((stream != SNDRV_PCM_STREAM_PLAYBACK && stream != SNDRV_PCM_STREAM_CAPTURE) || !freq)
			return -EINVAL;
		spin_lock_irqsave(&i2s_tdm->lock, flags);
		ret = i2s_checked_gate_locked(i2s_tdm);
		if (!ret) {
			i2s_tdm->mclk_tx_freq = freq;
			i2s_tdm->mclk_rx_freq = freq;
		}
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		return ret;
	}

	/* Put set mclk rate''')
    source = replace(source, original, changed)
    original = function(source, "rockchip_dai_tdm_slot")
    changed = replace(original, "\ti2s_tdm->tdm_mode = true;", "\tif (i2s_tdm->checked_lifecycle)\n\t\treturn -EOPNOTSUPP;\n\n\ti2s_tdm->tdm_mode = true;")
    source = replace(source, original, changed)
    return source
