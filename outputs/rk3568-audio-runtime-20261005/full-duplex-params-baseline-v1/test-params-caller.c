/* SPDX-License-Identifier: MIT */
/* All flow below invokes the extracted soc_pcm_hw_params/hw_free production callers. */
static bool params_order(void)
{
    const char *expected[] = {"MACHINE_BEGIN", "CODEC_BEGIN", "CPU_BEGIN", "COMPONENT_BEGIN", "DMA_BEGIN"};
    unsigned int next = 0;
    for (unsigned int i = 0; i < params_event_count && next < 5; i++)
        if (!strcmp(params_events[i].name, expected[next])) next++;
    return next == 5;
}
static bool params_trigger_order(void)
{
    const char *expected[] = {"PCM_TRIGGER_BEGIN", "COMPONENT_TRIGGER_BEGIN", "CPU_COMPONENT_TRIGGER_GATE", "DMA_TRIGGER_API", "DAI_TRIGGER_BEGIN", "CPU_DAI_TRIGGER_BEGIN"};
    unsigned int next = 0;
    for (unsigned int i = 0; i < params_event_count && next < 6; i++)
        if (!strcmp(params_events[i].name, expected[next])) next++;
    return next == 6;
}
static void params_setup(void)
{
    reset();
    memset(&codec_info, 0, sizeof(codec_info));
    codec_info.stereo_sysclk = 12288000;
    codec_info.chip_ver = 5;
    memset(codec_registers, 0, sizeof(codec_registers));
    memset(&params_dma_pcm, 0, sizeof(params_dma_pcm));
    memset(params_channels_dma, 0, sizeof(params_channels_dma));
    params_channels_dma[0].stream = 0;
    params_channels_dma[1].stream = 1;
    simple_cpu.clk = &tx;
    simple_codec.clk = &rx;
    params_clear_events();
    boundary("actual_two_open_with_latest_clean_PM_and_machine", open_both());
    params_clear_events();
}
static void params_success(int first)
{
    char name[100];
    params_setup();
    int a = soc_pcm_hw_params(&substreams[first], &params);
    snprintf(name, sizeof(name), "idle_first_%d", first);
    boundary("actual_first_full_params_order_and_two_DAI_cache", a == 0 && params_order() && cpu_dai.rate == 48000 && codec_dai.rate == 48000 && codec_pll_calls == 2);
    params_dump(name);
    params_clear_events();
    int b = soc_pcm_hw_params(&substreams[!first], &params);
    boundary("actual_second_idle_same_params_full_chain_success", b == 0 && params_order() && codec_pll_calls == 2 && info.started == 0);
    snprintf(name, sizeof(name), "idle_second_%d", !first);
    params_dump(name);
}
static void params_failure(int peer, bool component)
{
    char name[120];
    params_setup();
    boundary("peer_configuration_reaches_real_full_params", soc_pcm_hw_params(&substreams[peer], &params) == 0 && cpu_dai.rate == 48000 && codec_dai.rate == 48000);
    params_clear_events();
    params_inject_cpu_clock = !component;
    params_inject_slave_config = component;
    int ret = soc_pcm_hw_params(&substreams[!peer], &params);
    snprintf(name, sizeof(name), "peer_%d_%s_error_preserves_configured_DAI_rate", peer, component ? "component" : "CPU");
    contract(name, cpu_dai.rate == 48000 && codec_dai.rate == 48000);
    boundary("original_CPU_or_last_component_error_returned", ret == (component ? -ENOSPC : -EREMOTEIO));
    boundary("real_error_prefix_retains_peer_open_and_clock_requests", snd_soc_dai_active(&cpu_dai) == 2 && cpu_device.usage == 2 && info.mclk_tx_freq == 12288000 && codec_info.stereo_sysclk == 12288000);
    boundary("actual_CPU_failure_excludes_failing_DAI_or_component_failure_clears_both", component ? cpu_dai.rate == 0 && codec_dai.rate == 0 : cpu_dai.rate == 48000 && codec_dai.rate == 0 && info.runtime_error == -EREMOTEIO);
    params_dump(name);
    /* Sticky CPU fixture resources are intentionally retained, not claimed drained by reset(). */
}
static void params_two_free_close(int first)
{
    char name[120];
    params_setup();
    boundary("two_free_setup_both_actual_params", soc_pcm_hw_params(&substreams[0], &params) == 0 && soc_pcm_hw_params(&substreams[1], &params) == 0);
    params_clear_events();
    int a = soc_pcm_hw_free(&substreams[first]);
    int b = soc_pcm_hw_free(&substreams[!first]);
    boundary("actual_two_HW_FREE_while_both_still_open", a == 0 && b == 0 && snd_soc_dai_active(&cpu_dai) == 2 && cpu_dai.rate == 48000 && codec_dai.rate == 48000);
    int c = soc_pcm_clean(&substreams[first], 0);
    int d = soc_pcm_clean(&substreams[!first], 0);
    snprintf(name, sizeof(name), "two_HW_FREE_then_close_first_%d_clears_configuration_cache", first);
    contract(name, !cpu_dai.rate && !cpu_dai.channels && !cpu_dai.sample_bits && !codec_dai.rate && !codec_dai.channels && !codec_dai.sample_bits);
    boundary("latest_normal_close_balances_refs_and_clears_only_sysclk_requests", c == 0 && d == 0 && !snd_soc_dai_active(&cpu_dai) && !cpu_device.usage && !codec_device.usage && !platform_device.usage && !child_refs && !info.mclk_tx_freq && !info.mclk_rx_freq && !codec_info.stereo_sysclk);
    params_dump(name);
}
static void params_running(int peer, bool after_error)
{
    char name[140];
    params_setup();
    boundary("running_setup_actual_peer_params", soc_pcm_hw_params(&substreams[peer], &params) == 0);
    if (after_error) {
        params_inject_slave_config = true;
        boundary("running_precondition_real_component_error_clears_rate_without_CPU_sticky", soc_pcm_hw_params(&substreams[!peer], &params) == -ENOSPC && !cpu_dai.rate && !codec_dai.rate && !info.runtime_error);
    }
    boundary("running_peer_produced_by_real_prepare_and_single_START", i2s_checked_prepare(&substreams[peer], &cpu_dai) == 0 && soc_pcm_trigger(&substreams[peer], SNDRV_PCM_TRIGGER_START) == 0 && info.started == BIT(peer));
    boundary("actual_single_START_component_DMA_then_DAI_order", params_trigger_order());
    snprintf(name, sizeof(name), "single_START_peer_%d_after_error_%d", peer, after_error);
    params_dump(name);
    unsigned long tx_before = tx.rate, rx_before = rx.rate;
    unsigned int cache_before = codec_info.stereo_sysclk;
    struct snd_pcm_hw_params request = params;
    if (after_error) request.intervals[SNDRV_PCM_HW_PARAM_RATE - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min = 44100;
    params_clear_events();
    int ret = soc_pcm_hw_params(&substreams[!peer], &request);
    if (after_error) {
        snprintf(name, sizeof(name), "running_peer_%d_after_component_error_rejects_before_shared_mutation", peer);
        /* Parent-selected finite profile requires EINVAL before any shared mutation. */
        contract(name, ret == -EINVAL && tx.rate == tx_before && rx.rate == rx_before && codec_info.stereo_sysclk == cache_before && !params_count("CCF_SET_RATE"));
        boundary("post_error_different_rate_reaches_real_machine_CCF_then_CPU_sysclk_refusal", ret == -EBUSY && params_count("CCF_SET_RATE") == 2 && tx.rate == 11289600 && rx.rate == 11289600 && codec_info.stereo_sysclk == 11289600);
    } else {
        snprintf(name, sizeof(name), "healthy_running_peer_%d_same_rate", peer);
        boundary("healthy_running_same_rate_CPU_sysclk_gate_before_codec_PLL", ret == -EBUSY && !codec_io_calls && !params_count("CODEC_BEGIN") && !params_count("CPU_BEGIN") && tx.rate == tx_before && rx.rate == rx_before);
    }
    boundary("running_attempt_never_enters_codec_CPU_params_or_DMA_and_keeps_single_owner", !params_count("CODEC_BEGIN") && !params_count("CPU_BEGIN") && !params_count("COMPONENT_BEGIN") && info.started == BIT(peer) && !info.runtime_error);
    params_dump(name);
    if (!after_error) {
        params_clear_events();
        request.intervals[SNDRV_PCM_HW_PARAM_RATE - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min = 44100;
        int different = soc_pcm_hw_params(&substreams[!peer], &request);
        boundary("healthy_running_different_rate_retains_original_symmetry_EINVAL", different == -EINVAL && !params_event_count && tx.rate == tx_before && rx.rate == rx_before && codec_info.stereo_sysclk == cache_before);
        int second_start = soc_pcm_trigger(&substreams[!peer], SNDRV_PCM_TRIGGER_START);
        boundary("actual_second_START_keeps_CPU_component_early_gate_and_no_DMA_GO", second_start == -EBUSY && info.started == BIT(peer) && !dma_go[!peer] && !dma_running[!peer]);
        snprintf(name, sizeof(name), "refused_second_START_peer_%d", peer);
        params_dump(name);
    }
    boundary("explicit_real_single_STOP_after_running_fixture", soc_pcm_trigger(&substreams[peer], SNDRV_PCM_TRIGGER_STOP) == 0 && !info.started && info.stop_proven);
}
static void params_START_rollback(int direction)
{
    char name[100];
    params_setup();
    boundary("START_rollback_setup_actual_full_params_and_prepare", soc_pcm_hw_params(&substreams[direction], &params) == 0 && i2s_checked_prepare(&substreams[direction], &cpu_dai) == 0);
    params_clear_events();
    params_inject_start_error = true;
    int ret = soc_pcm_trigger(&substreams[direction], SNDRV_PCM_TRIGGER_START);
    boundary("actual_C3_START_prefix_and_first_errno_rollback_after_CPU_API_failure", ret == -EREMOTEIO && info.runtime_error == -EREMOTEIO && !info.started && dma_go[direction] == 1 && dma_stop[direction] == 1 && !dma_running[direction]);
    boundary("actual_failed_START_transcript_contains_component_DMA_before_CPU_DAI", params_trigger_order() && params_count("COMPONENT_TRIGGER_BEGIN") == 2);
    snprintf(name, sizeof(name), "single_START_CPU_API_error_%d", direction);
    params_dump(name);
    /* Sticky CPU fixture remains an explicit fault, with no healthy teardown claim. */
}
int main(void)
{
    for (int direction = 0; direction < 2; direction++) {
        params_success(direction);
        params_failure(direction, false);
        params_failure(direction, true);
        params_two_free_close(direction);
        params_running(direction, false);
        params_running(direction, true);
        params_START_rollback(direction);
    }
    printf("{\"contract_total\":%u,\"contract_passed\":%u,\"boundary_total\":%u,\"boundary_passed\":%u}\n", contract_total, contract_passed, boundary_total, boundary_passed);
    return boundary_passed == boundary_total && contract_passed == contract_total ? 0 : 1;
}
