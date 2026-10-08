#!/usr/bin/env python3
"""Add only the chosen overlay prerequisites to the already tested audio DT."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = ROOT / 'outputs/rk3568-boot-package-20261005'
AUDIO = ROOT / 'outputs/rk3568-audio-20261005/build/dtb-v3/audio.dtb'
AUDIO_SHA = '9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478'
LOCKS = {
    'dt-semantics-v2.py': 'b89b3e4dab11281e02ec4a31104907e8b66579ba2e44556c4108d470f468aa56',
    'libfdt-v2.py': None,
    'build-uart-shim-v2.py': None,
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), PACKAGE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    for name, expected in LOCKS.items():
        if expected and sha((PACKAGE / name).read_bytes()) != expected:
            raise ValueError('Locked dependency changed: ' + name)
    data = AUDIO.read_bytes()
    if len(data) != 163161 or sha(data) != AUDIO_SHA:
        raise ValueError('Exact tested audio DT required')
    semantic = load('dt-semantics-v2.py')
    bridge = load('libfdt-v2.py')
    before = semantic.parse(data)
    handles = semantic.phandles(before)
    if max(handles) != 0x2f9 or 0x2fa in handles:
        raise ValueError('Audio chosen phandle conflict')
    if any(key in before['properties'] for key in ['/chosen:phandle', '/chosen:linux,phandle', '/__symbols__:chosen']):
        raise ValueError('Chosen prerequisites already assigned')
    output = HERE / 'build/audio-ram-shim-v1'
    output.mkdir(parents=True, exist_ok=False)
    # The old UART allocator is intentionally rejected for the audio tree:
    # codec already owns 2f9. Preserve this actual incompatibility separately.
    try:
        bridge.create_shim(data)
    except ValueError as error:
        (output / 'old-uart-shim-rejected.json').write_text(json.dumps({'rejected': True, 'reason': str(error)}) + '\n')
    else:
        raise ValueError('Old UART phandle allocator unexpectedly accepted audio DT')
    real = bridge.RealLibFdt()
    opened = real.opened(data)
    real.set_property(opened, '/__symbols__', 'chosen', b'/chosen\0')
    real.set_property(opened, '/chosen', 'phandle', struct.pack('>I', 0x2fa))
    shim = real.packed(opened)
    expected_shim = {'/__symbols__:chosen': {'before': None, 'after': b'/chosen\0'.hex()},
                     '/chosen:phandle': {'before': None, 'after': '000002fa'}}
    if semantic.diff(before, semantic.parse(shim)) != expected_shim:
        raise ValueError('Unexpected audio shim change')
    semantic.phandles(semantic.parse(shim))
    dtbo_path = ROOT / 'outputs/rk3568-backup-linux-20261003/original/dtbo.img'
    dtbo = dtbo_path.read_bytes()
    if sha(dtbo) != '59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d':
        raise ValueError('Original DTBO changed')
    entry = load('build-uart-shim-v2.py').overlay_entry(dtbo)
    applied_results = []
    for attempt in range(3):
        report, applied = real.apply(shim, entry)
        if report['status'] or applied is None:
            raise ValueError('Real audio overlay failed')
        tree = semantic.parse(applied)
        paths = [key.rsplit(':', 1)[0] for key in before['properties'] if key.endswith(':mode-normal')]
        if len(paths) != 1:
            raise ValueError('Unique reboot mode required')
        expected = semantic.overlay_diff(paths[0])
        expected['/chosen:phandle'] = expected_shim['/chosen:phandle']
        difference = semantic.diff(before, tree)
        if difference != expected or tree['properties'][paths[0] + ':mode-normal'] != '5242c300':
            raise ValueError('Unexpected complete audio overlay change')
        semantic.phandles(tree)
        if any(tree['properties'].get(path + ':phandle', tree['properties'].get(path + ':linux,phandle')) != f'{value:08x}'
               for value, path in handles.items()):
            raise ValueError('Existing audio phandle changed')
        applied_results.append({'attempt': attempt + 1, 'sha256': sha(applied), 'bytes': len(applied), 'apply': report})
    (output / 'audio-ram-shim.dtb').write_bytes(shim)
    (output / 'applied-audit-only.dtb').write_bytes(applied)
    (output / 'overlay-entry0.dtbo').write_bytes(entry)
    manifest = {'mode': 'AUDIO_RAM_BOOTM_ONLY', 'audio_baseline_sha256': AUDIO_SHA,
                'shim_sha256': sha(shim), 'shim_bytes': len(shim), 'chosen_phandle': '0x2fa',
                'original_codec_phandle': '0x2f9', 'applied_sha256': sha(applied),
                'applied_bytes': len(applied), 'complete_property_diff': difference,
                'nodes_and_metadata_unchanged': True, 'existing_phandles_unchanged': True,
                'packaged_blob': 'audio-ram-shim.dtb', 'applied_blob_is_audit_only': True,
                'real_libfdt_sha256': bridge.LIB_SHA, 'real_apply_runs': applied_results,
                'source_sha256': sha(Path(__file__).read_bytes()),
                'dependencies_sha256': {name: sha((PACKAGE / name).read_bytes()) for name in LOCKS},
                'board_tested': False, 'formal_flash_ready': False}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({key: manifest[key] for key in ['shim_sha256', 'shim_bytes', 'chosen_phandle', 'applied_sha256', 'applied_bytes']}))


if __name__ == '__main__':
    main()
