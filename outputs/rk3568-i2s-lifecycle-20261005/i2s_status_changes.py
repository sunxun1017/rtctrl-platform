"""Real hardware stop readback, locked profile/config, read-only guard evidence."""
from source_utils import function, replace


HELPERS = r'''
static bool i2s_checked_profile(struct platform_device *pdev)
{
	struct device_node *node = pdev->dev.of_node;
	struct resource *res = platform_get_resource(pdev, IORESOURCE_MEM, 0);
	unsigned int val;

	if (!res || res->start != 0xfe410000 || resource_size(res) != 0x1000 ||
	    !of_device_is_compatible(node, "rockchip,rk3568-i2s-tdm") ||
	    of_property_read_u32(node, "rockchip,clk-trcm", &val) || val != 1)
		return false;
	if (!of_property_read_u32(node, "rockchip,bclk-fs", &val) && val != 64)
		return false;
	return !of_property_read_bool(node, "rockchip,always-on") &&
		!of_property_read_bool(node, "rockchip,hdmi-path") &&
		!of_property_read_bool(node, "rockchip,mclk-calibrate") &&
		!of_property_read_bool(node, "rockchip,io-multiplex") &&
		!of_property_read_bool(node, "rockchip,tdm-multi-lanes") &&
		!of_property_read_bool(node, "rockchip,no-dmaengine") &&
		!of_property_read_bool(node, "rockchip,digital-loopback") &&
		!of_find_property(node, "rockchip,i2s-tx-route", NULL) &&
		!of_find_property(node, "rockchip,i2s-rx-route", NULL);
}

static int i2s_checked_initial_config(struct rk_i2s_tdm_dev *i2s_tdm, u32 addr)
{
	int ret;

	ret = regmap_update_bits(i2s_tdm->regmap, I2S_DMACR,
				 I2S_DMACR_TDL_MASK, I2S_DMACR_TDL(16));
	if (ret)
		return ret;
	ret = regmap_update_bits(i2s_tdm->regmap, I2S_DMACR,
				 I2S_DMACR_RDL_MASK, I2S_DMACR_RDL(16));
	if (ret)
		return ret;
	ret = regmap_update_bits(i2s_tdm->regmap, I2S_CKR,
				 I2S_CKR_TRCM_MASK, i2s_tdm->clk_trcm);
	if (ret)
		return ret;
	return i2s_tdm->soc_data->init(i2s_tdm->dev, addr);
}

static ssize_t rk3568_lifecycle_state_show(struct device *dev,
					struct device_attribute *attr, char *buf)
{
	struct rk_i2s_tdm_dev *i2s_tdm = dev_get_drvdata(dev);
	unsigned long flags;
	unsigned int owners, open_mask, stopped, irq_live, irq_drained;
	unsigned int mclk_leases, hclk_lease, configuring, power_transition, shutting_down, ready;
	unsigned int stop_reads;
	int error;

	if (!i2s_tdm->checked_lifecycle)
		return -EOPNOTSUPP;
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	owners = i2s_tdm->started;
	open_mask = (!!READ_ONCE(i2s_tdm->substreams[0])) |
		(!!READ_ONCE(i2s_tdm->substreams[1]) << 1);
	error = i2s_tdm->runtime_error;
	stopped = i2s_tdm->stop_proven;
	irq_live = i2s_tdm->irq_live;
	irq_drained = i2s_tdm->irq_drained;
	mclk_leases = READ_ONCE(i2s_tdm->mclks_enabled);
	hclk_lease = READ_ONCE(i2s_tdm->hclk_enabled);
	configuring = i2s_tdm->configuring;
	power_transition = i2s_tdm->power_transition;
	shutting_down = i2s_tdm->shutting_down;
	ready = READ_ONCE(i2s_tdm->ready);
	stop_reads = i2s_tdm->stop_reads;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	/* No MMIO, PM get, clock operation or pointer disclosure in this reader. */
	return sysfs_emit(buf, "version=1 ready=%u error=%d owners=%u open=%u stop_proven=%u stop_reads=%u irq_live=%u irq_drained=%u mclk_leases=%u hclk_lease=%u configuring=%u power_transition=%u shutting_down=%u\n",
		ready, error, owners, open_mask, stopped, stop_reads, irq_live, irq_drained,
		mclk_leases, hclk_lease, configuring, power_transition, shutting_down);
}

static DEVICE_ATTR_RO(rk3568_lifecycle_state);
static struct attribute *i2s_checked_attrs[] = {
	&dev_attr_rk3568_lifecycle_state.attr,
	NULL,
};
static const struct attribute_group i2s_checked_group = {
	.attrs = i2s_checked_attrs,
};
'''


def status_and_profile(source):
    source = replace(source, "\tbool hclk_enabled;", "\tbool hclk_enabled;\n\tbool irq_drained;\n\tbool power_transition;\n\tbool ready;\n\tunsigned int stop_reads;\n\tvoid __iomem *regs;")
    source = replace(source, "\tret = i2s_checked_dma_locked(i2s_tdm, stream, false);\n\t/* FLAT cache", "\tret = i2s_checked_dma_locked(i2s_tdm, stream, false);\n\tnext = i2s_checked_dma_locked(i2s_tdm, SNDRV_PCM_STREAM_LAST - stream, false);\n\tret = i2s_checked_first_error(ret, next);\n\t/* FLAT cache")
    source = replace(source, "\tif (!ret) {\n\t\ti2s_tdm->started &= ~bit;", r'''	if (!ret) {
		/* Direct MMIO readback bypasses FLAT cache without a global bypass toggle. */
		i2s_tdm->stop_reads++;
		if ((readl(i2s_tdm->regs + I2S_XFER) & (I2S_XFER_TXS_MASK | I2S_XFER_RXS_MASK)) ||
		    (readl(i2s_tdm->regs + I2S_DMACR) & (I2S_DMACR_TDE_MASK | I2S_DMACR_RDE_MASK)) ||
		    (readl(i2s_tdm->regs + I2S_INTCR) & (I2S_INTCR_TXUIE_MASK | I2S_INTCR_RXOIE_MASK)))
			ret = -EIO;
	}
	if (!ret) {
		i2s_tdm->started &= ~bit;''')
    source = replace(source, "\tif (i2s_tdm->started)\n\t\treturn -EBUSY;\n\ti2s_tdm->stop_proven", "\tif (i2s_tdm->started || !i2s_tdm->stop_proven)\n\t\treturn -EBUSY;\n\ti2s_tdm->irq_drained = false;\n\ti2s_tdm->stop_proven")
    source = replace(source, "else if (i2s_tdm->configuring || (i2s_tdm->started & ~BIT(substream->stream)))", "else if (i2s_tdm->configuring || (i2s_tdm->started & ~BIT(substream->stream)) ||\n\t\t\t (!i2s_tdm->started && !i2s_tdm->stop_proven))")
    source = replace(source, "\t\t\tWRITE_ONCE(i2s_tdm->substreams[stream], substream);", "\t\t\ti2s_tdm->irq_drained = false;\n\t\t\tWRITE_ONCE(i2s_tdm->substreams[stream], substream);")
    original = function(source, "rockchip_i2s_tdm_shutdown")
    changed = replace(original, "\t\tif (ret)\n\t\t\tdev_err", "\t\tspin_lock_irqsave(&i2s_tdm->lock, flags);\n\t\tif (!READ_ONCE(i2s_tdm->substreams[0]) && !READ_ONCE(i2s_tdm->substreams[1]))\n\t\t\ti2s_tdm->irq_drained = true;\n\t\tspin_unlock_irqrestore(&i2s_tdm->lock, flags);\n\t\tif (ret)\n\t\t\tdev_err")
    source = replace(source, original, changed)
    original = function(source, "i2s_checked_runtime_suspend")
    changed = replace(original, "\tif (!ret)\n\t\ti2s_tdm->irq_live = false;", "\tif (!ret) {\n\t\ti2s_tdm->power_transition = true;\n\t\ti2s_tdm->irq_live = false;\n\t\ti2s_tdm->irq_drained = false;\n\t}")
    changed = replace(changed, "\treturn ret;\n}", "\tspin_lock_irqsave(&i2s_tdm->lock, flags);\n\ti2s_tdm->irq_drained = true;\n\ti2s_tdm->power_transition = false;\n\tspin_unlock_irqrestore(&i2s_tdm->lock, flags);\n\treturn ret;\n}")
    source = replace(source, original, changed)
    original = function(source, "i2s_checked_runtime_resume")
    changed = replace(original, "\tif (i2s_tdm->mclks_enabled)\n\t\treturn 0;", "\tif (i2s_tdm->mclks_enabled)\n\t\treturn 0;\n\tspin_lock_irqsave(&i2s_tdm->lock, flags);\n\ti2s_tdm->power_transition = true;\n\ti2s_tdm->irq_drained = false;\n\tspin_unlock_irqrestore(&i2s_tdm->lock, flags);")
    changed = replace(changed, "\ti2s_tdm->irq_live = !stopping;", "\ti2s_tdm->irq_live = !stopping;\n\ti2s_tdm->power_transition = false;")
    changed = replace(changed, "\ti2s_tdm->irq_live = false;\n\ti2s_checked_error_locked", "\ti2s_tdm->irq_live = false;\n\ti2s_tdm->power_transition = false;\n\ti2s_checked_error_locked")
    source = replace(source, original, changed)
    source = replace(source, "static int rockchip_i2s_tdm_probe(", HELPERS + "\nstatic int rockchip_i2s_tdm_probe(")
    start = source.index("\t/* Exact locked board/profile scope.")
    end = source.index("\t\ti2s_tdm->checked_lifecycle = true;", start) + len("\t\ti2s_tdm->checked_lifecycle = true;")
    source = source[:start] + "\ti2s_tdm->checked_lifecycle = i2s_checked_profile(pdev);" + source[end:]
    source = replace(source, "\ti2s_tdm->regmap = devm_regmap_init_mmio", "\ti2s_tdm->regs = regs;\n\ti2s_tdm->regmap = devm_regmap_init_mmio")
    source = replace(source, "\tirq = platform_get_irq_optional(pdev, 0);", "\tirq = platform_get_irq_optional(pdev, 0);\n\tif (i2s_tdm->checked_lifecycle && irq <= 0)\n\t\treturn irq ? irq : -ENXIO;")
    original = function(source, "common_soc_init")
    changed = replace(original, "\tif (IS_ERR(i2s_tdm->grf))\n\t\treturn 0;", "\tif (IS_ERR(i2s_tdm->grf))\n\t\treturn i2s_tdm->checked_lifecycle ? PTR_ERR(i2s_tdm->grf) : 0;")
    changed = replace(changed, "\t\tif (reg)\n\t\t\tregmap_write(i2s_tdm->grf, reg, val);", "\t\tif (reg) {\n\t\t\tint ret = regmap_write(i2s_tdm->grf, reg, val);\n\t\t\tif (i2s_tdm->checked_lifecycle && ret)\n\t\t\t\treturn ret;\n\t\t}")
    source = replace(source, original, changed)
    original = function(source, "rockchip_i2s_tdm_probe")
    start = original.index("\tregmap_update_bits(i2s_tdm->regmap, I2S_DMACR, I2S_DMACR_TDL_MASK,")
    end = original.index("\n\n\t/*\n\t * CLK_ALWAYS_ON", start)
    block = original[start:end]
    checked = "\tif (i2s_tdm->checked_lifecycle) {\n\t\tret = i2s_checked_initial_config(i2s_tdm, res->start);\n\t\tif (ret)\n\t\t\treturn ret;\n\t} else {\n" + block + "\n\t}"
    changed = replace(original, block, checked)
    changed = replace(changed, '\t\tdev_err(&pdev->dev, "Could not register PCM\\n");\n\t\treturn ret;', '\t\tdev_err(&pdev->dev, "Could not register PCM\\n");\n\t\tif (i2s_tdm->checked_lifecycle)\n\t\t\tgoto err_suspend;\n\t\treturn ret;')
    changed = replace(changed, "\treturn 0;\n\nerr_suspend:", "\tif (i2s_tdm->checked_lifecycle) {\n\t\tret = devm_device_add_group(&pdev->dev, &i2s_checked_group);\n\t\tif (ret)\n\t\t\tgoto err_suspend;\n\t\tWRITE_ONCE(i2s_tdm->ready, true);\n\t}\n\treturn 0;\n\nerr_suspend:")
    source = replace(source, original, changed)
    return source
