/* SPDX-License-Identifier: MIT */
static struct device cpu_device, codec_device, platform_device;
static struct clk tx, rx, parent;
static struct regmap map;
static struct rk_i2s_tdm_dev info;
static struct snd_soc_dai cpu_dai, codec_dai;
static struct snd_soc_component cpu_component, codec_component, platform_component;
static struct rk817_codec_priv codec_info;
static struct snd_pcm_substream substreams[2];
static struct snd_pcm_runtime runtimes[2];
static struct snd_pcm_hw_params params;
static struct asoc_simple_dai simple_cpu, simple_codec;
static struct simple_dai_props properties;
static struct asoc_simple_priv simple_priv;
static struct snd_soc_card card;
static struct snd_soc_pcm_runtime rtd;
static struct snd_soc_component *components[3];
static struct snd_soc_dai *dais[2];
static bool dma_running[2];
static unsigned int dma_go[2], dma_stop[2], codec_start[2];
static int codec_fail_stream = -1;
static int codec_startup_fail_stream = -1;
static int close_at_failed_open_gap = -1;
static int close_at_pm_failure = -1;
static bool concurrent_cut;
static pthread_barrier_t dma_barrier;
static bool initialized;
static unsigned int contract_total, contract_passed, boundary_total, boundary_passed;

/* Explicit platform DMA API model. It does not execute PL330 or allocate DMA. */
static int platform_trigger(struct snd_soc_component *component, struct snd_pcm_substream *ss, int cmd)
{
    (void)component;
    if (cmd == SNDRV_PCM_TRIGGER_START || cmd == SNDRV_PCM_TRIGGER_RESUME || cmd == SNDRV_PCM_TRIGGER_PAUSE_RELEASE) {
        dma_go[ss->stream]++;
        dma_running[ss->stream] = true;
        if (concurrent_cut) pthread_barrier_wait(&dma_barrier);
    } else {
        dma_stop[ss->stream]++;
        dma_running[ss->stream] = false;
    }
    return 0;
}

/* Codec trigger has no real production callback here; inject dispatcher failure. */
static int codec_trigger(struct snd_pcm_substream *ss, int cmd, struct snd_soc_dai *dai)
{
    (void)dai;
    if (cmd == SNDRV_PCM_TRIGGER_START) {
        codec_start[ss->stream]++;
        if (codec_fail_stream == ss->stream) return -EPIPE;
    }
    return 0;
}
static int codec_startup(struct snd_pcm_substream *ss, struct snd_soc_dai *dai)
{
    (void)dai;
    return ss->stream == codec_startup_fail_stream ? -EPIPE : 0;
}

/* A permitted deterministic scheduling cut, not a production-function rewrite. */
static void model_mutex_unlock(pthread_mutex_t *lock)
{
    pthread_mutex_unlock(lock);
    if (close_at_failed_open_gap >= 0) {
        int peer = close_at_failed_open_gap;
        close_at_failed_open_gap = -1;
        soc_pcm_clean(&substreams[peer], 0);
    }
}
static void pm_runtime_put_noidle(struct device *dev)
{
    dev->noidle_puts++;
    if (dev->usage) dev->usage--;
    if (close_at_pm_failure >= 0) {
        int peer = close_at_pm_failure;
        close_at_pm_failure = -1;
        soc_pcm_clean(&substreams[peer], 0);
    }
}

static const struct snd_soc_dai_ops cpu_ops = {
    .set_sysclk = rockchip_i2s_tdm_set_sysclk,
    .startup = rockchip_i2s_tdm_startup,
    .shutdown = rockchip_i2s_tdm_shutdown,
    .trigger = rockchip_i2s_tdm_trigger,
};
static const struct snd_soc_dai_ops codec_ops = {.set_sysclk = rk817_set_dai_sysclk, .trigger = codec_trigger, .startup = codec_startup};
static struct snd_soc_dai_driver cpu_driver = {.ops = &cpu_ops, .symmetric_rates = true}, codec_driver = {.ops = &codec_ops};
static const struct snd_soc_component_driver cpu_component_ops = {.trigger = i2s_checked_component_trigger};
static const struct snd_soc_component_driver codec_component_ops = {0};
static const struct snd_soc_component_driver platform_component_ops = {.trigger = platform_trigger};
static const struct snd_soc_ops link_ops = {.startup = asoc_simple_startup, .shutdown = asoc_simple_shutdown};
static struct snd_soc_dai_link link = {.ops = &link_ops, .name = "actual-simple-link"};

static void boundary(const char *name, bool condition)
{
    boundary_total++;
    boundary_passed += condition;
    printf("BOUNDARY_CHECK %s %u\n", name, condition);
}
static void contract(const char *name, bool condition)
{
    contract_total++;
    contract_passed += condition;
    printf("CONTRACT_CHECK %s %u\n", name, condition);
}

static void reset(void)
{
    if (initialized) {
        pthread_mutex_destroy(&info.lock);
        pthread_mutex_destroy(&card.pcm_mutex);
    }
    memset(&info, 0, sizeof(info));
    memset(&card, 0, sizeof(card));
    memset(&map, 0, sizeof(map));
    memset(&cpu_device, 0, sizeof(cpu_device));
    memset(&codec_device, 0, sizeof(codec_device));
    memset(&platform_device, 0, sizeof(platform_device));
    memset(&cpu_dai, 0, sizeof(cpu_dai));
    memset(&codec_dai, 0, sizeof(codec_dai));
    memset(&cpu_component, 0, sizeof(cpu_component));
    memset(&codec_component, 0, sizeof(codec_component));
    memset(&platform_component, 0, sizeof(platform_component));
    memset(substreams, 0, sizeof(substreams));
    memset(runtimes, 0, sizeof(runtimes));
    memset(dma_running, 0, sizeof(dma_running));
    memset(dma_go, 0, sizeof(dma_go));
    memset(dma_stop, 0, sizeof(dma_stop));
    memset(codec_start, 0, sizeof(codec_start));
    memset(&params, 0, sizeof(params));
    memset(&simple_cpu, 0, sizeof(simple_cpu));
    memset(&simple_codec, 0, sizeof(simple_codec));
    memset(&rtd, 0, sizeof(rtd));
    memset(&tx, 0, sizeof(tx));
    memset(&rx, 0, sizeof(rx));
    memset(&parent, 0, sizeof(parent));
    pthread_mutex_init(&info.lock, NULL);
    pthread_mutex_init(&card.pcm_mutex, NULL);
    initialized = true;
    cpu_device.data = &info;
    codec_device.data = &codec_info;
    info.dev = &cpu_device;
    info.regmap = &map;
    info.regs = map.hw;
    info.irq = 1;
    info.mclk_tx = &tx;
    info.mclk_rx = &rx;
    info.mclk_tx_freq = info.mclk_rx_freq = 12288000;
    info.bclk_fs = 64;
    info.lrck_ratio = 1;
    info.clk_trcm = I2S_CKR_TRCM_TXONLY;
    info.checked_lifecycle = info.is_master_mode = true;
    info.ready = info.stop_proven = info.irq_drained = true;
    info.mclks_enabled = info.hclk_enabled = info.irq_live = true;
    tx.parent = rx.parent = &parent;
    tx.rate = rx.rate = 12288000;
    codec_info.stereo_sysclk = 12288000;
    cpu_component.dev = &cpu_device;
    cpu_component.name = "cpu";
    cpu_component.driver = &cpu_component_ops;
    codec_component.dev = &codec_device;
    codec_component.name = "codec";
    codec_component.driver = &codec_component_ops;
    platform_component.dev = &platform_device;
    platform_component.name = "platform-api-model";
    platform_component.driver = &platform_component_ops;
    cpu_dai.dev = &cpu_device;
    cpu_dai.driver = &cpu_driver;
    cpu_dai.component = &cpu_component;
    cpu_dai.name = "cpu-dai";
    cpu_dai.playback_dma_data = &info.playback_dma_data;
    cpu_dai.capture_dma_data = &info.capture_dma_data;
    codec_dai.dev = &codec_device;
    codec_dai.driver = &codec_driver;
    codec_dai.component = &codec_component;
    codec_dai.name = "codec-dai";
    properties.cpu_dai = &simple_cpu;
    properties.codec_dai = &simple_codec;
    properties.mclk_fs = 256;
    simple_priv.dai_props = &properties;
    card.data = &simple_priv;
    components[0] = &cpu_component;
    components[1] = &codec_component;
    components[2] = &platform_component;
    dais[0] = &cpu_dai;
    dais[1] = &codec_dai;
    rtd.dev = &cpu_device;
    rtd.card = &card;
    rtd.dai_link = &link;
    rtd.components = components;
    rtd.dais = dais;
    rtd.num_components = 3;
    rtd.num_cpus = rtd.num_codecs = 1;
    for (int stream = 0; stream < 2; stream++) {
        substreams[stream].stream = stream;
        substreams[stream].runtime = &runtimes[stream];
        substreams[stream].private_data = &rtd;
    }
    params.intervals[SNDRV_PCM_HW_PARAM_CHANNELS - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min = 2;
    params.intervals[SNDRV_PCM_HW_PARAM_RATE - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min = 48000;
    params.masks[SNDRV_PCM_HW_PARAM_FORMAT].bits[0] = BIT(SNDRV_PCM_FORMAT_S16_LE);
    operations = reads = writes = clock_calls = fault_at = pm_error = 0;
    diagnostics = irq_sync_calls = 0;
    codec_fail_stream = -1;
    codec_startup_fail_stream = close_at_failed_open_gap = -1;
    close_at_pm_failure = -1;
    model_constraint_error = 0;
    child_enable_calls = child_disable_calls = 0;
    child_refs = 0;
    concurrent_cut = false;
}

static bool open_both(void)
{
    return soc_pcm_open(&substreams[0]) == 0 && soc_pcm_open(&substreams[1]) == 0 &&
        info.substreams[0] == &substreams[0] && info.substreams[1] == &substreams[1] &&
        snd_soc_dai_active(&cpu_dai) == 2 && snd_soc_dai_active(&codec_dai) == 2 && cpu_device.usage == 2;
}

static bool configure_both(void)
{
    for (int stream = 0; stream < 2; stream++) {
        /* Exact simple clock request + CPU params, not full codec/ASoC hw_params. */
        if (asoc_simple_hw_params(&substreams[stream], &params) ||
            rockchip_i2s_tdm_hw_params(&substreams[stream], &params, &cpu_dai)) return false;
    }
    for (int stream = 0; stream < 2; stream++)
        if (i2s_checked_prepare(&substreams[stream], &cpu_dai)) return false;
    return !info.started && info.stop_proven && !info.runtime_error;
}

static void test_one_close(int closing, bool peer_running)
{
    char name[160];
    int peer = !closing;
    reset();
    boundary("actual_open_both_idle", open_both());
    boundary("actual_simple_cpu_same_params_and_prepare", configure_both());
    if (peer_running) boundary("first_direction_START_before_peer_close", soc_pcm_trigger(&substreams[peer], SNDRV_PCM_TRIGGER_START) == 0);
    unsigned int old_started = info.started;
    unsigned int old_xfer = map.hw[I2S_XFER / 4];
    unsigned int old_irq = map.hw[I2S_INTCR / 4];
    unsigned int old_dma = map.hw[I2S_DMACR / 4];
    unsigned int old_diag = diagnostics;
    unsigned int old_sync = irq_sync_calls;
    int ret = soc_pcm_clean(&substreams[closing], 0);
    snprintf(name, sizeof(name), "close_%d_peer_%s_no_diagnostic", closing, peer_running ? "running" : "idle");
    contract(name, ret == 0 && diagnostics == old_diag);
    snprintf(name, sizeof(name), "close_%d_peer_%s_retains_codec_request", closing, peer_running ? "running" : "idle");
    contract(name, codec_info.stereo_sysclk == 12288000);
    boundary("one_close_keeps_cpu_requests_and_nonsticky", info.mclk_tx_freq == 12288000 && info.mclk_rx_freq == 12288000 && !info.runtime_error);
    boundary("actual_deactivate_keeps_peer_active_and_balances_PM", snd_soc_dai_active(&cpu_dai) == 1 && snd_soc_dai_active(&codec_dai) == 1 && cpu_device.usage == 1 && codec_device.usage == 1 && platform_device.usage == 1);
    boundary("real_shutdown_removes_only_own_substream_and_drains_IRQ", !info.substreams[closing] && info.substreams[peer] == &substreams[peer] && irq_sync_calls == old_sync + 1 && !info.irq_drained);
    boundary("one_close_preserves_peer_started_and_XFER", info.started == old_started && map.hw[I2S_XFER / 4] == old_xfer && (!peer_running || (map.hw[I2S_DMACR / 4] == old_dma && map.hw[I2S_INTCR / 4] == old_irq && dma_running[peer])));
    if (peer_running) boundary("peer_final_STOP_success", soc_pcm_trigger(&substreams[peer], SNDRV_PCM_TRIGGER_STOP) == 0);
    old_diag = diagnostics;
    boundary("last_close_success_after_actual_deactivate", soc_pcm_clean(&substreams[peer], 0) == 0 && diagnostics == old_diag && !info.mclk_tx_freq && !info.mclk_rx_freq && !codec_info.stereo_sysclk && !snd_soc_dai_active(&cpu_dai) && !snd_soc_dai_active(&codec_dai) && !cpu_device.usage && !info.started && info.stop_proven && info.irq_drained);
}

static void test_sequential_START(int first)
{
    char name[100];
    int second = !first;
    reset();
    boundary("sequential_open_configure", open_both() && configure_both());
    int first_ret = soc_pcm_trigger(&substreams[first], SNDRV_PCM_TRIGGER_START);
    int second_ret = soc_pcm_trigger(&substreams[second], SNDRV_PCM_TRIGGER_START);
    snprintf(name, sizeof(name), "sequential_first_%d_second_normal_START", first);
    contract(name, first_ret == 0 && second_ret == 0 && info.started == 3 && dma_running[0] && dma_running[1]);
    boundary("second_START_EBUSY_before_platform_GO_and_keeps_peer", first_ret == 0 && second_ret == -EBUSY && info.started == BIT(first) && dma_go[first] == 1 && !dma_go[second] && dma_running[first] && !dma_running[second] && !info.runtime_error);
    boundary("single_peer_STOP_still_clears_shared_MMIO", soc_pcm_trigger(&substreams[first], SNDRV_PCM_TRIGGER_STOP) == 0 && !info.started && info.stop_proven && !dma_running[first]);
}

struct concurrent_arg { int stream, result; };
static void *start_thread(void *data)
{
    struct concurrent_arg *arg = data;
    arg->result = soc_pcm_trigger(&substreams[arg->stream], SNDRV_PCM_TRIGGER_START);
    return NULL;
}

static void test_concurrent_START(void)
{
    reset();
    boundary("concurrent_open_configure", open_both() && configure_both());
    pthread_t threads[2];
    struct concurrent_arg args[2] = {{0, 777}, {1, 777}};
    pthread_barrier_init(&dma_barrier, NULL, 2);
    concurrent_cut = true;
    int create0 = pthread_create(&threads[0], NULL, start_thread, &args[0]);
    int create1 = pthread_create(&threads[1], NULL, start_thread, &args[1]);
    if (create0 || create1) { fprintf(stderr, "pthread_create failure\n"); exit(2); }
    pthread_join(threads[0], NULL);
    pthread_join(threads[1], NULL);
    concurrent_cut = false;
    pthread_barrier_destroy(&dma_barrier);
    int winner = args[0].result == 0 ? 0 : 1;
    int loser = !winner;
    contract("concurrent_two_normal_START_commit_both", args[0].result == 0 && args[1].result == 0 && info.started == 3 && dma_running[0] && dma_running[1]);
    boundary("both_component_admissions_reach_platform_DMA_GO", dma_go[0] == 1 && dma_go[1] == 1);
    boundary("real_DAI_gate_rejects_one_and_prefix_rollback_only_loser", args[winner].result == 0 && args[loser].result == -EBUSY && info.started == BIT(winner) && dma_running[winner] && !dma_running[loser] && !dma_stop[winner] && dma_stop[loser] == 1 && !info.runtime_error);
    boundary("winner_remains_live_until_explicit_STOP", soc_pcm_trigger(&substreams[winner], SNDRV_PCM_TRIGGER_STOP) == 0 && !info.started && info.stop_proven && !dma_running[winner]);
}

static void test_codec_failure_rollback(int stream)
{
    reset();
    boundary("rollback_open_configure", open_both() && configure_both());
    codec_fail_stream = stream;
    int ret = soc_pcm_trigger(&substreams[stream], SNDRV_PCM_TRIGGER_START);
    boundary("codec_injected_failure_after_real_CPU_commit_is_first_errno", ret == -EPIPE && codec_start[stream] == 1);
    boundary("real_failed_DAI_prefix_STOP_then_component_STOP", !info.started && info.stop_proven && !dma_running[stream] && dma_go[stream] == 1 && dma_stop[stream] == 1 && !dma_go[!stream] && !dma_stop[!stream] && !info.runtime_error);
}

static void test_failed_peer_open_rollback(int peer)
{
    char name[120];
    int failed = !peer;
    reset();
    boundary("failed_open_peer_actual_open_configure", soc_pcm_open(&substreams[peer]) == 0 &&
        asoc_simple_hw_params(&substreams[peer], &params) == 0 &&
        rockchip_i2s_tdm_hw_params(&substreams[peer], &params, &cpu_dai) == 0 &&
        i2s_checked_prepare(&substreams[peer], &cpu_dai) == 0);
    boundary("failed_open_peer_START", soc_pcm_trigger(&substreams[peer], SNDRV_PCM_TRIGGER_START) == 0);
    unsigned int old_diag = diagnostics;
    int ret = soc_pcm_open(&substreams[failed]);
    snprintf(name, sizeof(name), "failed_open_peer_%d_rollback_retains_codec_request", peer);
    contract(name, codec_info.stereo_sysclk == 12288000);
    snprintf(name, sizeof(name), "failed_open_peer_%d_rollback_has_only_startup_diagnostic", peer);
    contract(name, diagnostics == old_diag + 1);
    boundary("failed_open_actual_mark_unwind_keeps_peer_owner_and_activity", ret == -EBUSY &&
        info.substreams[peer] == &substreams[peer] && !info.substreams[failed] &&
        info.started == BIT(peer) && dma_running[peer] && !info.runtime_error &&
        snd_soc_dai_active(&cpu_dai) == 1 && snd_soc_dai_active(&codec_dai) == 1 &&
        cpu_device.usage == 1 && codec_device.usage == 1 && platform_device.usage == 1 &&
        !substreams[failed].component_opened &&
        info.mclk_tx_freq == 12288000 && info.mclk_rx_freq == 12288000);
    boundary("failed_open_peer_STOP_still_works", soc_pcm_trigger(&substreams[peer], SNDRV_PCM_TRIGGER_STOP) == 0);
}

static void test_hypothetical_dual_STOP(void)
{
    reset();
    boundary("hypothetical_dual_open_configure", open_both() && configure_both());
    /* Deliberately unreachable by v12 START: counterexample to merely removing gates. */
    info.started = 3;
    info.stop_proven = false;
    dma_running[0] = dma_running[1] = true;
    map.cache[I2S_XFER / 4] = map.hw[I2S_XFER / 4] = I2S_XFER_TXS_START | I2S_XFER_RXS_START;
    int ret0 = soc_pcm_trigger(&substreams[0], SNDRV_PCM_TRIGGER_STOP);
    int ret1 = soc_pcm_trigger(&substreams[1], SNDRV_PCM_TRIGGER_STOP);
    contract("hypothetical_dual_joint_STOP_reaches_global_proof", ret0 == 0 && ret1 == 0 && !info.started && info.stop_proven);
    boundary("hypothetical_dual_STOP_rejected_but_both_DMA_cleanup_attempted", ret0 == -EBUSY && ret1 == -EBUSY && info.started == 3 && !info.stop_proven && !dma_running[0] && !dma_running[1] && dma_stop[0] == 1 && dma_stop[1] == 1 && !info.runtime_error);
}

static void test_failed_open_unlocked_gap(int peer)
{
    char name[150];
    int failed = !peer;
    reset();
    /* Non-NULL child clocks are synthetic: audited board simple children have NULL. */
    simple_cpu.clk = &tx;
    simple_codec.clk = &rx;
    boundary("gap_first_peer_open_actual_activation", soc_pcm_open(&substreams[peer]) == 0 &&
        snd_soc_dai_active(&cpu_dai) == 1 && snd_soc_dai_active(&codec_dai) == 1 && child_refs == 2);
    /* Model an ALSA constraint errno through the real symmetry helper. */
    cpu_dai.rate = 48000;
    model_constraint_error = -EPIPE;
    close_at_failed_open_gap = peer;
    int ret = soc_pcm_open(&substreams[failed]);
    snprintf(name, sizeof(name), "gap_peer_%d_failed_startup_balances_both_child_clocks", peer);
    contract(name, child_refs == 0 && child_enable_calls == child_disable_calls);
    snprintf(name, sizeof(name), "gap_peer_%d_failed_startup_unpublishes_CPU_pointer", peer);
    contract(name, !info.substreams[0] && !info.substreams[1]);
    snprintf(name, sizeof(name), "gap_peer_%d_full_get_failure_put_owns_its_references", peer);
    contract(name, !cpu_device.usage && !codec_device.usage && !platform_device.usage);
    boundary("gap_actual_single_marks_clobbered_before_rollback", ret == -EPIPE &&
        !rtd.mark_startup && !cpu_dai.mark_startup && !codec_dai.mark_startup &&
        !snd_soc_dai_active(&cpu_dai) && !snd_soc_dai_active(&codec_dai) &&
        cpu_device.usage == 1 && codec_device.usage == 1 && platform_device.usage == 1 &&
        !cpu_component.mark_pm && !codec_component.mark_pm && !platform_component.mark_pm &&
        child_enable_calls == 4 && child_disable_calls == 2 && child_refs == 2 &&
        !info.substreams[peer] && info.substreams[failed] == &substreams[failed] && !info.irq_drained);
}

static void test_actual_PM_wrapper_interleavings(void)
{
    reset();
    boundary("PM_wrapper_full_get_success_both_streams", snd_soc_pcm_component_pm_runtime_get(&rtd, &substreams[0]) == 0 &&
        snd_soc_pcm_component_pm_runtime_get(&rtd, &substreams[1]) == 0 && cpu_device.usage == 2);
    snd_soc_pcm_component_pm_runtime_put(&rtd, &substreams[0], 0);
    snd_soc_pcm_component_pm_runtime_put(&rtd, &substreams[1], 1);
    contract("PM_full_get_normal_peer_put_does_not_clobber_rollback_ownership", !cpu_device.usage && !codec_device.usage && !platform_device.usage);
    boundary("actual_PM_single_mark_full_get_leaks_one_ref_per_component", cpu_device.usage == 1 && codec_device.usage == 1 && platform_device.usage == 1 && !cpu_component.mark_pm && !codec_component.mark_pm && !platform_component.mark_pm);

    reset();
    boundary("PM_partial_failure_peer_actual_open", soc_pcm_open(&substreams[0]) == 0);
    codec_device.inject_get_error = -EIO;
    close_at_pm_failure = 0;
    int ret = soc_pcm_open(&substreams[1]);
    contract("PM_partial_failure_recovers_local_prefix_after_peer_clobber", !cpu_device.usage && !codec_device.usage && !platform_device.usage);
    boundary("actual_PM_partial_failure_balances_failed_current_but_leaks_prefix", ret == -EIO && cpu_device.usage == 1 && !codec_device.usage && !platform_device.usage && !cpu_component.mark_pm && !codec_component.mark_pm && !platform_component.mark_pm && !snd_soc_dai_active(&cpu_dai) && !info.substreams[0] && !info.substreams[1]);

    reset();
    codec_device.inject_get_error = -EACCES;
    boundary("actual_PM_EACCES_is_success_with_owned_reference", snd_soc_pcm_component_pm_runtime_get(&rtd, &substreams[0]) == 0 && cpu_device.usage == 1 && codec_device.usage == 1 && platform_device.usage == 1 && codec_component.mark_pm == &substreams[0]);
    snd_soc_pcm_component_pm_runtime_put(&rtd, &substreams[0], 0);
    boundary("actual_PM_EACCES_reference_put_once", !cpu_device.usage && !codec_device.usage && !platform_device.usage);

    reset();
    boundary("PM_peer_get_then_prior_failure_full_refs", snd_soc_pcm_component_pm_runtime_get(&rtd, &substreams[0]) == 0 &&
        snd_soc_pcm_component_pm_runtime_get(&rtd, &substreams[1]) == 0);
    snd_soc_pcm_component_pm_runtime_put(&rtd, &substreams[0], 1);
    snd_soc_pcm_component_pm_runtime_put(&rtd, &substreams[1], 0);
    contract("PM_new_peer_get_does_not_clobber_prior_rollback_ownership", !cpu_device.usage && !codec_device.usage && !platform_device.usage);
    boundary("actual_new_get_overwrites_prior_pm_mark_and_leaks_rollback_ref", cpu_device.usage == 1 && codec_device.usage == 1 && platform_device.usage == 1 && cpu_device.auto_puts == 1 && codec_device.auto_puts == 1 && platform_device.auto_puts == 1);
}

static void test_actual_PM_serial_prefix_returns(void)
{
    char name[120];
    struct device *devices[3] = {&cpu_device, &codec_device, &platform_device};
    for (int failed = 0; failed < 3; failed++) {
        reset();
        devices[failed]->inject_get_error = -EIO;
        int ret = soc_pcm_open(&substreams[0]);
        bool exact = ret == -EIO && !cpu_device.usage && !codec_device.usage && !platform_device.usage;
        for (int i = 0; i < 3; i++) {
            exact &= devices[i]->get_calls == (unsigned int)(i <= failed);
            exact &= devices[i]->auto_puts == (unsigned int)(i < failed);
            exact &= devices[i]->noidle_puts == (unsigned int)(i == failed);
        }
        snprintf(name, sizeof(name), "actual_serial_PM_failure_index_%d_puts_prefix_once_current_noidle_once", failed);
        boundary(name, exact);
    }
    reset();
    cpu_device.inject_get_error = -EACCES;
    codec_device.inject_get_error = -EIO;
    boundary("actual_EACCES_owned_prefix_then_failure_get_cleanup", soc_pcm_open(&substreams[0]) == -EIO &&
        !cpu_device.usage && !codec_device.usage && !platform_device.usage &&
        cpu_device.auto_puts == 1 && !cpu_device.noidle_puts && codec_device.noidle_puts == 1 && !codec_device.auto_puts);
    reset();
    cpu_device.inject_get_error = 1;
    boundary("actual_positive_one_get_is_full_success", soc_pcm_open(&substreams[0]) == 0 && snd_soc_dai_active(&cpu_dai) == 1 && cpu_device.usage == 1);
    boundary("actual_positive_one_get_close_returns_each_reference_once", soc_pcm_clean(&substreams[0], 0) == 0 && !cpu_device.usage && !codec_device.usage && !platform_device.usage && cpu_device.auto_puts == 1 && codec_device.auto_puts == 1 && platform_device.auto_puts == 1 && !cpu_device.noidle_puts);
}

int main(void)
{
    for (int closing = 0; closing < 2; closing++) {
        test_one_close(closing, false);
        test_one_close(closing, true);
        test_sequential_START(closing);
        test_codec_failure_rollback(closing);
        test_failed_peer_open_rollback(closing);
        test_failed_open_unlocked_gap(closing);
    }
    test_concurrent_START();
    test_hypothetical_dual_STOP();
    test_actual_PM_wrapper_interleavings();
    test_actual_PM_serial_prefix_returns();
    pthread_mutex_destroy(&info.lock);
    pthread_mutex_destroy(&card.pcm_mutex);
    printf("{\"contract_total\":%u,\"contract_passed\":%u,\"boundary_total\":%u,\"boundary_passed\":%u}\n", contract_total, contract_passed, boundary_total, boundary_passed);
    if (boundary_total != boundary_passed) return 2;
    return contract_total != contract_passed;
}
