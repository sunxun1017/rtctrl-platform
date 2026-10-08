#!/usr/bin/env python3
"""Exercise the actual build cleanup with real patches and a failed reversal."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

here = Path(__file__).resolve().parent
repo = here.parents[1]
kernel = Path(sys.argv[1]).resolve()
patch_directory = repo / 'platforms/rk3568/boards/aiot-3568pq/patches'
patches = [patch_directory / name for name in (
    '0001-arm64-cache-kasan-include.patch', '0002-rk817-feedback-diagnostic.patch',
    '0003-printk-rcu-flush-context.patch')]
source = (here / 'build-kernel.sh').read_text()
start = source.index('restore_source() {')
end = source.index('\n}\n', start) + 3
function = source[start:end]


def run(arguments, cwd):
    result = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


with tempfile.TemporaryDirectory(prefix='rtctrl-build-restore-') as temporary:
    tree = Path(temporary)
    originals = {}
    for patch in patches:
        for name in re.findall(r'^--- a/(.+)$', patch.read_text(), re.MULTILINE):
            original = (kernel / name).read_bytes()
            target = tree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original)
            originals[name] = original
        run(['git', 'apply', str(patch)], tree)
    target = tree / 'drivers/mfd/rk808.c'
    patched = target.read_bytes()
    corrupted = patched.replace(b'dcdc3 feedback policy: external', b'dcdc3 diagnostic changed after patch')
    assert corrupted != patched
    target.write_bytes(corrupted)
    definitions = (f'kernel="{tree}"\npatch_one="{patches[0]}"\n'
                   f'patch_two="{patches[1]}"\npatch_three="{patches[2]}"\n')
    checks = '''
if restore_source; then
    echo UNEXPECTED_RESTORE_SUCCESS
    exit 1
fi
test "$applied_one" = 0
test "$applied_two" = 1
test "$applied_three" = 0
echo REMAINING_PATCH_ONLY
'''
    script = 'set -eu\n' + definitions + function + '\napplied_one=1\napplied_two=1\napplied_three=1\n' + checks
    assert 'REMAINING_PATCH_ONLY' in run(['sh', '-c', script], tree)
    for name, original in originals.items():
        if name != 'drivers/mfd/rk808.c':
            assert (tree / name).read_bytes() == original
    # A retry must not try reversing patches that were already restored.
    script = 'set -eu\n' + definitions + function + '\napplied_one=0\napplied_two=1\napplied_three=0\n' + checks
    assert 'REMAINING_PATCH_ONLY' in run(['sh', '-c', script], tree)
    target.write_bytes(patched)
    script = 'set -eu\n' + definitions + function + '''
applied_one=0
applied_two=1
applied_three=0
restore_source
test "$applied_one" = 0
test "$applied_two" = 0
test "$applied_three" = 0
echo RESTORED
'''
    assert 'RESTORED' in run(['sh', '-c', script], tree)
    assert all((tree / name).read_bytes() == original for name, original in originals.items())
print('PASS: failed middle reversal does not stop other cleanup; completed patches are not retried; remaining patch restores after conflict repair')
