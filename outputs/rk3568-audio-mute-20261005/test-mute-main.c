/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Cases catch unsafe OFF/unmute, lost errno, post-error output, and cache false recovery. */
struct event { char kind; unsigned int reg, mask, value; bool failed; };
static struct event events[256];
static int event_count, io_count, fail_at, second_fail_at;
static int primary_errno, second_errno, update_success;
static bool cache_hits;
static unsigned int cache[256], hardware[256];
static int speaker, headphone;
static struct gpio_desc spk_gpio = {1}, hp_gpio = {2};
static struct rk817_codec_priv codec;
static struct snd_soc_component component = {&codec};
static struct snd_soc_dai dai = {&component};
static int total, failed, reason_count;
static bool case_failed;
static char case_name[128], reasons[1024][512];

static struct event *record(char kind, unsigned int reg, unsigned int mask, unsigned int value)
{
    if (event_count == 256) abort();
    events[event_count] = (struct event){kind, reg, mask, value, false};
    return &events[event_count++];
}
static int boundary(char kind, unsigned int reg, unsigned int mask, unsigned int value)
{
    struct event *event = record(kind, reg, mask, value);
    if (reg >= 256) abort();
    io_count++;
    unsigned int next = kind == 'w' ? value : ((cache[reg] & ~mask) | (value & mask));
    bool changed = next != cache[reg];
    /* Model a bus failure after cache assignment; hardware retains its old value. */
    cache[reg] = next;
    if (io_count == fail_at || io_count == second_fail_at) {
        event->failed = true;
        return io_count == fail_at ? primary_errno : second_errno;
    }
    if (cache_hits && !changed && kind == 'u') return 0;
    hardware[reg] = next;
    return kind == 'u' ? update_success : 0;
}
static int snd_soc_component_write(struct snd_soc_component *c, unsigned int reg, unsigned int value)
{
    return boundary('w', reg, 0, value);
}
static int snd_soc_component_update_bits(struct snd_soc_component *c, unsigned int reg,
                                          unsigned int mask, unsigned int value)
{
    return boundary('u', reg, mask, value);
}
static void usleep_range(unsigned int low, unsigned int high) { record('d', low, high, 0); }
static void msleep(unsigned int delay) { record('d', delay, 0, 0); }
static void gpiod_set_value(struct gpio_desc *gpio, int level)
{
    record('g', gpio->id, 0, level);
    if (gpio->id == 1) speaker = level;
    else headphone = level;
}
static void begin(const char *name)
{
    if (total && case_failed) failed++;
    total++;
    snprintf(case_name, sizeof(case_name), "%s", name);
    case_failed = false;
    memset(&codec, 0, sizeof(codec));
    memset(events, 0, sizeof(events));
    memset(cache, 0, sizeof(cache));
    memset(hardware, 0, sizeof(hardware));
    codec.component = &component;
    codec.spk_ctl_gpio = &spk_gpio;
    codec.hp_ctl_gpio = &hp_gpio;
    codec.playback_path = SPK_PATH;
    codec.capture_path = MAIN_MIC;
    event_count = io_count = fail_at = second_fail_at = speaker = headphone = 0;
    primary_errno = -EREMOTEIO;
    second_errno = -ENOSPC;
    update_success = 1;
    cache_hits = false;
}
static void check(bool condition, const char *reason)
{
    if (!condition) {
        case_failed = true;
        if (reason_count < 1024)
            snprintf(reasons[reason_count++], 512, "%.127s: %.380s", case_name, reason);
    }
}
#define CHECK(c) check(!!(c), #c)
static void io_literal(int ordinal, char kind, unsigned int reg, unsigned int mask, unsigned int value)
{
    int count = 0;
    for (int i = 0; i < event_count; i++) {
        if (events[i].kind == 'u' || events[i].kind == 'w') {
            if (++count == ordinal) {
                CHECK(events[i].kind == kind && events[i].reg == reg);
                CHECK(events[i].mask == mask && events[i].value == value);
                return;
            }
        }
    }
    CHECK(false);
}
static void muted_dac_sequence(void)
{
    CHECK(io_count == 6 && !speaker && !headphone);
    CHECK(events[0].kind == 'g' && events[0].reg == 1 && events[0].value == 0);
    CHECK(events[1].kind == 'g' && events[1].reg == 2 && events[1].value == 0);
    io_literal(1, 'u', 0x38, 1, 1);
    io_literal(2, 'u', 0x2f, 8, 8);
    io_literal(3, 'u', 0x15, 15, 0);
    io_literal(4, 'u', 0x15, 15, 14);
    io_literal(5, 'u', 0x2f, 8, 0);
    io_literal(6, 'u', 0x15, 1, 0);
}
static void no_unmute_after_failure(int starting_event)
{
    bool seen_error = false;
    for (int i = starting_event; i < event_count; i++) {
        struct event e = events[i];
        if (e.failed) {
            seen_error = true;
            continue;
        }
        if (seen_error) {
            CHECK(!(e.kind == 'g' && e.value == 1));
            CHECK(!(e.kind == 'u' && e.reg == 0x38 && e.mask == 1 && e.value == 0));
            CHECK(!(e.kind == 'u' && e.reg == 0x15 && e.mask == 1 && e.value == 1));
            CHECK(!(e.kind == 'u' && e.reg == 0x15 && e.mask == 16 && e.value == 16));
        }
    }
    CHECK(seen_error);
}
static void fault_followups(void)
{
    codec.playback_path = SPK_PATH;
    codec.capture_path = MAIN_MIC;
    int before = event_count;
    CHECK(rk817_digital_mute(&dai, 0, 0) == -EREMOTEIO);
    CHECK(rk817_digital_mute(&dai, 0, 1) == -EREMOTEIO);
    CHECK(event_count == before);
    CHECK(rk817_digital_mute(&dai, 1, 0) == -EREMOTEIO);
    CHECK(event_count > before);
    CHECK(!speaker && !headphone);
    before = event_count;
    CHECK(rk817_digital_mute(&dai, 1, 1) == -EREMOTEIO);
    CHECK(event_count == before + 1);
    codec.playback_path = OFF;
    before = event_count;
    CHECK(rk817_digital_mute(&dai, 0, 0) == -EREMOTEIO);
    CHECK(event_count > before);
    codec.capture_path = MIC_OFF;
    before = event_count;
    CHECK(rk817_digital_mute(&dai, 0, 1) == -EREMOTEIO);
    CHECK(event_count == before + 1);
    before = event_count;
    CHECK(rk817_digital_mute(&dai, 0, -1) == -EINVAL);
    CHECK(event_count == before);
}
static void test_paths(void)
{
    for (int path = 0; path <= 10; path++) {
        for (int configuration = 0; configuration < 3; configuration++) {
            for (int changed = 0; changed <= 1; changed++) {
                char name[128];
                snprintf(name, sizeof(name), "playback path %d config %d update return %d", path, configuration, changed);
                begin(name);
                codec.playback_path = path;
                codec.out_l2spk_r2hp = configuration == 1;
                codec.use_ext_amplifier = configuration == 2;
                update_success = changed;
                CHECK(rk817_digital_mute(&dai, 0, 0) == 0);
                if (path == 0) {
                    muted_dac_sequence();
                } else {
                    io_literal(1, 'u', 0x15, 1, 1);
                    io_literal(2, 'u', 0x38, 1, 0);
                    if (path == 1 || path == 5) {
                        CHECK(io_count == 2 && !speaker && !headphone);
                    } else {
                        CHECK(io_count == 3);
                        unsigned int value = path == 2 || path == 7 ?
                                             (configuration == 0 ? 3 : configuration == 1 ? 0 : 4) :
                                             (path == 6 || path == 10 ? 0 : 4);
                        io_literal(3, 'w', 0x2f, 0, value);
                        CHECK(speaker == (path == 2 || path == 7 || path == 6 || path == 10));
                        CHECK(headphone == (path != 2 && path != 7));
                    }
                }
            }
        }
    }
    for (int path = 0; path < 4; path++) {
        for (int changed = 0; changed <= 1; changed++) {
            char name[80];
            snprintf(name, sizeof(name), "capture path %d update return %d", path, changed);
            begin(name);
            codec.capture_path = path;
            update_success = changed;
            CHECK(rk817_digital_mute(&dai, 0, 1) == 0);
            CHECK(io_count == 1 && event_count == 1);
            io_literal(1, 'u', 0x15, 16, path == 0 ? 0 : 16);
        }
    }
    for (int changed = 0; changed <= 1; changed++) {
        begin(changed ? "DAC explicit mute with changed updates" : "DAC explicit mute with unchanged updates");
        speaker = headphone = 1;
        update_success = changed;
        CHECK(rk817_digital_mute(&dai, 1, 0) == 0);
        muted_dac_sequence();
    }
    begin("optional NULL output GPIO mute remains checked");
    codec.spk_ctl_gpio = codec.hp_ctl_gpio = NULL;
    CHECK(rk817_digital_mute(&dai, 1, 0) == 0);
    CHECK(io_count == 6 && events[0].kind == 'u');
}
static void test_failures(void)
{
    for (int path = 0; path <= 10; path++) {
        int operations = path == 0 ? 6 : path == 1 || path == 5 ? 2 : 3;
        for (int configuration = 0; configuration < 3; configuration++) {
            for (int position = 1; position <= operations; position++) {
                char name[128];
                snprintf(name, sizeof(name), "playback path %d config %d I/O %d first errno", path, configuration, position);
                begin(name);
                codec.playback_path = path;
                codec.out_l2spk_r2hp = configuration == 1;
                codec.use_ext_amplifier = configuration == 2;
                fail_at = position;
                speaker = headphone = 1; /* Prior software output state must receive off requests. */
                CHECK(rk817_digital_mute(&dai, 0, 0) == -EREMOTEIO);
                no_unmute_after_failure(0);
                if (path == 0) CHECK(io_count == (position == 1 ? 2 : position < 6 ? position + 1 : 6));
                else CHECK(io_count == position + 6);
                CHECK(!speaker && !headphone);
                fault_followups();
            }
        }
    }
    for (int position = 1; position <= 6; position++) {
        char name[80];
        snprintf(name, sizeof(name), "explicit DAC mute I/O %d first errno and remaining RX shutdown", position);
        begin(name);
        fail_at = position;
        speaker = headphone = 1;
        CHECK(rk817_digital_mute(&dai, 1, 0) == -EREMOTEIO);
        CHECK(io_count == (position == 1 ? 2 : position < 6 ? position + 1 : 6));
        io_literal(io_count, 'u', 0x15, 1, 0);
        CHECK(!speaker && !headphone);
        no_unmute_after_failure(0);
        fault_followups();
    }
    for (int path = 0; path < 4; path++) {
        for (int mute = 0; mute <= 1; mute++) {
            char name[80];
            snprintf(name, sizeof(name), "capture path %d mute %d errno and sticky instance", path, mute);
            begin(name);
            codec.capture_path = path;
            fail_at = 1;
            CHECK(rk817_digital_mute(&dai, mute, 1) == -EREMOTEIO);
            CHECK(io_count == ((!mute && path) ? 2 : 1));
            io_literal(io_count, 'u', 0x15, 16, 0);
            no_unmute_after_failure(0);
            fault_followups();
        }
    }
    for (int primary = 1; primary <= 3; primary++) {
        for (int cleanup = 1; cleanup <= 6; cleanup++) {
            char name[80];
            snprintf(name, sizeof(name), "unmute I/O %d and rollback I/O %d preserve original errno", primary, cleanup);
            begin(name);
            fail_at = primary;
            second_fail_at = primary + cleanup;
            speaker = headphone = 1;
            CHECK(rk817_digital_mute(&dai, 0, 0) == -EREMOTEIO);
            CHECK(io_count == primary + (cleanup == 1 ? 2 : cleanup < 6 ? cleanup + 1 : 6));
            CHECK(!speaker && !headphone);
            no_unmute_after_failure(0);
            fault_followups();
        }
    }
    begin("cache before bus error cannot report recovery from later unchanged mute");
    cache_hits = true;
    fail_at = 1;
    second_fail_at = 2;
    CHECK(rk817_digital_mute(&dai, 0, 0) == -EREMOTEIO);
    CHECK(cache[0x38] == 1 && hardware[0x38] == 0);
    int before = io_count;
    codec.playback_path = OFF;
    CHECK(rk817_digital_mute(&dai, 0, 0) == -EREMOTEIO);
    CHECK(io_count > before);
    CHECK(cache[0x38] == 1 && hardware[0x38] == 0);
    codec.playback_path = SPK_PATH;
    before = event_count;
    CHECK(rk817_digital_mute(&dai, 0, 0) == -EREMOTEIO);
    CHECK(event_count == before);
    fault_followups();
}
static void test_invalid(void)
{
    int invalid[] = {-1, 2, 99};
    for (int i = 0; i < 3; i++) {
        for (int mute = 0; mute <= 1; mute++) {
            char name[80];
            snprintf(name, sizeof(name), "invalid dispatcher stream %d mute %d no I/O", invalid[i], mute);
            begin(name);
            CHECK(rk817_digital_mute(&dai, mute, invalid[i]) == -EINVAL);
            CHECK(event_count == 0);
        }
    }
    begin("DAC direct callback wrong direction rejected before GPIO");
    CHECK(rk817_digital_mute_dac(&dai, 1, 1) == -EINVAL);
    CHECK(event_count == 0);
    begin("ADC direct callback wrong direction rejected before I/O");
    CHECK(rk817_digital_mute_adc(&dai, 0, 0) == -EINVAL);
    CHECK(event_count == 0);
}
static void test_distinct_errnos(void)
{
    const int errors[] = {-EPIPE, -ETIMEDOUT, -ENOMEM};
    for (int stream = 0; stream <= 1; stream++) {
        for (int index = 0; index < 3; index++) {
            char name[80];
            snprintf(name, sizeof(name), "stream %d preserves distinct errno %d across rollback and later mute", stream, errors[index]);
            begin(name);
            fail_at = 1;
            second_fail_at = 2;
            primary_errno = errors[index];
            CHECK(rk817_digital_mute(&dai, 0, stream) == errors[index]);
            no_unmute_after_failure(0);
            int before = event_count;
            CHECK(rk817_digital_mute(&dai, 0, stream) == errors[index]);
            CHECK(event_count == before);
            CHECK(rk817_digital_mute(&dai, 1, stream) == errors[index]);
            CHECK(event_count > before);
            codec.playback_path = OFF;
            codec.capture_path = MIC_OFF;
            CHECK(rk817_digital_mute(&dai, 0, stream) == errors[index]);
        }
    }
}
int main(void)
{
    test_paths();
    test_failures();
    test_invalid();
    test_distinct_errnos();
    if (case_failed) failed++;
    printf("{\"total\":%d,\"passed\":%d,\"failed\":%d,\"failures\":[", total, total - failed, failed);
    for (int i = 0; i < reason_count; i++) printf("%s\"%s\"", i ? "," : "", reasons[i]);
    puts("]}");
    return failed ? 1 : 0;
}
