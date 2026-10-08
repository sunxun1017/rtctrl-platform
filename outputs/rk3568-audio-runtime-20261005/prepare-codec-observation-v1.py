#!/usr/bin/env python3
"""Fresh RAM accessory reconstruction and normal codec binding, no PCM START."""
from pathlib import Path
import hashlib
import json
HERE = Path(__file__).resolve().parent
OUT = HERE / 'build/ram-aux-v3'
old = (HERE / 'session-guard-v2/build/audio-session-guard').read_bytes()
new = (HERE / 'session-guard-v3/build/audio-session-guard').read_bytes()
assert len(old) == len(new) == 741432
assert [i for i, (a, b) in enumerate(zip(old, new)) if a != b] == [440404]
assert old[440404] == 0 and new[440404] == 99
assert hashlib.sha256(new).hexdigest() == '3b5971d0fd69d3e9418416d4f8315cb6556c398866e2033c7bad2c4103ee5683'
steps = []
def add(command, expect=None, wait=1):
    s = {'command': command, 'wait': wait}
    if expect:
        s['expect'] = expect
    steps.append(s)
checks = json.loads((OUT / 'live-dt-v2-expected.json').read_text())
empty = [key for key, value in checks.items() if not value]
for key in empty:
    node, prop = key.rsplit(':', 1)
    path = '/proc/device-tree' + node + '/' + prop
    add('test -f ' + path + ' && test "$(stat -c %s ' + path + ')" = 0 && echo AUDIO_EMPTY_DT_PROPERTY_PRESENT',
        r'(?m)^AUDIO_EMPTY_DT_PROPERTY_PRESENT\r?$')
add("test \"$(sha256sum /tmp/audio/audio-session-guard)\" = '8cf5190071fa61285605864014a1015e307b15bc274b7b15e7893d1c5e23a5ae  /tmp/audio/audio-session-guard' && test ! -e /tmp/audio/audio-session-guard-v3 && cp /tmp/audio/audio-session-guard /tmp/audio/audio-session-guard-v3 && chmod 600 /tmp/audio/audio-session-guard-v3 && echo AUDIO_V3_NEW_RAM_COPY", r'(?m)^AUDIO_V3_NEW_RAM_COPY\r?$')
add("printf '%b' '\\0143' | dd of=/tmp/audio/audio-session-guard-v3 bs=1 seek=440404 count=1 conv=notrunc", wait=1)
add("test \"$(sha256sum /tmp/audio/audio-session-guard-v3)\" = '3b5971d0fd69d3e9418416d4f8315cb6556c398866e2033c7bad2c4103ee5683  /tmp/audio/audio-session-guard-v3' && test \"$(stat -c %s /tmp/audio/audio-session-guard-v3)\" = 741432 && chmod 500 /tmp/audio/audio-session-guard-v3 && echo AUDIO_V3_FULL_SHA_VERIFIED", r'(?m)^AUDIO_V3_FULL_SHA_VERIFIED\r?$')
add('test ! -e /tmp/audio-debug && mkdir -m 700 /tmp/audio-debug && mount -t debugfs -o ro,nosuid,nodev,noexec debugfs /tmp/audio-debug && echo AUDIO_DEBUGFS_RO_MOUNTED', r'(?m)^AUDIO_DEBUGFS_RO_MOUNTED\r?$')
add("test \"$(sha256sum /tmp/audio/snd-soc-rk817.ko)\" = 'e0aecc775367f93555c5776938102d419865a19128b25f64d74a8e9df387ca80  /tmp/audio/snd-soc-rk817.ko' && test -z \"$(cat /proc/modules)\" && insmod /tmp/audio/snd-soc-rk817.ko && echo AUDIO_CODEC_MODULE_INSERTED", r'(?m)^AUDIO_CODEC_MODULE_INSERTED\r?$', 3)
add('readlink -f /sys/bus/platform/devices/rk817-codec/driver; cat /proc/asound/cards; cat /proc/asound/pcm; cat /proc/modules', wait=2)
add('cat /sys/bus/platform/devices/fe410000.i2s/rk3568_lifecycle_state; cat /sys/bus/platform/devices/fe410000.i2s/power/runtime_status; cat /sys/bus/amba/devices/fe550000.dmac/rk3568_lifecycle_state; cat /sys/class/sound/dma_quarantine_bytes', wait=2)
add('cat /tmp/audio-debug/gpio', wait=1)
target = OUT / 'codec-observation.json'
assert not target.exists()
target.write_bytes((json.dumps(steps, indent=2) + '\n').encode())
print(json.dumps({'empty_boolean_properties': len(empty), 'commands': len(steps), 'pcm_open': False, 'start': False}))
