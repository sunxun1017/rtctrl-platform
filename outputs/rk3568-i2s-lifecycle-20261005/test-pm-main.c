static struct platform_device pdev;
static struct regmap map;
static struct rk_i2s_tdm_dev info;
static struct clk tx, rx, hclk;
static struct snd_pcm_substream ss;
static bool lock_initialized, sync_called;
static unsigned int passed, total;
static void check(const char *name, bool ok)
{ total++; passed += ok; if (!ok) fprintf(stderr, "FAIL %s\n", name); }
static void synchronize_irq(unsigned int irq)
{
    int ret = pthread_mutex_trylock(&info.lock);
    check("PM IRQ sync outside spinlock", ret == 0);
    if (!ret) pthread_mutex_unlock(&info.lock);
    sync_called = true;
}
static void reset(bool active)
{
    if (lock_initialized) pthread_mutex_destroy(&info.lock);
    memset(&map, 0, sizeof(map));
    memset(&info, 0, sizeof(info));
    memset(&pdev, 0, sizeof(pdev));
    memset(&tx, 0, sizeof(tx));
    memset(&rx, 0, sizeof(rx));
    memset(&hclk, 0, sizeof(hclk));
    memset(faults, 0, sizeof(faults));
    memset(polls, 0, sizeof(polls));
    atomic_store(&operations, 0);
    poll_calls = reset_calls = force_calls = hw_writes = 0;
    clk_fault = enable_calls = disable_underflows = sync_error = pm_error = pinctrl_error = 0;
    panic_timeout = 10;
    panic_seen = sync_called = false;
    pdev.dev.data = &info;
    pdev.dev.suspended = !active;
    info.dev = &pdev.dev;
    info.regmap = &map;
    info.mclk_tx = &tx;
    info.mclk_rx = &rx;
    info.hclk = &hclk;
    info.is_master_mode = true;
    info.clk_trcm = I2S_CKR_TRCM_TXONLY;
    pthread_mutex_init(&info.lock, NULL);
    lock_initialized = true;
    tx.enables = rx.enables = active;
    hclk.enables = 1;
#ifdef HAVE_CHECKED_FIELDS
    info.checked_lifecycle = true;
#endif
#ifdef HAVE_CHECKED_IRQ
    info.irq = 85;
    info.irq_live = active;
    info.mclks_enabled = active;
    info.stop_proven = true;
#endif
#ifdef HAVE_CHECKED_PM
    info.hclk_enabled = true;
#endif
#ifdef HAVE_READBACK
    info.regs = map.hw;
#endif
}
int main(void)
{
    reset(true);
    check("runtime suspend success", i2s_tdm_runtime_suspend(&pdev.dev) == 0 && tx.enables == 0 && rx.enables == 0 && map.cache_only);
    check("runtime suspend no double release", i2s_tdm_runtime_suspend(&pdev.dev) == 0 && disable_underflows == 0);
    reset(false);
    sync_error = -EIO;
    check("resume cache error preserved", i2s_tdm_runtime_resume(&pdev.dev) == -EIO);
    check("resume cache error restores cache-only", map.cache_only && tx.enables == 0 && rx.enables == 0);
    for (int ordinal = 1; ordinal <= 2; ordinal++) {
        reset(false);
        clk_fault = ordinal;
        check("resume clock error prefix", i2s_tdm_runtime_resume(&pdev.dev) == -EREMOTEIO && tx.enables == 0 && rx.enables == 0 && disable_underflows == 0);
    }
    reset(true);
#ifdef HAVE_CHECKED_FIELDS
    info.runtime_error = -EIO;
#endif
    check("sticky runtime suspend refused", i2s_tdm_runtime_suspend(&pdev.dev) == -EIO && tx.enables == 1 && rx.enables == 1);
    reset(true);
#ifdef HAVE_CHECKED_TRIGGER
    info.started = 1;
#endif
    check("running runtime suspend refused", i2s_tdm_runtime_suspend(&pdev.dev) == -EBUSY && tx.enables == 1 && rx.enables == 1);
    reset(true);
    check("remove releases each clock once", rockchip_i2s_tdm_remove(&pdev) == 0 && tx.enables == 0 && rx.enables == 0 && hclk.enables == 0 && disable_underflows == 0);
    check("remove gated/drained IRQ", sync_called);
    reset(false);
#ifdef HAVE_CHECKED_IRQ
    info.stop_proven = false;
#endif
    check("initial runtime resume proves STOP before idle", i2s_tdm_runtime_resume(&pdev.dev) == 0 && poll_calls >= 2);
    check("initial idle suspend can release clocks", i2s_tdm_runtime_suspend(&pdev.dev) == 0 && tx.enables == 0 && rx.enables == 0 && disable_underflows == 0);
    reset(false);
    pm_error = -EHOSTDOWN;
    check("system resume PM get balanced", rockchip_i2s_tdm_resume(&pdev.dev) == -EHOSTDOWN && pdev.dev.usage == 0);
    reset(true);
    polls[0] = polls[1] = -ETIMEDOUT;
    if (!setjmp(panic_jump)) rockchip_i2s_tdm_remove(&pdev);
    check("unproved remove fails before devres", panic_seen && panic_timeout == 0 && hclk.enables == 1 && !pdev.dev.pm_disabled);
    reset(true);
    ss.stream = 0;
    info.substreams[0] = &ss;
    if (!setjmp(panic_jump)) rockchip_i2s_tdm_platform_shutdown(&pdev);
    check("shutdown open owner fails closed", panic_seen && panic_timeout == 0 && hclk.enables == 1);
    reset(true);
    pm_error = -EHOSTDOWN;
    if (!setjmp(panic_jump)) rockchip_i2s_tdm_platform_shutdown(&pdev);
    check("shutdown failed PM cannot continue", panic_seen && panic_timeout == 0 && pdev.dev.usage == 0 && hclk.enables == 1);
#ifdef HAVE_CHECKED_PM
    reset(true);
    i2s_checked_probe_clock_release(&info);
    check("probe unwind disables PM before releasing owned clocks", pdev.dev.pm_disabled && tx.enables == 0 && rx.enables == 0 && hclk.enables == 0 && disable_underflows == 0);
    reset(true);
    info.stop_proven = false;
    if (!setjmp(panic_jump)) i2s_checked_probe_clock_release(&info);
    check("probe unwind uncertain clock state fails before release", panic_seen && panic_timeout == 0 && tx.enables == 1 && rx.enables == 1 && hclk.enables == 1);
#endif
    printf("{\"passed\":%u,\"total\":%u}\n", passed, total);
    return passed != total;
}
