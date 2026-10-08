static void reset_case(void)
{
    if (managed_count) abort();
    memset(&pdev, 0, sizeof(pdev));
    memset(&node, 0, sizeof(node));
    memset(&map, 0, sizeof(map));
    memset(&grf, 0, sizeof(grf));
    memset(&consumers, 0, sizeof(consumers));
    memset(&component, 0, sizeof(component));
    memset(&dai, 0, sizeof(dai));
    memset(&ss, 0, sizeof(ss));
    memset(faults, 0, sizeof(faults));
    memset(polls, 0, sizeof(polls));
    atomic_store(&operations, 0);
    poll_calls = force_calls = hw_writes = enable_calls = disable_underflows = 0;
    clk_fault = sync_error = pm_error = pinctrl_error = 0;
    consumer_count = stale_clock_uses = leaked_clock_refs = early_enables = wrong_action_order = action_count = 0;
    allocated_info = NULL;
    registered_component = NULL;
    info_lock_initialized = action_registered = map_live = false;
    bind_fmt = true;
    inject_fmt_error = check_early_callbacks = inject_irq_exit = false;
    fmt_error_fired = irq_block = irq_entered = irq_release = probe_waiting = false;
    clock_block = clock_entered = clock_release = teardown_waiting = resume_revived_irq = false;
    irq_inflight = irq_syncs = 0;
    panic_seen = false;
    panic_timeout = 10;
    probe_fault = NULL;
    resource.start = 0xfe410000;
    resource.end = resource.start + 0xfff;
    pdev.resource = &resource;
    pdev.dev.of_node = &node;
    pdev.dev.suspended = true;
    pdev.dev.pm_disabled = true;
    node.name = "i2s@fe410000";
    node.compatible = "rockchip,rk3568-i2s-tdm";
    node.trcm = 1;
    saved_ready = saved_owners = saved_mclk = saved_hclk = saved_live = saved_drained = 99;
}
static void check_unwind(void)
{
    check("no stale clock consumer access", stale_clock_uses == 0);
    check("no owned clock reference lost at clk_put", leaked_clock_refs == 0);
    check("no double clock release", disable_underflows == 0);
    check("checked enables only after action registration", early_enables == 0);
    check("action after all handles and before enable", wrong_action_order == 0);
    check("PM usage balanced", pdev.dev.usage == 0);
    check("all devres released", managed_count == 0);
}
static void success_then_remove(void)
{
    check("whole real probe succeeds", rockchip_i2s_tdm_probe(&pdev) == 0 && allocated_info->ready);
    check("ready does not permit conflicting PM transaction", !allocated_info->power_transition);
    check("whole real remove succeeds", rockchip_i2s_tdm_remove(&pdev) == 0);
    check("remove revokes ready and IRQ entry", !allocated_info->ready && !allocated_info->irq_live && allocated_info->irq_drained);
    check("stale startup after revoke rejected", rockchip_i2s_tdm_startup(&ss, &dai) < 0 && !allocated_info->substreams[0]);
    devres_release_all_model();
    check_unwind();
}
static void *probe_worker(void *arg)
{ remove_result = rockchip_i2s_tdm_probe(&pdev); return NULL; }
static void *remove_worker(void *arg)
{ remove_result = rockchip_i2s_tdm_remove(&pdev); return NULL; }
static void *queued_pm_resume_worker(void *arg)
{
    /* Model core callback serialization, without introducing a user PM lease. */
    pthread_mutex_lock(&pm_mutex);
    int ret = i2s_tdm_runtime_resume(&pdev.dev);
    if (!ret) pdev.dev.suspended = false;
    resume_revived_irq = allocated_info->shutting_down && allocated_info->irq_live;
    pthread_mutex_unlock(&pm_mutex);
    return NULL;
}
int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    const char *mode = argv[1];
    if (!strcmp(mode, "partial")) {
        const char *stages[] = { "dai_alloc", "info_alloc", "reset_tx", "reset_rx", "hclk_get", "tx_get", "rx_get", "action", "hclk_enable", "map", "regmap", "irq_get", "irq_request", "component", "pcm", "sysfs" };
        for (unsigned int i = 0; i < ARRAY_SIZE(stages); i++) {
            reset_case();
            probe_fault = stages[i];
            check("probe partial/late failure returned", rockchip_i2s_tdm_probe(&pdev) < 0);
            if (allocated_info && info_lock_initialized) check("failed probe never publishes ready", !allocated_info->ready);
            devres_release_all_model();
            check_unwind();
            if (!strcmp(stages[i], "component") || !strcmp(stages[i], "pcm") || !strcmp(stages[i], "sysfs")) {
                check("late failure disables PM", pdev.dev.pm_disabled);
                check("late failure gates/drains IRQ and releases MCLK", !saved_live && saved_drained && !saved_mclk && !saved_hclk && !saved_owners);
            }
        }
        for (int ordinal = 1; ordinal <= 4; ordinal++) {
            reset_case();
            faults[ordinal] = -EREMOTEIO;
            check("whole probe real initial register fault", rockchip_i2s_tdm_probe(&pdev) == -EREMOTEIO);
            devres_release_all_model();
            check_unwind();
        }
    } else if (!strcmp(mode, "late-fault")) {
        reset_case();
        inject_fmt_error = true;
        check("whole probe nested callback failure preserved", rockchip_i2s_tdm_probe(&pdev) == -EREMOTEIO && fmt_error_fired);
        check("late callback fault keeps sticky and revokes ready", allocated_info->runtime_error == -EREMOTEIO && !allocated_info->ready);
        check("late callback fault quiesced before devres", !allocated_info->mclks_enabled && !allocated_info->hclk_enabled && !allocated_info->irq_live && allocated_info->irq_drained && pdev.dev.pm_disabled);
        devres_release_all_model();
        check_unwind();
    } else if (!strcmp(mode, "ready")) {
        reset_case();
        check_early_callbacks = true;
        success_then_remove();
    } else if (!strcmp(mode, "controls")) {
        reset_case();
        check("checked real probe registration succeeds", rockchip_i2s_tdm_probe(&pdev) == 0);
        check("registered checked descriptor has no legacy controls", registered_component->num_controls == 0 && registered_component->controls == NULL);
        for (unsigned int i = 0; i < registered_component->num_controls; i++) {
            if (strcmp(registered_component->controls[i].name, "I2STDM Digital Loopback Mode")) continue;
            struct snd_kcontrol control = { .component = &component };
            struct snd_ctl_elem_value value = { .value.enumerated.item = { LOOPBACK_MODE_1, 0 } };
            allocated_info->started = 1;
            allocated_info->configuring = true;
            int before = atomic_load(&operations);
            int ret = registered_component->controls[i].put(&control, &value);
            check("registered loopback cannot bypass owner/configuring", ret < 0 && atomic_load(&operations) == before);
            allocated_info->started = 0;
            allocated_info->configuring = false;
            allocated_info->runtime_error = -EIO;
            pm_error = -EIO;
            value.value.enumerated.item[0] = LOOPBACK_MODE_2;
            before = atomic_load(&operations);
            ret = registered_component->controls[i].put(&control, &value);
            check("registered loopback cannot bypass sticky/failed PM", ret < 0 && atomic_load(&operations) == before);
            pm_error = 0;
            /* Restore only the boundary fixture so teardown can be measured. */
            allocated_info->runtime_error = 0;
            faults[(atomic_load(&operations) + 1) % 64] = -EREMOTEIO;
            ret = registered_component->controls[i].get(&control, &value);
            check("registered loopback cannot swallow read error", ret == -EREMOTEIO);
            memset(faults, 0, sizeof(faults));
        }
        rockchip_i2s_tdm_remove(&pdev);
        devres_release_all_model();
        check_unwind();
        reset_case();
        node.trcm = 0;
        check("legacy profile still registers same controls", rockchip_i2s_tdm_probe(&pdev) == 0 && registered_component->controls == rockchip_i2s_tdm_snd_controls && registered_component->num_controls == ARRAY_SIZE(rockchip_i2s_tdm_snd_controls));
        raw_test_cleanup(); /* legacy clock lifecycle remains outside acceptance */
    } else if (!strcmp(mode, "nested")) {
        reset_case();
        bind_fmt = false;
        check("inactive whole probe succeeds", rockchip_i2s_tdm_probe(&pdev) == 0 && pdev.dev.suspended && !allocated_info->mclks_enabled);
        check("real set_fmt ticket permits nested runtime resume", i2s_checked_set_fmt(allocated_info, &pdev.dev, SND_SOC_DAIFMT_CBS_CFS | SND_SOC_DAIFMT_I2S) == 0 && allocated_info->stop_proven && allocated_info->mclks_enabled && !allocated_info->configuring && !allocated_info->power_transition && pdev.dev.usage == 0);
        allocated_info->power_transition = true;
        int before = atomic_load(&operations);
        check("external fmt denied during PM transition", i2s_checked_set_fmt(allocated_info, &pdev.dev, SND_SOC_DAIFMT_CBS_CFS | SND_SOC_DAIFMT_I2S) == -EBUSY && atomic_load(&operations) == before && !allocated_info->runtime_error);
        check("external START denied during PM transition", i2s_checked_component_trigger(&component, &ss, SNDRV_PCM_TRIGGER_START) == -EBUSY);
        int start_ret = i2s_checked_trigger(allocated_info, 0, SNDRV_PCM_TRIGGER_START);
        check("actual DAI START rechecks PM transaction", start_ret == -EBUSY);
        if (!start_ret) i2s_checked_trigger(allocated_info, 0, SNDRV_PCM_TRIGGER_STOP);
        allocated_info->power_transition = false;
        check("real runtime idle releases clocks", runtime_idle_model() == 0 && pdev.dev.suspended && !allocated_info->mclks_enabled && !allocated_info->irq_live && allocated_info->irq_drained);
        int enabled_before = enable_calls;
        check("inactive remove nests resume without self-rejection", rockchip_i2s_tdm_remove(&pdev) == 0 && enable_calls == enabled_before + 2 && allocated_info->stop_proven && !allocated_info->mclks_enabled && !allocated_info->hclk_enabled && !allocated_info->ready && !allocated_info->irq_live);
        devres_release_all_model();
        check_unwind();
    } else if (!strcmp(mode, "nested-errors")) {
        for (int failure = 0; failure < 4; failure++) {
            reset_case();
            bind_fmt = false;
            check("inactive probe before nested failure", rockchip_i2s_tdm_probe(&pdev) == 0);
            if (failure < 2) clk_fault = enable_calls + failure + 1;
            if (failure == 2) sync_error = -EIO;
            if (failure == 3) pm_error = -EHOSTDOWN;
            int expected = failure < 2 ? -EREMOTEIO : failure == 2 ? -EIO : -EHOSTDOWN;
            check("nested resume error preserves errno", i2s_checked_set_fmt(allocated_info, &pdev.dev, SND_SOC_DAIFMT_CBS_CFS | SND_SOC_DAIFMT_I2S) == expected && allocated_info->runtime_error == expected);
            check("nested resume error rolls back clock/gate/ticket", !allocated_info->mclks_enabled && !allocated_info->irq_live && !allocated_info->power_transition && !allocated_info->configuring && pdev.dev.usage == 0 && disable_underflows == 0);
            clk_fault = sync_error = pm_error = 0;
            memset(faults, 0, sizeof(faults));
            check("sticky teardown only forced STOP never resumes stream", rockchip_i2s_tdm_remove(&pdev) == 0 && allocated_info->runtime_error == expected && allocated_info->stop_proven && !allocated_info->mclks_enabled && !allocated_info->hclk_enabled && !allocated_info->ready);
            devres_release_all_model();
            check_unwind();
        }
        reset_case();
        bind_fmt = false;
        check("probe before unproved nested remove", rockchip_i2s_tdm_probe(&pdev) == 0);
        polls[0] = polls[1] = -ETIMEDOUT;
        if (!setjmp(panic_jump)) rockchip_i2s_tdm_remove(&pdev);
        check("inactive remove failure prevents all devres release", panic_seen && panic_timeout == 0 && managed_count > 0 && allocated_info->hclk_enabled && allocated_info->mclks_enabled && !allocated_info->ready && !allocated_info->irq_live);
        raw_test_cleanup();
    } else if (!strcmp(mode, "irq-exit")) {
        reset_case();
        inject_irq_exit = true;
        probe_fault = "pcm";
        pthread_t probe_thread;
        pthread_create(&probe_thread, NULL, probe_worker, NULL);
        pthread_mutex_lock(&irq_mutex);
        while (!probe_waiting) pthread_cond_wait(&irq_cond, &irq_mutex);
        check("late probe exit waits captured IRQ before clock release", allocated_info->mclks_enabled && allocated_info->hclk_enabled);
        irq_release = true;
        pthread_cond_broadcast(&irq_cond);
        pthread_mutex_unlock(&irq_mutex);
        pthread_join(irq_thread, NULL);
        pthread_join(probe_thread, NULL);
        check("late probe exit keeps first registration errno", remove_result == -EREMOTEIO);
        check("late probe exit drained IRQ before devres", irq_inflight == 0 && irq_syncs > 0 && !allocated_info->irq_live && !allocated_info->ready && allocated_info->irq_drained);
        devres_release_all_model();
        check_unwind();
    } else if (!strcmp(mode, "pm-exit")) {
        reset_case();
        bind_fmt = false;
        check("probe before queued PM callback teardown", rockchip_i2s_tdm_probe(&pdev) == 0 && pdev.dev.suspended);
        clock_block = true;
        pthread_t pm_thread, remove_thread;
        pthread_create(&pm_thread, NULL, queued_pm_resume_worker, NULL);
        pthread_mutex_lock(&irq_mutex);
        while (!clock_entered) pthread_cond_wait(&irq_cond, &irq_mutex);
        pthread_mutex_unlock(&irq_mutex);
        pthread_create(&remove_thread, NULL, remove_worker, NULL);
        pthread_mutex_lock(&irq_mutex);
        while (!teardown_waiting) pthread_cond_wait(&irq_cond, &irq_mutex);
        check("teardown revokes ready during pending PM callback", !allocated_info->ready && allocated_info->shutting_down && !allocated_info->irq_live);
        check("pending PM consumer handles retained", managed_count > 0 && clock_alive(allocated_info->mclk_tx) && clock_alive(allocated_info->mclk_rx) && clock_alive(allocated_info->hclk));
        clock_release = true;
        pthread_cond_broadcast(&irq_cond);
        pthread_mutex_unlock(&irq_mutex);
        pthread_join(pm_thread, NULL);
        pthread_join(remove_thread, NULL);
        check("PM callback never reopens revoked IRQ gate", !resume_revived_irq);
        check("teardown waits callback then proves STOP/releases", remove_result == 0 && !allocated_info->ready && !allocated_info->irq_live && allocated_info->irq_drained && allocated_info->stop_proven && !allocated_info->mclks_enabled && !allocated_info->hclk_enabled);
        devres_release_all_model();
        check_unwind();
    } else return 2;
    printf("{\"passed\":%u,\"total\":%u}\n", passed, total);
    return passed != total;
}
