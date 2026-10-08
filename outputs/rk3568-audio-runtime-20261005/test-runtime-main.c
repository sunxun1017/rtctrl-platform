/* SPDX-License-Identifier: GPL-2.0-or-later */
static int total, failed;
static struct rk817_codec_priv priv;
static struct snd_soc_component component;
static struct snd_soc_dai dai;
static struct snd_pcm_substream stream;
static struct snd_pcm_hw_params params;
static void fresh(int direction, unsigned int rate, int format, int version, int pdm)
{
    memset(&fault, 0, sizeof(fault));
    memset(&priv, 0, sizeof(priv));
    priv.chip_ver = version;
    priv.pdmdata_out_enable = pdm;
    component.data = &priv;
    dai.component = &component;
    stream.stream = direction;
    params = (struct snd_pcm_hw_params){ .rate = rate, .format = format };
    fault.error = -EREMOTEIO;
    fault.update_success = 1;
}
static void check(const char *name, bool ok)
{
    total++;
    failed += !ok;
    printf("{\"name\":\"%s\",\"passed\":%s}\n", name, ok ? "true" : "false");
}
static bool sequence(int direction, int pdm, int version, int format,
                     unsigned int cfg3, unsigned int rate_limit)
{
    const unsigned int regs[] = {
        RK817_CODEC_APLL_CFG0, RK817_CODEC_APLL_CFG4, RK817_CODEC_APLL_CFG3,
        RK817_CODEC_DDAC_SR_LMT0, RK817_CODEC_ADAC_CFG1, RK817_CODEC_DTOP_DIGEN_CLKE,
        RK817_CODEC_DTOP_DIGEN_CLKE, RK817_CODEC_APLL_CFG5, RK817_CODEC_APLL_CFG5,
        RK817_CODEC_ADAC_CFG1, RK817_CODEC_DI2S_RXCR2, RK817_CODEC_DI2S_TXCR2
    };
    const unsigned int vals[] = {
        version <= 4 ? 0x0c : 0x04, version <= 4 ? 0x95 : 0xa5, cfg3, rate_limit,
        PWD_DACBIAS_DOWN, DAC_DIG_CLK_DIS, DAC_DIG_CLK_EN, PLL_PW_DOWN, PLL_PW_UP,
        PWD_DACBIAS_ON, format == SNDRV_PCM_FORMAT_S16_LE ? VDW_RX_16BITS : VDW_RX_24BITS,
        format == SNDRV_PCM_FORMAT_S16_LE ? VDW_TX_16BITS : VDW_TX_24BITS
    };
    if (direction == SNDRV_PCM_STREAM_PLAYBACK) {
        for (int i = 0; i < 12; i++)
            if (fault.reg[i] != regs[i] || fault.value[i] != vals[i])
                return false;
        return fault.calls == 12;
    }
    if (pdm)
        return fault.calls == 4 && fault.reg[0] == regs[0] && fault.reg[1] == regs[1] &&
               fault.reg[2] == regs[10] && fault.reg[3] == regs[11] &&
               fault.value[0] == vals[0] && fault.value[1] == vals[1] &&
               fault.value[2] == vals[10] && fault.value[3] == vals[11];
    const unsigned int adc_regs[] = { regs[0], regs[1], regs[2], regs[3], regs[5], regs[6],
                                     regs[7], regs[8], regs[10], regs[11] };
    const unsigned int adc_vals[] = { vals[0], vals[1], vals[2], vals[3], ADC_DIG_CLK_DIS,
                                     ADC_DIG_CLK_EN, vals[7], vals[8], vals[10], vals[11] };
    return fault.calls == 10 && !memcmp(fault.reg, adc_regs, sizeof(adc_regs)) &&
           !memcmp(fault.value, adc_vals, sizeof(adc_vals));
}
int main(void)
{
    char name[100];
    const unsigned int rates[] = {8000, 16000, 32000, 44100, 48000, 96000};
    const unsigned int cfg3[] = {3, 6, 12, 12, 12, 24};
    const unsigned int limits[] = {0, 1, 2, 2, 2, 3};
    const int formats[] = {SNDRV_PCM_FORMAT_S16_LE, SNDRV_PCM_FORMAT_S24_LE, SNDRV_PCM_FORMAT_S32_LE};
    for (int direction = 0; direction < 2; direction++) {
        for (int version = 4; version <= 5; version++) {
            for (int pdm = 0; pdm < 2; pdm++) {
                for (int r = 0; r < 6; r++) {
                    for (int fmt = 0; fmt < 3; fmt++) {
                        fresh(direction, rates[r], formats[fmt], version, pdm);
                        int ret = rk817_hw_params(&stream, &params, &dai);
                        snprintf(name, sizeof(name), "valid_stream%d_chip%d_pdm%d_rate%u_fmt%d",
                                 direction, version, pdm, rates[r], formats[fmt]);
                        check(name, ret == 0 && sequence(direction, pdm, version, formats[fmt], cfg3[r], limits[r]));
                    }
                }
                int calls = direction == 0 ? 12 : (pdm ? 4 : 10);
                for (int failure = 1; failure <= calls; failure++) {
                    fresh(direction, 48000, SNDRV_PCM_FORMAT_S16_LE, version, pdm);
                    fault.fail_at = failure;
                    int ret = rk817_hw_params(&stream, &params, &dai);
                    snprintf(name, sizeof(name), "hwparams_stream%d_chip%d_pdm%d_io%d_preserves_errno_stops",
                             direction, version, pdm, failure);
                    check(name, ret == -EREMOTEIO && fault.calls == failure);
                }
            }
        }
        fresh(direction, 22050, SNDRV_PCM_FORMAT_S16_LE, 5, 0);
        snprintf(name, sizeof(name), "invalid_rate_stream%d_no_io", direction);
        check(name, rk817_hw_params(&stream, &params, &dai) == -EINVAL && fault.calls == 0);
        fresh(direction, 48000, SNDRV_PCM_FORMAT_S20_3LE, 5, 0);
        snprintf(name, sizeof(name), "unimplemented_format_stream%d_no_io", direction);
        check(name, rk817_hw_params(&stream, &params, &dai) == -EINVAL && fault.calls == 0);
    }
    fresh(3, 48000, SNDRV_PCM_FORMAT_S16_LE, 5, 0);
    check("invalid_stream_no_io", rk817_hw_params(&stream, &params, &dai) == -EINVAL && fault.calls == 0);
    check("advertised_formats_match_implemented_formats", RK817_FORMATS ==
          (SNDRV_PCM_FMTBIT_S16_LE | SNDRV_PCM_FMTBIT_S24_LE | SNDRV_PCM_FMTBIT_S32_LE));
    int (*restart[])(struct snd_soc_component *) = {
        rk817_restart_dac_digital_clk, rk817_restart_dac_digital_clk_and_apll,
        rk817_restart_adc_digital_clk, rk817_restart_adc_digital_clk_and_apll
    };
    const int counts[] = {4, 6, 2, 4};
    for (int fn = 0; fn < 4; fn++) {
        fresh(0, 48000, SNDRV_PCM_FORMAT_S16_LE, 5, 0);
        snprintf(name, sizeof(name), "restart%d_changed_update_is_success", fn);
        check(name, restart[fn](&component) == 0 && fault.calls == counts[fn]);
        for (int failure = 1; failure <= counts[fn]; failure++) {
            fresh(0, 48000, SNDRV_PCM_FORMAT_S16_LE, 5, 0);
            fault.fail_at = failure;
            snprintf(name, sizeof(name), "restart%d_io%d_preserves_errno_stops", fn, failure);
            check(name, restart[fn](&component) == -EREMOTEIO && fault.calls == failure);
        }
    }
    return failed ? 1 : 0;
}
