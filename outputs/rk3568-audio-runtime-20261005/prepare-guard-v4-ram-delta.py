#!/usr/bin/env python3
"""Reconstruct a fresh RAM ELF with verified copy ranges and byte literals."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--new-sha256', required=True)
args = parser.parse_args()
old = (HERE / 'session-guard-v3/build/audio-session-guard').read_bytes()
new = (HERE / 'session-guard-v4/build/audio-session-guard').read_bytes()
def sha(data):
    return hashlib.sha256(data).hexdigest()
assert sha(old) == '3b5971d0fd69d3e9418416d4f8315cb6556c398866e2033c7bad2c4103ee5683'
assert sha(new) == args.new_sha256
assert 0 < len(new) <= 1048576
out = HERE / 'build/guard-v4-ram-delta-v1'
out.mkdir(exist_ok=False)
source = '/tmp/audio/audio-session-guard-v3'
target = '/tmp/audio/audio-session-guard-v4'
script = '#!/bin/sh\nset -eu\n'
script += 'test ! -e ' + target + '\ntest ! -L ' + target + '\n'
script += 'test "$(sha256sum ' + source + ')" = \'' + sha(old) + '  ' + source + "'\n"
script += 'dd if=' + source + ' of=' + target + ' bs=1 count=' + str(min(len(old), len(new))) + '\n'
script += 'chmod 600 ' + target + '\n'
offset = 0
blocks = []
simulated = bytearray(old[:min(len(old), len(new))])
simulated.extend(b'\x00' * (len(new) - len(simulated)))
# Match aligned old windows anywhere in new. Hash hits are always byte-checked.
# This is a file copier; match quality cannot replace the final full SHA.
index = {}
for old_offset in range(0, len(old) - 31, 16):
    key = hashlib.blake2b(old[old_offset:old_offset + 32], digest_size=16).digest()
    slots = index.setdefault(key, [])
    if len(slots) < 8:
        slots.append(old_offset)
literal = bytearray()
literal_start = 0
def flush_literal():
    global script, literal
    if not literal:
        return
    data = bytes(literal)
    simulated[literal_start:literal_start + len(data)] = data
    blocks.append({'type': 'literal', 'offset': literal_start, 'bytes': len(data), 'sha256': sha(data)})
    encoded = ''.join('\\0' + f'{byte:03o}' for byte in data)
    script += "printf '%b' '" + encoded + "' | dd of=" + target + ' bs=1 seek=' + str(literal_start) + ' count=' + str(len(data)) + ' conv=notrunc\n'
    literal = bytearray()
while offset < len(new):
    best_offset, best_length = 0, 0
    if offset + 32 <= len(new):
        window = new[offset:offset + 32]
        key = hashlib.blake2b(window, digest_size=16).digest()
        for candidate in index.get(key, []):
            if old[candidate:candidate + 32] != window:
                continue
            length = 32
            limit = min(len(old) - candidate, len(new) - offset)
            while length < limit and old[candidate + length] == new[offset + length]:
                length += 1
            if length > best_length:
                best_offset, best_length = candidate, length
    if best_length >= 64:
        flush_literal()
        data = old[best_offset:best_offset + best_length]
        assert data == new[offset:offset + best_length]
        simulated[offset:offset + best_length] = data
        blocks.append({'type': 'copy', 'source_offset': best_offset, 'offset': offset,
                       'bytes': best_length, 'sha256': sha(data)})
        script += 'dd if=' + source + ' of=' + target + ' bs=1 skip=' + str(best_offset) + ' seek=' + str(offset) + ' count=' + str(best_length) + ' conv=notrunc\n'
        offset += best_length
    else:
        if not literal:
            literal_start = offset
        literal.append(new[offset])
        offset += 1
        if len(literal) == 96:
            flush_literal()
flush_literal()
assert bytes(simulated) == new, 'Finite byte edits must reconstruct the complete frozen ELF'
script += 'test "$(stat -c %s ' + target + ')" = ' + str(len(new)) + '\n'
script += 'test "$(sha256sum ' + target + ')" = \'' + sha(new) + '  ' + target + "'\n"
script += 'chmod 500 ' + target + '\necho AUDIO_GUARD_V4_FULL_SHA_IN_NEW_RAM_FILE\n'
raw = script.encode('ascii')
packed = gzip.compress(raw, compresslevel=9, mtime=0)
assert len(packed) <= 131072, 'Use normal return and ordinary staging if delta is too large'
assert gzip.decompress(packed) == raw
(out / 'apply.sh').write_bytes(raw)
(out / 'apply.sh.gz').write_bytes(packed)
ram = '/tmp/audio/guard-v4-delta.sh.gz'
steps = [{'command': 'test ! -e ' + ram + ' && test ! -L ' + ram + ' && echo AUDIO_GUARD_V4_DELTA_PATH_ABSENT',
          'wait': 1, 'expect': r'(?m)^AUDIO_GUARD_V4_DELTA_PATH_ABSENT\r?$'}]
for start in range(0, len(packed), 96):
    data = packed[start:start + 96]
    encoded = ''.join('\\0' + f'{byte:03o}' for byte in data)
    steps.append({'command': "printf '%b' '" + encoded + "' " + ('>' if start == 0 else '>>') + ' ' + ram, 'wait': 0.05})
steps += [{'command': 'test "$(sha256sum ' + ram + ')" = \'' + sha(packed) + '  ' + ram + "' && gunzip -c " + ram + ' > /tmp/audio/guard-v4-delta.sh && test "$(sha256sum /tmp/audio/guard-v4-delta.sh)" = \'' + sha(raw) + "  /tmp/audio/guard-v4-delta.sh' && sh /tmp/audio/guard-v4-delta.sh > /tmp/audio/guard-v4-delta.stdout 2> /tmp/audio/guard-v4-delta.stderr && cat /tmp/audio/guard-v4-delta.stdout", 'wait': 5, 'expect': r'(?m)^AUDIO_GUARD_V4_FULL_SHA_IN_NEW_RAM_FILE\r?$'}]
(out / 'copy.json').write_bytes((json.dumps(steps, indent=2) + '\n').encode())
record = {'old_sha256': sha(old), 'new_sha256': sha(new), 'new_bytes': len(new),
          'builder_sha256': sha(Path(__file__).read_bytes()),
          'blocks': blocks, 'literal_bytes': sum(b['bytes'] for b in blocks if b['type'] == 'literal'),
          'copy_bytes': sum(b['bytes'] for b in blocks if b['type'] == 'copy'),
          'script_bytes': len(raw), 'gzip_bytes': len(packed), 'script_sha256': sha(raw),
          'gzip_sha256': sha(packed), 'ordinary_ram_only': True, 'start_allowed': False}
(out / 'manifest.json').write_bytes((json.dumps(record, indent=2) + '\n').encode())
print(json.dumps({k: v for k, v in record.items() if k != 'blocks'}))
