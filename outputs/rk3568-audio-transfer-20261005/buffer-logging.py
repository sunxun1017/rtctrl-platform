#!/usr/bin/env python3
"""Apply bounded deferred trace after live-logging red control."""
from pathlib import Path
HERE = Path(__file__).resolve().parent
def replace(s, before, after):
    assert s.count(before) == 1, (before[:60], s.count(before))
    return s.replace(before, after)
body = (HERE / 'pcm-transfer-body.c').read_text()
body = replace(body, '    uint64_t frames, samples, zeros;\n};', '''    uint64_t frames, samples, zeros;
    unsigned long observed_hw_ptr;
    int card;
    size_t trace_used;
    char trace[262144];
};
static void log_line(struct transfer_run *run, const char *format, ...)
{
    size_t left = sizeof(run->trace)-run->trace_used;
    if (left < 256) {
        if (!run->first) { run->first = "LOG_CAPACITY"; run->error = ENOBUFS; }
        return;
    }
    va_list args;
    va_start(args, format);
    int size = vsnprintf(run->trace+run->trace_used, left, format, args);
    va_end(args);
    if (size < 0 || (size_t)size >= left) {
        if (!run->first) { run->first = "LOG_FORMAT"; run->error = EPROTO; }
        return;
    }
    run->trace_used += size;
}''')
before, main = body.split('int main(int argc, char **argv)', 1)
before = before.replace('fprintf(stderr, ', 'log_line(run, ').replace('printf("PCM_STATE', 'log_line(run, "PCM_STATE')
before = replace(before, '    if (now_ns(&now))', '''    /* Keep enough trace space for every cleanup operation/error. */
    if (run->trace_used > sizeof(run->trace)-4096) { fail(run, "LOG_CAPACITY", ENOBUFS); return 0; }
    if (now_ns(&now))''')
main = replace(main, 'struct transfer_run run = {0};', 'struct transfer_run run = { .card = -1 };')
main = replace(main, '    if (card < 0 || !remaining_ms(&run)) goto cleanup;', '    if (card < 0 || !remaining_ms(&run)) goto cleanup;\n    run.card = card;')
main = main.replace('fprintf(stderr, "PCM_STAGE', 'log_line(&run, "PCM_STAGE').replace('printf("PCM_INFO', 'log_line(&run, "PCM_INFO')
line = next(line for line in main.splitlines(True) if line.startswith('    printf("PCM_TRANSFER'))
main = replace(main, line, '    run.observed_hw_ptr = status.hw_ptr;\n')
main = replace(main, '    if (run.first) {\n', '''    /* No synchronous output while a PCM fd/transfer can still be active. */
    if (run.trace_used && fwrite(run.trace, 1, run.trace_used, stderr) != run.trace_used)
        fail(&run, "LOG_OUTPUT", errno ? errno : EIO);
    if (run.card >= 0) {
        int printed = printf("PCM_TRANSFER card=%d stream=%s frames=%" PRIu64 " samples=%" PRIu64 " zeros=%" PRIu64 " zero_ppm=%" PRIu64 " observed_hw_ptr=%lu\\n", run.card, argv[4], run.frames, run.samples, run.zeros, (uint64_t)(run.samples ? run.zeros * 1000000ULL / run.samples : 0), run.observed_hw_ptr);
        if (printed < 0) fail(&run, "SUMMARY_OUTPUT", errno ? errno : EIO);
    }
    if (run.first) {
''')
changed = before + 'int main(int argc, char **argv)' + main
old = (HERE / 'pcm-transfer-body.c').read_text()
(HERE / 'pcm-transfer-body.c').write_text(changed)
source = (HERE / 'pcm-transfer.c').read_text()
source = replace(source, '#include <stdbool.h>', '#include <stdbool.h>\n#include <stdarg.h>')
source = replace(source, old, changed)
(HERE / 'pcm-transfer.c').write_text(source)
print('deferred trace; reserve4KiB cleanup; fixed256KiB capacity')
