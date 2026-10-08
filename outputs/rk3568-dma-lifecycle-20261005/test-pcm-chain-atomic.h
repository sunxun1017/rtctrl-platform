/* SPDX-License-Identifier: GPL-2.0-or-later */
typedef struct {atomic_int value;} atomic_t;
static inline int atomic_read(atomic_t *a){return atomic_load(&a->value);}
static inline void atomic_set(atomic_t *a,int n){atomic_store(&a->value,n);}
static inline void atomic_inc(atomic_t *a){atomic_fetch_add(&a->value,1);}
static inline void atomic_dec(atomic_t *a){atomic_fetch_sub(&a->value,1);}
typedef struct {pthread_mutex_t value;} spinlock_t;
static _Thread_local int spin_depth;
static int process_in_spin,warnings;
#define spin_lock_init(l) pthread_mutex_init(&(l)->value,NULL)
#define spin_lock_irqsave(l,f) do{(f)=0;pthread_mutex_lock(&(l)->value);spin_depth++;}while(0)
#define spin_unlock_irqrestore(l,f) do{(void)(f);spin_depth--;pthread_mutex_unlock(&(l)->value);}while(0)
typedef struct {int value;} wait_queue_head_t;
#define init_waitqueue_head(w) ((w)->value=0)
#define wake_up_all(w) ((void)(w))
#define msecs_to_jiffies(n) (n)
#define wait_event_timeout(w,c,n) ({(void)(w);int remaining=(n);while(!(c)&&remaining--){usleep(1000);}!!(c);})
#define READ_ONCE(v) (v)
#define WRITE_ONCE(v,n) ((v)=(n))
#define might_sleep() do{if(spin_depth)process_in_spin++;}while(0)
#define __noreturn __attribute__((noreturn))
static int panic_timeout=30,panic_calls;
static jmp_buf panic_escape;
static inline __noreturn void panic(const char *message,...){(void)message;panic_calls++;longjmp(panic_escape,1);}
