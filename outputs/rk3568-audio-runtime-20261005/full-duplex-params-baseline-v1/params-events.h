/* SPDX-License-Identifier: MIT */
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct params_event { const char *name; unsigned int value; int result; };
static struct params_event params_events[1024];
static unsigned int params_event_count, params_phase;
static bool params_inject_cpu_clock, params_inject_slave_config, params_inject_start_error;
static unsigned int codec_registers[2048], codec_io_calls, codec_pll_calls;
static void __attribute__((no_instrument_function)) params_note(const char *name, unsigned int value, int result)
{
    if (params_event_count == 1024) { fputs("event capacity exceeded\n", stderr); exit(2); }
    params_events[params_event_count++] = (struct params_event){name, value, result};
}
static void params_clear_events(void)
{
    params_event_count = params_phase = codec_io_calls = codec_pll_calls = 0;
    params_inject_cpu_clock = params_inject_slave_config = params_inject_start_error = false;
}
static unsigned int params_count(const char *name)
{
    unsigned int count = 0;
    for (unsigned int i = 0; i < params_event_count; i++) count += !strcmp(params_events[i].name, name);
    return count;
}
static void params_dump(const char *case_name)
{
    for (unsigned int i = 0; i < params_event_count; i++)
        printf("PARAM_EVENT %s %u %s %u %d\n", case_name, i, params_events[i].name, params_events[i].value, params_events[i].result);
}
