#!/usr/bin/env python3
"""Execute existing strict DTBO parsing and real overlay failure/restore on the new pre-tree."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out).absolute()
    assert out == out.resolve() and out.is_relative_to(HERE / 'build')
    out.mkdir(parents=True, exist_ok=False)
    contract = load('overlay-contract-v3.py')
    contract.verify_inputs()
    audit = load('test-emmc-bridge-v3.py')
    candidate = (HERE / 'build/emmc-v3/audio-emmc-compatible.dtb').read_bytes()
    dtbo = (ROOT / 'outputs/rk3568-backup-linux-20261003/original/dtbo.img').read_bytes()
    entry_tool = contract.load('build-uart-shim-v2.py')
    overlay = entry_tool.overlay_entry(dtbo)
    real = contract.load('libfdt-v2.py').RealLibFdt()
    cases = []

    def reject(name, action, blob):
        (out / (name + '.bin')).write_bytes(blob)
        try:
            action(blob)
        except (ValueError, KeyError, struct.error) as error:
            cases.append({'name': name, 'rejected': True, 'sha256': sha(blob), 'reason': str(error)})
        else:
            raise AssertionError('Unexpectedly accepted ' + name)

    post = (HERE / 'build/emmc-v3/applied-emmc-audit-only.dtb').read_bytes()
    reject('post-overlay-tree-must-not-be-pre-input', audit.audit, post)
    for name, offset in [('count-overflow', 16), ('entry-offset-overflow', 20), ('payload-size-overflow', 32), ('payload-offset-overflow', 36)]:
        bad = bytearray(dtbo)
        struct.pack_into('>I', bad, offset, 0xffffffff)
        reject(name, entry_tool.overlay_entry, bytes(bad))
    reject('partition-truncated', entry_tool.overlay_entry, dtbo[:622])
    reject('partition-nonzero-tail', entry_tool.overlay_entry, dtbo[:-1] + b'x')

    def delete(blob, path, property_name):
        buffer = real.opened(blob)
        assert real.lib.fdt_delprop(buffer, real.node(buffer, path), property_name.encode()) == 0
        return real.packed(buffer)

    failures = [
        ('chosen-symbol-missing', delete(candidate, '/__symbols__', 'chosen'), overlay),
        ('chosen-phandle-missing', delete(candidate, '/chosen', 'phandle'), overlay),
        ('chosen-symbol-target-missing', audit.mutate(candidate, '/__symbols__', 'chosen', b'/no-such-node\0'), overlay),
        ('overlay-phandle-overflow', candidate, audit.mutate(overlay, '/fragment@0/__overlay__', 'phandle', struct.pack('>I', 0xffffff00))),
        ('second-fragment-fixup-missing', candidate, delete(overlay, '/__fixups__', 'reboot_mode')),
    ]
    for name, base, entry in failures:
        (out / (name + '-base.dtb')).write_bytes(base)
        (out / (name + '-overlay.dtbo')).write_bytes(entry)
        report, result = real.apply(base, entry)
        assert report['status'] < 0 and result is None
        assert report['restored_exact'] and report['backup_sha256'] == report['restored_sha256']
        assert report['failure_code_preserved_after_restore']
        if name == 'overlay-phandle-overflow':
            assert report['status'] == -17
        row = {'name': name, 'rejected': True, 'base_sha256': sha(base), 'overlay_sha256': sha(entry),
               'apply': report, 'applied_tree_returned': False}
        (out / (name + '.json')).write_text(json.dumps(row, indent=2) + '\n')
        cases.append(row)
    accepted, applied = real.apply(candidate, overlay)
    assert accepted['status'] == 0 and applied == post
    report = {'negative_cases': cases, 'negative_cases_rejected': len(cases),
              'positive_control_sha256': sha(applied), 'positive_apply': accepted,
              'candidate_sha256': sha(candidate), 'entry0_sha256': sha(overlay),
              'script_sha256': sha(Path(__file__).read_bytes()), 'board_tested': False,
              'exact_deployed_libfdt': False, 'restoration_does_not_swallow_error': True}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'negative_rejected': len(cases), 'real_overlay_failures': len(failures), 'positive_sha256': sha(applied)}))


if __name__ == '__main__':
    main()
