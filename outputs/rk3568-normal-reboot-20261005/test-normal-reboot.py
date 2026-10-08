#!/usr/bin/env python3
"""Exercise the actual helper main with link-time syscall wrappers; never reboot."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HARNESS = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/reboot.h>
#include <sys/utsname.h>
#include <sys/vfs.h>
#include <linux/magic.h>
#include <linux/reboot.h>
int normal_reboot_main(int, char **);
static int scenario, calls;
uid_t __wrap_geteuid(void) { return scenario == 2 ? 1000 : 0; }
pid_t __wrap_getpid(void) { return scenario == 3 ? 1 : 42; }
int __wrap_uname(struct utsname *v) {
    if (scenario == 4) { errno = EIO; return -1; }
    memset(v, 0, sizeof(*v));
    strcpy(v->release, scenario == 5 ? "4.19.232" : "5.10.160-rt89-g9f9e9d18574d-dirty");
    return 0;
}
ssize_t __wrap_readlink(const char *path, char *out, size_t n) {
    if (strcmp(path, "/proc/self/exe")) abort();
    if (scenario == 6) { errno = EIO; return -1; }
    const char *v = scenario == 7 ? "/cache/normal-reboot" : "/tmp/normal-reboot";
    if (scenario == 8) { memset(out, 'x', n); return n; }
    if (strlen(v) > n) abort();
    memcpy(out, v, strlen(v));
    return strlen(v);
}
int __wrap_statfs(const char *path, struct statfs *v) {
    if (strcmp(path, "/proc/self/exe")) abort();
    if (scenario == 9) { errno = EIO; return -1; }
    memset(v, 0, sizeof(*v));
    v->f_type = scenario == 10 ? EXT4_SUPER_MAGIC : scenario == 11 ? RAMFS_MAGIC : TMPFS_MAGIC;
    return 0;
}
int __wrap_fflush(FILE *stream) {
    if (stream != stdout) abort();
    if (scenario == 12) { errno = EIO; return EOF; }
    return 0;
}
int __wrap_reboot(int command) {
    if (command != LINUX_REBOOT_CMD_RESTART) abort();
    ++calls;
    if (scenario == 13) { errno = EPERM; return -1; }
    return 0;
}
int main(int argc, char **argv) {
    if (argc != 2) return 90;
    scenario = atoi(argv[1]);
    char *args[] = {"normal-reboot", "--request", NULL, NULL};
    int count = 2;
    if (scenario == 0) { count = 1; args[1] = NULL; }
    if (scenario == 1) args[1] = "--poweroff";
    if (scenario == 14) { args[2] = "unexpected"; count = 3; }
    int result = normal_reboot_main(count, args);
    int want_calls = scenario == 11 || scenario == 13 || scenario == 15;
    if (calls != want_calls || result == 0) {
        fprintf(stderr, "scenario=%d reboot_calls=%d expected=%d main_rc=%d\n", scenario, calls, want_calls, result);
        return 91;
    }
    printf("CASE_%d_PASSED\n", scenario);
    return 0;
}
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    import re
    if not re.fullmatch(r'v[1-9][0-9]*', args.revision):
        raise ValueError('Invalid revision')
    build = HERE / 'build' / ('tests-' + args.revision)
    if build.exists() or build.is_symlink():
        raise ValueError('Refusing existing output')
    build.mkdir(parents=True)
    record = {'production_source_exists': (HERE / 'normal-reboot.c').is_file(), 'passed': 0, 'cases': []}
    (build / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    (build / 'harness.c').write_text(HARNESS)
    wrappers = ['geteuid', 'getpid', 'uname', 'readlink', 'statfs', 'fflush', 'reboot']
    qemu = ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
    for label, cc, runner in [('host', 'gcc', []), ('aarch64', 'aarch64-linux-gnu-gcc', [str(qemu)])]:
        subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-Dmain=normal_reboot_main', '-c', str(HERE / 'normal-reboot.c'), '-o', str(build / (label + '.o'))], check=True)
        command = [cc, '-static', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', str(build / 'harness.c'), str(build / (label + '.o')), *['-Wl,--wrap=' + x for x in wrappers], '-o', str(build / (label + '-test'))]
        subprocess.run(command, check=True)
        for scenario in range(16):
            result = subprocess.run([*runner, str(build / (label + '-test')), str(scenario)], capture_output=True, text=True, timeout=5)
            passed = result.returncode == 0 and ('CASE_' + str(scenario) + '_PASSED') in result.stdout
            record['cases'].append({'architecture': label, 'case': scenario, 'passed': passed, 'exit': result.returncode, 'output': result.stdout + result.stderr})
            record['passed'] += int(passed)
    record['source_sha256'] = hashlib.sha256((HERE / 'normal-reboot.c').read_bytes()).hexdigest()
    (build / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    if record['passed'] != 32:
        raise ValueError('Helper syscall contract failed')
    print(json.dumps({'passed': record['passed'], 'source_sha256': record['source_sha256']}))

if __name__ == '__main__':
    main()
