/* These models supply APIs, not alternative copies of production probe/PM. */
static struct platform_device pdev;
static struct resource resource;
static struct device_node node;
static struct regmap map, grf;
static struct rk_i2s_tdm_dev *allocated_info;
static struct snd_soc_component component;
static struct snd_soc_dai dai;
static struct snd_pcm_substream ss;
static const struct snd_soc_component_driver *registered_component;
static const struct of_device_id rockchip_i2s_tdm_match[] = {
    { "rockchip,rk3568-i2s-tdm", &rk3568_i2s_soc_data }, { NULL, NULL }
};
struct managed_resource { void (*release)(void *); void *data; const char *kind; };
static struct managed_resource managed[64];
static int managed_count, stale_clock_uses, leaked_clock_refs, early_enables, wrong_action_order, action_count;
static struct { struct clk *handle; const char *name; bool alive; } consumers[8];
static int consumer_count;
static bool info_lock_initialized, action_registered, map_live;
static bool bind_fmt, inject_fmt_error, check_early_callbacks, inject_irq_exit;
static bool fmt_error_fired, irq_block, irq_entered, irq_release, probe_waiting;
static bool clock_block, clock_entered, clock_release, teardown_waiting, resume_revived_irq;
static int irq_inflight, irq_syncs, remove_result;
static const char *probe_fault;
static pthread_mutex_t pm_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t irq_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t irq_cond = PTHREAD_COND_INITIALIZER;
static pthread_t irq_thread;
static unsigned int saved_ready, saved_owners, saved_mclk, saved_hclk, saved_live, saved_drained;
static void boundary_spin_lock(pthread_mutex_t *lock)
{
    pthread_mutex_lock(&irq_mutex);
    if (irq_entered && !irq_release && !pthread_equal(pthread_self(), irq_thread)) {
        probe_waiting = true;
        pthread_cond_broadcast(&irq_cond);
    }
    pthread_mutex_unlock(&irq_mutex);
    pthread_mutex_lock(lock);
}
#undef spin_lock_irqsave
#define spin_lock_irqsave(lock, flags) do { (flags) = 0; boundary_spin_lock(lock); } while (0)
#define spin_lock_init(lock) do { pthread_mutex_init(lock, NULL); info_lock_initialized = true; } while (0)
static void atomic_set(atomic_t *v, int value) { v->counter = value; }
static bool failing(const char *stage) { return probe_fault && !strcmp(probe_fault, stage); }
static void push(void (*release)(void *), void *data, const char *kind)
{ if (managed_count == 64) abort(); managed[managed_count++] = (struct managed_resource){ release, data, kind }; }
static bool clock_alive(struct clk *clk)
{ for (int i = 0; i < consumer_count; i++) if (consumers[i].handle == clk) return consumers[i].alive; return false; }
static void release_clock(void *data)
{
    struct clk *clk = data;
    leaked_clock_refs += clk->enables;
    for (int i = 0; i < consumer_count; i++) if (consumers[i].handle == clk) consumers[i].alive = false;
    free(clk);
}
static void release_alloc(void *data)
{
    if (data == allocated_info) {
        saved_ready = allocated_info->ready;
        saved_owners = allocated_info->started;
        saved_mclk = allocated_info->mclks_enabled;
        saved_hclk = allocated_info->hclk_enabled;
        saved_live = allocated_info->irq_live;
        saved_drained = allocated_info->irq_drained;
        if (info_lock_initialized) pthread_mutex_destroy(&allocated_info->lock);
    }
    free(data);
}
static void release_map(void *data) { map_live = false; }
static void release_irq(void *data) { synchronize_irq(85); }
static void release_registration(void *data) { }
static void devres_release_all_model(void)
{ while (managed_count) { struct managed_resource res = managed[--managed_count]; res.release(res.data); } }
static void raw_test_cleanup(void)
{
    /* Test-only collector after assertions. Never substitutes for driver exit. */
    while (managed_count) {
        struct managed_resource res = managed[--managed_count];
        if (res.release == release_clock || res.release == release_alloc) res.release(res.data);
    }
}
static void *devm_kmemdup(struct device *dev, const void *input, size_t size, int flags)
{ if (failing("dai_alloc")) return NULL; void *p = malloc(size); if (!p) abort(); memcpy(p, input, size); push(release_alloc, p, "dai"); return p; }
static void *devm_kzalloc(struct device *dev, size_t size, int flags)
{ if (failing("info_alloc")) return NULL; void *p = calloc(1, size); if (!p) abort(); allocated_info = p; push(release_alloc, p, "info"); return p; }
static struct clk *devm_clk_get(struct device *dev, const char *name)
{
    const char *stage = !strcmp(name, "hclk") ? "hclk_get" : !strcmp(name, "mclk_tx") ? "tx_get" : "rx_get";
    if (failing(stage)) return ERR_PTR(-EREMOTEIO);
    struct clk *clk = calloc(1, sizeof(*clk));
    if (!clk) abort();
    consumers[consumer_count++] = (typeof(consumers[0])){ clk, name, true };
    push(release_clock, clk, name);
    return clk;
}
static int devm_add_action_or_reset(struct device *dev, void (*action)(void *), void *data)
{
    action_count++;
    if (consumer_count != 3 || enable_calls) wrong_action_order++;
    if (failing("action")) { action(data); return -EREMOTEIO; }
    action_registered = true;
    push(action, data, "clock_action");
    return 0;
}
static int clk_prepare_enable(struct clk *clk)
{
    pthread_mutex_lock(&irq_mutex);
    if (clock_block && clk == allocated_info->mclk_tx) {
        clock_entered = true;
        pthread_cond_broadcast(&irq_cond);
        while (!clock_release) pthread_cond_wait(&irq_cond, &irq_mutex);
    }
    pthread_mutex_unlock(&irq_mutex);
    if (!clock_alive(clk)) stale_clock_uses++;
    if (allocated_info && allocated_info->checked_lifecycle && !action_registered) early_enables++;
    if (failing("hclk_enable") && clk == allocated_info->hclk) return -EREMOTEIO;
    return baseline_clk_prepare_enable(clk);
}
static void clk_disable_unprepare(struct clk *clk)
{
    if (!clock_alive(clk)) stale_clock_uses++;
    /* Actual handle is freed on devres clk_put; ASan detects any late access. */
    baseline_clk_disable_unprepare(clk);
}
static unsigned long clk_get_rate(struct clk *clk) { return clk->rate; }
static struct resource *platform_get_resource(struct platform_device *dev, unsigned int type, unsigned int index) { return dev->resource; }
static unsigned long resource_size(struct resource *res) { return res->end - res->start + 1; }
static bool of_device_is_compatible(struct device_node *n, const char *compat) { return !strcmp(n->compatible, compat); }
static int of_property_read_u32(struct device_node *n, const char *name, unsigned int *value)
{
    if (!strcmp(name, "rockchip,clk-trcm")) { if (n->missing_trcm) return -EINVAL; *value = n->trcm; return 0; }
    if (!strcmp(name, "rockchip,bclk-fs")) { if (!n->has_bclk) return -EINVAL; *value = n->bclk; return 0; }
    return -EINVAL;
}
static bool of_property_read_bool(struct device_node *n, const char *name) { return n->extra && !strcmp(n->extra, name); }
static void *of_find_property(struct device_node *n, const char *name, void *length) { return of_property_read_bool(n, name) ? n : NULL; }
static const struct of_device_id *of_match_device(const struct of_device_id *ids, struct device *dev) { return &ids[0]; }
static void *of_parse_phandle(struct device_node *n, const char *name, int index) { return NULL; }
static void *of_iomap(void *n, int index) { return NULL; }
static int of_i2s_resetid_get(struct device_node *n, const char *name) { return 0; }
static void *syscon_regmap_lookup_by_phandle(struct device_node *n, const char *name) { return &grf; }
static void *devm_pinctrl_get(struct device *dev) { return NULL; }
static void *pinctrl_lookup_state(void *pinctrl, const char *name) { return NULL; }
static void *devm_reset_control_get(struct device *dev, const char *name)
{ return ERR_PTR(failing(!strcmp(name, "tx-m") ? "reset_tx" : "reset_rx") ? -EREMOTEIO : -ENOENT); }
static void *devm_platform_get_and_ioremap_resource(struct platform_device *dev, unsigned int i, struct resource **res)
{ *res = dev->resource; if (failing("map")) return ERR_PTR(-EREMOTEIO); map_live = true; push(release_map, &map, "map"); return map.hw; }
static struct regmap *devm_regmap_init_mmio(struct device *dev, void *regs, const void *config)
{ return failing("regmap") ? ERR_PTR(-EREMOTEIO) : &map; }
static int platform_get_irq_optional(struct platform_device *dev, int index) { return failing("irq_get") ? -EREMOTEIO : 85; }
static int rockchip_i2s_tdm_isr(int irq, void *data) { return i2s_checked_isr(data); }
static int devm_request_irq(struct device *dev, int irq, int (*handler)(int, void *), int flags, const char *name, void *data)
{ if (failing("irq_request")) return -EREMOTEIO; push(release_irq, data, "irq"); return 0; }
static int rockchip_i2s_tdm_tx_path_prepare(struct rk_i2s_tdm_dev *info, struct device_node *n) { return 0; }
static int rockchip_i2s_tdm_rx_path_prepare(struct rk_i2s_tdm_dev *info, struct device_node *n) { return 0; }
static int rockchip_i2s_tdm_keep_clk_always_on(struct rk_i2s_tdm_dev *info) { return 0; }
static void rockchip_i2s_tdm_stop(struct rk_i2s_tdm_dev *info, int stream) { }
static void dev_set_drvdata(struct device *dev, void *data) { dev->data = data; }
static void pm_runtime_enable(struct device *dev) { dev->pm_disabled = false; }
static bool pm_runtime_enabled(struct device *dev) { return !dev->pm_disabled; }
static int pm_runtime_get_sync(struct device *dev)
{
    pthread_mutex_lock(&pm_mutex);
    dev->usage++;
    int ret = pm_error;
    if (!ret && dev->suspended) {
        ret = i2s_tdm_runtime_resume(dev);
        if (!ret) dev->suspended = false;
    }
    pthread_mutex_unlock(&pm_mutex);
    return ret;
}
static int pm_runtime_put(struct device *dev)
{ pthread_mutex_lock(&pm_mutex); dev->usage--; pthread_mutex_unlock(&pm_mutex); return 0; /* Kernel API schedules idle asynchronously. */ }
static void pm_runtime_put_noidle(struct device *dev)
{ pthread_mutex_lock(&pm_mutex); dev->usage--; pthread_mutex_unlock(&pm_mutex); }
static void pm_runtime_disable(struct device *dev)
{ pthread_mutex_lock(&pm_mutex); dev->pm_disabled = true; pthread_mutex_unlock(&pm_mutex); }
static int runtime_idle_model(void)
{
    pthread_mutex_lock(&pm_mutex);
    int ret = i2s_tdm_runtime_suspend(&pdev.dev);
    if (!ret) pdev.dev.suspended = true;
    pthread_mutex_unlock(&pm_mutex);
    return ret;
}
static int regmap_read(struct regmap *regmap, unsigned int reg, unsigned int *value)
{
    if (reg == I2S_INTSR) {
        pthread_mutex_lock(&irq_mutex);
        if (irq_block) {
            irq_entered = true;
            pthread_cond_broadcast(&irq_cond);
            while (!irq_release) pthread_cond_wait(&irq_cond, &irq_mutex);
        }
        pthread_mutex_unlock(&irq_mutex);
    }
    return baseline_regmap_read(regmap, reg, value);
}
static int regmap_update_bits(struct regmap *regmap, unsigned int reg, unsigned int mask, unsigned int value)
{
    if (inject_fmt_error && allocated_info->configuring && !allocated_info->power_transition && !fmt_error_fired) {
        fmt_error_fired = true;
        faults[(atomic_load(&operations) + 1) % 64] = -EREMOTEIO;
    }
    return baseline_regmap_update_bits(regmap, reg, mask, value);
}
static int regmap_write_bits(struct regmap *regmap, unsigned int reg, unsigned int mask, unsigned int value)
{ return baseline_regmap_write_bits(regmap, reg, mask, value); }
static int regmap_write(struct regmap *regmap, unsigned int reg, unsigned int value)
{ return regmap_write_bits(regmap, reg, ~0U, value); }
static void synchronize_irq(unsigned int irq)
{
    int unlocked = pthread_mutex_trylock(&allocated_info->lock);
    check("process IRQ wait outside I2S lock", unlocked == 0);
    if (!unlocked) pthread_mutex_unlock(&allocated_info->lock);
    pthread_mutex_lock(&irq_mutex);
    while (irq_inflight) pthread_cond_wait(&irq_cond, &irq_mutex);
    irq_syncs++;
    if (clock_block && allocated_info->shutting_down) {
        teardown_waiting = true;
        pthread_cond_broadcast(&irq_cond);
    }
    pthread_mutex_unlock(&irq_mutex);
}
static int snd_pcm_stop_xrun(struct snd_pcm_substream *substream) { return 0; }
static void *irq_worker(void *data)
{
    pthread_mutex_lock(&irq_mutex);
    irq_inflight++;
    pthread_mutex_unlock(&irq_mutex);
    i2s_checked_isr(allocated_info);
    pthread_mutex_lock(&irq_mutex);
    irq_inflight--;
    pthread_cond_broadcast(&irq_cond);
    pthread_mutex_unlock(&irq_mutex);
    return NULL;
}
static void early_callbacks(void)
{
    if (!check_early_callbacks) return;
    int ret = rockchip_i2s_tdm_startup(&ss, &dai);
    check("startup before ready rejected without poison", ret == -EAGAIN && !allocated_info->runtime_error);
    if (!ret) rockchip_i2s_tdm_shutdown(&ss, &dai);
    int before = atomic_load(&operations);
    check("component START before ready rejected", i2s_checked_component_trigger(&component, &ss, SNDRV_PCM_TRIGGER_START) == -EAGAIN);
    ret = i2s_checked_trigger(allocated_info, 0, SNDRV_PCM_TRIGGER_START);
    check("actual DAI START rechecks ready", ret == -EAGAIN);
    if (!ret) i2s_checked_trigger(allocated_info, 0, SNDRV_PCM_TRIGGER_STOP);
    check("prepare before ready rejected", i2s_checked_prepare(&ss, &dai) == -EAGAIN);
    check("unready callbacks do not touch hardware", atomic_load(&operations) == before);
}
static int devm_snd_soc_register_component(struct device *dev, const struct snd_soc_component_driver *driver, struct snd_soc_dai_driver *soc_dai, int count)
{
    registered_component = driver;
    component.dev = dev;
    dai.dev = dev;
    dai.component = &component;
    if (allocated_info->checked_lifecycle && bind_fmt) {
        int ret = i2s_checked_set_fmt(allocated_info, dev, SND_SOC_DAIFMT_CBS_CFS | SND_SOC_DAIFMT_NB_NF | SND_SOC_DAIFMT_I2S);
        if (ret) return ret;
    }
    if (failing("component")) return -EREMOTEIO;
    push(release_registration, &component, "component");
    early_callbacks();
    return 0;
}
static int devm_snd_dmaengine_pcm_register(struct device *dev, const void *config, int flags)
{
    early_callbacks();
    if (inject_irq_exit) {
        irq_block = true;
        pthread_create(&irq_thread, NULL, irq_worker, NULL);
        pthread_mutex_lock(&irq_mutex);
        while (!irq_entered) pthread_cond_wait(&irq_cond, &irq_mutex);
        pthread_mutex_unlock(&irq_mutex);
    }
    if (failing("pcm")) return -EREMOTEIO;
    push(release_registration, dev, "pcm");
    return 0;
}
static int devm_snd_dmaengine_dlp_register(struct device *dev, const void *config) { return devm_snd_dmaengine_pcm_register(dev, config, 0); }
static int devm_device_add_group(struct device *dev, const struct attribute_group *group)
{ early_callbacks(); if (failing("sysfs")) return -EREMOTEIO; push(release_registration, dev, "sysfs"); return 0; }
#define dev_info(...) ((void)0)
