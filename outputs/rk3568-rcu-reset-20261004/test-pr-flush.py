#!/usr/bin/env python3
"""Run the real printk wait functions with controlled console progress/context."""
from pathlib import Path
import resource
import subprocess
import sys
import tempfile

resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
source = Path(sys.argv[1]).read_text()
start = source.index('static void pr_msleep(bool may_sleep, int ms)')
end = source.index('\nEXPORT_SYMBOL(pr_flush);', start)
functions = source[start:end]
prefix = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef uint64_t u64;
struct console {
    int flags;
    void (*write)(void);
    void (*write_atomic)(void);
    u64 printk_seq;
};
#define CON_ENABLED 1
#define SYSTEM_RUNNING 1
static struct console printer;
static int context_preemptible, context_softirq, context_rcu_depth;
static int system_state, slept_ms, delayed_ms, catch_up;
static u64 target_seq;
static void *prb;
#define preemptible() context_preemptible
#define in_softirq() context_softirq
#define rcu_preempt_depth() context_rcu_depth
#define for_each_console(con) for ((con) = &printer; (con); (con) = NULL)
#define atomic64_read(value) (*(value))
static u64 prb_next_seq(void *buffer) { return target_seq; }
static void write_console(void) {}
static void fail(const char *message) {
    fprintf(stderr, "FAIL: %s\n", message);
    exit(1);
}
static void msleep(int ms) {
    if (context_rcu_depth) fail("voluntary sleep inside RCU read-side section");
    if (!context_preemptible || context_softirq || system_state < SYSTEM_RUNNING)
        fail("voluntary sleep in atomic/softirq/early context");
    slept_ms += ms;
    if (catch_up) printer.printk_seq = target_seq;
}
static void udelay(int microseconds) {
    if (microseconds != 1000) fail("delay units changed");
    delayed_ms++;
    if (catch_up) printer.printk_seq = target_seq;
}
'''
suffix = r'''
static void reset(void) {
    printer = (struct console){.flags = CON_ENABLED, .write = write_console, .printk_seq = 0};
    target_seq = 1;
    context_preemptible = 1;
    context_softirq = context_rcu_depth = slept_ms = delayed_ms = catch_up = 0;
    system_state = SYSTEM_RUNNING;
}
static void check(bool value, const char *message) {
    if (!value) fail(message);
}
int main(void) {
    reset();
    context_rcu_depth = 1;
    check(!pr_flush(7, false), "stalled RCU console must time out");
    check(slept_ms == 0 && delayed_ms == 7, "RCU wait must use bounded delay");

    reset();
    context_rcu_depth = 3;
    catch_up = 1;
    check(pr_flush(5, true), "nested RCU console must report caught up");
    check(slept_ms == 0 && delayed_ms == 5, "nested RCU must not sleep");

    reset();
    catch_up = 1;
    check(pr_flush(7, true), "normal console progress must succeed");
    check(slept_ms == 7 && delayed_ms == 0, "normal process should retain sleeping wait");

    reset();
    check(!pr_flush(200, false), "stalled normal console must time out");
    check(slept_ms == 200 && delayed_ms == 0, "normal timeout budget changed");

    reset();
    context_preemptible = 0;
    check(!pr_flush(3, false), "atomic context timeout");
    check(slept_ms == 0 && delayed_ms == 3, "atomic context must not sleep");

    reset();
    context_softirq = 1;
    check(!pr_flush(3, false), "softirq timeout");
    check(slept_ms == 0 && delayed_ms == 3, "softirq must not sleep");

    reset();
    system_state = 0;
    check(!pr_flush(3, false), "early boot timeout");
    check(slept_ms == 0 && delayed_ms == 3, "early boot must not sleep");

    reset();
    check(!pr_flush(0, true), "zero timeout must not pretend console caught up");
    check(slept_ms == 0 && delayed_ms == 0, "zero timeout must not wait");

    reset();
    printer.printk_seq = 1;
    context_rcu_depth = 1;
    check(pr_flush(7, true), "already caught up console must succeed");
    check(slept_ms == 0 && delayed_ms == 0, "caught up console must not wait");

    reset();
    printer.flags = 0;
    check(pr_flush(7, true), "disabled console must not block flush");
    check(slept_ms == 0 && delayed_ms == 0, "disabled console must not wait");
    puts("PASS: real pr_flush/pr_msleep RCU and nested RCU, normal progress/timeout, atomic/softirq/early, zero timeout and inactive console");
}
'''
with tempfile.TemporaryDirectory(prefix='rtctrl-pr-flush-') as temporary:
    code = Path(temporary) / 'test.c'
    program = Path(temporary) / 'test'
    code.write_text(prefix + functions + suffix)
    subprocess.run(['cc', '-std=c11', '-O2', str(code), '-o', str(program)], check=True)
    subprocess.run([str(program)], check=True)
