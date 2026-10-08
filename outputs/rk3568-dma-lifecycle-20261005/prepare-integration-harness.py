#!/usr/bin/env python3
"""Fork immutable tested PL330 API boundary for a shared provider/PCM unit."""
from pathlib import Path
p=Path(__file__).resolve().parent
s=(p/'test-pl330-start-shim.h').read_text()
s=s.replace('typedef int gfp_t;','typedef unsigned int gfp_t;')
s=s.replace('#include <time.h>','#include <time.h>\n#include <limits.h>')
s=s.replace('struct device { atomic_int pm;','struct device { int refs;void *iommu_group;atomic_int pm;')
s=s.replace('atomic_int pm;', 'union {atomic_int pm;struct {atomic_t usage_count;} power;};')
s=s.replace('struct device { int refs;', 'struct device {struct {int unused;} kobj;int refs;')
s=s.replace('    int lifecycle_error;','    int lifecycle_error;atomic_t owned_descs;bool stop_proven;u64 stop_reads;')
s=s.replace('struct pl330_dmac {','struct timer_list {int unused;};\nstruct pl330_dmac {')
s=s.replace('atomic_t owned_descs;bool stop_proven;u64 stop_reads;', 'atomic_t owned_descs;bool stop_proven;u64 stop_reads;struct timer_list reader_timer;')
s=s.replace('struct dma_device {struct device *dev;', '''struct dma_device {struct device *dev;
 int privatecnt;unsigned cap_mask;void (*device_free_chan_resources)(struct dma_chan *);
 int (*device_resume)(struct dma_chan *),(*device_pause)(struct dma_chan *),(*device_terminate_all)(struct dma_chan *);
 void (*device_issue_pending)(struct dma_chan *);
 enum dma_status (*device_tx_status)(struct dma_chan *,dma_cookie_t,struct dma_tx_state *);
 struct dma_async_tx_descriptor *(*device_prep_dma_cyclic)(struct dma_chan *,dma_addr_t,size_t,size_t,enum dma_transfer_direction,unsigned long);
''')
s=s.replace('int client_count;};','int client_count;struct {struct device device;} *dev;struct device *slave;char *name;struct {void *dev;void (*route_free)(void *,void *);} *router;void *route_data;};')
s=s.replace('struct pl330_thread {','struct _pl330_req {struct dma_pl330_desc *desc;u32 mc_bus;};\nstruct pl330_thread {')
s=s.replace('struct {struct dma_pl330_desc *desc;} req[2];','struct _pl330_req req[2];')
for start,end in [('static int _stop(', 'static bool _start('),('static bool _trigger(', 'static u32 readl('),('static u32 readl(', 'static int destructive_calls')]:
    i=s.index(start);j=s.index(end,i);s=s[:i]+s[j:]
s=s.replace('static void kfree(void *memory){destructive_calls++;}','static void kfree(void *memory){destructive_calls++;free(memory);}')
s=s.replace('#define might_sleep() ((void)0)', '#define might_sleep() do{if(spin_depth)atomic_fetch_add(&process_in_spin,1);}while(0)')
s=s.replace('static atomic_int warn_attempts;', 'static atomic_int process_in_spin;\nstatic atomic_int warn_attempts;')
s+='''
#define DEFINE_MUTEX(n) struct mutex n={PTHREAD_MUTEX_INITIALIZER}
#define init_waitqueue_head(q) ((void)(q))
#define WRITE_ONCE(v,n) ((v)=(n))
#define EXPORT_SYMBOL(v)
#define EXPORT_SYMBOL_GPL(v)
#define PCM_RUNTIME_CHECK(s) (!(s)->runtime)
#define snd_BUG_ON(c) (c)
#define SNDRV_PCM_STREAM_PLAYBACK 0
#define SNDRV_PCM_STREAM_CAPTURE 1
#define BIT(n) (1U << (n))
#define SNDRV_PCM_INFO_PAUSE 1
#define SNDRV_PCM_HW_PARAM_PERIODS 0
#include "pcm-trigger-constants.h"
#include "dma-flags.h"
#include "dmaengine-pcm-flags.h"
typedef uint32_t __le32;
struct _arg_GO {u8 chan;u32 addr;bool ns;};
static unsigned long loops_per_jiffy __attribute__((unused))=10000;
#define HZ 100
#define PL330_DBGCMD_DUMP(...) ((void)0)
static inline u32 le32_to_cpu(u32 value){return value;}
static inline u32 get_unaligned_le32(const void *p){u32 v;memcpy(&v,p,sizeof(v));return v;}
static void pl330_error_locked(struct pl330_dmac *pl330,int error);
static inline bool spin_try_boundary(spinlock_t *l){if(pthread_mutex_trylock(&l->mutex))return false;spin_depth++;return true;}
#define spin_trylock_irqsave(l,f) ((f)=0,spin_try_boundary(l))
#define dev_get_drvdata(dev) ((dev)->driver_data)
#define scnprintf snprintf
struct device_attribute {int unused;};
static struct device_attribute dev_attr_rk3568_lifecycle_state;
static inline void device_remove_file(struct device *dev,struct device_attribute *attr){(void)dev;(void)attr;}
#define from_timer(v,t,m) container_of(t,typeof(*(v)),m)
static unsigned long jiffies;
static inline int mod_timer(struct timer_list *timer,unsigned long expires){(void)timer;(void)expires;return 0;}
static inline int del_timer_sync(struct timer_list *timer){(void)timer;return 0;}
static struct mutex dma_list_mutex={PTHREAD_MUTEX_INITIALIZER};
#define WARN_ONCE(c,...) WARN_ON(c)
#define DMA_PRIVATE 0
#define dma_cap_clear(cap,mask) ((mask)=0)
#define DMA_SLAVE_NAME "slave"
static inline void sysfs_remove_link(void *kobj,const char *name){(void)kobj;(void)name;abort();}
static inline void dma_device_put(struct dma_device *dev){(void)dev;}
static inline void *dma_chan_to_owner(struct dma_chan *chan){(void)chan;return NULL;}
static inline void module_put(void *owner){(void)owner;}
static u32 readl(void *address);
static void writel(u32 value,void *address);
'''
(p/'test-dma-pcm-provider-shim.h').write_text(s)
