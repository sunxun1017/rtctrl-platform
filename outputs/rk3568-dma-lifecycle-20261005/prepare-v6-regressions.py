#!/usr/bin/env python3
"""Fork mutable C3 suites, preserving all v5 files and frozen result snapshots."""
from pathlib import Path
from source_utils import declaration
HERE=Path(__file__).resolve().parent
production=(HERE/'driver-source-c3-v6/drivers/dma/pl330.c').read_text()
block=declaration(production,'struct','pl330_desc_block')+'\n'

def write(name,text):
    (HERE/name).write_bytes(text.encode())

s=(HERE/'test-pl330-c3.py').read_text().replace('test-pl330-c3','test-pl330-c3-probe').replace('pl330-c3-tests-','pl330-c3-probe-tests-')
s=s.replace('names.extend(["pl330_reader_deadline","pl330_reader_remove"])','names.extend(["pl330_reader_deadline","pl330_reader_remove","pl330_irqs_remove"])')
s=s.replace("unit=output/\"real-functions.c\";", "extracted=declaration(text,'struct','pl330_desc_block')+'\\n'+extracted\n    unit=output/\"real-functions.c\";")
write('test-pl330-c3-probe.py',s)
s=(HERE/'test-pl330-c3-shim.h').read_text()
s=s.replace('    struct list_head desc_pool;', '    struct list_head desc_pool,desc_blocks;\n    struct dma_pl330_chan *peripherals;bool irq_ready;unsigned irqs_registered;')
s+='\nstatic inline void *kzalloc(size_t size,int flags){(void)flags;return calloc(1,size);}\n'
s=s.replace('static void kfree(void *memory){destructive_calls++;}', 'static void kfree(void *memory){if(memory)destructive_calls++;}')
write('test-pl330-c3-probe-shim.h',s)
s=(HERE/'test-pl330-c3-main.c').read_text()
s=s.replace('INIT_LIST_HEAD(&dmac.desc_pool);', 'INIT_LIST_HEAD(&dmac.desc_pool);INIT_LIST_HEAD(&dmac.desc_blocks);dmac.irq_ready=true;dmac.irqs_registered=2;')
write('test-pl330-c3-probe-main.c',s)

s=(HERE/'test-dma-pcm.py').read_text().replace('test-dma-pcm','test-dma-pcm-probe').replace('dma-pcm-tests-','dma-pcm-probe-tests-')
s=s.replace("['pl330_reader_deadline','pl330_reader_remove']", "['pl330_reader_deadline','pl330_reader_remove','pl330_irqs_remove']")
s=s.replace("extracted='\\n\\n'.join([*api.values()", "extracted=declaration(pl,'struct','pl330_desc_block')+'\\n'+'\\n\\n'.join([*api.values()")
write('test-dma-pcm-probe.py',s)
s=(HERE/'test-dma-pcm-provider-shim.h').read_text()
s=s.replace('    struct list_head desc_pool;', '    struct list_head desc_pool,desc_blocks;\n    struct dma_pl330_chan *peripherals;bool irq_ready;unsigned irqs_registered;')
write('test-dma-pcm-probe-provider-shim.h',s)
for leaf in ['runtime-shim.h','mmio.h']:
    (HERE/('test-dma-pcm-probe-'+leaf)).write_bytes((HERE/('test-dma-pcm-'+leaf)).read_bytes())
s=(HERE/'test-dma-pcm-main.c').read_text()
s=s.replace('INIT_LIST_HEAD(&dmac.desc_pool);', 'INIT_LIST_HEAD(&dmac.desc_pool);INIT_LIST_HEAD(&dmac.desc_blocks);dmac.irq_ready=true;')
write('test-dma-pcm-probe-main.c',s)
print('created independent v6 regression suites')
