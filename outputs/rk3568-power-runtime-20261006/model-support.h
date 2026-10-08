/* Test dependency model; production functions are extracted byte-for-byte. */
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sched.h>

typedef uint32_t u32;
typedef uint64_t u64;
typedef int64_t s64;
typedef uint8_t u8;
typedef long long time64_t;
#ifdef THREADED
typedef pthread_mutex_t spinlock_t;
struct mutex { pthread_mutex_t native; };
#else
typedef unsigned long spinlock_t;
struct mutex { int held; };
#endif
typedef int irqreturn_t;
struct regmap {};
struct regmap_field { int field; };
struct reg_field { int unused; };
struct device_node {};
struct device { struct device *parent; struct device_node *of_node; void *data; };
struct platform_device { struct device dev; };
struct i2c_client { struct device dev; };
struct rk808 { struct i2c_client *i2c; struct regmap *regmap; int variant; void *irq_data; };
struct power_supply { int live; void *data; };
struct work_struct { int pending; void (*function)(struct work_struct *); pthread_t thread; int thread_started; };
struct delayed_work { struct work_struct work; };
struct timer_list { int pending; void (*function)(struct timer_list *); unsigned long expires; pthread_t thread; int thread_started; };
struct workqueue_struct { int live; };
struct wake_lock { int live; };
struct of_device_id { int unused; };
struct rtc_time { int unused; };
struct rtc_device { struct device dev; };
union power_supply_propval { int intval; };
enum power_supply_property { POWER_SUPPLY_PROP_ONLINE, POWER_SUPPLY_PROP_STATUS };
#define POWER_SUPPLY_STATUS_CHARGING 1
#define POWER_SUPPLY_STATUS_DISCHARGING 2
enum rk817_battery_fields { TEST_FIELD };

#define GFP_KERNEL 0
#define WQ_MEM_RECLAIM 1
#define WQ_FREEZABLE 2
#define IRQF_TRIGGER_RISING 1
#define IRQF_ONESHOT 2
#define IRQ_HANDLED 1
#define WAKE_LOCK_SUSPEND 0
#define RK809_ID 0x8090
#define RK817_ID 0x8170
#define F_MAX_FIELDS 64
#define DRIVER_VERSION "1.00"
#define RK817_IRQ_PLUG_IN 1
#define RK817_IRQ_PLUG_OUT 2
#define PLUG_IN_STS 3
#define CHIP_NAME_H 4
#define CHIP_NAME_L 5
#define CUR_CALIB_UPD 6
#define VCALIB0_H 7
#define VCALIB0_L 8
#define VCALIB1_H 9
#define VCALIB1_L 10
#define IOFFSET_H 11
#define IOFFSET_L 12
#define CAL_OFFSET_H 13
#define CAL_OFFSET_L 14
#define PWRON_CUR_H 15
#define PWRON_CUR_L 16
#define OCV_THRE_VOL 17
#define CONFIG_RTC_HCTOSYS_DEVICE "rtc0"
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define container_of(p,t,m) ((t *)((char *)(p) - offsetof(t,m)))
#define from_timer(v,t,m) container_of(t, struct rk817_battery_device, m)
#define READ_ONCE(v) (v)
#define WRITE_ONCE(v,x) ((v)=(x))
#ifdef THREADED
#define spin_lock_init(p) pthread_mutex_init(p,NULL)
#define mutex_init(p) pthread_mutex_init(&(p)->native,NULL)
#define mutex_lock(p) pthread_mutex_lock(&(p)->native)
#define mutex_unlock(p) pthread_mutex_unlock(&(p)->native)
#define spin_lock_irqsave(p,f) do { (f)=0; pthread_mutex_lock(p); } while (0)
#define spin_unlock_irqrestore(p,f) do { (void)(f); pthread_mutex_unlock(p); } while (0)
#else
#define spin_lock_init(p) (*(p)=0)
#define mutex_init(p) ((p)->held=0)
#define mutex_lock(p) do { if ((p)->held) bad++; (p)->held=1; } while (0)
#define mutex_unlock(p) do { if (!(p)->held) bad++; (p)->held=0; } while (0)
#define spin_lock_irqsave(p,f) do { (void)(p); (f)=0; } while (0)
#define spin_unlock_irqrestore(p,f) do { (void)(p); (void)(f); } while (0)
#endif
#define cmpxchg(p,old,new) ((*(p)==(old)) ? (*(p)=(new),(old)) : *(p))
#define min(a,b) ((a)<(b)?(a):(b))
#define msecs_to_jiffies(n) (n)
#define MINUTE(n) ((n)*60)
#define HZ 100
#define TIMER_MS_COUNTS 1000
#define DEFAULT_BAT_RES 135
#define DEFAULT_MONITOR_SEC 5
#define DEFAULT_PWROFF_VOL_THRESD 3400
#define DEFAULT_SLP_EXIT_CUR 300
#define DEFAULT_SLP_ENTER_CUR 300
#define DEFAULT_SLP_FILTER_CUR 100
#define MODE_BATTARY 0
#define MODE_VIRTUAL 1
#define DEFAULT_MAX_SOC_OFFSET 60
#define DEFAULT_FB_TEMP 3
#define DEFAULT_ENERGY_MODE 0
#define DEFAULT_ZERO_RESERVE_DSOC 10
#define DEFAULT_SAMPLE_RES 20
#define SAMPLE_RES_10MR 10
#define SAMPLE_RES_20MR 20
#define MAX_INTERPOLATE 1000
#define MAX_PERCENTAGE 100
#define MAX_INT 0x7fff
#define DIV(x) ((x)?(x):1)
#define CC_OR_CV_CHRG 1
#define CHARGE_FINISH 2
#define MODE_ZERO 0
#define MODE_FINISH 1
#define MODE_SMOOTH 2
#define DISCHRG_TIME_STEP1 600
#define DISCHRG_TIME_STEP2 3600
#define VIRTUAL_TEMPERATURE 188
#define DBG(...) do { if (debug_on) model_debug(__VA_ARGS__); } while (0)
#define BAT_INFO(...) do {} while (0)
#define dev_err(d,...) do { if (!(d)) bad++; } while (0)
#define dev_info(d,...) do { if (!(d)) bad++; } while (0)
#define dev_dbg(d,...) do {} while (0)
#define IS_ERR(p) ((intptr_t)(p)<0 && (intptr_t)(p)>-4096)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define ERR_PTR(n) ((void *)(intptr_t)(n))
#define IS_ERR_OR_NULL(p) (!(p)||IS_ERR(p))
#define INIT_DELAYED_WORK(w,f) do { memset((w),0,sizeof(*(w))); (w)->work.function=(f); } while (0)
#define INIT_WORK(w,f) do { memset((w),0,sizeof(*(w))); (w)->function=(f); } while (0)
#define timer_setup(t,f,flags) do { memset((t),0,sizeof(*(t))); (t)->function=(f); } while (0)

static int bad, fail_alloc, fail_ps, fail_chg_ps, fail_virq, fail_irq, fail_action;
static int queues, updates, writes, cancels, irq_count, destroyed, wake_count, live_ps;
static int property_invalid, ocv_count, read_error, trigger_stop, field_failure;
static int register_order, first_queue_order, allocations, last_owner_pdev;
static int rtc_fail, rtc_refs, irq_callbacks;
static int irq_mask;
static int debug_on;
static int plug_sample,plug_event_during_read,ps_notifications;
static void model_debug(const char *fmt,...) {}
static unsigned long jiffies;
static struct of_device_id rk817_bat_of_match[1];
static struct reg_field rk817_battery_reg_fields[18]={{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10},{11},{12},{13},{14},{15},{16},{17}};
static struct regmap_field register_fields[18];
static struct rtc_device rtc;
struct resource { int kind, key; void (*action)(void *); void *data; };
static struct resource resources[32];
static int resource_count;
#ifdef THREADED
static pthread_mutex_t engine_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t engine_cv=PTHREAD_COND_INITIALIZER;
static int engine_block_stage,engine_entered,engine_release;
static atomic_int engine_join_entered,engine_stop_done;
static atomic_int engine_stop_started;
static pthread_t engine_irq_threads[2];
static int engine_irq_running[2];
static irqreturn_t (*engine_irq_functions[2])(int,void *);
static void engine_pause(int stage) {
    pthread_mutex_lock(&engine_lock);
    if(engine_block_stage==stage) {
        engine_entered=1;
        pthread_cond_broadcast(&engine_cv);
        while(!engine_release) pthread_cond_wait(&engine_cv,&engine_lock);
    }
    pthread_mutex_unlock(&engine_lock);
}
static void engine_join_work(struct work_struct *w) {
    if(w->thread_started) { atomic_store(&engine_join_entered,1); pthread_join(w->thread,NULL); w->thread_started=0; }
}
#else
#define engine_pause(stage) do {} while(0)
#define engine_join_work(w) do {} while(0)
#endif
static struct platform_device pdev;
static struct i2c_client client;
static struct rk808 pmic;
static struct regmap regmap;
static struct workqueue_struct wq;
static struct power_supply bat_ps, chg_ps;
static struct rk817_battery_device *instance;
static void (*cleanup_action)(void *);
static void *cleanup_data;
static void *allocated[16];
static const struct of_device_id *of_match_device(const struct of_device_id *ids, struct device *d) { return ids; }
static void *dev_get_drvdata(struct device *d) { return d->data; }
static void *power_supply_get_drvdata(struct power_supply *p) { return p->data; }
static void platform_set_drvdata(struct platform_device *p, void *d) { p->dev.data=d; }
static void *platform_get_drvdata(struct platform_device *p) { return p->dev.data; }
static struct platform_device *to_platform_device(struct device *d) { return container_of(d,struct platform_device,dev); }
static void *devm_kzalloc(struct device *d,size_t n,int flags) {
    if (allocations == 0) last_owner_pdev = d == &pdev.dev;
    if (allocations == fail_alloc) { allocations++; return NULL; }
    void *p=calloc(1,n); allocated[allocations++]=p; return p;
}
static struct regmap_field *devm_regmap_field_alloc(struct device *d,struct regmap *r,struct reg_field f) { register_fields[f.unused].field=f.unused; return field_failure ? ERR_PTR(-EIO) : &register_fields[f.unused]; }
static struct workqueue_struct *alloc_ordered_workqueue(const char *fmt,int flags,const char *name) { return fail_alloc == 99 ? NULL : (wq.live=1,&wq); }
static void destroy_workqueue(struct workqueue_struct *q) { if (!q||!q->live) bad++; else q->live=0; destroyed++; }
static int queue_delayed_work(struct workqueue_struct *q,struct delayed_work *w,unsigned long delay) {
    if(delay==10) engine_pause(3);
    if (!q||!q->live||!w->work.function) bad++;
    if (!first_queue_order) first_queue_order=++register_order;
    queues++; w->work.pending=1; return 1;
}
static int queue_work(struct workqueue_struct *q,struct work_struct *w) {
    if (!q||!q->live||!w->function) bad++;
    queues++; w->pending=1; return 1;
}
static void cancel_work_sync(struct work_struct *w) { engine_join_work(w); w->pending=0; cancels++; }
static void cancel_delayed_work_sync(struct delayed_work *w) { engine_join_work(&w->work); w->work.pending=0; cancels++; }
static void add_timer(struct timer_list *t) { if (!wq.live) bad++; t->pending=1; }
static void mod_timer(struct timer_list *t,unsigned long n) { t->pending=1; }
static void del_timer_sync(struct timer_list *t) {
#ifdef THREADED
    if(t->thread_started) { atomic_store(&engine_join_entered,1); pthread_join(t->thread,NULL); t->thread_started=0; }
#endif
    t->pending=0; cancels++;
}
static void wake_lock_init(struct wake_lock *w,int type,const char *name) { w->live=1; wake_count++; }
static void wake_lock_destroy(struct wake_lock *w) { if (!w->live) bad++; else w->live=0; wake_count--; }
static void wake_lock_timeout(struct wake_lock *w,unsigned long ms) { if (!w->live) bad++; }
static int devm_add_action_or_reset(struct device *d,void (*f)(void *),void *data) { if (fail_action) { f(data); return -ENOMEM; } cleanup_action=f; cleanup_data=data; resources[resource_count++]=(struct resource){.kind=3,.action=f,.data=data}; return 0; }
static void devm_remove_action(struct device *d,void (*f)(void *),void *data) { cleanup_action=NULL; cleanup_data=NULL; }
static int regmap_irq_get_virq(void *data,int which) { return fail_virq==which ? -ENXIO : which+20; }
static int devm_request_threaded_irq(struct device *d,int irq,void *top,irqreturn_t (*fn)(int,void*),int flags,const char *name,void *data) { if (fail_irq==irq-20) return -EBUSY; irq_count++; register_order++; resources[resource_count++]=(struct resource){.kind=2,.key=irq}; irq_callbacks++; fn(irq,data); return 0; }
static void devm_free_irq(struct device *d,int irq,void *data) { int found=0; for(int i=resource_count-1;i>=0;i--) if(resources[i].kind==2&&resources[i].key==irq) { resources[i].kind=0; found=1; break; } if (!found||irq_count<=0) bad++; else irq_count--; }
static int request_threaded_irq(int irq,void *top,irqreturn_t (*fn)(int,void*),int flags,const char *name,void *data) {
    if(fail_irq==irq-20) return -EBUSY;
    irq_mask|=1<<(irq-20); irq_count++; register_order++; irq_callbacks++;
#ifdef THREADED
    engine_irq_functions[irq-21]=fn;
#endif
    fn(irq,data); return 0;
}
static void free_irq(int irq,void *data) {
#ifdef THREADED
    if(engine_irq_running[irq-21]) { atomic_store(&engine_join_entered,1); pthread_join(engine_irq_threads[irq-21],NULL); engine_irq_running[irq-21]=0; }
#endif
    if(!(irq_mask&(1<<(irq-20)))||irq_count<=0) bad++; else { irq_mask&=~(1<<(irq-20)); irq_count--; }
}
static void synchronize_irq(int irq) {
#ifdef THREADED
    if(engine_irq_running[irq-21]) { atomic_store(&engine_join_entered,1); pthread_join(engine_irq_threads[irq-21],NULL); engine_irq_running[irq-21]=0; }
#endif
}
static void power_supply_changed(struct power_supply *p) { engine_pause(4); ps_notifications++; if (!p||!p->live) bad++; }
static int of_find_property(struct device_node *n,const char *name,int *len) { *len=ocv_count*4; return 1; }
#include "original-dt-fixture.h"
static int of_property_read_u32_array(struct device_node *n,const char *name,u32 *out,int count) {
    if (property_invalid==1) return -EIO;
    for (int i=0;i<count;i++) out[i]=count==21 ? original_ocv[i] : 7000+i*60;
    if (property_invalid==2 && count>1) out[1]=out[0];
    if (property_invalid==3 && count>1) out[1]=out[0]-1;
    if (property_invalid==12) out[0]=0;
    if (property_invalid==13) out[count-1]=UINT_MAX;
    return 0;
}
static int of_property_read_u32(struct device_node *n,const char *name,u32 *v) {
    if (!strcmp(name,"design_capacity")) *v=property_invalid==4 ? 0 : 3500;
    else if (!strcmp(name,"design_qmax")) *v=property_invalid==5 ? 1 : 3750;
    else if (!strcmp(name,"sample_res")) *v=property_invalid==6 ? 0 : 10;
    else if (!strcmp(name,"bat_res_up")) *v=property_invalid==14 ? INT_MAX : 140;
    else if (!strcmp(name,"bat_res_down")) { if (property_invalid==7) return -EINVAL; *v=property_invalid==8 ? 0 : (property_invalid==14 ? 1 : 20); }
    else if (!strcmp(name,"monitor_sec")) *v=property_invalid==9 ? 0 : 5;
    else if (!strcmp(name,"register_chg_psy")) *v=property_invalid==11 ? 1 : 0;
    else return original_dt_u32(name,v);
    return 0;
}
static struct rtc_device *rtc_class_open(const char *name) { if (rtc_fail==1) return NULL; rtc_refs++; rtc.dev.parent=&pdev.dev; return &rtc; }
static int rtc_read_time(struct rtc_device *r,struct rtc_time *t) { return rtc_fail==2 ? -EIO : 0; }
static int rtc_valid_tm(struct rtc_time *t) { return rtc_fail==3 ? -EINVAL : 0; }
static time64_t rtc_tm_to_time64(struct rtc_time *t) { return 123; }
static void rtc_class_close(struct rtc_device *r) { rtc_refs--; }
