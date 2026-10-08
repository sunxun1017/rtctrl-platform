#!/usr/bin/env python3
"""Exercise the real property function with failed/valid reads and mock register writes."""
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
start = source.index("static void rk817_of_property_prepare(")
end = source.index("\nstatic struct kobject", start)
function = source[start:end]
prefix = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
struct device_node { int unused; };
struct device { struct device_node *of_node; };
struct rk808 { void *regmap; };
struct notifier_block { int (*notifier_call)(void); };
static struct { struct rk808 *rk808; struct notifier_block reboot_notifier; } rk817_reboot_data;
#define RK817_ID_DCDC3 2
#define RK817_POWER_CONFIG 0xb9
#define RK817_BUCK3_FB_RES_MSK 0x40
#define RK817_BUCK3_FB_RES_INTER 0x40
#define RK817_BUCK3_FB_RES_EXT 0
#define RK817_SLPPIN_FUNC_MSK 0x18
#define RK817_RST_FUNC_MSK 0xc0
#define RK817_RST_FUNC_SFT 6
#define RK817_RST_FUNC_CNT 3
#define RK817_RST_FUNC_REG 0x40
#define SLPPIN_NULL_FUN 0
#define RK817_SYS_CFG(i) (0xf1 + (i))
static int property_ret, requested_index, writes, last_feedback;
static char logs[1024];
static int of_property_read_u32_index(struct device_node *np, const char *key, int i, u32 *value) {
    /* Poison returned storage on errors: diagnostics must not consume invalid data. */
    *value = property_ret ? 0xdddddddd : (u32)requested_index;
    return property_ret;
}
static int of_property_read_u32(struct device_node *np, const char *key, int *value) {
    *value = 0;
    return 0;
}
static int regmap_update_bits(void *map, int reg, int mask, int value) {
    writes++;
    if (reg == RK817_POWER_CONFIG) last_feedback = value;
    return 0;
}
static void dev_info(struct device *dev, const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    vsnprintf(logs + strlen(logs), sizeof(logs) - strlen(logs), fmt, args);
    va_end(args);
}
#define dev_err dev_info
static int rk817_reboot_notifier_handler(void) { return 0; }
static int register_reboot_notifier(struct notifier_block *nb) { return 0; }
'''
suffix = r'''
int main(void) {
    struct device_node node = {0};
    struct device dev = {&node};
    struct rk808 chip = {0};
    int errors[] = {-22, -61, 0, 0};
    int indices[] = {0, 0, RK817_ID_DCDC3, 0};
    for (int i = 0; i < 4; i++) {
        property_ret = errors[i]; requested_index = indices[i];
        writes = 0; last_feedback = -1; logs[0] = 0;
        rk817_of_property_prepare(&chip, &dev);
        assert(writes == 2);
        assert(last_feedback == ((!property_ret && requested_index == RK817_ID_DCDC3) ?
            RK817_BUCK3_FB_RES_INTER : RK817_BUCK3_FB_RES_EXT));
        if (property_ret) {
            /* No failed reader's poison, signed or unsigned, may reach diagnostic output. */
            assert(!strstr(logs, "3722304989"));
            assert(!strstr(logs, "-572662307"));
        }
    }
    puts("PASS: missing/invalid/inner/external properties; register branch unchanged; invalid data not logged");
}
'''
with tempfile.TemporaryDirectory(prefix="rtctrl-pmic-test-") as temp:
    code = Path(temp) / "test.c"
    executable = Path(temp) / "test"
    code.write_text(prefix + function + suffix)
    subprocess.run(["cc", "-std=c11", "-O2", str(code), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
