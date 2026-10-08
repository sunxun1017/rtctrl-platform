#!/usr/bin/env python3
"""Fork old fixtures; add first ready and failed complete STOP probe regressions."""
import re
from pathlib import Path
HERE = Path(__file__).resolve().parent


def create(name, data):
    target = HERE / name
    if target.exists():
        raise ValueError('fresh harness required: ' + name)
    target.write_text(data)


script = (HERE / 'test-pl330-c3-probe.py').read_text()
script = script.replace('test-pl330-c3-probe', 'test-pl330-c3-order').replace('pl330-c3-probe-tests-', 'pl330-c3-order-tests-')
script = script.replace('    (output/"source-input.c").write_bytes(data);(output/"extracted.c").write_text(extracted)\n    (output/"dmaengine-input.h").write_bytes(api_source)\n    extracted=declaration(text,\'struct\',\'pl330_desc_block\')+\'\\n\'+extracted', '    extracted=declaration(text,\'struct\',\'pl330_desc_block\')+\'\\n\'+extracted\n    (output/"source-input.c").write_bytes(data);(output/"extracted.c").write_text(extracted)\n    (output/"dmaengine-input.h").write_bytes(api_source)')
create('test-pl330-c3-order.py', script)
shim = (HERE / 'test-pl330-c3-probe-shim.h').read_text()
shim = shim.replace('static int panic_timeout=30,panics;', 'static int panic_timeout=30,panics;\nstatic bool panic_expected;')
shim = shim.replace('panics++;longjmp(panic_escape,1);', 'panics++;if(!panic_expected){fprintf(stderr,"unexpected fixture panic\\n");exit(99);}longjmp(panic_escape,1);')
create('test-pl330-c3-order-shim.h', shim)
main = (HERE / 'test-pl330-c3-probe-main.c').read_text()
main = main.replace('dmac.irqs_registered=2;', 'dmac.irqs_registered=1;')
main = main.replace('list_del_init(&descriptor[0].node);for(int i=0;i<2;i++)', 'list_del_init(&descriptor[0].node);pl330_desc_release(&dmac,&descriptor[0]);pl330_desc_release(&dmac,&descriptor[1]);for(int i=0;i<2;i++)')
main = main.replace('if(destructive==2){memset(&platform,0,sizeof(platform));', 'if(destructive==2){descriptor[1].status=PREP;list_add_tail(&descriptor[1].node,&channel[1].work_list);memset(&platform,0,sizeof(platform));')
main = re.sub(r'if\(!setjmp\(panic_escape\)\)([^;\n]+);', lambda m: 'panic_expected=true;\n        if(!setjmp(panic_escape))' + m.group(1) + ';\n        panic_expected=false;', main)
create('test-pl330-c3-order-main.c', main)

script = (HERE / 'test-pl330-probe.py').read_text().replace('test-pl330-probe', 'test-pl330-ready').replace('pl330-probe-tests-', 'pl330-ready-tests-')
script = script.replace("extracted=(declaration(pl,'struct','pl330_desc_block')", "amba_probe_body=function(sources['drivers/amba/bus.c'].decode(),'amba_probe')\n    core['amba:amba_probe']=amba_probe_body\n    extracted=(declaration(pl,'struct','pl330_desc_block')")
create('test-pl330-ready.py', script)
for suffix in ['runtime-shim.h']:
    create('test-pl330-ready-' + suffix, (HERE / ('test-pl330-probe-' + suffix)).read_text())
shim = (HERE / 'test-pl330-probe-provider-shim.h').read_text()
shim = shim.replace('void *driver_data,*of_node;struct device_driver *driver;', 'void *driver_data,*of_node;bool pm_active,pm_enabled;struct device_driver *driver;')
shim = shim.replace('struct amba_driver {struct device_driver drv;', 'struct amba_id;\nstruct amba_driver {struct device_driver drv;const struct amba_id *id_table;int (*probe)(struct amba_device *,const struct amba_id *);')
create('test-pl330-ready-provider-shim.h', shim)
api = (HERE / 'test-pl330-probe-api.h').read_text()
api += '''\n/* Kernel API leaves surrounding the exact production AMBA probe wrapper. */
static int of_clk_set_defaults(void *node,bool supplier){(void)node;(void)supplier;return 0;}
static int dev_pm_domain_attach(struct device *dev,bool power_on){(void)dev;(void)power_on;return 0;}
static void dev_pm_domain_detach(struct device *dev,bool power_off){(void)dev;(void)power_off;}
static int amba_get_enable_pclk(struct amba_device *dev){(void)dev;return 0;}
static void amba_put_disable_pclk(struct amba_device *dev){(void)dev;}
static const struct amba_id *amba_lookup(const struct amba_id *table,struct amba_device *dev){(void)dev;return table;}
static void pm_runtime_set_active(struct device *dev){dev->pm_active=true;}
static void pm_runtime_enable(struct device *dev){dev->pm_enabled=true;}
static void pm_runtime_disable(struct device *dev){dev->pm_enabled=false;}
static void pm_runtime_set_suspended(struct device *dev){dev->pm_active=false;}
'''
create('test-pl330-ready-api.h', api)
mmio = (HERE / 'test-pl330-probe-mmio.h').read_text()
mmio = mmio.replace('static bool stall_kill;', 'static bool stall_kill,stall_manager;')
mmio = mmio.replace('else registers[DS/4]=stall_kill?DS_ST_KILL:DS_ST_STOP;', 'else registers[DS/4]=(stall_kill||stall_manager)?DS_ST_KILL:DS_ST_STOP;')
create('test-pl330-ready-mmio.h', mmio)
main = (HERE / 'test-pl330-probe-main.c').read_text()
point = 'int main(void){'
extra = '''static int run_ready_case(bool partial_failure)
{
    struct amba_id id={0};
    struct amba_driver driver={.id_table=&id,.probe=pl330_probe};
    struct amba_device adev={0};
    char state[4096];
    adev.irq[0]=17;
    adev.irq[1]=18;
    adev.periphid=PERIPH_ID_VAL;
    adev.dev.of_node=(void *)1;
    adev.dev.driver=&driver.drv;
    atomic_store(&adev.dev.pm,0);
    atomic_store(&pm_result,0);
    memset(registers,0,sizeof(registers));
    registers[CR0/4]=0;
    total=passed=failed=0;
    volatile bool ok=true;
    volatile int ret=99;
    name=partial_failure?"partial STOP cannot publish cached success":"first ready after exact AMBA probe wrapper";
    if(partial_failure){
        registers[CS(0)/4]=DS_ST_EXEC;
        registers[DS/4]=DS_ST_EXEC;
        stall_manager=true;
    }
    if(!setjmp(panic_escape))
        ret=amba_probe(&adev.dev);
    CHECK(probed!=NULL);
    if(partial_failure){
        CHECK(panics==1&&panic_timeout==0&&ret==99);
        CHECK(registers[CS(0)/4]==DS_ST_STOP&&registers[DS/4]==DS_ST_KILL);
        CHECK(!probed->stop_proven&&probed->stop_reads==0);
        CHECK(reader_published==0&&dma_published==0&&live_irqs==0);
        CHECK(blocks_live>0&&mcode_live==1&&atomic_load(&adev.dev.pm)==2);
    }else{
        CHECK(ret==0&&panics==0&&adev.dev.pm_active&&adev.dev.pm_enabled);
        CHECK(atomic_load(&adev.dev.pm)==0);
        unsigned before_reads=atomic_load(&mmio_calls);
        CHECK(rk3568_lifecycle_state_show(&adev.dev,NULL,state)>0);
        fprintf(stderr,"initial state: %s",state);
        CHECK(strstr(state,"ready=1 ")!=NULL);
        CHECK(probed->stop_proven&&probed->stop_reads==probed->pcfg.num_chan+1);
        CHECK(atomic_load(&mmio_calls)==before_reads);
        pl330_remove(&adev);
        CHECK(live_irqs==0&&dma_published==0&&of_published==0&&blocks_live==0&&mcode_live==0);
    }
    return !ok;
}

'''
main = main.replace(point, extra + point)
main = main.replace('for(int i=0;i<12;i++)', 'for(int i=0;i<14;i++)')
main = main.replace('name=cases[i];pid_t child=fork();if(child==0)_exit(run_probe_case(i));', 'name=i<12?cases[i]:i==12?"first cached ready uses exact AMBA wrapper":"partial manager STOP failure records no cached success";pid_t child=fork();if(child==0)_exit(i<12?run_probe_case(i):run_ready_case(i==13));')
create('test-pl330-ready-main.c', main)
print('created separate C1 fixture and real AMBA first-ready/partial-STOP regression suites')
