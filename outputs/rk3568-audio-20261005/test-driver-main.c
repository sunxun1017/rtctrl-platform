/* SPDX-License-Identifier: GPL-2.0-or-later */
static int total, failures;
static struct device parent_dev, codec_dev;
static struct rk808 pmic;
static struct platform_device platform;
static struct rk817_codec_priv priv;
static struct snd_soc_component component;

static void fresh(void)
{
    free(allocated_priv);
    allocated_priv = NULL;
    memset(&f, 0, sizeof(f));
    memset(&priv, 0, sizeof(priv));
    parent_dev = (struct device){ .of_node = &child_node, .data = &pmic };
    codec_dev = (struct device){ .parent = &parent_dev };
    platform = (struct platform_device){ .dev = codec_dev };
    pmic.regmap = &map;
    f.map_live = 1;
    priv.regmap = &map;
    priv.mclk = &clock_stub;
    component = (struct snd_soc_component){ .dev = &codec_dev, .data = &priv };
    f.chip_name = 0x80;
    f.chip_ver = 0x15;
    f.read_errno = -EREMOTEIO;
    f.write_errno = -EIO;
}

static void check(const char *name, bool passed)
{
    total++;
    failures += !passed;
    printf("{\"name\":\"%s\",\"passed\":%s}\n", name, passed ? "true" : "false");
}

static bool no_probe_resources(void)
{
    return f.clk_refs == 0 && f.mutex_live == 0 && !priv.component &&
           !component.regmap && f.map_frees == 0;
}

static bool reset_sequence(int version)
{
    const unsigned int regs[12] = { 0x14, 0x30, 0x48, 0x15, 0x43, 0x44,
                                    0x45, 0x47, 0x15, 0x42, 0x46, 0x15 };
    const unsigned int vals[12] = { 0x40, 0x02, 0x00, 0xff, 0x58, 0x2d,
                                    0x0c, 0x00, 0x00, version <= 4 ? 0x0c : 0x04,
                                    version <= 4 ? 0x95 : 0xa5, 0x00 };
    return f.write_count == 12 && !memcmp(f.regs, regs, sizeof(regs)) &&
           !memcmp(f.vals, vals, sizeof(vals));
}

int main(void)
{
    int ret;
    char name[96];
    for (int version = 4; version <= 5; version++) {
        fresh();
        priv.chip_ver = version;
        ret = rk817_reset(&component);
        snprintf(name, sizeof(name), "reset_sequence_chip_%d_default_clocks_off", version);
        check(name, ret == 0 && reset_sequence(version));
        for (int failure = 1; failure <= 12; failure++) {
            fresh();
            priv.chip_ver = version;
            f.write_fail = failure;
            ret = rk817_reset(&component);
            snprintf(name, sizeof(name), "reset_chip_%d_write_%02d_error_stops", version, failure);
            check(name, ret == -EIO && f.write_count == failure);
        }
    }
    fresh();
    component.data = NULL;
    check("probe_missing_private", rk817_probe(&component) == -EINVAL && f.map_init == 0);
    for (int failure = 1; failure <= 2; failure++) {
        fresh();
        f.read_fail = failure;
        ret = rk817_probe(&component);
        snprintf(name, sizeof(name), "probe_chip_read_%d_preserves_errno_releases_borrowed_map", failure);
        check(name, ret == -EREMOTEIO && f.read_count == failure && f.clk_calls == 0 &&
                    f.write_count == 0 && no_probe_resources());
    }
    fresh();
    f.clk_error = -EPROBE_DEFER;
    ret = rk817_probe(&component);
    check("probe_mclk_enable_defer_no_disable_failed_enable", ret == -EPROBE_DEFER &&
          f.clk_disables == 0 && f.write_count == 0 && no_probe_resources());
    for (int failure = 1; failure <= 12; failure++) {
        fresh();
        f.write_fail = failure;
        ret = rk817_probe(&component);
        snprintf(name, sizeof(name), "probe_reset_write_%02d_failure_self_cleanup_no_remove", failure);
        check(name, ret == -EIO && f.write_count == failure && f.controls_calls == 0 &&
                    f.clk_disables == 1 && no_probe_resources());
    }
    fresh();
    f.controls_error = -ENOMEM;
    ret = rk817_probe(&component);
    check("probe_controls_failure_self_cleanup_no_remove", ret == -ENOMEM && f.controls_calls == 1 &&
          f.mutex_inits == 1 && f.mutex_destroys == 1 && f.clk_disables == 1 && no_probe_resources());
    fresh();
    ret = rk817_probe(&component);
    check("probe_success_default_OFF_read_and_reset_only", ret == 0 &&
          priv.playback_path == OFF && priv.capture_path == MIC_OFF &&
          priv.clk_capture == 0 && priv.clk_playback == 0 && priv.chip_ver == 5 &&
          f.read_count == 2 && f.read_regs[0] == 0xed && f.read_regs[1] == 0xee &&
          f.clk_refs == 1 && f.mutex_live == 1 && f.controls_calls == 1 &&
          priv.component == &component && component.regmap == &map && reset_sequence(5));
    rk817_remove(&component);
    check("remove_after_success_or_later_machine_failure_no_devm_map_free", f.power_down == 1 &&
          f.clk_disables == 1 && f.mutex_destroys == 1 && no_probe_resources());

    fresh();
    parent_dev.of_node = NULL;
    check("dt_missing_parent_node", rk817_codec_parse_dt_property(&codec_dev, &priv) == -ENODEV &&
          f.node_refs == 0 && f.node_puts == 0);
    fresh();
    f.node_missing = 1;
    check("dt_missing_child", rk817_codec_parse_dt_property(&codec_dev, &priv) == -ENODEV &&
          f.node_refs == 0 && f.node_puts == 0);
    for (int gpio = 0; gpio <= 1; gpio++) {
        const int errors[3] = { -EPROBE_DEFER, -EIO, -EBUSY };
        for (int i = 0; i < 3; i++) {
            fresh();
            if (gpio)
                f.spk_error = errors[i];
            else
                f.hp_error = errors[i];
            ret = rk817_codec_parse_dt_property(&codec_dev, &priv);
            snprintf(name, sizeof(name), "dt_%s_gpio_errno_%d_put_child", gpio ? "spk" : "hp", -errors[i]);
            check(name, ret == errors[i] && f.node_refs == 0 && f.node_puts == 1 &&
                        !IS_ERR(priv.hp_ctl_gpio) && !IS_ERR(priv.spk_ctl_gpio) &&
                        (gpio || f.spk_calls == 0));
        }
    }
    fresh();
    ret = rk817_codec_parse_dt_property(&codec_dev, &priv);
    check("dt_optional_missing_defaults_put_child", ret == 0 && f.node_refs == 0 && f.node_puts == 1 &&
          !priv.hp_ctl_gpio && !priv.spk_ctl_gpio && priv.hp_volume == 3 && priv.spk_volume == 3 &&
          priv.capture_volume == 0 && priv.spk_mute_delay == 0 && priv.hp_mute_delay == 0 &&
          !priv.mic_in_differential && !f.gpio_flags_bad);
    fresh();
    f.property_values = 1;
    ret = rk817_codec_parse_dt_property(&codec_dev, &priv);
    check("dt_existing_properties_preserved_gpio_logical_OFF", ret == 0 &&
          priv.hp_ctl_gpio == &hp_gpio && priv.spk_ctl_gpio == &spk_gpio &&
          priv.spk_volume == 3 && priv.hp_volume == 3 && priv.capture_volume == 1 &&
          priv.spk_mute_delay == 12 && priv.hp_mute_delay == 30 && priv.mic_in_differential &&
          f.node_refs == 0 && f.node_puts == 1 && !f.gpio_flags_bad);

    fresh();
    parent_dev.data = NULL;
    check("platform_missing_parent_private", rk817_platform_probe(&platform) == -EINVAL && !platform.dev.data);
    fresh();
    f.alloc_error = 1;
    check("platform_allocation_failure", rk817_platform_probe(&platform) == -ENOMEM && !platform.dev.data);
    const int errors[4] = { -EPROBE_DEFER, -EREMOTEIO, -EPROBE_DEFER, -ENOMEM };
    for (int stage = 0; stage < 4; stage++) {
        fresh();
        if (stage == 0)
            f.hp_error = errors[stage];
        if (stage == 1)
            pmic.regmap = ERR_PTR(errors[stage]);
        if (stage == 2)
            f.getclk_error = errors[stage];
        if (stage == 3)
            f.register_error = errors[stage];
        ret = rk817_platform_probe(&platform);
        snprintf(name, sizeof(name), "platform_stage_%d_preserves_errno_clears_failed_drvdata", stage);
        check(name, ret == errors[stage] && !platform.dev.data && f.clk_refs == 0 && f.map_frees == 0 &&
                    f.register_calls == (stage == 3));
    }
    fresh();
    ret = rk817_platform_probe(&platform);
    check("platform_success_no_component_probe_yet", ret == 0 && platform.dev.data == allocated_priv &&
          f.register_calls == 1 && f.clk_calls == 0 && f.write_count == 0 && f.node_refs == 0);
    release_child_devres();
    check("platform_child_devres_unregister_keeps_borrowed_pmic_map", f.parent_maps == 0 &&
          f.map_live == 1 && f.map_frees == 0 && f.unregister_order > 0 && f.map_allocs == 0);
    fresh();
    f.getclk_error = -EPROBE_DEFER;
    ret = rk817_platform_probe(&platform);
    release_child_devres();
    check("platform_mclk_defer_before_any_map_allocation", ret == -EPROBE_DEFER &&
          f.getclk_calls == 1 && f.map_allocs == 0 && f.parent_maps == 0 && !platform.dev.data);
    fresh();
    pmic.regmap = NULL;
    ret = rk817_platform_probe(&platform);
    release_child_devres();
    check("platform_missing_parent_map_rejected_no_alloc_or_free", ret == -ENODEV &&
          f.map_allocs == 0 && f.map_frees == 0 && f.map_live == 1 &&
          f.register_calls == 0 && !platform.dev.data);
    fresh();
    f.register_error = -ENOMEM;
    ret = rk817_platform_probe(&platform);
    release_child_devres();
    check("platform_component_register_failure_keeps_pmic_map", ret == -ENOMEM &&
          f.map_allocs == 0 && f.map_frees == 0 && f.map_live == 1 &&
          f.parent_maps == 0 && !platform.dev.data);
    fresh();
    ret = rk817_platform_probe(&platform);
    struct rk817_codec_priv *live = allocated_priv;
    component.data = live;
    f.read_fail = 1;
    int failed_probe = rk817_probe(&component);
    check("component_probe_failure_keeps_borrowed_pmic_map_for_rebind", ret == 0 &&
          failed_probe == -EREMOTEIO && f.map_live == 1 && f.map_frees == 0 && !live->component &&
          !component.regmap && f.parent_maps == 0);
    release_child_devres();
    check("failed_component_then_child_remove_retains_pmic_map", f.map_live == 1 &&
          f.map_frees == 0 && f.map_allocs == 0 && f.unregister_order > 0);

    struct snd_soc_dai dai = { .component = &component };
    for (int mode = 0; mode < 2; mode++) {
        fresh();
        ret = rk817_set_dai_fmt(&dai, mode ? SND_SOC_DAIFMT_CBM_CFM : SND_SOC_DAIFMT_CBS_CFS);
        snprintf(name, sizeof(name), "machine_set_fmt_%s", mode ? "master" : "slave");
        check(name, ret == 0 && f.update_count == 1 && f.update_reg == 0x48 &&
                    f.update_mask == RK817_I2S_MODE_MASK && f.update_val == (mode ? RK817_I2S_MODE_MST : 0));
    }
    fresh();
    f.update_error = 1;
    check("set_fmt_changed_positive_normalized_success", rk817_set_dai_fmt(&dai, SND_SOC_DAIFMT_CBS_CFS) == 0);
    fresh();
    f.update_error = -EREMOTEIO;
    check("set_fmt_io_failure_propagates", rk817_set_dai_fmt(&dai, SND_SOC_DAIFMT_CBS_CFS) == -EREMOTEIO);
    fresh();
    check("set_fmt_invalid_master_no_io", rk817_set_dai_fmt(&dai, 0) == -EINVAL && f.update_count == 0);
    free(allocated_priv);
    fprintf(stderr, "RK817_REAL_FUNCTION_TESTS total=%d failures=%d\n", total, failures);
    return failures ? 1 : 0;
}
