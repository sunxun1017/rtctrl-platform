/* SPDX-License-Identifier: MIT */
static void terminal_setup(void)
{
    static bool core_initialized;
    if (core_initialized) {
        pthread_mutex_destroy(&terminal_card.mutex.native);
        pthread_mutex_destroy(&terminal_snd_card.files_lock);
    }
    memset(&terminal_card, 0, sizeof(terminal_card));
    memset(&terminal_snd_card, 0, sizeof(terminal_snd_card));
    pthread_mutex_init(&terminal_card.mutex.native, NULL);
    pthread_mutex_init(&terminal_snd_card.files_lock, NULL);
    core_initialized = true;
    unbind_card_list.count = 0;
    if (!clock_native_valid) mutex_init(&codec.clk_lock);
    reset_codec(true);
    /* The inherited fixture initialized clk_lock; actual probe now owns its lifetime. */
    mutex_destroy(&codec.clk_lock);
    codec.component = NULL;
    component.regmap = NULL;
    codec.regmap = &terminal_map;
    platform.dev.data = &codec;
    component.dev = &platform.dev;
    panic_timeout = 7;
    panic_seen = panic_expected = false;
    panic_errno = 0;
    map_reads = register_controls_calls = unregister_calls = 0;
    map_read_fail_at = 0;
    map_read_error = -ENXIO;
    control_register_error = 0;
    helper_calls = disconnect_calls = cleanup_calls = file_waits = component_close_calls = 0;
    core_steps = component_remove_calls = 0;
    core_before_file_drain = close_borrow_lost = wait_has_card_lock = wait_has_params_lock = false;
    disconnect_error = close_schedule = 0;
    component_registered = true;
    component.driver = &soc_codec_dev_rk817;
    terminal_card.instantiated = true;
    terminal_card.snd_card = &terminal_snd_card;
    terminal_card.component_count = 1;
    terminal_card.components[0] = &component;
    component.card = &terminal_card;
}

static bool probe_healthy(void)
{
    int ret = rk817_probe(&component);
    expect("real_checked_probe_has_exact_one_actual_clock_ref", ret == 0 && clock_model.references == 1 &&
           codec.component == &component && component.regmap == &terminal_map);
    return ret == 0;
}

static void terminal_after_panic(void)
{
    panic_expected = false;
    /* Test-only unwind after the model nonreturning API. Production panic never returns. */
    int ret = pthread_mutex_trylock(&codec.params_lock.native);
    if (ret == EBUSY) pthread_mutex_unlock(&codec.params_lock.native);
    else if (ret == 0) pthread_mutex_unlock(&codec.params_lock.native);
    else abort();
    ret = pthread_mutex_trylock(&client_mutex.native);
    if (ret == EBUSY) pthread_mutex_unlock(&client_mutex.native);
    else if (!ret) pthread_mutex_unlock(&client_mutex.native);
    else abort();
}

static void terminal_call(int kind)
{
    if (kind == 0) rk817_remove(&component);
    else if (kind == 1) rk817_platform_shutdown(&platform);
    else rk817_platform_remove(&platform);
}

static void healthy_terminal(void)
{
    for (int kind = 0; kind < 3; kind++) {
        for (int paths = 0; paths < 4; paths++) {
            terminal_setup();
            if (!probe_healthy()) continue;
            if (paths & 1) path_put(0, SPK_PATH);
            if (paths & 2) path_put(1, MAIN_MIC);
            unsigned int before = io_count;
            unsigned int references = 1 + !!(paths & 1) + !!(paths & 2);
            expect("healthy_paths_own_actual_probe_plus_path_refs", clock_model.references == references);
            check_io_lock = true;
            terminal_call(kind);
            expect("healthy_terminal_checks_all_IO_then_releases_exact_refs", io_count > before &&
                   !clock_model.references && clk_disable_count == references &&
                   !codec.clk_playback && !codec.clk_capture && !codec.playback_path && !codec.capture_path &&
                   !MODEL_PROBE_CLOCK_OWNED && MODEL_TERMINAL_STARTED && MODEL_TERMINAL_DONE &&
                   !codec.params_error && !panic_seen && !io_without_lock);
            expect("framework_remove_or_shutdown_detaches_component_borrow", !codec.component && !component.regmap);
            unsigned int writes = io_count, disables = clk_disable_count;
            terminal_call(kind);
            expect("terminal_repeat_has_no_IO_or_clock_return", io_count == writes && clk_disable_count == disables && !clock_model.references);
            expect("terminal_control_and_format_reject_before_IO", path_put(0, 0) == -ESHUTDOWN && path_put(1, 0) == -ESHUTDOWN &&
                   path_put(2, 0) == -ESHUTDOWN && rk817_shared_set_fmt(&dai, SND_SOC_DAIFMT_CBS_CFS | SND_SOC_DAIFMT_I2S) == -ESHUTDOWN && io_count == writes);
            expect("terminal_PCM_entries_reject_before_IO", rk817_shared_startup(&streams[0], &dai) == -ESHUTDOWN &&
                   rk817_shared_free(&streams[0], &dai) == -ESHUTDOWN &&
                   rk817_shared_sysclk(&dai, 0, 12288000, SND_SOC_CLOCK_IN) == -ESHUTDOWN &&
                   MODEL_MUTE_STREAM(&dai, 1, 0) == -ESHUTDOWN && io_count == writes);
            struct snd_ctl_elem_value value = {0};
            expect("terminal_getters_and_component_PM_have_no_borrow", rk817_playback_path_get(&control, &value) == -ESHUTDOWN &&
                   rk817_capture_path_get(&control, &value) == -ESHUTDOWN && rk817_resume_path_get(&control, &value) == -ESHUTDOWN &&
                   rk817_suspend(&component) == -ESHUTDOWN && rk817_resume(&component) == -ESHUTDOWN && io_count == writes);
            if (kind != 1) {
                expect("healthy_detached_component_reprobe_opens_fresh_lifetime", rk817_probe(&component) == 0 &&
                       clock_model.references == 1 && !MODEL_TERMINAL_STARTED && !MODEL_TERMINAL_DONE && MODEL_PROBE_CLOCK_OWNED);
            } else {
                expect("shutdown_latch_rejects_accidental_rebind_before_lease_or_IO", MODEL_SHUTDOWN_STARTED &&
                       rk817_probe(&component) == -ESHUTDOWN && io_count == writes && !clock_model.references);
            }
        }
    }
}

static void unsafe_terminal(void)
{
    for (volatile int kind = 0; kind < 3; kind++) {
        for (volatile int fault = 0; fault < 10; fault++) {
            terminal_setup();
            if (!probe_healthy()) continue;
            path_put(0, SPK_PATH);
            path_put(1, MAIN_MIC);
            volatile int first = -EBUSY;
            if (fault == 0) codec.shared_open[0] = &streams[0];
            if (fault == 1) codec.shared_open[1] = &streams[1];
            if (fault == 2) codec.shared_params.pending = &streams[0];
            if (fault == 3) codec.shared_params.owner[0] = &streams[0];
            if (fault == 4) codec.shared_params.owner[1] = &streams[1];
            if (fault == 5) { codec.params_error = -ENOSPC; first = -ENOSPC; }
            if (fault == 6) { codec.mute_io_error = -EREMOTEIO; first = -EREMOTEIO; }
            if (fault == 7) { codec.retained_clock[0] = true; first = -EIO; }
            if (fault == 8) { codec.retained_clock[1] = true; first = -EIO; }
            if (fault == 9) { codec.clk_playback = 2; first = -EIO; }
            unsigned int writes = io_count;
            panic_expected = true;
            if (setjmp(panic_jump) == 0) terminal_call(kind);
            expect("unsafe_terminal_nonreturn_gate_before_IO_or_resource_release", panic_seen && panic_timeout == 0 &&
                   panic_errno == first && codec.params_error == first && io_count == writes &&
                   !clk_disable_count && clock_model.references == 3 && codec.component == &component &&
                   component.regmap == &terminal_map && unregister_calls == (kind == 2 && fault < 5 ? 1U : 0U) && !MODEL_TERMINAL_DONE);
            terminal_after_panic();
        }
    }
    for (volatile int kind = 0; kind < 3; kind++) {
        terminal_setup();
        if (!probe_healthy()) continue;
        path_put(0, SPK_PATH);
        path_put(1, MAIN_MIC);
        volatile unsigned int before = io_count;
        terminal_call(kind);
        expect("healthy_terminal_ALL_has_literal_twenty_primitive_IO", io_count - before == 20);
        unsigned int writes = 20;
        for (volatile unsigned int failure = 1; failure <= writes; failure++) {
            terminal_setup();
            if (!probe_healthy()) continue;
            path_put(0, SPK_PATH);
            path_put(1, MAIN_MIC);
            before = io_count;
            fail_at = before + failure;
            panic_expected = true;
            if (setjmp(panic_jump) == 0) terminal_call(kind);
            expect("each_terminal_powerdown_IO_failure_preserves_actual_resources", panic_seen && panic_timeout == 0 &&
                   panic_errno == -EREMOTEIO && codec.params_error == -EREMOTEIO && io_count == before + failure &&
                   clock_model.references == 3 && !clk_disable_count && codec.clk_playback == 1 && codec.clk_capture == 1 &&
                   codec.playback_path == SPK_PATH && codec.capture_path == MAIN_MIC && codec.component == &component &&
                   component.regmap == &terminal_map && unregister_calls == (kind == 2 ? 1U : 0U) && !MODEL_TERMINAL_DONE);
            terminal_after_panic();
        }
    }
}

static void probe_failures(void)
{
    for (unsigned int read = 1; read <= 2; read++) {
        terminal_setup();
        map_read_fail_at = read;
        expect("probe_read_failure_no_write_no_clock_detaches_normally", rk817_probe(&component) == -ENXIO &&
               !io_count && !clk_enable_count && !clock_model.references && !codec.component && !component.regmap && !panic_seen);
    }
    terminal_setup();
    clk_error = -ENXIO;
    expect("probe_clock_failure_no_write_no_lease_detaches_normally", rk817_probe(&component) == -ENXIO &&
           !io_count && !clock_model.references && !codec.component && !component.regmap && !panic_seen);
    terminal_setup();
    probe_healthy();
    expect("actual_probe_reset_has_literal_twelve_primitive_IO", io_count == 12);
    unsigned int reset_writes = 12;
    for (volatile unsigned int failure = 1; failure <= reset_writes; failure++) {
        terminal_setup();
        fail_at = failure;
        panic_expected = true;
        if (setjmp(panic_jump) == 0) rk817_probe(&component);
        expect("each_probe_reset_error_failstops_without_clock_or_map_release", panic_seen && panic_timeout == 0 &&
               panic_errno == -EREMOTEIO && codec.params_error == -EREMOTEIO && io_count == failure &&
               clock_model.references == 1 && !clk_disable_count && MODEL_PROBE_CLOCK_OWNED &&
               codec.component == &component && component.regmap == &terminal_map);
        terminal_after_panic();
    }
    terminal_setup();
    control_register_error = -ENOSPC;
    expect("controls_registration_error_confirmed_cleanup_returns_first_errno", rk817_probe(&component) == -ENOSPC &&
           io_count > reset_writes && !clock_model.references && clk_disable_count == 1 &&
           !codec.component && !component.regmap && !MODEL_PROBE_CLOCK_OWNED && !codec.params_error && !panic_seen);
    unsigned int cleanup_writes = 20;
    for (volatile unsigned int failure = 1; failure <= cleanup_writes; failure++) {
        terminal_setup();
        control_register_error = -ENOSPC;
        fail_at = reset_writes + failure;
        panic_expected = true;
        if (setjmp(panic_jump) == 0) rk817_probe(&component);
        expect("each_controls_cleanup_error_retains_original_errno_and_resources", panic_seen && panic_timeout == 0 &&
               panic_errno == -ENOSPC && codec.params_error == -ENOSPC && io_count == reset_writes + failure &&
               clock_model.references == 1 && !clk_disable_count && MODEL_PROBE_CLOCK_OWNED &&
               codec.component == &component && component.regmap == &terminal_map);
        terminal_after_panic();
    }
}

static void sticky_cpu_runtime(void)
{
    for (int owner = -1; owner < 2; owner++) {
        struct rk_i2s_tdm_dev cpu = {.shared_params_enabled = true, .stop_proven = true,
            .runtime_error = -EREMOTEIO, .configuring = true, .format_pm_release = true,
            .irq_live = true, .irq_drained = true, .irq = 2};
        pthread_mutex_init(&cpu.lock, NULL);
        if (owner < 0) cpu.shared_params.pending = &streams[0];
        else cpu.shared_params.owner[owner] = &streams[owner];
        cpu_side_effects = 0;
        expect("CPU_runtime_sticky_errno_precedes_owner_with_format_release", i2s_checked_runtime_suspend(&cpu) == -EREMOTEIO &&
               !cpu_side_effects && !cpu.power_transition && cpu.irq_live && cpu.irq_drained);
        pthread_mutex_destroy(&cpu.lock);
    }
}

static void terminal_release_hook(void)
{
    if (!close_schedule) return;
    if (!terminal_snd_card.shutdown || MODEL_TERMINAL_STARTED || !codec.component ||
        component.regmap != &terminal_map || clock_model.references != 3)
        close_borrow_lost = true;
    if (close_schedule == 1) {
        /* Real checked callbacks remain callable after shutdown admission latch. */
        if (rk817_shared_free(&streams[1], &dai) || MODEL_MUTE_STREAM(&dai, 1, 1))
            close_borrow_lost = true;
        MODEL_SHUTDOWN(&streams[1], &dai);
        if (codec.shared_open[1] || codec.shared_params.owner[1]) close_borrow_lost = true;
    }
    /* Component close/DMA drain and post-unlock PM occur before file_remove. */
    component_close_calls++;
    if (MODEL_TERMINAL_STARTED || !codec.component || clock_model.references != 3)
        close_borrow_lost = true;
    pthread_mutex_lock(&terminal_snd_card.files_lock);
    terminal_snd_card.files_list.count = 0;
    pthread_mutex_unlock(&terminal_snd_card.files_lock);
    close_schedule = 0;
}

static void file_drain_boundaries(void)
{
    for (int kind = 1; kind < 3; kind++) {
        for (int window = 1; window <= 2; window++) {
            terminal_setup();
            if (!probe_healthy()) continue;
            path_put(0, SPK_PATH);
            path_put(1, MAIN_MIC);
            codec.shared_open[1] = codec.shared_params.owner[1] = &streams[1];
            terminal_snd_card.files_list.count = 1;
            if (window == 2) {
                rk817_shared_free(&streams[1], &dai);
                MODEL_SHUTDOWN(&streams[1], &dai);
            }
            close_schedule = window;
            terminal_call(kind);
            expect("file_close_window_drains_before_terminal_IO_or_clock_return", file_waits == 1 &&
                   component_close_calls == 1 && !close_borrow_lost && !core_before_file_drain &&
                   !wait_has_card_lock && !wait_has_params_lock && !terminal_snd_card.files_list.count &&
                   cleanup_calls == 1 && component_remove_calls == 1 && !codec.component && !component.card &&
                   !terminal_card.snd_card && !clock_model.references && !panic_seen);
            expect("normal_unbind_false_preserves_later_machine_unregister_list_state", !terminal_card.instantiated &&
                   terminal_card.list.count == 1 && unbind_card_list.count == 1);
            mutex_lock(&client_mutex);
            snd_soc_unbind_card(&terminal_card, true);
            mutex_unlock(&client_mutex);
            expect("later_machine_unregister_deletes_unbind_list_without_second_cleanup", !terminal_card.list.count &&
                   !unbind_card_list.count && cleanup_calls == 1 && component_remove_calls == 1);
        }
    }
    terminal_setup();
    probe_healthy();
    path_put(0, SPK_PATH);
    path_put(1, MAIN_MIC);
    terminal_snd_card.files_list.count = 1;
    unsigned int before = io_count;
    panic_expected = true;
    if (!setjmp(panic_jump)) rk817_platform_shutdown(&platform);
    expect("shutdown_file_wait_timeout_failstops_without_cleanup_IO_or_release", panic_seen && panic_errno == -ETIMEDOUT &&
           panic_timeout == 0 && codec.params_error == -ETIMEDOUT && MODEL_SHUTDOWN_STARTED &&
           terminal_snd_card.shutdown && terminal_snd_card.files_list.count == 1 && terminal_card.instantiated &&
           terminal_card.snd_card == &terminal_snd_card && component.card == &terminal_card &&
           !cleanup_calls && !core_steps && io_count == before && !clk_disable_count && clock_model.references == 3 &&
           codec.component == &component && component.regmap == &terminal_map);
    terminal_after_panic();
    terminal_setup();
    probe_healthy();
    disconnect_error = -ENOSPC;
    before = io_count;
    panic_expected = true;
    if (!setjmp(panic_jump)) rk817_platform_shutdown(&platform);
    expect("disconnect_error_keeps_first_errno_and_all_component_resources", panic_seen && panic_errno == -ENOSPC &&
           codec.params_error == -ENOSPC && !terminal_snd_card.shutdown && !core_steps && !cleanup_calls &&
           io_count == before && clock_model.references == 1 && codec.component == &component && !clk_disable_count);
    terminal_after_panic();
    terminal_setup();
    probe_healthy();
    expect("helper_invalid_timeout_and_identity_reject_without_disconnect", 
           snd_soc_component_shutdown_card(&platform.dev, &soc_codec_dev_rk817, 0) == -EINVAL &&
           snd_soc_component_shutdown_card(&platform.dev, &soc_codec_dev_rk817, 5001) == -EINVAL &&
           !disconnect_calls && !cleanup_calls);
    const struct snd_soc_component_driver other = {.name = NULL};
    expect("helper_exact_driver_identity_preserves_other_component", 
           snd_soc_component_shutdown_card(&platform.dev, &other, 5000) == -EINVAL && !disconnect_calls && !cleanup_calls);
    terminal_setup();
    probe_healthy();
    codec.shared_params_enabled = false;
    rk817_platform_shutdown(&platform);
    expect("default_codec_shutdown_does_not_call_opt_in_card_helper", !helper_calls && !disconnect_calls && !cleanup_calls &&
           terminal_card.instantiated && terminal_card.snd_card == &terminal_snd_card && clock_model.references == 1);
}

int main(void)
{
    peripheral_main();
    healthy_terminal();
    unsafe_terminal();
    probe_failures();
    sticky_cpu_runtime();
    file_drain_boundaries();
    printf("{\"checks\":%u,\"passed\":%u,\"failed\":%u}\n", checked, checked - failed, failed);
    return failed ? 1 : 0;
}
