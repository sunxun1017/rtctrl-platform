/* Calls private production soc_pcm_hw_params/hw_free and real C3 START callers. */
static void shared_setup(void)
{
    reset();
    simple_cpu.clk = &tx; simple_codec.clk = &rx; /* Synthetic child CCF refs. */
    params_clear_events();
    boundary("checked_synthetic_registration_and_real_new_startup", open_both() &&
        codec_info.shared_open[0] == &substreams[0] && codec_info.shared_open[1] == &substreams[1]);
    params_clear_events();
}
static bool shared_caches(unsigned int rate)
{
    return cpu_dai.rate == rate && codec_dai.rate == rate &&
        cpu_dai.channels == (rate ? 2U : 0U) && codec_dai.channels == (rate ? 2U : 0U) &&
        cpu_dai.sample_bits == (rate ? 16U : 0U) && codec_dai.sample_bits == (rate ? 16U : 0U);
}
static bool shared_sequence(void)
{
    const char *ordered[] = {"CPU_RESERVE", "CODEC_RESERVE", "MACHINE_BEGIN",
        "CODEC_BEGIN", "CPU_BEGIN", "COMPONENT_BEGIN", "DMA_BEGIN",
        "CODEC_COMMIT", "CPU_COMMIT"};
    unsigned int next = 0;
    for (unsigned int i = 0; i < params_event_count && next < 9; i++)
        if (!strcmp(params_events[i].name, ordered[next])) next++;
    return next == 9;
}
static bool shared_start_sequence(void)
{
    const char *ordered[] = {"PCM_TRIGGER_BEGIN", "COMPONENT_TRIGGER_BEGIN",
        "CPU_COMPONENT_TRIGGER_GATE", "DMA_TRIGGER_API", "DAI_TRIGGER_BEGIN", "CPU_DAI_TRIGGER_BEGIN"};
    unsigned int next = 0;
    for (unsigned int i = 0; i < params_event_count && next < 6; i++)
        if (!strcmp(params_events[i].name, ordered[next])) next++;
    return next == 6;
}
static void shared_peer_failure(int peer, bool component)
{
    char name[130];
    shared_setup();
    boundary("first_real_whole_chain_commits_both_endpoints", soc_pcm_hw_params(&substreams[peer], &params) == 0 &&
        shared_sequence() && shared_caches(48000) && codec_pll_calls == 2);
    params_clear_events();
    params_inject_cpu_clock = !component;
    params_inject_slave_config = component;
    int ret = soc_pcm_hw_params(&substreams[!peer], &params);
    snprintf(name, sizeof(name), "peer_%d_%s_error_preserves_configured_DAI_rate", peer, component ? "component" : "CPU");
    contract(name, shared_caches(48000));
    boundary("reuse_eliminates_CPU_CCF_error_or_preserves_component_errno", component ? ret == -ENOSPC : ret == 0 && params_inject_cpu_clock);
    boundary("idle_reuse_has_zero_shared_CCF_PLL_and_codec_IO", !params_count("CCF_SET_RATE") &&
        !params_count("CCF_SET_PARENT") && !codec_io_calls && !codec_pll_calls);
    boundary("reuse_outcome_owns_only_successful_params_and_preserves_open_leases",
        info.shared_params.owner[peer] == &substreams[peer] &&
        codec_info.shared_params.owner[peer] == &substreams[peer] &&
        (component ? !info.shared_params.owner[!peer] && !codec_info.shared_params.owner[!peer] :
          info.shared_params.owner[!peer] == &substreams[!peer] && codec_info.shared_params.owner[!peer] == &substreams[!peer]) &&
        !info.configuring && !info.runtime_error && !codec_info.params_error &&
        cpu_device.usage == 2 && codec_device.usage == 2 && child_refs == 4);
    params_dump(name);
}
static void shared_two_free(int first)
{
    char name[130];
    shared_setup();
    boundary("two_params_real_callers_success", soc_pcm_hw_params(&substreams[0], &params) == 0 &&
        soc_pcm_hw_params(&substreams[1], &params) == 0);
    params_clear_events();
    boundary("first_HW_FREE_keeps_peer_tuple_at_active_two", soc_pcm_hw_free(&substreams[first]) == 0 &&
        shared_caches(48000) && snd_soc_dai_active(&cpu_dai) == 2 && snd_soc_dai_active(&codec_dai) == 2);
    boundary("last_HW_FREE_clears_three_caches_before_any_close", soc_pcm_hw_free(&substreams[!first]) == 0 &&
        shared_caches(0) && snd_soc_dai_active(&cpu_dai) == 2 && info.mclk_tx_freq == 12288000 &&
        codec_info.stereo_sysclk == 12288000 && !info.runtime_error && !codec_info.params_error);
    int a = soc_pcm_clean(&substreams[first], 0), b = soc_pcm_clean(&substreams[!first], 0);
    snprintf(name, sizeof(name), "two_HW_FREE_then_close_first_%d_clears_configuration_cache", first);
    contract(name, a == 0 && b == 0 && shared_caches(0));
    boundary("last_normal_close_keeps_old_active_zero_gate_and_balances_PM_child_refs",
        !snd_soc_dai_active(&cpu_dai) && !snd_soc_dai_active(&codec_dai) &&
        !cpu_device.usage && !codec_device.usage && !platform_device.usage && !child_refs &&
        !info.mclk_tx_freq && !info.mclk_rx_freq && !codec_info.stereo_sysclk &&
        !codec_info.shared_open[0] && !codec_info.shared_open[1]);
    params_dump(name);
}
static void shared_running(int peer)
{
    char name[140];
    shared_setup();
    boundary("running_peer_real_params_before_late_component_error", soc_pcm_hw_params(&substreams[peer], &params) == 0);
    params_inject_slave_config = true;
    boundary("late_component_error_restores_peer_without_sticky_shared_fault",
        soc_pcm_hw_params(&substreams[!peer], &params) == -ENOSPC && shared_caches(48000) &&
        !info.runtime_error && !codec_info.params_error);
    boundary("real_single_prepare_START_and_C3_component_DMA_DAI_order",
        i2s_checked_prepare(&substreams[peer], &cpu_dai) == 0 &&
        soc_pcm_trigger(&substreams[peer], SNDRV_PCM_TRIGGER_START) == 0 && info.started == BIT(peer) &&
        shared_start_sequence());
    params_clear_events();
    struct snd_pcm_hw_params request = params;
    request.intervals[SNDRV_PCM_HW_PARAM_RATE - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min = 44100;
    int ret = soc_pcm_hw_params(&substreams[!peer], &request);
    snprintf(name, sizeof(name), "running_peer_%d_after_component_error_rejects_before_shared_mutation", peer);
    contract(name, ret == -EINVAL && !params_event_count && shared_caches(48000) &&
        tx.rate == 12288000 && rx.rate == 12288000 && codec_info.stereo_sysclk == 12288000);
    params_dump(name);
    ret = soc_pcm_hw_params(&substreams[!peer], &params);
    boundary("running_same_profile_reserved_before_machine_IO_returns_EBUSY",
        ret == -EBUSY && !params_count("MACHINE_BEGIN") && !codec_io_calls && !params_count("CCF_SET_RATE"));
    params_clear_events();
    boundary("running_HW_FREE_rejected_before_owner_mute_or_DMA_release",
        soc_pcm_hw_free(&substreams[peer]) == -EBUSY && shared_caches(48000) &&
        info.shared_params.owner[peer] == &substreams[peer] && !params_event_count && info.started == BIT(peer));
    boundary("explicit_single_STOP_keeps_existing_checked_stop_contract",
        soc_pcm_trigger(&substreams[peer], SNDRV_PCM_TRIGGER_STOP) == 0 && !info.started && info.stop_proven);
}
static void shared_commit_undo(int peer)
{
    char name[90];
    shared_setup();
    boundary("commit_undo_peer_real_params", soc_pcm_hw_params(&substreams[peer], &params) == 0);
    params_clear_events();
    params_inject_commit_error = true;
    int ret = soc_pcm_hw_params(&substreams[!peer], &params);
    boundary("codec_commit_then_CPU_fault_returns_first_errno_and_undo_cache",
        ret == -EREMOTEIO && params_count("CODEC_COMMIT") == 1 && params_count("CPU_COMMIT") == 1 &&
        shared_caches(48000) && info.shared_params.owner[peer] == &substreams[peer] &&
        codec_info.shared_params.owner[peer] == &substreams[peer] &&
        !info.shared_params.owner[!peer] && !codec_info.shared_params.owner[!peer] &&
        !info.shared_params.pending && !codec_info.shared_params.pending && !info.configuring);
    boundary("commit_fault_is_sticky_without_shared_IO_or_lease_release", info.runtime_error == -EREMOTEIO &&
        !codec_io_calls && !params_count("CCF_SET_RATE") && cpu_device.usage == 2 && child_refs == 4);
    snprintf(name, sizeof(name), "codec_commit_CPU_error_peer_%d", peer);
    params_dump(name);
}
static void shared_commit_idempotence_and_window(void)
{
    shared_setup();
    boundary("duplicate_commit_setup_real_chain", soc_pcm_hw_params(&substreams[0], &params) == 0);
    struct snd_soc_dai_params_state c = info.shared_params, k = codec_info.shared_params;
    boundary("duplicate_successful_commit_does_not_undo_owner_cache_or_generation",
        i2s_shared_commit(&substreams[0], &cpu_dai, c.cookie) == -EINVAL &&
        rk817_shared_commit(&substreams[0], &codec_dai, k.cookie) == -EINVAL &&
        !memcmp(&c, &info.shared_params, sizeof(c)) && !memcmp(&k, &codec_info.shared_params, sizeof(k)) &&
        shared_caches(48000) && !info.configuring);
    boundary("commit_window_peer_prepared", i2s_checked_prepare(&substreams[0], &cpu_dai) == 0);
    params_clear_events();
    params_inject_commit_busy = true;
    int ret = soc_pcm_hw_params(&substreams[1], &params);
    boundary("CPU_failed_commit_keeps_gate_through_codec_undo_window",
        ret == -EBUSY && params_commit_window_result == -EBUSY && !dma_go[0] &&
        params_count("CODEC_COMMIT") == 1 && params_count("CPU_COMMIT") == 1 &&
        !info.shared_params.pending && !codec_info.shared_params.pending && !info.configuring &&
        !info.shared_params.owner[1] && !codec_info.shared_params.owner[1] && shared_caches(48000) &&
        !info.runtime_error && !codec_info.params_error);
    params_dump("matched_CPU_commit_failure_window");
}
static void shared_runtime_init(void)
{
    shared_setup();
    info.mclk_tx_freq = info.mclk_rx_freq = codec_info.stereo_sysclk = 0;
    simple_cpu.sysclk = simple_codec.sysclk = 12288000;
    simple_cpu.clk_direction = simple_codec.clk_direction = SND_SOC_CLOCK_IN;
    boundary("real_simple_init_dai_default_IN_fixed_positive_request_is_no_IO_no_cache",
        asoc_simple_init_dai(&cpu_dai, &simple_cpu) == 0 &&
        asoc_simple_init_dai(&codec_dai, &simple_codec) == 0 &&
        !info.mclk_tx_freq && !info.mclk_rx_freq && !codec_info.stereo_sysclk &&
        !params_count("CCF_SET_RATE") && !codec_io_calls && !info.shared_params.pending);
    simple_cpu.clk_direction = simple_codec.clk_direction = SND_SOC_CLOCK_OUT;
    boundary("real_simple_init_dai_explicit_OUT_is_validation_not_owner",
        asoc_simple_init_dai(&cpu_dai, &simple_cpu) == 0 &&
        asoc_simple_init_dai(&codec_dai, &simple_codec) == 0 && shared_caches(0) &&
        !codec_info.stereo_sysclk && !info.mclk_tx_freq);
    simple_cpu.sysclk = 11289600;
    boundary("real_runtime_init_nonprofile_positive_clock_is_rejected_without_IO",
        asoc_simple_init_dai(&cpu_dai, &simple_cpu) == -EINVAL && !codec_io_calls &&
        !params_count("CCF_SET_RATE") && !info.shared_params.pending);
    params_dump("real_runtime_init_positive_sysclk");
}
static void shared_outer_native_error_cleanup(void)
{
    shared_setup();
    boundary("outer_error_setup_two_real_params_owners",
        soc_pcm_hw_params(&substreams[0], &params) == 0 && soc_pcm_hw_params(&substreams[1], &params) == 0);
    params_clear_events();
    params_inject_slave_config = true;
    boundary("failed_reparams_restores_snapshot_owner_before_native_outer_cleanup",
        soc_pcm_hw_params(&substreams[1], &params) == -ENOSPC &&
        info.shared_params.owner[1] == &substreams[1] && codec_info.shared_params.owner[1] == &substreams[1] &&
        shared_caches(48000));
    /* Explicit native error API boundary, not extracted full pcm_native hw_params body. */
    boundary("native_error_boundary_real_HW_FREE_removes_only_failed_direction",
        soc_pcm_hw_free(&substreams[1]) == 0 && !info.shared_params.owner[1] &&
        !codec_info.shared_params.owner[1] && info.shared_params.owner[0] == &substreams[0] &&
        codec_info.shared_params.owner[0] == &substreams[0] && shared_caches(48000));
    boundary("surviving_peer_can_real_prepare_and_single_START_after_outer_free",
        i2s_checked_prepare(&substreams[0], &cpu_dai) == 0 &&
        soc_pcm_trigger(&substreams[0], SNDRV_PCM_TRIGGER_START) == 0 && info.started == 1 && dma_running[0]);
    boundary("outer_cleanup_peer_explicit_STOP_is_still_required_and_succeeds",
        soc_pcm_trigger(&substreams[0], SNDRV_PCM_TRIGGER_STOP) == 0 && !info.started && info.stop_proven);
    params_dump("native_error_boundary_real_HW_FREE");
}
static void shared_first_failure(bool codec)
{
    shared_setup();
    info.mclk_tx_freq = info.mclk_rx_freq = codec_info.stereo_sysclk = 0;
    params_inject_cpu_clock = !codec;
    params_codec_fail_at = codec ? 1 : 0;
    int ret = soc_pcm_hw_params(&substreams[0], &params);
    boundary("first_shared_chain_error_restores_software_cache_and_latches_both_faults",
        ret == -EREMOTEIO && shared_caches(0) && !info.mclk_tx_freq && !info.mclk_rx_freq &&
        !codec_info.stereo_sysclk && info.runtime_error == -EREMOTEIO && codec_info.params_error == -EREMOTEIO &&
        !info.shared_params.owner[0] && !codec_info.shared_params.owner[0] &&
        !info.shared_params.pending && !codec_info.shared_params.pending && !info.configuring);
    boundary("HW_FREE_and_close_cannot_launder_first_shared_fault_or_clock_lease",
        soc_pcm_hw_free(&substreams[0]) == 0 && info.runtime_error == -EREMOTEIO &&
        codec_info.params_error == -EREMOTEIO && info.mclks_enabled &&
        i2s_checked_prepare(&substreams[0], &cpu_dai) == -EREMOTEIO);
    params_dump(codec ? "first_codec_API_error" : "first_CPU_CCF_API_error");
}
static void shared_profile_and_cookie(void)
{
    shared_setup();
    struct snd_pcm_hw_params bad = params;
    memset(&bad.masks[SNDRV_PCM_HW_PARAM_FORMAT - SNDRV_PCM_HW_PARAM_FIRST_MASK], 0, sizeof(struct snd_mask));
    bad.masks[SNDRV_PCM_HW_PARAM_FORMAT - SNDRV_PCM_HW_PARAM_FIRST_MASK].bits[0] = BIT(SNDRV_PCM_FORMAT_S24_LE);
    boundary("unsupported_format_fails_before_shared_IO_and_reservation",
        soc_pcm_hw_params(&substreams[0], &bad) == -EINVAL && !params_count("MACHINE_BEGIN") &&
        !codec_io_calls && !info.configuring && !info.shared_params.pending);
    params_clear_events();
    boundary("profile_setup_real_params_and_prepare", soc_pcm_hw_params(&substreams[0], &params) == 0 &&
        i2s_checked_prepare(&substreams[0], &cpu_dai) == 0);
    params_clear_events();
    u64 cookie = 0, newer = 0;
    boundary("CPU_begin_freezes_whole_C3_START_and_HW_FREE_before_DMA_or_cache_changes",
        i2s_shared_begin(&substreams[1], &params, &cpu_dai, &cookie) == 0 &&
        soc_pcm_trigger(&substreams[0], SNDRV_PCM_TRIGGER_START) == -EBUSY &&
        !dma_go[0] && soc_pcm_hw_free(&substreams[0]) == -EBUSY && shared_caches(48000));
    params_clear_events();
    boundary("pending_sysclk_is_only_exact_value_validation_not_owner_authentication",
        i2s_shared_sysclk(&cpu_dai, 0, 12288000, SND_SOC_CLOCK_OUT) == 0 &&
        i2s_shared_sysclk(&cpu_dai, 0, 11289600, SND_SOC_CLOCK_OUT) == -EINVAL &&
        i2s_shared_sysclk(&cpu_dai, 0, 0, SND_SOC_CLOCK_OUT) == -EINVAL &&
        !params_count("CCF_SET_RATE") && info.mclk_tx_freq == 12288000);
    boundary("owned_apply_consumes_pending_once_and_wrong_substream_is_rejected",
        i2s_shared_hw_params(&substreams[0], &params, &cpu_dai) == -EBUSY &&
        i2s_shared_hw_params(&substreams[1], &params, &cpu_dai) == 0 &&
        i2s_shared_hw_params(&substreams[1], &params, &cpu_dai) == -EBUSY && !codec_io_calls &&
        !params_count("CCF_SET_RATE"));
    i2s_shared_abort(&substreams[1], &cpu_dai, cookie, -EINVAL, false);
    boundary("stale_abort_and_commit_cannot_overwrite_new_generation",
        i2s_shared_begin(&substreams[1], &params, &cpu_dai, &newer) == 0 && newer > cookie &&
        (i2s_shared_abort(&substreams[1], &cpu_dai, cookie, -EIO, true), true) &&
        i2s_shared_commit(&substreams[1], &cpu_dai, cookie) == -EINVAL &&
        info.shared_params.pending == &substreams[1] && info.configuring && !info.runtime_error);
    i2s_shared_abort(&substreams[1], &cpu_dai, newer, -EINVAL, false);
    i2s_shared_abort(&substreams[1], &cpu_dai, newer, -EINVAL, true);
    info.shared_params.generation = ~(u64)0;
    boundary("CPU_cookie_exhaustion_is_EOVERFLOW_without_wrap_or_reservation",
        i2s_shared_begin(&substreams[1], &params, &cpu_dai, &newer) == -EOVERFLOW &&
        info.shared_params.generation == ~(u64)0 && !info.configuring && !info.runtime_error);
    info.shared_params.generation = 100;
    codec_info.shared_params.generation = ~(u64)0;
    boundary("codec_begin_exhaustion_aborts_successful_CPU_prefix_without_shared_IO",
        soc_pcm_hw_params(&substreams[1], &params) == -EOVERFLOW && !info.configuring &&
        !info.shared_params.pending && !codec_info.shared_params.pending && shared_caches(48000) &&
        !params_count("CCF_SET_RATE") && !codec_io_calls);
    params_dump("finite_profile_cookie_reservation");
}
static void shared_default_partial_voice(void)
{
    shared_setup();
    struct snd_soc_dai_ops partial = checked_cpu_ops;
    partial.hw_params_begin = NULL;
    cpu_driver.ops = &partial;
    boundary("any_partial_new_hook_rejected_before_legacy_machine_IO",
        soc_pcm_hw_params(&substreams[0], &params) == -EINVAL && !params_event_count && shared_caches(0));
    cpu_driver.ops = &checked_cpu_ops;
    codec_driver.ops = &codec_ops;
    boundary("mixed_checked_and_default_endpoint_rejected_before_IO",
        soc_pcm_hw_params(&substreams[0], &params) == -EINVAL && !params_event_count && !info.configuring);
    codec_driver.ops = &checked_codec_ops;
    codec_dai.id = RK817_VOICE;
    boundary("checked_voice_startup_format_clock_and_params_all_reject_without_IO",
        rk817_shared_startup(&substreams[0], &codec_dai) == -EINVAL &&
        rk817_shared_set_fmt(&codec_dai, info.shared_dai_fmt) == -EINVAL &&
        rk817_shared_sysclk(&codec_dai, 0, 12288000, SND_SOC_CLOCK_IN) == -EINVAL &&
        soc_pcm_hw_params(&substreams[0], &params) == -EINVAL && !codec_io_calls &&
        !params_count("CCF_SET_RATE") && !info.configuring);
    codec_dai.id = RK817_HIFI;
    info.shared_params_enabled = codec_info.shared_params_enabled = false;
    cpu_driver.ops = &cpu_ops;
    codec_driver.ops = &codec_ops;
    params_clear_events();
    boundary("default_empty_hooks_keep_real_legacy_hw_params_and_HW_FREE_behavior",
        soc_pcm_hw_params(&substreams[0], &params) == 0 && shared_caches(48000) &&
        soc_pcm_hw_free(&substreams[0]) == 0 && shared_caches(48000));
    params_dump("default_empty_hooks");
}
static void shared_free_errors(int kind)
{
    shared_setup();
    boundary("free_error_setup_real_owner", soc_pcm_hw_params(&substreams[0], &params) == 0);
    params_clear_events();
    params_inject_codec_release = kind == 0;
    params_mute_error = kind == 1 ? -EPIPE : 0;
    params_component_free_error = kind == 2 ? -ENOSPC : kind == 1 ? -ENOSPC : 0;
    params_link_free_error = kind == 3 ? -EPROTO : 0;
    int ret = soc_pcm_hw_free(&substreams[0]);
    int expected = kind == 0 ? -ENXIO : kind == 1 ? -EPIPE : kind == 2 ? -ENOSPC : -EPROTO;
    boundary("late_release_mute_component_or_link_error_latches_both_first_errno",
        ret == expected && info.runtime_error == expected && codec_info.params_error == expected &&
        cpu_device.usage == 2 && codec_device.usage == 2 && child_refs == 4 && info.mclks_enabled);
    boundary("half_release_or_full_resource_prefix_is_reported_as_actual_fault_state",
        kind == 0 ? !info.shared_params.owner[0] && codec_info.shared_params.owner[0] == &substreams[0] &&
          cpu_dai.rate == 0 && codec_dai.rate == 48000 && !params_count("COMPONENT_FREE_API") :
          shared_caches(0) && params_count("COMPONENT_FREE_API") == 3 && params_count("LINK_FREE_API") == 1);
    boundary("release_fault_blocks_future_whole_C3_START_without_pretending_joint_STOP",
        soc_pcm_trigger(&substreams[0], SNDRV_PCM_TRIGGER_START) == expected && !dma_go[0] && !info.started);
    char name[50]; snprintf(name, sizeof(name), "HW_FREE_error_kind_%d", kind); params_dump(name);
}
static void shared_single_START_rollback(void)
{
    shared_setup();
    boundary("single_START_error_setup_actual_params_prepare", soc_pcm_hw_params(&substreams[0], &params) == 0 &&
        i2s_checked_prepare(&substreams[0], &cpu_dai) == 0);
    params_clear_events();
    params_inject_start_error = true;
    boundary("C3_single_START_API_failure_retains_first_errno_and_actual_DMA_prefix_rollback",
        soc_pcm_trigger(&substreams[0], SNDRV_PCM_TRIGGER_START) == -EREMOTEIO &&
        info.runtime_error == -EREMOTEIO && !info.started && dma_go[0] == 1 &&
        dma_stop[0] == 1 && !dma_running[0] && shared_start_sequence());
    params_dump("single_START_C3_failure");
}
int main(void)
{
    for (int direction = 0; direction < 2; direction++) {
        shared_peer_failure(direction, false);
        shared_peer_failure(direction, true);
        shared_two_free(direction);
        shared_running(direction);
        shared_commit_undo(direction);
    }
    shared_first_failure(false); shared_first_failure(true);
    shared_commit_idempotence_and_window(); shared_runtime_init();
    shared_outer_native_error_cleanup();
    shared_profile_and_cookie(); shared_default_partial_voice();
    for (int kind = 0; kind < 4; kind++) shared_free_errors(kind);
    shared_single_START_rollback();
    /* Prior four red contracts keep checked whole-params configuration premises. */
    test_sequential_START(0); test_sequential_START(1);
    test_concurrent_START(); test_hypothetical_dual_STOP();
    printf("{\"contract_total\":%u,\"contract_passed\":%u,\"boundary_total\":%u,\"boundary_passed\":%u}\n",
        contract_total, contract_passed, boundary_total, boundary_passed);
    return boundary_passed == boundary_total && contract_total == 12 && contract_passed == 8 ? 1 : 2;
}
