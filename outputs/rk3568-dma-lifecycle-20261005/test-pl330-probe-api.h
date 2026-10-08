/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Probe API boundaries; controller/add/IRQ/stop/free bodies come from production. */
#define INIT 1
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define DMA_BIT_MASK(n) ((1ULL<<(n))-1)
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define dev_warn(...) ((void)0)
#define max_t(t,a,b) ((t)(a)>(t)(b)?(t)(a):(t)(b))
#define PL330_DMA_BUSWIDTHS 0xff
#define DMA_MEMCPY 1
#define DMA_SLAVE 2
#define DMA_CYCLIC 3
#define DMA_RESIDUE_GRANULARITY_BURST 2
#define dma_cap_set(cap,mask) ((mask)|=BIT(cap))
#define amba_set_drvdata(d,v) ((d)->dev.driver_data=(v))
#define timer_setup(t,fn,flags) ((void)(t),(void)(fn),(void)(flags))
struct amba_id {unsigned id;};
struct device_node {int unused;};
struct of_phandle_args {int args_count;unsigned args[1];};
struct of_dma {void *of_dma_data;};
static struct {const char *quirk;int id;} of_quirks[]={{"unused",0}};
static void init_pl330_debugfs(struct pl330_dmac *d){(void)d;}
static void pl330_irqs_remove(struct pl330_dmac *d);
enum probe_stage {ST_NONE,ST_MASK,ST_DEVM,ST_MAP,ST_RESET1,ST_RESET2,ST_MCODE,ST_THREAD,ST_POOL,ST_PERIPHERAL,ST_IRQ1,ST_IRQ2,ST_READER,ST_REGISTER,ST_OF,ST_SEG};
static enum probe_stage probe_fail;
static bool inject_initial_irq,inject_fault_irq,inject_unwind_irq,inject_live_client;
static int requested_irqs,live_irqs,dma_published,of_published,reader_published,blocks_live,mcode_live;
static int probe_irq_entries,probe_initialized_irq,probe_frees_with_irq,probe_unwind_irq_count;
static int request_numbers[AMBA_NR_IRQS],free_numbers[AMBA_NR_IRQS],free_number_count,calloc_number;
static void *allocation_blocks[128];
static unsigned allocation_count;
static struct pl330_dmac *probed;
static irqreturn_t (*probe_handler)(int,void *);
static int stage_errno(enum probe_stage stage){return probe_fail==stage?-EREMOTEIO:0;}
static int dma_set_mask_and_coherent(struct device *dev,uint64_t mask){(void)dev;(void)mask;return stage_errno(ST_MASK);}
static void *devm_kzalloc(struct device *dev,size_t size,int flags){(void)dev;(void)flags;if(probe_fail==ST_DEVM)return NULL;probed=calloc(1,size);return probed;}
static int device_property_read_u32(struct device *dev,const char *name,int *value){(void)dev;(void)name;(void)value;return -EINVAL;}
static bool of_property_read_bool(struct device_node *np,const char *name){(void)np;(void)name;return false;}
static void *devm_ioremap_resource(struct device *dev,struct resource *res){(void)dev;(void)res;return probe_fail==ST_MAP?(void *)(intptr_t)-EREMOTEIO:registers;}
static int reset_get_count;
static void *devm_reset_control_get_optional(struct device *dev,const char *name){(void)dev;(void)name;reset_get_count++;return stage_errno(reset_get_count==1?ST_RESET1:ST_RESET2)?(void *)(intptr_t)-EREMOTEIO:NULL;}
static int dev_err_probe(struct device *dev,int error,const char *fmt){(void)dev;(void)fmt;return error;}
static int reset_control_deassert(void *reset){(void)reset;return 0;}
static void *dma_alloc_attrs(struct device *dev,size_t size,dma_addr_t *bus,int flags,unsigned attrs){(void)dev;(void)flags;(void)attrs;if(probe_fail==ST_MCODE)return NULL;mcode_live++;*bus=0x4000;return calloc(1,size);}
static void *kcalloc(int n,size_t size,int flags){(void)flags;calloc_number++;if((probe_fail==ST_THREAD&&calloc_number==1)||(probe_fail==ST_POOL&&calloc_number==2)||(probe_fail==ST_PERIPHERAL&&calloc_number==3))return NULL;void *p=calloc(n,size);if(p){assert(allocation_count<128);allocation_blocks[allocation_count++]=p;blocks_live++;}return p;}
static void kfree(void *memory){if(memory){for(unsigned i=0;i<allocation_count;i++)if(allocation_blocks[i]==memory){allocation_blocks[i]=NULL;blocks_live--;break;}free(memory);}destructive_calls++;}
static void fire_unwind_irq(void){if(inject_unwind_irq&&live_irqs){probe_frees_with_irq++;registers[FSM/4]=1;probe_unwind_irq_count++;probe_handler(17,probed);}}
static void dma_free_attrs(struct device *dev,size_t size,void *memory,dma_addr_t bus,unsigned attrs){(void)dev;(void)size;(void)bus;(void)attrs;fire_unwind_irq();if(memory){free(memory);mcode_live--;}controller_frees++;}
static int devm_request_irq(struct device *dev,int irq,irqreturn_t (*handler)(int,void *),unsigned flags,const char *name,void *data){(void)dev;(void)flags;(void)name;requested_irqs++;if(stage_errno(requested_irqs==1?ST_IRQ1:ST_IRQ2))return -EREMOTEIO;request_numbers[live_irqs++]=irq;probe_handler=handler;struct pl330_dmac *d=data;if(inject_initial_irq||inject_fault_irq){probe_irq_entries++;probe_initialized_irq+=(d->state==INIT&&d->req_done.next!=NULL&&d->channels!=NULL);if(inject_fault_irq)registers[FSM/4]=1;handler(irq,data);}return 0;}
static void devm_free_irq(struct device *dev,int irq,void *data){(void)dev;(void)data;assert(live_irqs>0);free_numbers[free_number_count++]=irq;live_irqs--;irq_frees++;}
static int device_create_file(struct device *dev,struct device_attribute *attr){(void)dev;(void)attr;if(stage_errno(ST_READER))return -EREMOTEIO;reader_published++;return 0;}
static int dma_async_device_register_checked(struct dma_device *dev,int (*checked)(struct dma_chan *)){if(stage_errno(ST_REGISTER))return -EREMOTEIO;dev->device_synchronize_checked=checked;dma_published++;return 0;}
static void dma_async_device_unregister(struct dma_device *dev){(void)dev;assert(dma_published==1);dma_published--;}
static int of_dma_controller_register(struct device_node *node,struct dma_chan *(*xlate)(struct of_phandle_args *,struct of_dma *),void *data){(void)node;(void)xlate;if(inject_live_client){struct pl330_dmac *d=data;list_first_entry(&d->ddma.channels,struct dma_pl330_chan,chan.device_node)->chan.client_count=1;}if(stage_errno(ST_OF))return -EREMOTEIO;of_published++;return 0;}
static void of_dma_controller_free(void *node){(void)node;if(of_published)of_published--;}
static struct dma_chan *dma_get_slave_channel(struct dma_chan *c){(void)c;return NULL;}
static int dma_set_max_seg_size(struct device *dev,size_t size){(void)dev;(void)size;return stage_errno(ST_SEG);}
static void pm_runtime_irq_safe(struct device *dev){(void)dev;}
static void pm_runtime_use_autosuspend(struct device *dev){(void)dev;}
static void pm_runtime_set_autosuspend_delay(struct device *dev,int value){(void)dev;(void)value;}
