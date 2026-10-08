static struct platform_device pdev;
static struct resource resource;
static struct device_node node;
static struct rk_i2s_tdm_dev info;
static struct regmap map, grf;
static bool lock_initialized;
static unsigned int passed, total;
static void check(const char *name, bool ok) { total++; passed += ok; if (!ok) fprintf(stderr, "FAIL %s\n", name); }
static void reset(void)
{
    if (lock_initialized) pthread_mutex_destroy(&info.lock);
    memset(&pdev, 0, sizeof(pdev));
    memset(&info, 0, sizeof(info));
    memset(&map, 0, sizeof(map));
    memset(&grf, 0, sizeof(grf));
    memset(&node, 0, sizeof(node));
    memset(faults, 0, sizeof(faults));
    atomic_store(&operations, 0);
    resource.start = 0xfe410000;
    resource.end = resource.start + 0xfff;
    pdev.resource = &resource;
    pdev.dev.data = &info;
    pdev.dev.of_node = &node;
    node.compatible = "rockchip,rk3568-i2s-tdm";
    node.trcm = 1;
    info.dev = &pdev.dev;
    info.regmap = &map;
    info.grf = &grf;
    info.clk_trcm = I2S_CKR_TRCM_TXONLY;
    info.soc_data = &rk3568_i2s_soc_data;
    pthread_mutex_init(&info.lock, NULL);
    lock_initialized = true;
#ifdef HAVE_CONFIG_CHECKED
    info.checked_lifecycle = true;
#endif
}
int main(void)
{
    reset();
    check("probe config success", real_probe_initial_block(&pdev, &info) == 0 && atomic_load(&operations) == 4);
    check("real SoC GRF TX clock route", grf.hw[0x504 / 4] == RK3568_I2S1_CLK_TXONLY);
    for (int ordinal = 1; ordinal <= 4; ordinal++) {
        reset();
        faults[ordinal] = -EREMOTEIO;
        check("probe config errno propagated", real_probe_initial_block(&pdev, &info) == -EREMOTEIO);
        check("probe config failure prefix", atomic_load(&operations) == ordinal);
    }
    reset();
    info.grf = ERR_PTR(-EPROBE_DEFER);
    check("required GRF defer preserved", real_probe_initial_block(&pdev, &info) == -EPROBE_DEFER);
#ifdef HAVE_CONFIG_CHECKED
    reset();
    check("locked actual profile accepted", i2s_checked_profile(&pdev));
    const char *extras[] = { "rockchip,always-on", "rockchip,hdmi-path", "rockchip,mclk-calibrate", "rockchip,io-multiplex", "rockchip,tdm-multi-lanes", "rockchip,no-dmaengine", "rockchip,digital-loopback", "rockchip,i2s-tx-route", "rockchip,i2s-rx-route" };
    for (unsigned int i = 0; i < sizeof(extras) / sizeof(extras[0]); i++) { reset(); node.extra = extras[i]; check("other feature retains legacy profile", !i2s_checked_profile(&pdev)); }
    reset(); resource.start = 0xfe430000; check("other controller not opted in", !i2s_checked_profile(&pdev));
    reset(); resource.end--; check("wrong MMIO span not opted in", !i2s_checked_profile(&pdev));
    reset(); node.trcm = 0; check("independent TRCM not opted in", !i2s_checked_profile(&pdev));
    reset(); node.missing_trcm = true; check("missing TRCM not guessed", !i2s_checked_profile(&pdev));
    reset(); node.has_bclk = true; node.bclk = 32; check("different BCLK not opted in", !i2s_checked_profile(&pdev));
    reset(); node.compatible = "rockchip,rk3588-i2s-tdm"; check("different SoC not opted in", !i2s_checked_profile(&pdev));
    reset();
    char buffer[4096];
    info.ready = info.stop_proven = info.irq_drained = info.hclk_enabled = true;
    info.stop_reads = 2;
    check("readonly closed proof schema", rk3568_lifecycle_state_show(&pdev.dev, NULL, buffer) > 0 && !strcmp(buffer, "version=1 ready=1 error=0 owners=0 open=0 stop_proven=1 stop_reads=2 irq_live=0 irq_drained=1 mclk_leases=0 hclk_lease=1 configuring=0 power_transition=0 shutting_down=0\n"));
    check("readonly reader no hardware/PM operation", atomic_load(&operations) == 0 && pdev.dev.usage == 0);
    info.runtime_error = -EIO;
    info.started = 2;
    struct snd_pcm_substream owner = { .stream = 1 };
    info.substreams[1] = &owner;
    info.power_transition = info.mclks_enabled = true;
    rk3568_lifecycle_state_show(&pdev.dev, NULL, buffer);
    check("readonly exposes sticky and direction owners", strstr(buffer, "error=-5 owners=2 open=2") != NULL);
    check("readonly exposes clock transition lease", strstr(buffer, "mclk_leases=1") && strstr(buffer, "power_transition=1"));
#else
    check("locked actual profile accepted", false);
    check("readonly state evidence available", false);
#endif
    printf("{\"passed\":%u,\"total\":%u}\n", passed, total);
    return passed != total;
}
