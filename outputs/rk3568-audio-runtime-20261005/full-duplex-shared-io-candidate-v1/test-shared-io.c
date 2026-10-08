/* SPDX-License-Identifier: MIT */
/* Assertions use literal contracts; production functions come from extraction. */
static void reset_codec(bool enabled)
{
    static bool initialized;
    if (initialized) {
        pthread_mutex_destroy(&codec.params_lock.native);
        pthread_mutex_destroy(&codec.clk_lock.native);
    }
    memset(&codec, 0, sizeof(codec));
    memset(&component, 0, sizeof(component));
    memset(&dai, 0, sizeof(dai));
    memset(&clock_model, 0, sizeof(clock_model));
    memset(registers_model, 0, sizeof(registers_model));
    pthread_mutex_init(&codec.params_lock.native, NULL);
    pthread_mutex_init(&codec.clk_lock.native, NULL);
    initialized = true;
    codec.shared_params_enabled = enabled;
    codec.chip_ver = 5;
    codec.mclk = &clock_model;
    component.data = &codec;
    codec.component = &component;
    control.component = &component;
    dai.component = &component;
    dai.id = RK817_HIFI;
    io_count = gpio_count = clk_enable_count = clk_disable_count = 0;
    fail_at = fail_at_second = 0;
    clk_error = 0;
    io_error = -EREMOTEIO;
    io_error_second = -ENXIO;
    check_io_lock = io_without_lock = check_publish = premature_publish = false;
    pm_side_effects = 0;
}

static int path_put(int kind, long value)
{
    struct snd_ctl_elem_value request = {.value.integer.value = {value, 0}};
    if (kind == 0) return rk817_playback_path_put(&control, &request);
    if (kind == 1) return rk817_capture_path_put(&control, &request);
    return rk817_resume_path_put(&control, &request);
}

static void controls_gate(void)
{
    for (int kind = 0; kind < 3; kind++) {
        for (int owner = -1; owner < 2; owner++) {
            reset_codec(true);
            if (owner < 0) codec.shared_params.pending = &streams[0];
            else codec.shared_params.owner[owner] = &streams[owner];
            int ret = path_put(kind, 1);
            expect("changed_control_busy_before_all_IO", ret == -EBUSY && !io_count &&
                   !clk_enable_count && !clk_disable_count && !gpio_count &&
                   !codec.playback_path && !codec.capture_path && !codec.resume_path);
            ret = path_put(kind, 0);
            expect("same_control_even_busy_no_IO", ret == 0 && !io_count && !clk_enable_count);
        }
        reset_codec(true);
        codec.params_error = -ENOSPC;
        expect("same_control_FAULT_no_IO_no_recovery", path_put(kind, 0) == 0 &&
               codec.params_error == -ENOSPC && !io_count && !clk_enable_count);
        expect("changed_control_FAULT_returns_first_error", path_put(kind, 1) == -ENOSPC &&
               !io_count && !clk_enable_count);
        reset_codec(true);
        expect("invalid_negative_control_before_IO", path_put(kind, -1) == -EINVAL &&
               !io_count && !clk_enable_count && !codec.playback_path && !codec.capture_path);
        reset_codec(true);
        expect("invalid_large_control_before_IO", path_put(kind, 11) == -EINVAL &&
               !io_count && !clk_enable_count && !codec.playback_path && !codec.capture_path);
    }
    reset_codec(false);
    codec.shared_params.pending = &streams[0];
    expect("legacy_control_ignores_new_owner_fields", path_put(0, SPK_PATH) == 0 && io_count > 0);
}

static void path_enable_faults(int stream, long target, bool ext, bool split, bool differential,
                               bool oldchip, bool loopback, bool pdm)
{
    reset_codec(true);
    codec.use_ext_amplifier = ext;
    codec.out_l2spk_r2hp = split;
    codec.mic_in_differential = differential;
    codec.adc_for_loopback = loopback;
    codec.pdmdata_out_enable = pdm;
    codec.chip_ver = oldchip ? 4 : 5;
    check_io_lock = check_publish = true;
    wanted_old_path = 0;
    watched_stream = stream;
    int ret = path_put(stream, target);
    unsigned int writes = io_count;
    expect("successful_path_lease_and_path_publish", ret == 0 && clock_model.references == 1 &&
           (stream ? codec.clk_capture : codec.clk_playback) == 1 &&
           (stream ? codec.capture_path : codec.playback_path) == target &&
           !codec.params_error && !io_without_lock && !premature_publish && !MODEL_RETAINED(stream));
    for (unsigned int failure = 1; failure <= writes; failure++) {
        reset_codec(true);
        codec.use_ext_amplifier = ext;
        codec.out_l2spk_r2hp = split;
        codec.mic_in_differential = differential;
        codec.adc_for_loopback = loopback;
        codec.pdmdata_out_enable = pdm;
        codec.chip_ver = oldchip ? 4 : 5;
        fail_at = failure;
        check_io_lock = check_publish = true;
        wanted_old_path = 0;
        watched_stream = stream;
        ret = path_put(stream, target);
        expect("each_enable_IO_error_stops_and_retains_actual_lease", ret == -EREMOTEIO &&
               io_count == failure && clock_model.references == 1 && !clk_disable_count &&
               !(stream ? codec.clk_capture : codec.clk_playback) &&
               !(stream ? codec.capture_path : codec.playback_path) &&
               codec.params_error == -EREMOTEIO && !io_without_lock && !premature_publish && MODEL_RETAINED(stream));
        unsigned int saved = io_count;
        expect("faulted_path_retry_cannot_rewrite_or_reenable", path_put(stream, target) == -EREMOTEIO &&
               io_count == saved && clk_enable_count == 1);
    }
}

static void path_faults(void)
{
    for (int stream = 0; stream < 2; stream++) {
        reset_codec(true);
        clk_error = -ENXIO;
        expect("MCLK_error_before_codec_IO_or_publish", path_put(stream, stream ? MAIN_MIC : SPK_PATH) == -ENXIO &&
               !io_count && !clock_model.references && !codec.playback_path && !codec.capture_path &&
               !codec.clk_playback && !codec.clk_capture && !codec.params_error && !MODEL_RETAINED(stream));
    }
    for (int stream = 0; stream < 2; stream++) {
        reset_codec(true);
        long active = stream ? MAIN_MIC : SPK_PATH;
        long target = stream ? HANDS_FREE_MIC : HP_PATH;
        if (stream) { codec.capture_path = active; codec.clk_capture = 1; }
        else { codec.playback_path = active; codec.clk_playback = 1; }
        clock_model.references = 1;
        int ret = path_put(stream, target);
        unsigned int writes = io_count;
        expect("active_path_change_keeps_single_lease", ret == 0 && !clk_enable_count && !clk_disable_count &&
               clock_model.references == 1 && (stream ? codec.capture_path : codec.playback_path) == target);
        for (unsigned int failure = 1; failure <= writes; failure++) {
            reset_codec(true);
            if (stream) { codec.capture_path = active; codec.clk_capture = 1; }
            else { codec.playback_path = active; codec.clk_playback = 1; }
            clock_model.references = 1;
            fail_at = failure;
            ret = path_put(stream, target);
            expect("active_path_failure_preserves_old_path_and_single_lease", ret == -EREMOTEIO && io_count == failure &&
                   !clk_enable_count && !clk_disable_count && clock_model.references == 1 &&
                   (stream ? codec.capture_path : codec.playback_path) == active &&
                   codec.params_error == -EREMOTEIO && !MODEL_RETAINED(stream));
        }
    }
    for (long path = 1; path <= 10; path++)
        path_enable_faults(0, path, false, false, false, false, false, false);
    path_enable_faults(0, SPK_PATH, true, false, false, false, false, false);
    path_enable_faults(0, SPK_PATH, false, true, false, true, false, false);
    path_enable_faults(0, SPK_HP, true, false, false, false, false, false);
    for (long path = 1; path <= 3; path++)
        path_enable_faults(1, path, false, false, false, false, false, false);
    path_enable_faults(1, MAIN_MIC, false, false, true, true, false, true);
    path_enable_faults(1, HANDS_FREE_MIC, false, false, false, false, true, false);
    path_enable_faults(1, MAIN_MIC, false, false, false, false, true, false);

    for (int stream = 0; stream < 2; stream++) {
        reset_codec(true);
        long active = stream ? MAIN_MIC : SPK_PATH;
        if (stream) { codec.capture_path = active; codec.clk_capture = 1; }
        else { codec.playback_path = active; codec.clk_playback = 1; }
        clock_model.references = 1;
        int ret = path_put(stream, 0);
        unsigned int writes = io_count;
        expect("successful_OFF_powers_then_releases_lease", ret == 0 && writes > 0 &&
               !clock_model.references && clk_disable_count == 1 &&
               !(stream ? codec.capture_path : codec.playback_path));
        for (unsigned int failure = 1; failure <= writes; failure++) {
            reset_codec(true);
            if (stream) { codec.capture_path = active; codec.clk_capture = 1; }
            else { codec.playback_path = active; codec.clk_playback = 1; }
            clock_model.references = 1;
            fail_at = failure;
            ret = path_put(stream, 0);
            expect("each_OFF_IO_error_preserves_path_and_lease", ret == -EREMOTEIO &&
                   io_count == failure && clock_model.references == 1 && !clk_disable_count &&
                   (stream ? codec.capture_path : codec.playback_path) == active &&
                   (stream ? codec.clk_capture : codec.clk_playback) == 1 && codec.params_error == -EREMOTEIO);
        }
    }
}

static void mute_and_shutdown(void)
{
    for (int stream = 0; stream < 2; stream++) {
        reset_codec(true);
        dai.id = RK817_VOICE;
        expect("checked_voice_mute_before_IO", MODEL_MUTE_STREAM(&dai, 1, stream) == -EINVAL && !io_count);
        reset_codec(true);
        expect("checked_mute_requires_independent_open", MODEL_MUTE_STREAM(&dai, 1, stream) == -EINVAL && !io_count);
        codec.shared_open[stream] = &streams[stream];
        expect("unmute_requires_own_params_owner", MODEL_MUTE_STREAM(&dai, 0, stream) == -EINVAL && !io_count);
        codec.shared_params.owner[stream] = &streams[stream];
        codec.shared_params.pending = &streams[1 - stream];
        expect("pending_blocks_mute_before_IO", MODEL_MUTE_STREAM(&dai, 1, stream) == -EBUSY && !io_count);
        expect("pending_blocks_unmute_before_IO", MODEL_MUTE_STREAM(&dai, 0, stream) == -EBUSY && !io_count);
        codec.shared_params.pending = NULL;
        codec.shared_params.owner[stream] = NULL;
        check_io_lock = true;
        expect("post_HW_FREE_mute_keeps_normal_cleanup", MODEL_MUTE_STREAM(&dai, 1, stream) == 0 &&
               io_count > 0 && !io_without_lock);
        reset_codec(true);
        codec.shared_open[stream] = &streams[stream];
        codec.shared_params.owner[stream] = &streams[stream];
        if (stream) codec.capture_path = MAIN_MIC;
        else codec.playback_path = SPK_PATH;
        check_io_lock = true;
        expect("owned_unmute_allowed_and_serialized", MODEL_MUTE_STREAM(&dai, 0, stream) == 0 &&
               io_count > 0 && !io_without_lock);
        reset_codec(true);
        codec.shared_open[stream] = &streams[stream];
        fail_at = 1;
        expect("mute_failure_latches_real_first_errno", MODEL_MUTE_STREAM(&dai, 1, stream) == -EREMOTEIO &&
               codec.params_error == -EREMOTEIO);
        unsigned int saved = io_count;
        codec.shared_params.owner[stream] = &streams[stream];
        expect("mute_fault_blocks_unmute_without_IO", MODEL_MUTE_STREAM(&dai, 0, stream) == -EREMOTEIO && io_count == saved);
    }
    reset_codec(true);
    codec.shared_open[1] = &streams[1];
    fail_at = 1;
    fail_at_second = 2;
    MODEL_SHUTDOWN(&streams[1], &dai);
    expect("capture_shutdown_second_errno_cannot_replace_first", io_count == 2 && codec.params_error == -EREMOTEIO && !codec.shared_open[1]);
    reset_codec(true);
    codec.shared_open[0] = &streams[0];
    expect("invalid_mute_stream_before_IO", MODEL_MUTE_STREAM(&dai, 1, 2) == -EINVAL && !io_count);
    for (int peer = 0; peer < 2; peer++) {
        for (unsigned int failure = 0; failure < 3; failure++) {
            reset_codec(true);
            codec.shared_open[1] = &streams[1];
            codec.shared_params.owner[1] = &streams[1];
            if (peer) {
                codec.shared_open[0] = &streams[0];
                codec.shared_params.owner[0] = &streams[0];
            }
            dai.rate = 48000; dai.channels = 2; dai.sample_bits = 16;
            registers_model[RK817_CODEC_DTOP_DIGEN_CLKE] = 0x0f;
            fail_at = failure;
            check_io_lock = true;
            MODEL_SHUTDOWN(&streams[1], &dai);
            expect("capture_close_pulse_preserves_peer_DAC_bits", io_count == 2 &&
                   registers_model[RK817_CODEC_DTOP_DIGEN_CLKE] == 0x0f && !io_without_lock &&
                   !codec.shared_open[1] && !codec.shared_params.owner[1] &&
                   codec.shared_open[0] == (peer ? &streams[0] : NULL) &&
                   codec.shared_params.owner[0] == (peer ? &streams[0] : NULL) &&
                   codec.params_error == (failure ? -EREMOTEIO : 0));
            unsigned int saved = io_count;
            MODEL_SHUTDOWN(&streams[1], &dai);
            expect("repeated_capture_shutdown_is_no_IO", io_count == saved);
        }
    }
    reset_codec(true);
    codec.shared_open[0] = &streams[0];
    codec.shared_params.owner[0] = &streams[0];
    codec.shared_params.pending = &streams[1];
    MODEL_SHUTDOWN(&streams[0], &dai);
    expect("shutdown_pending_keeps_own_identity_and_latches_busy", !io_count &&
           codec.shared_open[0] == &streams[0] && codec.shared_params.owner[0] == &streams[0] &&
           codec.params_error == -EBUSY);
}

static void format_control(void)
{
    reset_codec(true);
    unsigned int fmt = SND_SOC_DAIFMT_CBS_CFS | SND_SOC_DAIFMT_NB_NF | SND_SOC_DAIFMT_I2S;
    check_io_lock = true;
    expect("first_format_programming_serialized", rk817_shared_set_fmt(&dai, fmt) == 0 &&
           io_count == 1 && codec.shared_dai_fmt == fmt && !io_without_lock);
    expect("same_format_idle_no_IO", rk817_shared_set_fmt(&dai, fmt) == 0 && io_count == 1);
    codec.shared_params.pending = &streams[0];
    expect("same_format_pending_no_IO", rk817_shared_set_fmt(&dai, fmt) == 0 && io_count == 1);
    expect("invalid_format_no_IO", rk817_shared_set_fmt(&dai, fmt | SND_SOC_DAIFMT_CBM_CFM) == -EINVAL && io_count == 1);
}

static void card_pm(void)
{
    struct snd_soc_dai_ops ops[4] = {{0}};
    struct snd_soc_dai_driver drivers[4];
    struct snd_soc_dai dais[4];
    struct snd_soc_dai_link links[2] = {{0}};
    struct snd_soc_pcm_runtime rtd[2] = {{0}};
    struct snd_soc_card card = {.instantiated = true, .count = 2, .component_count = 1};
    struct device device = {.data = &card};
    card.components[0] = &component;
    for (int i = 0; i < 4; i++) {
        drivers[i].ops = &ops[i];
        dais[i] = (struct snd_soc_dai){.driver = &drivers[i], .component = &component};
        rtd[i / 2].dais[i % 2] = &dais[i];
    }
    for (int i = 0; i < 2; i++) {
        rtd[i].num_cpus = rtd[i].num_codecs = rtd[i].num_components = 1;
        rtd[i].dai_link = &links[i];
        rtd[i].components[0] = &component;
        card.rtds[i] = &rtd[i];
    }
    for (int dai_index = 0; dai_index < 4; dai_index++) {
        for (int hook = 0; hook < 6; hook++) {
            memset(ops, 0, sizeof(ops));
            void **slots[] = {&ops[dai_index].hw_params_begin, &ops[dai_index].hw_params_commit,
                &ops[dai_index].hw_params_abort, &ops[dai_index].hw_params_reuse,
                &ops[dai_index].hw_params_free_check, &ops[dai_index].hw_params_fault};
            *slots[hook] = &card;
            links[dai_index / 2].ignore_suspend = true;
            pm_side_effects = 0;
            expect("any_partial_hook_card_suspend_before_first_sideeffect", snd_soc_suspend(&device) == -EOPNOTSUPP && !pm_side_effects);
            pm_side_effects = 0;
            expect("any_partial_hook_card_poweroff_before_first_sideeffect", snd_soc_poweroff(&device) == -EOPNOTSUPP && !pm_side_effects);
            links[dai_index / 2].ignore_suspend = false;
        }
    }
    memset(ops, 0, sizeof(ops));
    pm_side_effects = 0;
    component.suspended = false;
    expect("legacy_card_suspend_original_effects", snd_soc_suspend(&device) == 0 && pm_side_effects == 19);
    pm_side_effects = 0;
    expect("legacy_card_poweroff_original_effects", snd_soc_poweroff(&device) == 0 && pm_side_effects == 3);
    card.instantiated = false;
    ops[0].hw_params_begin = &card;
    pm_side_effects = 0;
    expect("uninstantiated_card_before_managed_gate", snd_soc_suspend(&device) == 0 && snd_soc_poweroff(&device) == 0 && !pm_side_effects);
}

static void cpu_pm(void)
{
    for (int owner = -1; owner < 2; owner++) {
        struct rk_i2s_tdm_dev cpu = {.shared_params_enabled = true, .stop_proven = true,
                                    .irq_live = true, .irq_drained = true, .irq = 2};
        pthread_mutex_init(&cpu.lock, NULL);
        if (owner < 0) cpu.shared_params.pending = &streams[0];
        else cpu.shared_params.owner[owner] = &streams[owner];
        cpu_side_effects = 0;
        expect("CPU_runtime_suspend_owner_pending_before_mutation", i2s_checked_runtime_suspend(&cpu) == -EBUSY &&
               !cpu_side_effects && !cpu.power_transition && cpu.irq_live && cpu.irq_drained);
        pthread_mutex_destroy(&cpu.lock);
    }
    struct rk_i2s_tdm_dev cpu = {.shared_params_enabled = true, .stop_proven = true,
                                .configuring = true, .format_pm_release = true, .irq = 2};
    pthread_mutex_init(&cpu.lock, NULL);
    cpu_side_effects = 0;
    expect("ownerless_initial_format_PM_release_preserved", i2s_checked_runtime_suspend(&cpu) == 0 &&
           cpu_side_effects == 3 && cpu.irq_drained && !cpu.power_transition);
    pthread_mutex_destroy(&cpu.lock);
}

int main(void)
{
    controls_gate();
    path_faults();
    mute_and_shutdown();
    format_control();
    card_pm();
    cpu_pm();
    printf("{\"checks\":%u,\"passed\":%u,\"failed\":%u}\n", checked, checked - failed, failed);
    return failed ? 1 : 0;
}
