static struct device dev;
static struct regmap map;
static struct rk_i2s_tdm_dev info;
static struct snd_soc_dai dai;
static struct snd_soc_component component;
static struct snd_pcm_substream ss[2];
static bool lock_initialized;
static unsigned int passed, total, xruns;
static bool xrun_under_lock, runtime_alive, used_after_close;
static pthread_mutex_t irq_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t irq_cond = PTHREAD_COND_INITIALIZER;
static bool pause_xrun, xrun_captured, release_xrun, close_done, sync_entered;
static int active_irq;
static void check(const char *name, bool ok)
{ total++; passed += ok; if (!ok) fprintf(stderr, "FAIL %s\n", name); }
static void reset(void)
{
    if (lock_initialized) pthread_mutex_destroy(&info.lock);
    memset(&map, 0, sizeof(map));
    memset(&info, 0, sizeof(info));
    memset(&dai, 0, sizeof(dai));
    memset(faults, 0, sizeof(faults));
    memset(polls, 0, sizeof(polls));
    atomic_store(&operations, 0);
    poll_calls = reset_calls = force_calls = hw_writes = 0;
    dev.data = &info;
    dai.dev = &dev;
    component.dev = &dev;
    info.dev = &dev;
    info.regmap = &map;
    info.is_master_mode = true;
    info.clk_trcm = I2S_CKR_TRCM_TXONLY;
    ss[0].stream = 0;
    ss[1].stream = 1;
    pthread_mutex_init(&info.lock, NULL);
    lock_initialized = true;
#ifdef HAVE_CHECKED_FIELDS
    info.checked_lifecycle = true;
#endif
#ifdef HAVE_CHECKED_IRQ
    info.irq = 85;
    info.irq_live = true;
    info.mclks_enabled = true;
    info.stop_proven = true;
#endif
#ifdef HAVE_READBACK
    info.regs = map.hw;
#endif
    xruns = 0;
    xrun_under_lock = used_after_close = pause_xrun = xrun_captured = release_xrun = close_done = sync_entered = false;
    runtime_alive = true;
    active_irq = 0;
}
static int snd_pcm_stop_xrun(struct snd_pcm_substream *substream)
{
    int lock_ret = pthread_mutex_trylock(&info.lock);
    if (lock_ret == 0) pthread_mutex_unlock(&info.lock);
    else xrun_under_lock = true;
    pthread_mutex_lock(&irq_mutex);
    xruns++;
    xrun_captured = true;
    pthread_cond_broadcast(&irq_cond);
    while (pause_xrun && !release_xrun) pthread_cond_wait(&irq_cond, &irq_mutex);
    used_after_close |= !runtime_alive;
    pthread_mutex_unlock(&irq_mutex);
    return rockchip_i2s_tdm_trigger(substream, SNDRV_PCM_TRIGGER_STOP, &dai);
}
static void synchronize_irq(unsigned int irq)
{
    int lock_ret = pthread_mutex_trylock(&info.lock);
    if (lock_ret == 0) pthread_mutex_unlock(&info.lock);
    else xrun_under_lock = true;
    pthread_mutex_lock(&irq_mutex);
    sync_entered = true;
    pthread_cond_broadcast(&irq_cond);
    while (active_irq) pthread_cond_wait(&irq_cond, &irq_mutex);
    pthread_mutex_unlock(&irq_mutex);
}
static void *irq_thread(void *unused)
{
    pthread_mutex_lock(&irq_mutex);
    active_irq++;
    pthread_mutex_unlock(&irq_mutex);
    rockchip_i2s_tdm_isr(85, &info);
    pthread_mutex_lock(&irq_mutex);
    active_irq--;
    pthread_cond_broadcast(&irq_cond);
    pthread_mutex_unlock(&irq_mutex);
    return NULL;
}
static void *close_thread(void *direction)
{
    rockchip_i2s_tdm_shutdown(&ss[(intptr_t)direction], &dai);
    pthread_mutex_lock(&irq_mutex);
    close_done = true;
    runtime_alive = false;
    pthread_cond_broadcast(&irq_cond);
    pthread_mutex_unlock(&irq_mutex);
    return NULL;
}
int main(void)
{
    for (int direction = 0; direction < 2; direction++) {
        reset();
        check("startup publishes", rockchip_i2s_tdm_startup(&ss[direction], &dai) == 0 && info.substreams[direction] == &ss[direction]);
        check("duplicate startup rejected", rockchip_i2s_tdm_startup(&ss[direction], &dai) == -EBUSY);
        rockchip_i2s_tdm_trigger(&ss[direction], SNDRV_PCM_TRIGGER_START, &dai);
        map.cache[I2S_INTSR / 4] = direction ? I2S_INTSR_RXOI_ACT : I2S_INTSR_TXUI_ACT;
        check("ISR handled actual active IRQ", rockchip_i2s_tdm_isr(85, &info) == IRQ_HANDLED && xruns == 1);
        check("ISR releases I2S lock before ALSA", !xrun_under_lock);
        reset();
        rockchip_i2s_tdm_startup(&ss[direction], &dai);
        rockchip_i2s_tdm_trigger(&ss[direction], SNDRV_PCM_TRIGGER_START, &dai);
        map.cache[I2S_INTSR / 4] = direction ? I2S_INTSR_RXOI_ACT : I2S_INTSR_TXUI_ACT;
        pause_xrun = true;
        pthread_t irq_worker, close_worker;
        pthread_create(&irq_worker, NULL, irq_thread, NULL);
        pthread_mutex_lock(&irq_mutex);
        while (!xrun_captured) pthread_cond_wait(&irq_cond, &irq_mutex);
        pthread_mutex_unlock(&irq_mutex);
        pthread_create(&close_worker, NULL, close_thread, (void *)(intptr_t)direction);
        pthread_mutex_lock(&irq_mutex);
        while (!sync_entered && !close_done) pthread_cond_wait(&irq_cond, &irq_mutex);
        check("shutdown blocks captured CPU IRQ", sync_entered && !close_done && runtime_alive);
        check("shutdown revoked pointer before barrier", info.substreams[direction] == NULL);
        release_xrun = true;
        pthread_cond_broadcast(&irq_cond);
        pthread_mutex_unlock(&irq_mutex);
        pthread_join(irq_worker, NULL);
        pthread_join(close_worker, NULL);
        check("captured IRQ cannot use released runtime", !used_after_close && close_done);
        check("shutdown does not wait under I2S lock", !xrun_under_lock);
        reset();
        rockchip_i2s_tdm_startup(&ss[direction], &dai);
        rockchip_i2s_tdm_trigger(&ss[direction], SNDRV_PCM_TRIGGER_START, &dai);
        atomic_store(&operations, 0);
        faults[1] = -EREMOTEIO;
        check("ISR read error handled", rockchip_i2s_tdm_isr(85, &info) == IRQ_HANDLED);
#ifdef HAVE_CHECKED_FIELDS
        check("ISR read fault sticky", info.runtime_error == -EREMOTEIO);
#else
        check("ISR read fault sticky", false);
#endif
    }
    reset();
    check("shared unrelated IRQ returns NONE", rockchip_i2s_tdm_isr(85, &info) == IRQ_NONE && xruns == 0);
#ifdef HAVE_CHECKED_IRQ
    info.irq_live = false;
#endif
    atomic_store(&operations, 0);
    check("gated IRQ no MMIO", rockchip_i2s_tdm_isr(85, &info) == IRQ_NONE && atomic_load(&operations) == 0);
    reset();
#ifdef HAVE_CHECKED_FIELDS
    info.runtime_error = -EIO;
#endif
    check("startup sticky refused", rockchip_i2s_tdm_startup(&ss[0], &dai) == -EIO && info.substreams[0] == NULL);
#ifdef HAVE_CHECKED_IRQ
    check("prepare sticky refused", i2s_checked_prepare(&ss[0], &dai) == -EIO && atomic_load(&operations) == 0);
    check("component START precheck sticky", i2s_checked_component_trigger(&component, &ss[0], SNDRV_PCM_TRIGGER_START) == -EIO && atomic_load(&operations) == 0);
    check("component STOP does not block cleanup", i2s_checked_component_trigger(&component, &ss[0], SNDRV_PCM_TRIGGER_STOP) == 0 && atomic_load(&operations) == 0);
#else
    check("prepare sticky refused", false);
    check("component START precheck sticky", false);
    check("component STOP does not block cleanup", false);
#endif
    reset();
#ifdef HAVE_CHECKED_IRQ
    info.stop_proven = false;
    check("component START requires CPU stop proof before DMA", i2s_checked_component_trigger(&component, &ss[0], SNDRV_PCM_TRIGGER_START) == -EBUSY && atomic_load(&operations) == 0);
#else
    check("component START requires CPU stop proof before DMA", false);
#endif
    printf("{\"passed\":%u,\"total\":%u}\n", passed, total);
    return passed != total;
}
