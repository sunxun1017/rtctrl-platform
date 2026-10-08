/* SPDX-License-Identifier: MIT */
static struct device cpu_device, codec_device;
static struct clk tx, rx, parent;
static struct regmap map;
static struct rk_i2s_tdm_dev info;
static struct snd_soc_dai cpu_dai, codec_dai;
static struct snd_soc_component codec_component;
static struct rk817_codec_priv codec_info;
static struct snd_pcm_substream substream, other_substream;
static struct snd_pcm_hw_params params;
static struct asoc_simple_dai simple_cpu, simple_codec;
static struct simple_dai_props properties;
static struct asoc_simple_priv simple_priv;
static struct snd_soc_card card;
static const struct snd_soc_dai_ops cpu_ops = {.set_sysclk = rockchip_i2s_tdm_set_sysclk};
static const struct snd_soc_dai_ops codec_ops = {.set_sysclk = rk817_set_dai_sysclk};
static struct snd_soc_dai_driver cpu_driver = {.ops = &cpu_ops};
static struct snd_soc_dai_driver codec_driver = {.ops = &codec_ops};
static unsigned int total, passed;
static bool lock_initialized;

static void check(const char *name, bool condition)
{
    total++;
    passed += condition;
    printf("SYSCLK_CHECK %s %u\n", name, condition);
}

static void reset(int direction)
{
    if (lock_initialized) pthread_mutex_destroy(&info.lock);
    memset(&info, 0, sizeof(info));
    memset(&map, 0, sizeof(map));
    memset(&tx, 0, sizeof(tx));
    memset(&rx, 0, sizeof(rx));
    memset(&parent, 0, sizeof(parent));
    memset(&cpu_device, 0, sizeof(cpu_device));
    memset(&codec_device, 0, sizeof(codec_device));
    memset(&cpu_dai, 0, sizeof(cpu_dai));
    memset(&codec_dai, 0, sizeof(codec_dai));
    memset(&params, 0, sizeof(params));
    memset(&simple_cpu, 0, sizeof(simple_cpu));
    memset(&simple_codec, 0, sizeof(simple_codec));
    cpu_device.data = &info;
    codec_device.data = &codec_info;
    codec_component.dev = &codec_device;
    cpu_dai.dev = &cpu_device;
    cpu_dai.driver = &cpu_driver;
    cpu_dai.playback_dma_data = &info.playback_dma_data;
    cpu_dai.capture_dma_data = &info.capture_dma_data;
    codec_dai.dev = &codec_device;
    codec_dai.component = &codec_component;
    codec_dai.driver = &codec_driver;
    info.dev = &cpu_device;
    info.regmap = &map;
    info.mclk_tx = &tx;
    info.mclk_rx = &rx;
    info.mclk_tx_freq = info.mclk_rx_freq = 12288000;
    info.lrck_ratio = 1;
    info.bclk_fs = 64;
    info.clk_trcm = I2S_CKR_TRCM_TXONLY;
    info.checked_lifecycle = true;
    info.is_master_mode = true;
    info.ready = info.stop_proven = info.irq_drained = true;
    info.mclks_enabled = info.hclk_enabled = info.irq_live = true;
    info.stop_reads = 7;
    tx.parent = rx.parent = &parent;
    tx.rate = rx.rate = 12288000;
    codec_info.stereo_sysclk = 12288000;
    properties.cpu_dai = &simple_cpu;
    properties.codec_dai = &simple_codec;
    properties.mclk_fs = 256;
    simple_priv.dai_props = &properties;
    card.data = &simple_priv;
    model_rtd.card = &card;
    model_rtd.num = 0;
    model_rtd.cpu = &cpu_dai;
    model_rtd.codec = &codec_dai;
    substream.stream = direction;
    other_substream.stream = !direction;
    params.intervals[SNDRV_PCM_HW_PARAM_CHANNELS - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min = 2;
    params.intervals[SNDRV_PCM_HW_PARAM_RATE - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min = 48000;
    params.masks[SNDRV_PCM_HW_PARAM_FORMAT].bits[0] = BIT(SNDRV_PCM_FORMAT_S16_LE);
    pthread_mutex_init(&info.lock, NULL);
    lock_initialized = true;
    operations = reads = writes = clock_calls = fault_at = pm_error = 0;
    model_diagnostics = model_unexpected = model_clock_releases = 0;
    model_cpu_sysclk_return = 12345;
}

static bool no_hardware_change(void)
{
    return operations == 0 && clock_calls == 0 && reads == 0 && writes == 0 &&
           cpu_device.usage == 0 && model_clock_releases == 0 &&
           tx.rate == 12288000 && rx.rate == 12288000 &&
           info.mclks_enabled && info.hclk_enabled && info.irq_live &&
           info.stop_proven && info.irq_drained && info.stop_reads == 7 && !model_unexpected;
}

static void primary_shutdown(void)
{
    reset(SNDRV_PCM_STREAM_PLAYBACK);
    asoc_simple_shutdown(&substream);
    check("simple_shutdown_clears_shared_requests", model_cpu_sysclk_return == 0 &&
          !info.mclk_tx_freq && !info.mclk_rx_freq && !model_diagnostics);
    check("simple_shutdown_codec_cache_zero", !codec_info.stereo_sysclk);
    check("simple_shutdown_no_cpu_or_codec_clock_release", no_hardware_change());
    check("simple_shutdown_does_not_clear_or_set_sticky", !info.runtime_error);
}

int main(int argc, char **argv)
{
    (void)argv;
    primary_shutdown();
    if (argc == 2) {
        printf("{\"total\":%u,\"passed\":%u}\n", total, passed);
        return passed != total;
    }
    char name[128];
    for (int direction = 0; direction < 2; direction++) {
        reset(direction);
        asoc_simple_shutdown(&substream);
        snprintf(name, sizeof(name), "direction_%d_zero_double_cache", direction);
        check(name, model_cpu_sysclk_return == 0 && !info.mclk_tx_freq && !info.mclk_rx_freq && no_hardware_change());
        check("next_direct_hw_params_without_positive_request_refused", rockchip_i2s_tdm_hw_params(&substream, &params, &cpu_dai) == -EINVAL &&
              !operations && !info.configuring && !info.runtime_error && !info.mclk_tx_freq && !info.mclk_rx_freq);
        check("next_real_simple_hw_params_rebuilds_nonzero_request", asoc_simple_hw_params(&substream, &params) == 0 &&
              info.mclk_tx_freq == 12288000 && info.mclk_rx_freq == 12288000 && codec_info.stereo_sysclk == 12288000 && !operations);
        check("next_actual_cpu_hw_params_accepts_nonzero_request", rockchip_i2s_tdm_hw_params(&substream, &params, &cpu_dai) == 0 &&
              tx.rate == 12288000 && rx.rate == 12288000 && clock_calls > 0 && !info.runtime_error && !info.configuring);
        reset(direction);
        check("zero_reset_is_idempotent", rockchip_i2s_tdm_set_sysclk(&cpu_dai, direction, 0, SND_SOC_CLOCK_OUT) == 0 &&
              rockchip_i2s_tdm_set_sysclk(&cpu_dai, direction, 0, SND_SOC_CLOCK_OUT) == 0 &&
              !info.mclk_tx_freq && !info.mclk_rx_freq && no_hardware_change());
        for (unsigned int state = 0; state < 10; state++) {
            reset(direction);
            int expected = -EBUSY;
            if (state == 0) { info.runtime_error = -EIO; expected = -EIO; }
            else if (state == 1) { info.runtime_error = -ETIMEDOUT; expected = -ETIMEDOUT; }
            else if (state == 2) { info.shutting_down = true; expected = -ESHUTDOWN; }
            else if (state == 3) info.configuring = true;
            else if (state == 4) info.power_transition = true;
            else if (state == 5) info.started = BIT(direction);
            else if (state == 6) info.started = BIT(!direction);
            else if (state == 7) info.substreams[direction] = &substream;
            else if (state == 8) info.substreams[!direction] = &other_substream;
            else info.stop_proven = false;
            int sticky = info.runtime_error;
            int ret = rockchip_i2s_tdm_set_sysclk(&cpu_dai, direction, 0, SND_SOC_CLOCK_OUT);
            snprintf(name, sizeof(name), "direction_%d_zero_reject_state_%u", direction, state);
            check(name, ret == expected && info.mclk_tx_freq == 12288000 && info.mclk_rx_freq == 12288000 &&
                  !operations && !clock_calls && info.runtime_error == sticky && !model_clock_releases);
        }
        reset(direction);
        info.irq_drained = false;
        check("zero_refuses_unproved_irq_drain", rockchip_i2s_tdm_set_sysclk(&cpu_dai, direction, 0, SND_SOC_CLOCK_OUT) == -EBUSY &&
              info.mclk_tx_freq == 12288000 && info.mclk_rx_freq == 12288000 && !operations);
        reset(direction);
        info.substreams[direction] = &substream;
        info.stop_proven = info.irq_drained = false;
        check("positive_request_still_allowed_during_preconfiguration", rockchip_i2s_tdm_set_sysclk(&cpu_dai, direction, 24576000, SND_SOC_CLOCK_OUT) == 0 &&
              info.mclk_tx_freq == 24576000 && info.mclk_rx_freq == 24576000 && !operations && !info.runtime_error);
        reset(direction);
        info.runtime_error = -EIO;
        info.mclk_tx_freq = info.mclk_rx_freq = 0;
        check("zero_and_positive_do_not_clear_sticky", rockchip_i2s_tdm_set_sysclk(&cpu_dai, direction, 0, SND_SOC_CLOCK_OUT) == -EIO &&
              rockchip_i2s_tdm_set_sysclk(&cpu_dai, direction, 12288000, SND_SOC_CLOCK_OUT) == -EIO &&
              info.runtime_error == -EIO && !info.mclk_tx_freq && !info.mclk_rx_freq && !operations);
        for (unsigned int invalid = 0; invalid < 2; invalid++) {
            reset(direction);
            int clock_id = invalid ? 2 : -1;
            check("invalid_clock_id_zero_or_positive_refused", rockchip_i2s_tdm_set_sysclk(&cpu_dai, clock_id, 0, SND_SOC_CLOCK_OUT) == -EINVAL &&
                  rockchip_i2s_tdm_set_sysclk(&cpu_dai, clock_id, 12288000, SND_SOC_CLOCK_OUT) == -EINVAL &&
                  info.mclk_tx_freq == 12288000 && info.mclk_rx_freq == 12288000 && !operations);
        }
        reset(direction);
        info.checked_lifecycle = false;
        check("legacy_shared_zero_behavior_retained", rockchip_i2s_tdm_set_sysclk(&cpu_dai, direction, 0, SND_SOC_CLOCK_OUT) == 0 &&
              !info.mclk_tx_freq && !info.mclk_rx_freq && !operations);
        reset(direction);
        info.checked_lifecycle = false;
        info.clk_trcm = 0;
        check("legacy_independent_zero_behavior_retained", rockchip_i2s_tdm_set_sysclk(&cpu_dai, direction, 0, SND_SOC_CLOCK_OUT) == 0 &&
              (direction ? info.mclk_tx_freq == 12288000 && !info.mclk_rx_freq : !info.mclk_tx_freq && info.mclk_rx_freq == 12288000) && !operations);
    }
    if (lock_initialized) pthread_mutex_destroy(&info.lock);
    printf("{\"total\":%u,\"passed\":%u}\n", total, passed);
    return passed != total;
}
