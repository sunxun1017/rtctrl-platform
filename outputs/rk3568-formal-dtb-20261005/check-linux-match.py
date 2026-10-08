#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile the real Linux OF matcher/table and run fixed compatibility vectors."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / 'third_party/linux-rk3588'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def function(text, start):
    index = text.index(start)
    opening = text.index('{', index)
    depth = 1
    for end in range(opening + 1, len(text)):
        depth += (text[end] == '{') - (text[end] == '}')
        if depth == 0:
            return text[index:end + 1]
    raise ValueError('Unbalanced actual function')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out).absolute()
    if out != out.resolve() or not out.is_relative_to(HERE / 'build'):
        raise ValueError('Own fresh ordinary output required')
    inputs = {name: KERNEL / name for name in (
        'drivers/of/base.c', 'drivers/of/property.c', 'include/linux/of.h',
        'drivers/mmc/host/sdhci-of-dwcmshc.c')}
    content = {name: path.read_text() for name, path in inputs.items()}
    of = content['drivers/of/base.c']
    prop = content['drivers/of/property.c']
    driver = content['drivers/mmc/host/sdhci-of-dwcmshc.c']
    matcher = function(of, 'static int __of_device_is_compatible(')
    select = function(of, 'const struct of_device_id *__of_match_node(')
    next_string = function(prop, 'const char *of_prop_next_string(')
    table = function(driver, 'static const struct of_device_id sdhci_dwcmshc_dt_ids[] =') + ';'
    table = re.sub(r'&([a-zA-Z0-9_]+_drvdata)', r'"\1"', table)
    if '#define of_compat_cmp(s1, s2, l)\tstrcasecmp((s1), (s2))' not in content['include/linux/of.h']:
        raise ValueError('OF compatible compare changed')
    semantic_path = ROOT / 'outputs/rk3568-boot-package-20261005/dt-semantics-v2.py'
    spec = importlib.util.spec_from_file_location('linux_match_semantic', semantic_path)
    semantic = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(semantic)
    candidate = Path(args.candidate).read_bytes()
    compatible = bytes.fromhex(semantic.parse(candidate)['properties']['/sdhci@fe310000:compatible'])
    vectors = [
        ('candidate', compatible, 'rk3568_drvdata'),
        ('tested_baseline', b'rockchip,rk3568-dwcmshc\0rockchip,dwcmshc-sdhci\0', 'rk3568_drvdata'),
        ('generic_only', b'snps,dwcmshc-sdhci\0', 'dwcmshc_drvdata'),
        ('generic_first_rejected_by_candidate_audit', b'snps,dwcmshc-sdhci\0rockchip,rk3568-dwcmshc\0', 'dwcmshc_drvdata'),
        ('old_rockchip_only', b'rockchip,dwcmshc-sdhci\0', None),
        ('unknown', b'other,controller\0', None),
        ('other_soc_precedes_generic', b'rockchip,rk3588-dwcmshc\0snps,dwcmshc-sdhci\0', 'rk3588_drvdata'),
    ]
    # Only node/property access is modeled. The actual complete score/selection
    # functions and actual driver table execute unchanged. Name/type fields are
    # empty in this table, so their accessors are unreachable for these cases.
    prefix = '''#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
struct property { const char *name; const void *value; int length; };
struct device_node { struct property compatible; };
struct of_device_id { char name[32]; char type[32]; char compatible[128]; const void *data; };
static struct property *__of_find_property(const struct device_node *node, const char *name, int *len)
{
    if (strcmp(name, "compatible")) abort();
    if (len) *len = node->compatible.length;
    return (struct property *)&node->compatible;
}
static int __of_node_is_type(const struct device_node *node, const char *type)
{
    (void)node; (void)type; abort();
}
static int of_node_name_eq(const struct device_node *node, const char *name)
{
    (void)node; (void)name; abort();
}
#define of_compat_cmp(a, b, len) strcasecmp((a), (b))
'''
    generated = prefix + '\n' + next_string + '\n' + matcher + '\n' + select + '\n' + table + '\n'
    generated += 'int main(void)\n{\n    int passed = 0;\n'
    for index, (name, value, expected) in enumerate(vectors):
        escaped = ''.join('\\%03o' % byte for byte in value)
        generated += ('    {\n        static const char bytes[] = "' + escaped + '";\n'
                      '        const struct device_node node = {{"compatible", bytes, sizeof(bytes) - 1}};\n'
                      '        const struct of_device_id *match = __of_match_node(sdhci_dwcmshc_dt_ids, &node);\n')
        assertion = 'match && !strcmp(match->data, "' + expected + '")' if expected else '!match'
        generated += '        if (!(' + assertion + ')) return ' + str(index + 1) + ';\n'
        generated += '        printf("PASS ' + name + ': %s\\n", match ? (const char *)match->data : "no match");\n'
        generated += '        passed++;\n    }\n'
    generated += '    printf("%d/7 actual OF matcher vectors passed\\n", passed);\n    return passed == 7 ? 0 : 20;\n}\n'
    out.mkdir(parents=True, exist_ok=False)
    source = out / 'actual-of-match.c'
    source.write_text(generated)
    receipts = []
    for name, extra in [('host', []), ('asan-ubsan', ['-fsanitize=address,undefined', '-fno-omit-frame-pointer'])]:
        binary = out / name
        argv = ['gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', *extra, str(source), '-o', str(binary)]
        compile_result = subprocess.run(argv, capture_output=True, timeout=30)
        (out / (name + '-compile.stdout')).write_bytes(compile_result.stdout)
        (out / (name + '-compile.stderr')).write_bytes(compile_result.stderr)
        if compile_result.returncode:
            raise ValueError('Compile failed: ' + name)
        run_result = subprocess.run([str(binary)], capture_output=True, timeout=30)
        (out / (name + '-run.stdout')).write_bytes(run_result.stdout)
        (out / (name + '-run.stderr')).write_bytes(run_result.stderr)
        if run_result.returncode or b'7/7 actual OF matcher vectors passed' not in run_result.stdout:
            raise ValueError('Actual matcher failed: ' + name)
        receipts.append({'mode': name, 'compile_argv': argv, 'compile_exit_code': compile_result.returncode,
                         'run_argv': [str(binary)], 'run_exit_code': run_result.returncode,
                         'passed': 7, 'total': 7, 'binary_sha256': sha(binary.read_bytes()),
                         'stdout_sha256': sha(run_result.stdout), 'stderr_sha256': sha(run_result.stderr)})
    report = {'candidate_sha256': sha(candidate), 'actual_functions': ['of_prop_next_string',
              '__of_device_is_compatible', '__of_match_node'], 'actual_driver_table': 'sdhci_dwcmshc_dt_ids',
              'model_scope': 'node/property access only; no MMIO, driver probe, or hardware operation',
              'receipts': receipts, 'board_tested': False, 'emmc_io_tested': False,
              'inputs_sha256': {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in inputs.values()},
              'generated_c_sha256': sha(source.read_bytes()), 'script_sha256': sha(Path(__file__).read_bytes())}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'host': '7/7', 'asan_ubsan': '7/7', 'candidate_linux_data': 'rk3568_drvdata'}))


if __name__ == '__main__':
    main()
