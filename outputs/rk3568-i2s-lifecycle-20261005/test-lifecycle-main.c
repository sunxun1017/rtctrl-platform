static struct device dev;
static struct regmap map;
static struct rk_i2s_tdm_dev info;
static struct snd_soc_dai dai;
static struct snd_pcm_substream ss[2];
static bool lock_initialized;
static unsigned int passed, total;
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
    ignore_xfer_stop = false;
    dev.data = &info;
    dai.dev = &dev;
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
#ifdef HAVE_CHECKED_TRIGGER
    info.stop_proven = true;
#endif
#ifdef HAVE_READBACK
    info.regs = map.hw;
#endif
}
static bool poisoned(void)
{
#ifdef HAVE_CHECKED_FIELDS
    return info.runtime_error != 0;
#else
    return false;
#endif
}
static int owners(void)
{
#ifdef HAVE_CHECKED_TRIGGER
    return info.started;
#else
    return info.refcount.counter;
#endif
}
static int fifo_clear(void)
{
#ifdef HAVE_CHECKED_TRIGGER
    return i2s_checked_clear_locked(&info);
#else
    return rockchip_i2s_tdm_clear(&info, I2S_CLR_TXC | I2S_CLR_RXC);
#endif
}
static unsigned int dma_mask(int direction)
{ return direction ? I2S_DMACR_RDE_MASK : I2S_DMACR_TDE_MASK; }
static int trigger(int direction, int cmd)
{ return rockchip_i2s_tdm_trigger(&ss[direction], cmd, &dai); }
static pthread_barrier_t start_barrier;
static int start_results[2];
static void *concurrent_start(void *direction)
{
    int index = (intptr_t)direction;
    pthread_barrier_wait(&start_barrier);
    start_results[index] = trigger(index, SNDRV_PCM_TRIGGER_START);
    return NULL;
}
int main(void)
{
    for (int direction = 0; direction < 2; direction++) {
        reset();
        check("STOP before START does not underflow", trigger(direction, SNDRV_PCM_TRIGGER_STOP) == 0 && owners() == 0);
        reset();
        check("START succeeds", trigger(direction, SNDRV_PCM_TRIGGER_START) == 0);
        int expected_owner = direction == 0 ? 1 : 2;
        check("direction ownership", owners() == expected_owner);
        check("START requests/XFER physically enabled", (map.hw[I2S_DMACR / 4] & dma_mask(direction)) && (map.hw[I2S_XFER / 4] & 3) == 3);
        check("duplicate START no extra ownership", trigger(direction, SNDRV_PCM_TRIGGER_START) == 0 && owners() == expected_owner);
        check("opposite START conflict", trigger(1 - direction, SNDRV_PCM_TRIGGER_START) == -EBUSY && !poisoned() && owners() == expected_owner);
        check("STOP succeeds and releases", trigger(direction, SNDRV_PCM_TRIGGER_STOP) == 0 && owners() == 0);
        check("STOP requests/XFER physically off", !(map.hw[I2S_DMACR / 4] & dma_mask(direction)) && !(map.hw[I2S_XFER / 4] & 3));
        check("duplicate STOP no underflow", trigger(direction, SNDRV_PCM_TRIGGER_STOP) == 0 && owners() == 0);
        for (int ordinal = 1; ordinal <= 4; ordinal++) {
            reset();
            faults[ordinal] = -EREMOTEIO;
            check("START errno preserved", trigger(direction, SNDRV_PCM_TRIGGER_START) == -EREMOTEIO);
            check("START failure sticky", poisoned());
            check("START rollback hardware off", !(map.hw[I2S_DMACR / 4] & dma_mask(direction)) && !(map.hw[I2S_XFER / 4] & 3));
            check("START failed no owner", owners() == 0);
            int before = atomic_load(&operations);
            check("START retry rejected without hardware", trigger(direction, SNDRV_PCM_TRIGGER_START) == -EREMOTEIO && atomic_load(&operations) == before);
        }
        reset();
        trigger(direction, SNDRV_PCM_TRIGGER_START);
        atomic_store(&operations, 0);
        faults[1] = -EREMOTEIO;
        faults[3] = -EIO;
        check("STOP multiple errors first wins", trigger(direction, SNDRV_PCM_TRIGGER_STOP) == -EREMOTEIO);
        check("STOP keeps trying independent cleanup", atomic_load(&operations) >= 6 && !(map.hw[I2S_XFER / 4] & 3) && poll_calls > 0);
        check("STOP failure sticky", poisoned());
        reset();
        trigger(direction, SNDRV_PCM_TRIGGER_START);
        atomic_store(&operations, 0);
        faults[
#ifdef HAVE_READBACK
            7
#else
            4
#endif
        ] = -EIO;
        check("failed STOP XFER returns error", trigger(direction, SNDRV_PCM_TRIGGER_STOP) == -EIO && (map.hw[I2S_XFER / 4] & 3));
        memset(faults, 0, sizeof(faults));
        atomic_store(&operations, 0);
        check("cache poisoned STOP retries real write", trigger(direction, SNDRV_PCM_TRIGGER_STOP) == 0 && !(map.hw[I2S_XFER / 4] & 3));
        check("successful later STOP cannot clear sticky", poisoned());
        reset();
        check("PAUSE/RESUME balanced", trigger(direction, SNDRV_PCM_TRIGGER_RESUME) == 0 && trigger(direction, SNDRV_PCM_TRIGGER_PAUSE_PUSH) == 0 && trigger(direction, SNDRV_PCM_TRIGGER_PAUSE_RELEASE) == 0 && trigger(direction, SNDRV_PCM_TRIGGER_SUSPEND) == 0 && owners() == 0);
    }
    reset();
    faults[1] = -EIO;
    check("FIFO initial write error", fifo_clear() == -EIO && poll_calls == 0);
    reset();
    faults[2] = -EREMOTEIO;
    check("FIFO read error", fifo_clear() == -EREMOTEIO && poll_calls == 1);
    reset();
    polls[0] = -ETIMEDOUT;
    check("FIFO one timeout retry success", fifo_clear() == 0 && poll_calls == 2);
    reset();
    polls[0] = polls[1] = -ETIMEDOUT;
    check("FIFO dual timeout not fake reset success", fifo_clear() == -ETIMEDOUT && reset_calls == 0);
    reset();
    check("unknown trigger rejected", trigger(0, 42) == -EINVAL && atomic_load(&operations) == 0);
    reset();
#ifdef HAVE_CHECKED_TRIGGER
    info.stop_proven = false;
#endif
    check("START refuses unproved CPU stop", trigger(0, SNDRV_PCM_TRIGGER_START) == -EBUSY && atomic_load(&operations) == 0 && !poisoned());
    reset();
    pthread_t starters[2];
    pthread_barrier_init(&start_barrier, NULL, 2);
    pthread_create(&starters[0], NULL, concurrent_start, (void *)(intptr_t)0);
    pthread_create(&starters[1], NULL, concurrent_start, (void *)(intptr_t)1);
    pthread_join(starters[0], NULL);
    pthread_join(starters[1], NULL);
    pthread_barrier_destroy(&start_barrier);
    check("simultaneous opposite START one owner", (start_results[0] == 0 && start_results[1] == -EBUSY && owners() == 1) || (start_results[1] == 0 && start_results[0] == -EBUSY && owners() == 2));
    check("simultaneous admission only one hardware transaction", atomic_load(&operations) == 4);
    reset();
    trigger(0, SNDRV_PCM_TRIGGER_START);
    ignore_xfer_stop = true;
    check("MMIO success but XFER still START rejects stop proof", trigger(0, SNDRV_PCM_TRIGGER_STOP) == -EIO && poisoned() && owners() != 0);
    printf("{\"passed\":%u,\"total\":%u}\n", passed, total);
    return passed != total;
}
