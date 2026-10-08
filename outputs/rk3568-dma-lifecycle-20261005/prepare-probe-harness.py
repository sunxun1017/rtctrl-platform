#!/usr/bin/env python3
"""New probe suite; frozen C3 v5 suites are not edited."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
s=(HERE/'test-dma-pcm.py').read_text().replace('test-dma-pcm','test-pl330-probe').replace('dma-pcm-tests-','pl330-probe-tests-')
s=s.replace("names=hardware+[n for n in names if n not in hardware]", """names=hardware+[n for n in names if n not in hardware]
    names.extend(['read_dmac_config','_reset_thread','dmac_alloc_threads','dmac_alloc_resources','pl330_add','get_burst_len','__pl330_prep_dma_memcpy','pl330_prep_dma_memcpy','pl330_config','of_dma_pl330_xlate','pl330_probe'])
    for helper in ['pl330_irqs_remove','pl330_probe_cleanup']:
        if ('static void '+helper+'(') in pl:names.insert(names.index('pl330_probe'),helper)""")
s=s.replace("|msecs_to_loops\\(|UNTIL\\(|CC_|", "|CR[0-4D]\\b|CR[0-4D]_|PART\\b|DESIGNER\\b|PERIPH_ID_VAL\\b|NR_DEFAULT_DESC\\b|MCODE_BUFF_PER_REQ\\b|PL330_AUTOSUSPEND_DELAY\\b|msecs_to_loops\\(|UNTIL\\(|CC_|")
s=s.replace("'test-pl330-probe-main.c','test-pcm-chain-runtime.h'", "'test-pl330-probe-main.c','test-pl330-probe-api.h','test-dma-pcm-main.c','test-pcm-chain-runtime.h'")
s=s.replace('test-pcm-chain-asoc.h"\\n\'+extracted','test-pcm-chain-asoc.h"\\n#include "test-pl330-probe-api.h"\\n\'+extracted')
s=s.replace("extracted='\\n\\n'.join([*api.values()", "extracted=(declaration(pl,'struct','pl330_desc_block')+'\\n' if 'struct pl330_desc_block {' in pl else '')+'\\n\\n'.join([*api.values()")
s=s.replace("'-Wno-unused-variable','-DCONFIG_NO_GKI=1'", "'-Wno-unused-variable','-Wno-sign-compare','-DCONFIG_NO_GKI=1'")
# Base integration main supplies its initialization/barrier helpers, renamed below.
(HERE/'test-pl330-probe.py').write_text(s)
s=(HERE/'test-dma-pcm-provider-shim.h').read_text()
s=s.replace('struct amba_device {struct device dev;int irq[AMBA_NR_IRQS];};','struct resource {int unused;};\nstruct amba_device {struct device dev;int irq[AMBA_NR_IRQS];unsigned periphid;struct resource res;};')
s=s.replace('    int id;\n    int ev;', '    int id;\n    int ev;')
s=s.replace('struct _pl330_req {struct dma_pl330_desc *desc;u32 mc_bus;};','struct _pl330_req {struct dma_pl330_desc *desc;u32 mc_bus;void *mc_cpu;};')
s=s.replace('struct pl330_config {int num_chan,num_events,mode;unsigned num_peri,irq_ns;};','struct pl330_config {int num_chan,num_events,mode;unsigned num_peri,irq_ns,periph_id,data_bus_width,data_buf_dep,peri_ns;};')
s=s.replace('    struct list_head desc_pool;', '    struct list_head desc_pool,desc_blocks;\n    struct dma_pl330_chan *peripherals;unsigned num_peripherals,irqs_registered;bool irq_ready;')
s=s.replace('struct dma_device {struct device *dev;', '''struct dma_device {struct device *dev;
 struct dma_async_tx_descriptor *(*device_prep_dma_memcpy)(struct dma_chan *,dma_addr_t,dma_addr_t,size_t,unsigned long);
 struct dma_async_tx_descriptor *(*device_prep_slave_sg)(struct dma_chan *,struct scatterlist *,unsigned,enum dma_transfer_direction,unsigned long,void *);
 int (*device_alloc_chan_resources)(struct dma_chan *);
 int (*device_config)(struct dma_chan *,struct dma_slave_config *);
 unsigned src_addr_widths,dst_addr_widths,directions,residue_granularity,max_burst;''')
s=s.replace('static void *kcalloc(int n,size_t sz,int flags){if(pause_calloc){pause_calloc=false;boundary_pause();}return calloc(n,sz);}', 'static void *kcalloc(int n,size_t sz,int flags);')
s=s.replace('static void kfree(void *memory){destructive_calls++;free(memory);}', 'static void kfree(void *memory);')
s=s.replace('static void dma_free_attrs(struct device *dev,size_t size,void *memory,dma_addr_t address,unsigned attrs){destructive_calls++;controller_frees++;}', 'static void dma_free_attrs(struct device *dev,size_t size,void *memory,dma_addr_t address,unsigned attrs);')
s=s.replace('static void devm_free_irq(struct device *dev,int irq,void *data){destructive_calls++;irq_frees++;}', 'static void devm_free_irq(struct device *dev,int irq,void *data);')
s=s.replace('static void dma_async_device_unregister(struct dma_device *dev){destructive_calls++;}', 'static void dma_async_device_unregister(struct dma_device *dev);')
s=s.replace('static void of_dma_controller_free(void *node){destructive_calls++;}', 'static void of_dma_controller_free(void *node);')
(HERE/'test-pl330-probe-provider-shim.h').write_text(s)
for leaf in ['runtime-shim.h','mmio.h']:
    (HERE/('test-pl330-probe-'+leaf)).write_bytes((HERE/('test-dma-pcm-'+leaf)).read_bytes())
print('generated isolated probe suite')
