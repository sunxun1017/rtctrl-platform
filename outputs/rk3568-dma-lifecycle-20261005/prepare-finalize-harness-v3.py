#!/usr/bin/env python3
"""Bind the final optional read-only provider ABI into regression fixtures."""
from pathlib import Path
HERE = Path(__file__).resolve().parent


def create(name, text):
    path = HERE / name
    if path.exists():
        raise ValueError('fresh file required: ' + name)
    path.write_text(text)


ready = (HERE / 'test-pl330-ready2.py').read_text()
ready = ready.replace("names.append('pl330_check_open')", "names.insert(names.index('pl330_probe'),'pl330_check_open')")
(HERE / 'test-pl330-ready2-attempt-v1.py').write_bytes((HERE / 'test-pl330-ready2.py').read_bytes())
(HERE / 'test-pl330-ready2.py').write_text(ready)
script = (HERE / 'test-asoc-cpu.py').read_text()
script = script.replace('test-asoc-cpu', 'test-asoc-cpu-open').replace('trigger-cpu-tests-', 'trigger-cpu-open-tests-')
for name in ['shim.h', 'dma.h', 'main.c']:
    script = script.replace('test-pcm-chain-' + name, 'test-pcm-chain-open-' + name)
script = script.replace('    excerpts={"dmaapi:"+n:function(public,n)', '    public_names.append("dmaengine_check_open")\n    excerpts={"dmaapi:"+n:function(public,n)')
create('test-asoc-cpu-open.py', script)
create('test-asoc-cpu-open-shim.h', (HERE / 'test-asoc-cpu-shim.h').read_text())
create('test-asoc-cpu-open-main.c', (HERE / 'test-asoc-cpu-main.c').read_text())
create('test-pcm-chain-open-shim.h', (HERE / 'test-pcm-chain-shim.h').read_text())
dma = (HERE / 'test-pcm-chain-dma.h').read_text()
dma = dma.replace('int (*device_synchronize_checked)(struct dma_chan *);', 'int (*device_synchronize_checked)(struct dma_chan *);\n int (*device_check_open)(struct dma_chan *);')
dma += '\nstatic inline int fake_open_admission(struct dma_chan *chan){(void)chan;return checked_error;}\n'
create('test-pcm-chain-open-dma.h', dma)
main = (HERE / 'test-pcm-chain-main.c').read_text()
main = main.replace('provider.device_synchronize_checked=checked?fake_checked:NULL;', 'provider.device_synchronize_checked=checked?fake_checked:NULL;provider.device_check_open=checked?fake_open_admission:NULL;')
create('test-pcm-chain-open-main.c', main)
print('prepared final CPU open ABI fixture and ready callback declaration order')
