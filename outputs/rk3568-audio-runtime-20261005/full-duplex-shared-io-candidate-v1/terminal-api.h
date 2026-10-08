/* SPDX-License-Identifier: MIT */
/* Explicit API and nonreturning panic simulation; no kernel teardown occurs. */
#include "model-api.h"
#include <setjmp.h>
#include <stdarg.h>
#define WRITE_ONCE(var, value) ((var) = (value))
#define dev_info(...) do { } while (0)
static int panic_timeout = 7;
static jmp_buf panic_jump;
static bool panic_expected, panic_seen;
static int panic_errno;
static unsigned int unregister_calls, register_controls_calls, map_reads;
static unsigned int helper_calls, disconnect_calls, cleanup_calls, file_waits, component_close_calls;
static unsigned int core_steps, component_remove_calls;
static bool core_before_file_drain, close_borrow_lost, wait_has_card_lock, wait_has_params_lock;
static int disconnect_error;
static unsigned int close_schedule; /* 0: no release, 1: full close, 2: post-DAI close window. */
static struct snd_soc_card terminal_card;
static struct snd_card terminal_snd_card;
static struct mutex client_mutex = { PTHREAD_MUTEX_INITIALIZER };
static struct list_head unbind_card_list;
static bool component_registered;
static const struct snd_soc_component_driver soc_codec_dev_rk817 = { .name = NULL };
static int control_register_error, map_read_error;
static unsigned int map_read_fail_at;
static struct regmap terminal_map;
struct platform_device { struct device dev; };
static struct platform_device platform;
static int rk817_snd_path_controls[3]; /* API fixture size, not a control registration proof. */
static bool clock_native_valid = true;
static void mutex_init(struct mutex *lock)
{ pthread_mutex_init(&lock->native, NULL); if (lock == &codec.clk_lock) clock_native_valid = true; }
static void mutex_destroy(struct mutex *lock)
{
    if (lock == &codec.clk_lock) {
        if (clock_native_valid) pthread_mutex_destroy(&lock->native);
        clock_native_valid = false;
    } else pthread_mutex_destroy(&lock->native);
}
static void terminal_disable_clock(struct clk *clock)
{
    primitive_boundary();
    clk_disable_count++;
    /* CCF cannot decrement below zero; an unowned disable attempt is still observed. */
    if (clock->references > 0) clock->references--;
    printf("CLK DISABLE %d\n", clock->references);
}
#define clk_disable_unprepare terminal_disable_clock
static void mdelay(unsigned int ms) { (void)ms; }
static bool snd_soc_dai_active(struct snd_soc_dai *d) { (void)d; return false; }
static void snd_soc_component_init_regmap(struct snd_soc_component *c, struct regmap *map) { c->regmap = map; }
static int regmap_read(struct regmap *map, unsigned int reg, unsigned int *value)
{
    (void)map;
    map_reads++;
    int ret = map_reads == map_read_fail_at ? map_read_error : 0;
    *value = reg == RK817_PMIC_CHIP_VER ? 5 : 0x817;
    printf("READ %u %u %d\n", map_reads, reg, ret);
    return ret;
}
static int snd_soc_add_component_controls(struct snd_soc_component *c, const void *controls, unsigned int count)
{
    (void)c; (void)controls;
    if (count != 3) abort();
    register_controls_calls++;
    printf("ADD_CONTROLS %d\n", control_register_error);
    return control_register_error;
}
static void snd_soc_unregister_component(struct device *dev);
static int snd_soc_component_shutdown_card(struct device *dev, const struct snd_soc_component_driver *driver,
                                           unsigned int timeout_ms);
__attribute__((noreturn, format(printf, 1, 2)))
static void panic(const char *format, ...)
{
    (void)format;
    va_list args;
    va_start(args, format);
    const char *operation = va_arg(args, const char *);
    panic_errno = va_arg(args, int);
    va_end(args);
    panic_seen = true;
    printf("FAILSTOP %s %d %d\n", operation, panic_errno, panic_timeout);
    if (!panic_expected) abort();
    longjmp(panic_jump, 1);
}
