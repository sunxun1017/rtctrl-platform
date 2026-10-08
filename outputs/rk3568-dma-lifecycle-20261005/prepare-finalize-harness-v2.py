#!/usr/bin/env python3
"""Fork bounded ownership fixtures and generic-held open regressions."""
from pathlib import Path
HERE = Path(__file__).resolve().parent


def create(name, text):
    target = HERE / name
    if target.exists():
        raise ValueError('fresh file required: ' + name)
    target.write_text(text)


script = (HERE / 'test-pl330-c3-order.py').read_text().replace('test-pl330-c3-order', 'test-pl330-c3-order2').replace('pl330-c3-order-tests-', 'pl330-c3-order2-tests-')
create('test-pl330-c3-order2.py', script)
shim = (HERE / 'test-pl330-c3-order-shim.h').read_text()
shim = shim.replace('static void kfree(void *memory){if(memory)destructive_calls++;}', '''static void *fixture_blocks[128];
static unsigned fixture_block_count;
static void fixture_blocks_clear(void)
{
    for(unsigned i=0;i<fixture_block_count;i++)
        free(fixture_blocks[i]);
    fixture_block_count=0;
}
static void kfree(void *memory)
{
    if(memory){
        for(unsigned i=0;i<fixture_block_count;i++){
            if(fixture_blocks[i]==memory){
                fixture_blocks[i]=NULL;
                free(memory);
                break;
            }
        }
        destructive_calls++;
    }
}''')
shim = shim.replace('return calloc(1,size);', 'void *block=calloc(1,size);assert(fixture_block_count<128);fixture_blocks[fixture_block_count++]=block;return block;')
create('test-pl330-c3-order2-shim.h', shim)
main = (HERE / 'test-pl330-c3-order-main.c').read_text()
main = main.replace('static void init(bool cyclic){', 'static void init(bool cyclic){\n    fixture_blocks_clear();')
main = main.replace('    return failed?1:0;', '    fixture_blocks_clear();\n    return failed?1:0;')
create('test-pl330-c3-order2-main.c', main)

script = (HERE / 'test-dma-pcm-probe.py').read_text().replace('test-dma-pcm-probe', 'test-dma-pcm-open').replace('dma-pcm-probe-tests-', 'dma-pcm-open-tests-')
script = script.replace("bodies={'provider:'+n:function(pl,n) for n in names}", "if 'static int pl330_check_open(' in pl:names.append('pl330_check_open')\n    bodies={'provider:'+n:function(pl,n) for n in names}")
script = script.replace("api={**{'api:'+n:function(public,n)", "if 'static inline int dmaengine_check_open(' in public:api_names.append('dmaengine_check_open')\n    api={**{'api:'+n:function(public,n)")
script = script.replace("['dmaengine_pcm_trigger','dmaengine_pcm_release_chan'", "['dmaengine_pcm_open','dmaengine_pcm_trigger','dmaengine_pcm_release_chan'")
script = script.replace("unit.write_text('#define HAVE_PCM_QUIESCE", "unit.write_text(('#define HAVE_READONLY_OPEN 1\\n' if 'static int pl330_check_open(' in pl else '')+'#define HAVE_PCM_QUIESCE")
create('test-dma-pcm-open.py', script)
shim = (HERE / 'test-dma-pcm-probe-provider-shim.h').read_text()
shim = shim.replace('int (*device_synchronize_checked)(struct dma_chan *);', 'int (*device_synchronize_checked)(struct dma_chan *);\n int (*device_check_open)(struct dma_chan *);')
create('test-dma-pcm-open-provider-shim.h', shim)
for suffix in ['runtime-shim.h', 'mmio.h']:
    text = (HERE / ('test-dma-pcm-probe-' + suffix)).read_text()
    if suffix == 'runtime-shim.h':
        text += '\nstatic int dmaengine_pcm_set_runtime_hwparams(struct snd_soc_component *component,struct snd_pcm_substream *substream){(void)component;(void)substream;return 0;}\n'
    create('test-dma-pcm-open-' + suffix, text)
main = (HERE / 'test-dma-pcm-probe-main.c').read_text()
main = main.replace('dmac.ddma.device_synchronize_checked=pl330_synchronize_checked;', 'dmac.ddma.device_synchronize_checked=pl330_synchronize_checked;\n#ifdef HAVE_READONLY_OPEN\n dmac.ddma.device_check_open=pl330_check_open;\n#endif\n')
extra = ''' {bool ok=true;name="same generic-held channel reopens only before permanent STOP poison";init_asoc();register_component();
  CHECK(snd_dmaengine_pcm_trigger(&stream,SNDRV_PCM_TRIGGER_START)==0);stall_kill=true;
  CHECK(snd_dmaengine_pcm_quiesce(&stream)==-ETIMEDOUT);
  CHECK(snd_dmaengine_pcm_close(&stream)==-ETIMEDOUT&&runtime.private_data==NULL&&runtime.dma_area==NULL);
  int mmio=atomic_load(&mmio_calls),pm=atomic_load(&pm_get_calls),alloc=kalloc_calls,go=go_commands,kill=kill_commands;
  int ret=dmaengine_pcm_open(&registered_pcm->component,&stream);
  fprintf(stderr,"held poison reopen: ret=%d expected=%d private=%d\\n",ret,dmac.lifecycle_error,runtime.private_data!=NULL);
  CHECK(ret==dmac.lifecycle_error&&ret<0&&runtime.private_data==NULL&&runtime.dma_quiesce==NULL);
  CHECK(atomic_load(&mmio_calls)==mmio&&atomic_load(&pm_get_calls)==pm&&kalloc_calls==alloc&&go_commands==go&&kill_commands==kill);
  CHECK(channel.thread==&hardware[0]&&channel.pm_ref_held&&!list_empty(&channel.retired_list));
  if(ret==0)snd_dmaengine_pcm_close(&stream);
  free(registered_pcm);registered_pcm=NULL;finish(ok);
 }
 {bool ok=true;name="healthy held provider read-only open performs no controller MMIO or PM";init_asoc();register_component();cleanup();
  int mmio=atomic_load(&mmio_calls),pm=atomic_load(&pm_get_calls),kill=kill_commands;
  CHECK(dmaengine_pcm_open(&registered_pcm->component,&stream)==0&&runtime.private_data!=NULL);
  CHECK(atomic_load(&mmio_calls)==mmio&&atomic_load(&pm_get_calls)==pm&&kill_commands==kill);
  cleanup();free(registered_pcm);registered_pcm=NULL;finish(ok);
 }
 {bool ok=true;name="legacy unchecked provider retains original open despite cached field";init_asoc();register_component();cleanup();
  dmac.ddma.device_synchronize_checked=NULL;dmac.lifecycle_error=-EREMOTEIO;
  int mmio=atomic_load(&mmio_calls),pm=atomic_load(&pm_get_calls);
  CHECK(dmaengine_pcm_open(&registered_pcm->component,&stream)==0&&runtime.private_data!=NULL);
  CHECK(!substream_to_prtd(&stream)->checked&&runtime.dma_quiesce==NULL);
  CHECK(atomic_load(&mmio_calls)==mmio&&atomic_load(&pm_get_calls)==pm);
  dmac.lifecycle_error=0;cleanup();free(registered_pcm);registered_pcm=NULL;finish(ok);
 }
 {bool ok=true;name="checked provider missing readonly admission callback is incomplete";init_asoc();register_component();cleanup();
  dmac.ddma.device_check_open=NULL;
  int mmio=atomic_load(&mmio_calls),pm=atomic_load(&pm_get_calls),alloc=kalloc_calls;
  int ret=dmaengine_pcm_open(&registered_pcm->component,&stream);
  CHECK(ret==-EOPNOTSUPP&&runtime.private_data==NULL&&runtime.dma_quiesce==NULL);
  CHECK(atomic_load(&mmio_calls)==mmio&&atomic_load(&pm_get_calls)==pm&&kalloc_calls==alloc);
  if(ret==0)cleanup();
  free(registered_pcm);registered_pcm=NULL;finish(ok);
 }
'''
main = main.replace(' printf("{\\"total\\":%d,\\"passed\\":%d,\\"failed\\":%d}\\n",total,passed,failed);', extra + ' printf("{\\"total\\":%d,\\"passed\\":%d,\\"failed\\":%d}\\n",total,passed,failed);')
create('test-dma-pcm-open-main.c', main)

script = (HERE / 'test-pl330-ready.py').read_text().replace('test-pl330-ready', 'test-pl330-ready2').replace('pl330-ready-tests-', 'pl330-ready2-tests-')
script = script.replace("bodies={'provider:'+n:function(pl,n) for n in names}", "if 'static int pl330_check_open(' in pl:names.append('pl330_check_open')\n    bodies={'provider:'+n:function(pl,n) for n in names}")
script = script.replace("api={**{'api:'+n:function(public,n)", "if 'static inline int dmaengine_check_open(' in public:api_names.append('dmaengine_check_open')\n    api={**{'api:'+n:function(public,n)")
create('test-pl330-ready2.py', script)
for suffix in ['provider-shim.h', 'runtime-shim.h', 'mmio.h', 'main.c', 'api.h']:
    text = (HERE / ('test-pl330-ready-' + suffix)).read_text()
    if suffix == 'provider-shim.h':
        text = text.replace('int (*device_synchronize_checked)(struct dma_chan *);', 'int (*device_synchronize_checked)(struct dma_chan *);\n int (*device_check_open)(struct dma_chan *);')
    create('test-pl330-ready2-' + suffix, text)
print('created bounded C1 order2 and read-only open/ready2 fixture variants')
