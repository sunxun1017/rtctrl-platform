/* Finite unlinked atomic native API/IRQ/XRUN boundary, not kernel lock proof. */
#include <limits.h>
typedef int irqreturn_t;
#define DRV_NAME "rockchip-i2s-tdm"
static int panic_timeout;
static void panic(const char *format, ...) { (void)format;abort(); } /* fatal API boundary, not exercised by legal close */
#define IRQ_NONE 0
#define IRQ_HANDLED 1
#define HZ 100
#define jiffies 1000UL
#define SNDRV_TIMER_EVENT_MSTART 12
struct snd_pcm_group { int unused; };
static pthread_mutex_t native_stream_locks[2] = { PTHREAD_MUTEX_INITIALIZER, PTHREAD_MUTEX_INITIALIZER };
static void snd_pcm_stream_lock_irq(struct snd_pcm_substream *ss) { pthread_mutex_lock(&native_stream_locks[ss->stream]); }
static void snd_pcm_stream_unlock_irq(struct snd_pcm_substream *ss) { pthread_mutex_unlock(&native_stream_locks[ss->stream]); }
static struct snd_pcm_group *snd_pcm_stream_group_ref(struct snd_pcm_substream *ss) { (void)ss; return NULL; }
static void snd_pcm_group_unref(struct snd_pcm_group *g,struct snd_pcm_substream *ss) { (void)g;(void)ss; }
static int snd_pcm_action_group(const struct action_ops *ops,struct snd_pcm_substream *ss,snd_pcm_state_t state,bool locked)
{ (void)ops;(void)ss;(void)state;(void)locked;return -ENOTSUPP; }
static bool snd_pcm_playback_data(struct snd_pcm_substream *ss) { (void)ss;return true; }
static void snd_pcm_trigger_tstamp(struct snd_pcm_substream *ss) { (void)ss; }
static void snd_pcm_playback_silence(struct snd_pcm_substream *ss,unsigned long n) { (void)ss;(void)n; }
static void snd_pcm_timer_notify(struct snd_pcm_substream *ss,int n) { (void)ss;(void)n; }
static void regcache_cache_only(struct regmap *map,bool cache) { (void)map;(void)cache; }
static int pinctrl_pm_select_idle_state(struct device *dev) { (void)dev;return 0; }
static int snd_pcm_stop_xrun(struct snd_pcm_substream *ss);
static void trcm_native_cut(void *function) __attribute__((no_instrument_function));
static void trcm_GO_cut(struct snd_pcm_substream *ss);
