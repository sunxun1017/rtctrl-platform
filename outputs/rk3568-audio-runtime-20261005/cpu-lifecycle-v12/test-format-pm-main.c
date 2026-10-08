/* SPDX-License-Identifier: MIT */
static struct rk_i2s_tdm_dev info;
static struct device device;
static struct regmap map;
static struct clk tx, rx, hclk;
static struct snd_soc_dai dai;
static struct snd_soc_component component;
static struct snd_pcm_substream stream;
static bool initialized;
static unsigned int total, passed;
static int pm_put_error, worker_mode, worker_ret, workers, releases, drains;
static int idle_error, pm_disables, pm_sets, resumes, forced_stops, failstops;
static int terminal_sticky;
static bool early_checks, terminal_checks;
static jmp_buf teardown_jump;
static pthread_mutex_t schedule_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t schedule_cond = PTHREAD_COND_INITIALIZER;
static pthread_t worker_thread;
static int callback_at_irq, release_callback;
static bool worker_pending, worker_joined;
static const unsigned int fmt = SND_SOC_DAIFMT_CBS_CFS | SND_SOC_DAIFMT_NB_NF | SND_SOC_DAIFMT_I2S;

static void check(const char *name, bool condition)
{
    total++;
    passed += condition;
    printf("FORMAT_PM_CHECK %s %u\n", name, condition);
}

static bool terminal(void)
{
#ifdef HAVE_FORMAT_PM_RELEASE
    return info.format_pm_release;
#else
    return false;
#endif
}

static bool clear_phase(void) { return !info.configuring && !terminal(); }
static bool leases_held(void) { return info.mclks_enabled && releases == 0 && !map.cache_only; }
static bool idle(void)
{
    return device.usage == 0 && device.status == 0 && !device.core_error &&
           !info.irq_live && info.irq_drained && !info.mclks_enabled &&
           info.hclk_enabled && map.cache_only && releases == 2 && drains == 1;
}

static void reset(void)
{
    if (initialized) pthread_mutex_destroy(&info.lock);
    memset(&info, 0, sizeof(info));
    memset(&device, 0, sizeof(device));
    memset(&map, 0, sizeof(map));
    memset(&dai, 0, sizeof(dai));
    pthread_mutex_init(&info.lock, NULL);
    initialized = true;
    device.data = &info;
    device.status = 1;
    info.dev = &device;
    info.regmap = &map;
    info.mclk_tx = &tx;
    info.mclk_rx = &rx;
    info.hclk = &hclk;
    info.ready = info.checked_lifecycle = info.stop_proven = true;
    info.irq_live = info.mclks_enabled = info.hclk_enabled = true;
    info.pm_enabled = true;
    info.irq = 5;
    dai.dev = &device;
    component.dev = &device;
    stream.stream = 0;
    operations = writes = reads = clock_calls = fault_at = pm_error = 0;
    pm_put_error = worker_mode = workers = releases = drains = idle_error = 0;
    pm_disables = pm_sets = resumes = forced_stops = failstops = 0;
    terminal_sticky = 0;
    worker_ret = 12345;
    early_checks = terminal_checks = false;
    callback_at_irq = release_callback = 0;
    worker_pending = worker_joined = false;
}

/* Bounded model of the actual PM core's EBUSY handling, without autosuspend. */
static void run_worker(void)
{
    workers++;
    worker_ret = i2s_checked_runtime_suspend(&info);
    if (!worker_ret) device.status = 0;
    else {
        device.status = 1;
        device.core_error = (worker_ret == -EBUSY || worker_ret == -EAGAIN) ? 0 : worker_ret;
    }
    /* use_autosuspend=false => expiration=0 => EBUSY is not rescheduled. */
}

static void *async_worker(void *unused)
{
    run_worker();
    return NULL;
}

static void drain_async_worker(void)
{
    pthread_mutex_lock(&schedule_lock);
    release_callback = 1;
    pthread_cond_broadcast(&schedule_cond);
    pthread_mutex_unlock(&schedule_lock);
    pthread_join(worker_thread, NULL);
    worker_pending = false;
    worker_joined = true;
}

static void check_teardown_blocked(void)
{
    int before = failstops;
    if (!setjmp(teardown_jump)) i2s_checked_quiesce(&info, "model remove");
    check("teardown_during_fmt_failstops", failstops == before + 1 &&
          info.configuring && !info.shutting_down && info.ready &&
          pm_disables == 0 && pm_sets == 0 && resumes == 0 && forced_stops == 0);
}

static void check_other_commands_blocked(void)
{
    check("config_gate_stays_busy", i2s_checked_gate_locked(&info) == -EBUSY);
    check("startup_during_fmt_refused", rockchip_i2s_tdm_startup(&stream, &dai) == -EBUSY && !info.substreams[0]);
    check("start_during_fmt_refused", i2s_checked_component_trigger(&component, &stream, SNDRV_PCM_TRIGGER_START) == -EBUSY);
    check("nested_fmt_refused", i2s_checked_set_fmt(&info, &device, fmt) == -EBUSY);
    check_teardown_blocked();
}

static int pm_runtime_get_sync(struct device *dev)
{
    dev->usage++;
    return pm_error;
}

static void pm_runtime_put_noidle(struct device *dev) { dev->usage--; }

static int pm_runtime_put(struct device *dev)
{
    dev->usage--;
    if (terminal_checks) {
        check("terminal_only_after_all_writes", writes == 4 && info.configuring && terminal());
        check_other_commands_blocked();
    }
    if (terminal_sticky) {
        unsigned long flags;
        spin_lock_irqsave(&info.lock, flags);
        i2s_checked_error_locked(&info, terminal_sticky);
        spin_unlock_irqrestore(&info.lock, flags);
    }
    if (worker_mode == 1) run_worker();
    if (worker_mode == 2 || worker_mode == 3) {
        worker_pending = true;
        pthread_create(&worker_thread, NULL, async_worker, NULL);
        pthread_mutex_lock(&schedule_lock);
        while (!callback_at_irq) pthread_cond_wait(&schedule_cond, &schedule_lock);
        pthread_mutex_unlock(&schedule_lock);
        check("async_callback_started_before_fmt_out", info.configuring && terminal() && info.power_transition &&
              !info.irq_live && !info.irq_drained && (info.mclks_enabled == (worker_mode == 2)));
        check_other_commands_blocked();
    }
    return pm_put_error;
}

static int regmap_update_bits(struct regmap *r, unsigned int reg, unsigned int mask, unsigned int value)
{
    int ret = fault_operation();
    writes++;
    if (early_checks) {
        check("early_suspend_config_refused", i2s_checked_runtime_suspend(&info) == -EBUSY && leases_held() && drains == 0 && !terminal());
        check_other_commands_blocked();
    }
    if (!ret) r->hw[reg / 4] = r->cache[reg / 4] = (r->cache[reg / 4] & ~mask) | (value & mask);
    return ret;
}

static void synchronize_irq(int irq)
{
    drains++;
    if (worker_mode == 2 && worker_pending && !worker_joined) {
        pthread_mutex_lock(&schedule_lock);
        callback_at_irq = 1;
        pthread_cond_broadcast(&schedule_cond);
        while (!release_callback) pthread_cond_wait(&schedule_cond, &schedule_lock);
        pthread_mutex_unlock(&schedule_lock);
    }
}
static void regcache_cache_only(struct regmap *r, bool only) { r->cache_only = only; }
static void clk_disable_unprepare(struct clk *clock) { releases++; }
static int pinctrl_pm_select_idle_state(struct device *dev)
{
    if (worker_mode == 3 && worker_pending && !worker_joined) {
        pthread_mutex_lock(&schedule_lock);
        callback_at_irq = 1;
        pthread_cond_broadcast(&schedule_cond);
        while (!release_callback) pthread_cond_wait(&schedule_cond, &schedule_lock);
        pthread_mutex_unlock(&schedule_lock);
    }
    return idle_error;
}
static void pm_runtime_disable(struct device *dev)
{
    pm_disables++;
    if (worker_pending) drain_async_worker();
}
static int pm_runtime_set_suspended(struct device *dev) { pm_sets++; return 0; }
static int i2s_checked_runtime_resume(struct rk_i2s_tdm_dev *dev)
{
    resumes++;
    if (worker_mode >= 2) check("teardown_resume_only_after_pm_callback_drained", worker_joined && !worker_pending);
    return 0;
}
static int i2s_checked_stop_locked(struct rk_i2s_tdm_dev *dev, int direction, bool force) { forced_stops++; return 0; }
static void i2s_checked_failstop(struct rk_i2s_tdm_dev *dev, const char *op, int ret)
{
    failstops++;
    longjmp(teardown_jump, 1);
}

int main(void)
{
    reset();
    worker_mode = 1;
    int ret = i2s_checked_set_fmt(&info, &device, fmt);
    check("fmt_success_pm_balanced", ret == 0 && writes == 4 && device.usage == 0 && clear_phase());
    check("worker_before_fmt_out_reaches_idle", idle());
#ifdef EXPECT_RED
    check("old_rejected_worker_leaves_active_zero_usage", worker_ret == -EBUSY &&
          device.status == 1 && device.usage == 0 && !device.core_error && leases_held() &&
          info.irq_live && !info.irq_drained && clear_phase() && workers == 1);
    reset();
    check("old_deferred_fmt_success", i2s_checked_set_fmt(&info, &device, fmt) == 0 && clear_phase());
    run_worker();
    check("old_worker_after_flag_clear_idle", idle());
#else
    reset();
    check("deferred_fmt_success", i2s_checked_set_fmt(&info, &device, fmt) == 0 && clear_phase());
    run_worker();
    check("worker_after_fmt_out_reaches_idle", idle());
    reset();
    early_checks = terminal_checks = true;
    worker_mode = 1;
    check("all_write_and_terminal_gates_preserved", i2s_checked_set_fmt(&info, &device, fmt) == 0 && clear_phase() && idle());
    reset();
    worker_mode = 1;
    terminal_sticky = -EUCLEAN;
    ret = i2s_checked_set_fmt(&info, &device, fmt);
    check("sticky_after_terminal_before_suspend_gate_refused", worker_ret == -EUCLEAN && leases_held() && drains == 0);
    check("sticky_after_terminal_returned_and_phase_cleared", ret == -EUCLEAN && info.runtime_error == ret && clear_phase() && device.usage == 0);
    reset();
    worker_mode = 1;
    pm_error = 1;
    check("positive_get_sync_result_not_treated_as_error", i2s_checked_set_fmt(&info, &device, fmt) == 0 && idle() && clear_phase() && !info.runtime_error);
    for (int ordinal = 1; ordinal <= 4; ordinal++) {
        reset();
        fault_at = ordinal;
        worker_mode = 1;
        pm_put_error = -ENOSPC;
        ret = i2s_checked_set_fmt(&info, &device, fmt);
        check("write_error_first_errno", ret == injected_errno && info.runtime_error == injected_errno);
        check("write_error_published_before_worker", worker_ret == injected_errno && leases_held() && drains == 0);
        check("write_error_balances_and_clears_phase", clear_phase() && device.usage == 0 && writes == ordinal);
        check("write_error_retry_retains_sticky", i2s_checked_set_fmt(&info, &device, fmt) == injected_errno && writes == ordinal);
    }
    reset();
    pm_error = -EHOSTDOWN;
    worker_mode = 1;
    ret = i2s_checked_set_fmt(&info, &device, fmt);
    check("get_error_no_mmio_noidle_balance", ret == -EHOSTDOWN && info.runtime_error == ret &&
          writes == 0 && device.usage == 0 && workers == 0 && clear_phase() && leases_held());
    reset();
    pm_put_error = -ENOSPC;
    ret = i2s_checked_set_fmt(&info, &device, fmt);
    check("put_error_not_swallowed", ret == -ENOSPC && info.runtime_error == ret && clear_phase() && device.usage == 0);
    run_worker();
    check("put_error_sticky_blocks_later_suspend", worker_ret == -ENOSPC && leases_held() && drains == 0);
    reset();
    worker_mode = 1;
    pm_put_error = -ENOSPC;
    ret = i2s_checked_set_fmt(&info, &device, fmt);
    check("put_error_after_successful_callback_not_swallowed", ret == -ENOSPC && info.runtime_error == ret && clear_phase() && idle());
    reset();
    worker_mode = 1;
    idle_error = -EIO;
    pm_put_error = -ENOSPC;
    ret = i2s_checked_set_fmt(&info, &device, fmt);
    check("callback_first_errno_survives_put_error", ret == -ENOSPC && info.runtime_error == -EIO && clear_phase() &&
          worker_ret == -EIO && releases == 2 && drains == 1 && !info.mclks_enabled && !info.power_transition);
    /* Existing return precedence reports initiating PM-put errno, first sticky remains EIO. */
    reset();
    info.runtime_error = -EPIPE;
    check("preexisting_sticky_not_cleared", i2s_checked_set_fmt(&info, &device, fmt) == -EPIPE &&
          info.runtime_error == -EPIPE && writes == 0 && device.usage == 0 && clear_phase());
    reset();
    check("invalid_fmt_no_phase_or_pm", i2s_checked_set_fmt(&info, &device, fmt ^ 1) == -EINVAL &&
          writes == 0 && device.usage == 0 && clear_phase() && !info.runtime_error);
    for (int reason = 0; reason < 4; reason++) {
        reset();
        if (reason == 0) info.configuring = true;
        if (reason == 1) info.started = 1;
        if (reason == 2) info.power_transition = true;
        if (reason == 3) info.shutting_down = true;
        ret = i2s_checked_set_fmt(&info, &device, fmt);
        check("ordinary_busy_shutdown_no_pm", ret == (reason == 3 ? -ESHUTDOWN : -EBUSY) && writes == 0 && device.usage == 0 && !terminal());
    }
    for (int reason = 0; reason < 3; reason++) {
        reset();
        info.configuring = true;
        if (reason == 1) { info.configuring = false; info.started = 1; }
        if (reason == 2) { info.configuring = false; info.stop_proven = false; }
        check("ordinary_suspend_busy_unchanged", i2s_checked_runtime_suspend(&info) == -EBUSY && leases_held() && drains == 0 && !terminal());
    }
    reset();
    info.configuring = info.format_pm_release = true;
    info.started = 1;
    check("terminal_does_not_waive_started", i2s_checked_runtime_suspend(&info) == -EBUSY && leases_held() && drains == 0);
    reset();
    info.configuring = info.format_pm_release = true;
    info.stop_proven = false;
    check("terminal_does_not_waive_stop", i2s_checked_runtime_suspend(&info) == -EBUSY && leases_held() && drains == 0);
    reset();
    worker_mode = 2;
    ret = i2s_checked_set_fmt(&info, &device, fmt);
    check("async_fmt_out_clears_phase_without_waiting_callback", ret == 0 && clear_phase() && info.power_transition && writes == 4);
    check("power_transition_after_fmt_still_blocks_gate", i2s_checked_gate_locked(&info) == -EBUSY);
    check("power_transition_after_fmt_still_blocks_startup", rockchip_i2s_tdm_startup(&stream, &dai) == -EBUSY && !info.substreams[0]);
    check("power_transition_after_fmt_still_blocks_START", i2s_checked_component_trigger(&component, &stream, SNDRV_PCM_TRIGGER_START) == -EBUSY);
    drain_async_worker();
    check("async_callback_finishes_real_release_after_fmt", idle() && !info.power_transition && clear_phase() && writes == 4);
    reset();
    worker_mode = 3;
    ret = i2s_checked_set_fmt(&info, &device, fmt);
    check("second_async_fmt_ready_for_teardown", ret == 0 && clear_phase() && info.power_transition);
    /* This worker has drained IRQs/released MCLK and is held in pinctrl.
     * The real quiesce reaches PM disable, which must await that callback. */
    int before_teardown = failstops;
    i2s_checked_quiesce(&info, "model remove after fmt");
    check("teardown_after_fmt_drains_callback_before_owned_release", pm_disables == 1 && worker_joined && !worker_pending &&
          resumes == 1 && forced_stops == 2 && pm_sets == 1 && !info.hclk_enabled && !info.ready &&
          info.shutting_down && clear_phase() && failstops == before_teardown);
#endif
    printf("{\"total\":%u,\"passed\":%u}\n", total, passed);
    pthread_mutex_destroy(&info.lock);
    return total == passed ? 0 : 1;
}
