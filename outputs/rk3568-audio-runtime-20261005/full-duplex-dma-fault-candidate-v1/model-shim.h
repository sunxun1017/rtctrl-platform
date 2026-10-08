#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
typedef uint64_t u64;
typedef int dma_cookie_t;
typedef size_t snd_pcm_uframes_t;
typedef int64_t ktime_t;
typedef struct { atomic_int value; } atomic_t;
typedef struct { atomic_uint value; } refcount_t;
typedef struct { atomic_long value; } atomic_long_t;
typedef struct { int unused; } wait_queue_head_t;
typedef struct { pthread_mutex_t value; } spinlock_t;
struct mutex { pthread_mutex_t value; };
static _Thread_local int spin_depth;
static void spin_lock(spinlock_t *s) { pthread_mutex_lock(&s->value); spin_depth++; }
static void spin_unlock(spinlock_t *s) { spin_depth--; pthread_mutex_unlock(&s->value); }
#define spin_lock_irqsave(s,f) do { (f)=0; spin_lock(s); } while (0)
#define spin_unlock_irqrestore(s,f) do { (void)(f); spin_unlock(s); } while (0)
static void mutex_init(struct mutex *s) { pthread_mutex_init(&s->value,NULL); }
static void mutex_lock(struct mutex *s) { pthread_mutex_lock(&s->value); }
static void mutex_unlock(struct mutex *s) { pthread_mutex_unlock(&s->value); }
#define DEFINE_MUTEX(n) struct mutex n={PTHREAD_MUTEX_INITIALIZER}
#define ATOMIC_LONG_INIT(n) { ATOMIC_VAR_INIT(n) }
static void atomic_inc(atomic_t *a) { atomic_fetch_add(&a->value,1); }
static void atomic_dec(atomic_t *a) { atomic_fetch_sub(&a->value,1); }
static int atomic_read(atomic_t *a) { return atomic_load(&a->value); }
static unsigned refcount_read(refcount_t *a) { return atomic_load(&a->value); }
static bool refcount_inc_not_zero(refcount_t *a) { unsigned v=atomic_load(&a->value); while(v&&!atomic_compare_exchange_weak(&a->value,&v,v+1)){} return !!v; }
static bool refcount_dec_and_test(refcount_t *a) { return atomic_fetch_sub(&a->value,1)==1; }
static void atomic_long_add(long n,atomic_long_t *a) { atomic_fetch_add(&a->value,n); }
static long atomic_long_read(atomic_long_t *a) { return atomic_load(&a->value); }
static void wake_up_all(wait_queue_head_t *q) { (void)q; }
static ktime_t ktime_get(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return (ktime_t)t.tv_sec*1000000000+t.tv_nsec; }
static ktime_t ktime_add_ms(ktime_t n,int ms) { return n+(ktime_t)ms*1000000; }
static int ktime_compare(ktime_t a,ktime_t b) { return (a>b)-(a<b); }
#define wait_event_timeout(q,c,t) ({ ktime_t _d=ktime_add_ms(ktime_get(),t); int _r; while(!(_r=(c))&&ktime_get()<_d)usleep(1000); _r; })
#define msecs_to_jiffies(n) (n)
#define might_sleep() ((void)0)
#define READ_ONCE(v) (v)
#define WRITE_ONCE(v,n) ((v)=(n))
#define WARN_ON(c) assert(!(c))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define from_tasklet(v,p,m) container_of(p,typeof(*(v)),m)
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define __noreturn __attribute__((noreturn))
#define __iomem
#define EXPORT_SYMBOL_GPL(n)
#define GFP_KERNEL 0
#define THIS_MODULE NULL
#define SNDRV_DMA_TYPE_DEV 2
#define PCM_RUNTIME_CHECK(s) (!(s)->runtime)
#define SNDRV_PCM_POS_XRUN ((snd_pcm_uframes_t)-1)
#define SNDRV_PCM_INFO_PAUSE 1
#define SNDRV_PCM_TRIGGER_START 0
#define SNDRV_PCM_TRIGGER_STOP 1
#define SNDRV_PCM_TRIGGER_RESUME 2
#define SNDRV_PCM_TRIGGER_SUSPEND 3
#define SNDRV_PCM_TRIGGER_PAUSE_PUSH 4
#define SNDRV_PCM_TRIGGER_PAUSE_RELEASE 5
#define PL330_STATE_STOPPED 0
#define DMA_MIN_COOKIE 1
#define INIT 1
#define DYING 2
#define FSM 0
#define FSC 4
struct list_head { struct list_head *next,*prev; };
#define LIST_HEAD(n) struct list_head n={&n,&n}
static void INIT_LIST_HEAD(struct list_head *n) { n->next=n->prev=n; }
static bool list_empty(const struct list_head *h) { return h->next==h; }
static void list_add_tail(struct list_head *n,struct list_head *h) { n->prev=h->prev; n->next=h; h->prev->next=n; h->prev=n; }
static void list_del_init(struct list_head *n) { n->prev->next=n->next; n->next->prev=n->prev; INIT_LIST_HEAD(n); }
static void list_splice_tail_init(struct list_head *h,struct list_head *d) { if(list_empty(h))return; h->next->prev=d->prev; d->prev->next=h->next; h->prev->next=d; d->prev=h->prev; INIT_LIST_HEAD(h); }
#define list_entry(p,t,m) container_of(p,t,m)
#define list_first_entry(h,t,m) list_entry((h)->next,t,m)
#define list_for_each_entry(p,h,m) for(p=list_entry((h)->next,typeof(*p),m); &(p)->m!=(h); p=list_entry((p)->m.next,typeof(*p),m))
#define list_for_each_entry_safe(p,n,h,m) for(p=list_entry((h)->next,typeof(*p),m),n=list_entry((p)->m.next,typeof(*n),m); &(p)->m!=(h); p=n,n=list_entry((n)->m.next,typeof(*n),m))
struct device { int refs; bool iommu; };
struct dma_chan;
struct dma_device { struct device *dev; bool lifecycle_closing; int (*device_synchronize_checked)(struct dma_chan *); };
struct dma_chan { struct dma_device *device; };
enum dmaengine_tx_result { DMA_TRANS_NOERROR, DMA_TRANS_READ_FAILED, DMA_TRANS_WRITE_FAILED, DMA_TRANS_ABORTED };
struct dmaengine_result { enum dmaengine_tx_result result; unsigned residue; };
typedef void (*dma_async_tx_callback)(void *);
typedef void (*dma_async_tx_callback_result)(void *,const struct dmaengine_result *);
struct dma_async_tx_descriptor { dma_async_tx_callback callback; dma_async_tx_callback_result callback_result; void *callback_param; dma_cookie_t cookie; };
enum dma_status { DMA_COMPLETE,DMA_IN_PROGRESS,DMA_PAUSED,DMA_ERROR };
struct dma_tx_state { unsigned residue,in_flight_bytes; };
struct tasklet_struct { bool queued; };
static void tasklet_schedule(struct tasklet_struct *t) { t->queued=true; }
struct pl330_dmac;
struct dma_pl330_chan;
struct dma_pl330_desc;
struct pl330_thread { int state,id,req_running; unsigned lstenq; struct { struct dma_pl330_desc *desc; } req[2]; bool accept_callbacks; struct dma_pl330_chan *owner_pch; };
struct dma_pl330_chan {
    struct dma_chan chan; spinlock_t lock; struct pl330_dmac *dmac; struct pl330_thread *thread;
    struct list_head work_list,submitted_list,retired_list;
    u64 epoch,fault_notified_epoch; bool fault_notified,quiescing,tasklet_queued,gc_queued,pm_ref_held;
    atomic_t producers,runners,issuers,operations,preparations,faults,gc_users;
    wait_queue_head_t drain_wait; struct mutex sync_mutex;
    struct dma_pl330_desc *model_desc; int go_calls;
};
struct pl330_dmac {
    spinlock_t lock; int lifecycle_error,state; bool stop_proven,removing,system_suspended,fault_tasklet_queued;
    u64 stop_reads; unsigned char registers[8]; void *base; struct dma_device ddma;
    struct tasklet_struct tasks; unsigned num_peripherals; struct dma_pl330_chan *peripherals;
    struct { unsigned num_chan; } pcfg; struct pl330_thread *channels,*manager;
    wait_queue_head_t drain_wait;
    atomic_t producers; bool pm_failed;
    struct { bool reset_dmac,reset_mngr; unsigned reset_chan; } dmac_tbd;
};
struct dma_pl330_desc { struct list_head node; struct dma_async_tx_descriptor txd; struct dma_pl330_chan *owner_pch; u64 owner_epoch; refcount_t refs; };
static struct dma_pl330_chan *to_pchan(struct dma_chan *c) { return container_of(c,struct dma_pl330_chan,chan); }
static int _state(struct pl330_thread *t) { return t->state; }
static unsigned readl(void *p) { return *(unsigned *)p; }
static void pl330_failstop(struct pl330_dmac *d,const char *s) { fprintf(stderr,"unexpected failstop %s\n",s); abort(); }
static void pl330_desc_release(struct pl330_dmac *d,struct dma_pl330_desc *s) { (void)d; assert(refcount_read(&s->refs)==1); }
enum pl330_op_err { PL330_ERR_NONE,PL330_ERR_FAIL,PL330_ERR_ABORT };
static void _stop(struct pl330_thread *t) { t->state=PL330_STATE_STOPPED; }
static void pl330_desc_put(struct dma_pl330_desc *);
static void dma_pl330_rqcb(struct dma_pl330_desc *d,enum pl330_op_err error) { (void)error; if(d)pl330_desc_put(d); }
static int inject_terminate_errno;
static void provider_fault(struct pl330_dmac *,int);
static int pl330_terminate_channel(struct dma_chan *c) {
    struct dma_pl330_chan *p=to_pchan(c); unsigned long f;
    if(inject_terminate_errno){provider_fault(p->dmac,inject_terminate_errno);inject_terminate_errno=0;}
    spin_lock_irqsave(&p->lock,f);
    if(!p->quiescing){p->quiescing=true;p->epoch++;}
    if(p->thread){p->thread->accept_callbacks=false;p->thread->state=PL330_STATE_STOPPED;}
    list_splice_tail_init(&p->work_list,&p->retired_list); list_splice_tail_init(&p->submitted_list,&p->retired_list);
    spin_unlock_irqrestore(&p->lock,f); return p->dmac->lifecycle_error;
}
static void usleep_range(unsigned a,unsigned b) { (void)b; usleep(a); }
static void pm_runtime_mark_last_busy(struct device *d) { (void)d; assert(!spin_depth); }
static void pm_runtime_put_autosuspend(struct device *d) { (void)d; assert(!spin_depth); }
struct snd_dma_device { int type; struct device *dev; };
struct snd_dma_buffer { struct snd_dma_device dev; unsigned char *area; uintptr_t addr; size_t bytes; void *private_data; };
struct snd_pcm_substream;
struct snd_pcm_runtime { void *private_data; struct snd_dma_buffer *dma_buffer_p; unsigned char *dma_area; uintptr_t dma_addr; size_t dma_bytes; long delay; bool no_period_wakeup; unsigned info; int (*dma_quiesce)(struct snd_pcm_substream *); };
struct snd_card { struct mutex memory_mutex; size_t total_pcm_alloc_bytes; };
struct snd_pcm { struct snd_card *card; };
struct snd_pcm_substream { struct snd_pcm_runtime *runtime; spinlock_t stream_lock; int state,periods,xruns,sink_calls,index; struct snd_dma_buffer dma_buffer; struct snd_pcm *pcm; void *private_data; int stream; };
static void snd_pcm_stream_lock_irq(struct snd_pcm_substream *s) { spin_lock(&s->stream_lock); }
static void snd_pcm_stream_unlock_irq(struct snd_pcm_substream *s) { spin_unlock(&s->stream_lock); }
static unsigned snd_pcm_lib_period_bytes(struct snd_pcm_substream *s) { (void)s; return 16; }
static unsigned snd_pcm_lib_buffer_bytes(struct snd_pcm_substream *s) { (void)s; return 64; }
static size_t bytes_to_frames(struct snd_pcm_runtime *r,size_t b) { (void)r; return b/4; }
static void snd_pcm_period_elapsed(struct snd_pcm_substream *s) { assert(!spin_depth); s->periods++; }
static int snd_pcm_stop_xrun(struct snd_pcm_substream *s) { assert(!spin_depth); if(s->state==2){s->state=3;s->xruns++;} return 0; }
static void dmaengine_pcm_failstop(const char *s) { fprintf(stderr,"PCM unexpected failstop %s\n",s); abort(); }
static void *kzalloc(size_t n,int f) { (void)f; return calloc(1,n); }
static void kfree(void *p) { free(p); }
static void __module_get(void *m) { (void)m; }
static struct device *get_device(struct device *d) { d->refs++; return d; }
static bool device_iommu_mapped(struct device *d) { return d->iommu; }
static void snd_pcm_set_runtime_buffer(struct snd_pcm_substream *s,struct snd_dma_buffer *b) { s->runtime->dma_buffer_p=b; s->runtime->dma_area=b?b->area:NULL; s->runtime->dma_addr=b?b->addr:0; s->runtime->dma_bytes=b?b->bytes:0; }
static int dmaengine_check_open(struct dma_chan *c);
static int dmaengine_synchronize_checked(struct dma_chan *c);
static int inject_prepare_errno,inject_submit_errno,inject_go_errno,inject_status_errno;
static bool inject_status_without_sticky;
static void pl330_error_locked(struct pl330_dmac *,int);
static void provider_fault(struct pl330_dmac *d,int error) { unsigned long f; spin_lock_irqsave(&d->lock,f); pl330_error_locked(d,error); spin_unlock_irqrestore(&d->lock,f); }
static enum dma_status dmaengine_tx_status(struct dma_chan *c,dma_cookie_t k,struct dma_tx_state *s) {
    (void)k; if(s){s->residue=16;s->in_flight_bytes=0;}
    if(inject_status_errno){provider_fault(to_pchan(c)->dmac,inject_status_errno);inject_status_errno=0;}
    return (to_pchan(c)->dmac->lifecycle_error||inject_status_without_sticky)?DMA_ERROR:DMA_IN_PROGRESS;
}
enum dma_transfer_direction { DMA_MEM_TO_DEV,DMA_DEV_TO_MEM };
#define DMA_CTRL_ACK 1
#define DMA_PREP_INTERRUPT 2
static enum dma_transfer_direction snd_pcm_substream_to_dma_direction(struct snd_pcm_substream *s) { return s->index?DMA_DEV_TO_MEM:DMA_MEM_TO_DEV; }
static struct dma_async_tx_descriptor *dmaengine_prep_dma_cyclic(struct dma_chan *c,uintptr_t addr,size_t bytes,size_t period,enum dma_transfer_direction dir,unsigned long flags) {
    (void)addr;(void)bytes;(void)period;(void)dir;(void)flags;
    if(inject_prepare_errno){provider_fault(to_pchan(c)->dmac,inject_prepare_errno);inject_prepare_errno=0;return NULL;}
    return &to_pchan(c)->model_desc->txd;
}
static struct dma_chan *submit_chan;
static dma_cookie_t dmaengine_submit(struct dma_async_tx_descriptor *x) {
    if(inject_submit_errno){provider_fault(to_pchan(submit_chan)->dmac,inject_submit_errno);inject_submit_errno=0;return -EIO;}
    x->cookie=2; return 2;
}
static int dma_submit_error(dma_cookie_t c) { return c<0?c:0; }
static void dma_async_issue_pending(struct dma_chan *c) { to_pchan(c)->go_calls++; if(inject_go_errno){provider_fault(to_pchan(c)->dmac,inject_go_errno);inject_go_errno=0;} }
static int dmaengine_resume(struct dma_chan *c) { (void)c; return 0; }
static int dmaengine_pause(struct dma_chan *c) { (void)c; return 0; }
static int dmaengine_terminate_async(struct dma_chan *c) { return pl330_terminate_channel(c); }
struct snd_soc_dai;
struct snd_soc_dai_ops { void (*pcm_async_fault)(struct snd_soc_dai *,int); };
struct snd_soc_dai_driver { struct snd_soc_dai_ops *ops; };
struct snd_soc_dai { struct snd_soc_dai_driver *driver; void *model_arg; struct snd_pcm_substream *model_ss; };
struct snd_soc_pcm_runtime { unsigned num_cpus; struct snd_soc_dai *dais[2]; };
struct dmaengine_pcm { struct dma_chan *chan[2]; };
struct snd_soc_component { struct dmaengine_pcm *pcm; };
static struct dmaengine_pcm *soc_component_to_pcm(struct snd_soc_component *c) { return c->pcm; }
#define asoc_substream_to_rtd(s) ((struct snd_soc_pcm_runtime *)(s)->private_data)
#define asoc_rtd_to_cpu(r,i) ((r)->dais[i])
static int dmaengine_pcm_set_runtime_hwparams(struct snd_soc_component *c,struct snd_pcm_substream *s) { (void)c;(void)s;return 0; }
static int open_leaf_calls,close_leaf_calls;
static int snd_dmaengine_pcm_open(struct snd_pcm_substream *s,struct dma_chan *c) { (void)s;(void)c;open_leaf_calls++;return 0; }
static int snd_dmaengine_pcm_close(struct snd_pcm_substream *s) { (void)s;close_leaf_calls++;return 0; }
