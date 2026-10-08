static struct device test_dev;
static struct clk tx, rx, parent;
static struct regmap map;
static struct rk_i2s_tdm_dev info;
static struct snd_soc_dai dai;
static struct snd_pcm_substream stream;
static struct snd_pcm_hw_params params;
static unsigned int passed, total;
static bool lock_initialized;

static void check(const char *name, bool ok)
{
    total++;
    passed += ok;
    if (!ok) fprintf(stderr, "FAIL %s\n", name);
}

static void reset(int direction, bool clean)
{
    if (lock_initialized) pthread_mutex_destroy(&info.lock);
    memset(&test_dev, 0, sizeof(test_dev));
    memset(&tx, 0, sizeof(tx));
    memset(&rx, 0, sizeof(rx));
    memset(&parent, 0, sizeof(parent));
    memset(&map, 0, sizeof(map));
    memset(&info, 0, sizeof(info));
    memset(&dai, 0, sizeof(dai));
    memset(&params, 0, sizeof(params));
    operations = reads = writes = clock_calls = fault_at = pm_error = 0;
    stream.stream = direction;
    params.intervals[SNDRV_PCM_HW_PARAM_CHANNELS - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min = 2;
    params.intervals[SNDRV_PCM_HW_PARAM_RATE - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min = 48000;
    params.masks[SNDRV_PCM_HW_PARAM_FORMAT].bits[0] = BIT(SNDRV_PCM_FORMAT_S16_LE);
    test_dev.data = &info;
    dai.dev = &test_dev;
    dai.playback_dma_data = &info.playback_dma_data;
    dai.capture_dma_data = &info.capture_dma_data;
    info.dev = &test_dev;
    info.mclk_tx = &tx;
    info.mclk_rx = &rx;
    info.regmap = &map;
    info.mclk_tx_freq = info.mclk_rx_freq = 12288000;
    info.lrck_ratio = 1;
    info.bclk_fs = 64;
    info.clk_trcm = I2S_CKR_TRCM_TXONLY;
    info.is_master_mode = true;
    tx.parent = rx.parent = &parent;
    tx.rate = rx.rate = 12288000;
    pthread_mutex_init(&info.lock, NULL);
    lock_initialized = true;
#ifdef HAVE_CHECKED
    info.checked_lifecycle = true;
#endif
    if (clean) {
        map.cache[I2S_CLKDIV / 4] = I2S_CLKDIV_TXM(4) | I2S_CLKDIV_RXM(4);
        map.cache[I2S_CKR / 4] = I2S_CKR_TSD(64) | I2S_CKR_RSD(64);
        map.cache[I2S_TXCR / 4] = map.cache[I2S_RXCR / 4] = I2S_TXCR_VDW(16) | I2S_CHN_2;
        memcpy(map.hw, map.cache, sizeof(map.hw));
    }
}

static bool poisoned(void)
{
#ifdef HAVE_CHECKED
    return info.runtime_error != 0;
#else
    return false;
#endif
}

int main(void)
{
    for (int direction = 0; direction < 2; direction++) {
        reset(direction, false);
        check("params success", rockchip_i2s_tdm_hw_params(&stream, &params, &dai) == 0);
        check("params exact divider", map.hw[I2S_CLKDIV / 4] == (I2S_CLKDIV_TXM(4) | I2S_CLKDIV_RXM(4)));
        check("params maxburst", (direction ? info.capture_dma_data.maxburst : info.playback_dma_data.maxburst) == 8);
        int count = operations;
        for (int ordinal = 1; ordinal <= count; ordinal++) {
            reset(direction, false);
            fault_at = ordinal;
            check("dirty params fault errno", rockchip_i2s_tdm_hw_params(&stream, &params, &dai) == injected_errno);
            check("dirty params fault sticky", poisoned());
            check("dirty params no later operations", operations == ordinal);
            fault_at = 0;
            int before = operations;
            check("params retry refuses sticky", rockchip_i2s_tdm_hw_params(&stream, &params, &dai) == injected_errno && operations == before);
        }
        reset(direction, true);
        check("clean params success", rockchip_i2s_tdm_hw_params(&stream, &params, &dai) == 0 && writes == 0);
        count = operations;
        for (int ordinal = 1; ordinal <= count; ordinal++) {
            reset(direction, true);
            fault_at = ordinal;
            check("clean shortcut read/clock fault", rockchip_i2s_tdm_hw_params(&stream, &params, &dai) == injected_errno);
            check("clean shortcut fault sticky", poisoned());
        }
        reset(direction, false);
        params.masks[SNDRV_PCM_HW_PARAM_FORMAT].bits[0] = BIT(SNDRV_PCM_FORMAT_FLOAT_LE);
        check("bad format rejected before hardware", rockchip_i2s_tdm_hw_params(&stream, &params, &dai) == -EINVAL && operations == 0 && !poisoned());
        reset(direction, false);
        params.intervals[SNDRV_PCM_HW_PARAM_CHANNELS - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min = 3;
        check("bad channels rejected before hardware", rockchip_i2s_tdm_hw_params(&stream, &params, &dai) == -EINVAL && operations == 0 && !poisoned());
        reset(direction, false);
        params.intervals[SNDRV_PCM_HW_PARAM_RATE - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min = 0;
        check("zero rate rejected before hardware", rockchip_i2s_tdm_hw_params(&stream, &params, &dai) == -EINVAL && operations == 0 && !poisoned());
    }
    unsigned int fmt = SND_SOC_DAIFMT_CBS_CFS | SND_SOC_DAIFMT_NB_NF | SND_SOC_DAIFMT_I2S;
    reset(0, false);
    check("fmt successful balanced PM", rockchip_i2s_tdm_set_fmt(&dai, fmt) == 0 && test_dev.usage == 0 && writes == 4);
    for (int ordinal = 1; ordinal <= 4; ordinal++) {
        reset(0, false);
        fault_at = ordinal;
        check("fmt write errno", rockchip_i2s_tdm_set_fmt(&dai, fmt) == injected_errno);
        check("fmt prefix and PM balance", operations == ordinal && test_dev.usage == 0);
        check("fmt sticky", poisoned());
    }
    reset(0, false);
    pm_error = -EHOSTDOWN;
    check("fmt PM failure forbids MMIO", rockchip_i2s_tdm_set_fmt(&dai, fmt) == -EHOSTDOWN && operations == 0 && test_dev.usage == 0);
    reset(0, false);
    check("invalid fmt has no hardware/PM effect", rockchip_i2s_tdm_set_fmt(&dai, 0xffff) == -EINVAL && operations == 0 && test_dev.usage == 0 && !poisoned());
    reset(0, false);
#ifdef HAVE_CHECKED
    info.runtime_error = -EIO;
#endif
    check("sysclk rejects sticky", rockchip_i2s_tdm_set_sysclk(&dai, 0, 24576000, 0) == -EIO && info.mclk_tx_freq == 12288000 && operations == 0);
    reset(0, false);
    check("sysclk validates direction before mutation", rockchip_i2s_tdm_set_sysclk(&dai, 2, 24576000, 0) == -EINVAL && info.mclk_tx_freq == 12288000);
    reset(0, false);
    check("checked board refuses unsupported TDM reconfiguration", rockchip_dai_tdm_slot(&dai, 3, 3, 2, 32) == -EOPNOTSUPP && !info.tdm_mode && operations == 0);
    printf("{\"passed\":%u,\"total\":%u}\n", passed, total);
    return passed != total;
}
