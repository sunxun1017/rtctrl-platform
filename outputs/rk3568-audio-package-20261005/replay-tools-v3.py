#!/usr/bin/env python3
"""Verify additive generator replay and restore the exact prior executed red source."""
import hashlib
import difflib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    current = (HERE / 'audio-package-v3.py').read_text()
    old = current[:current.index('def codec_abi_names():')] + current[current.index('def validate_codec('):]
    old = old.replace("    require(set(abi) == codec_abi_names(), 'Codec ABI exact ordinary file set')\n", '')
    old = old.replace("    require(info == codec_elf_info(module, exports), 'Codec actual complete ELF audit binding')\n", '')
    sha = hashlib.sha256(old.encode()).hexdigest()
    expected = json.loads((HERE / 'build/closure-red-v3/result.json').read_text())['core_source']['sha256']
    assert sha == expected, (sha, expected)
    snapshot = HERE / 'build/closure-red-v3/core-snapshot.py'
    if snapshot.exists():
        assert snapshot.read_bytes() == old.encode()
    else:
        with snapshot.open('xb') as stream:
            stream.write(old.encode())
    spec = importlib.util.spec_from_file_location('replay_v3', HERE / 'create-v3-tools.py')
    creator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(creator)
    generated = {}
    creator.write = lambda name, value: generated.update({name: value})
    creator.main()
    if generated['audio-package-v3.py'] != current:
        print(''.join(difflib.unified_diff(generated['audio-package-v3.py'].splitlines(True), current.splitlines(True),
                                         fromfile='generated', tofile='actual')))
        raise AssertionError('Generator replay differs')
    result = {'prior_executed_source_restored_exact': sha,
              'generator_replay_exact': hashlib.sha256(current.encode()).hexdigest()}
    with (HERE / 'build/closure-green-v3/replay-result.json').open('xb') as stream:
        stream.write((json.dumps(result, indent=2) + '\n').encode())
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
