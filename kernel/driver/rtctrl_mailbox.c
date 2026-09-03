// SPDX-License-Identifier: GPL-2.0
/* Kernel-staged coherent-DMA mailbox for a robot real-time endpoint. */

#include <linux/atomic.h>
#include <linux/build_bug.h>
#include <linux/capability.h>
#include <linux/compat.h>
#include <linux/dma-mapping.h>
#include <linux/fs.h>
#include <linux/hrtimer.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/kernel.h>
#include <linux/kref.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/property.h>
#include <linux/reset.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/uaccess.h>
#include <linux/version.h>

#include <linux/rtctrl_mailbox.h>

#define RTCTRL_REG_CONTROL 0x00
#define RTCTRL_REG_STATUS 0x04
#define RTCTRL_REG_IRQ_STATUS 0x08
#define RTCTRL_REG_IRQ_ACK 0x0c
#define RTCTRL_REG_TX_DOORBELL 0x10
#define RTCTRL_REG_TX_CONSUMER 0x14
#define RTCTRL_REG_DMA_ADDR_LO 0x18
#define RTCTRL_REG_DMA_ADDR_HI 0x1c
#define RTCTRL_REG_DMA_BYTES 0x20
#define RTCTRL_REG_ABI_VERSION 0x24

#define RTCTRL_CONTROL_ENABLE BIT(0)
#define RTCTRL_CONTROL_RESET BIT(1)
#define RTCTRL_IRQ_RX_READY BIT(0)
#define RTCTRL_IRQ_FAULT BIT(1)
#define RTCTRL_DEFAULT_WATCHDOG_US 100000U
#define RTCTRL_MIN_WATCHDOG_US 1000U
#define RTCTRL_MAX_WATCHDOG_US 1000000U
#define RTCTRL_SAFE_STOP_MAX_KD_BITS 0x447a0000U /* 1000.0f */
#define RTCTRL_DMA_QUIESCE_TIMEOUT_US 10000U
#define RTCTRL_ENDPOINT_RESET_TIMEOUT_US 10000U

struct rtctrl_mailbox_dev {
    struct device* dev;
    void __iomem* regs;
    int irq;
    void* dma_cpu;
    dma_addr_t dma_handle;
    size_t dma_bytes;
    struct rtctrl_mb_layout* layout;
    struct miscdevice misc;
    struct reset_control* reset;
    struct hrtimer watchdog;
    struct mutex transition_lock;
    spinlock_t state_lock;
    struct kref refcount;
    u64 watchdog_timeout_ns;
    u64 last_kick_ns;
    u64 command_deadline_ns;
    atomic64_t irq_count;
    atomic64_t submit_count;
    atomic64_t watchdog_trips;
    atomic64_t invalid_ring_events;
    atomic_t opened;
    atomic_t state;
    u32 command_producer_shadow;
    u32 feedback_consumer_shadow;
    u32 joint_count;
    u64 last_command_sequence;
    u64 last_feedback_sequence;
    u32 session_epoch;
    bool staged_safe_command;
    bool reset_asserted;
    bool preserve_dma;
};

static int rtctrl_wait_dma_quiesced(struct rtctrl_mailbox_dev* mb);

struct rtctrl_file_ctx {
    struct rtctrl_mailbox_dev* mb;
    struct mutex command_lock;
    struct mutex feedback_lock;
    struct rtctrl_mb_command_frame command_staging;
    struct rtctrl_mb_feedback_frame feedback_staging;
};

static void rtctrl_kref_release(struct kref* ref) {
    struct rtctrl_mailbox_dev* mb = container_of(ref, struct rtctrl_mailbox_dev, refcount);

    kfree(mb);
}

static void rtctrl_put_device_ref(void* data) {
    struct rtctrl_mailbox_dev* mb = data;

    kref_put(&mb->refcount, rtctrl_kref_release);
}

static void rtctrl_free_dma(void* data) {
    struct rtctrl_mailbox_dev* mb = data;

    if (mb->dma_cpu && !mb->preserve_dma)
        dma_free_coherent(mb->dev, mb->dma_bytes, mb->dma_cpu, mb->dma_handle);
}

static int rtctrl_assert_reset(struct rtctrl_mailbox_dev* mb) {
    int error;

    if (mb->reset_asserted)
        return 0;
    error = reset_control_assert(mb->reset);
    if (!error)
        mb->reset_asserted = true;
    return error;
}

static int rtctrl_deassert_reset(struct rtctrl_mailbox_dev* mb) {
    int error;

    if (!mb->reset_asserted)
        return 0;
    error = reset_control_deassert(mb->reset);
    if (!error)
        mb->reset_asserted = false;
    return error;
}

static void rtctrl_hw_disable_locked(struct rtctrl_mailbox_dev* mb) {
    writel(0, mb->regs + RTCTRL_REG_CONTROL);
    readl(mb->regs + RTCTRL_REG_CONTROL);
}

/* transition_lock must be held. Hardware is disabled before timer sync. */
static int rtctrl_stop_locked(struct rtctrl_mailbox_dev* mb, int final_state) {
    unsigned long flags;
    bool initiated = false;
    int error = 0;
    int state;

    spin_lock_irqsave(&mb->state_lock, flags);
    state = atomic_read(&mb->state);
    if (state != RTCTRL_MB_STATE_DEAD && state != RTCTRL_MB_STATE_SUSPENDED) {
        rtctrl_hw_disable_locked(mb);
        atomic_set(&mb->state, RTCTRL_MB_STATE_STOPPING);
        mb->staged_safe_command = false;
        initiated = true;
    }
    spin_unlock_irqrestore(&mb->state_lock, flags);
    hrtimer_cancel(&mb->watchdog);
    if (initiated)
        error = rtctrl_wait_dma_quiesced(mb);
    spin_lock_irqsave(&mb->state_lock, flags);
    if (atomic_read(&mb->state) == RTCTRL_MB_STATE_STOPPING)
        atomic_set(&mb->state, error ? RTCTRL_MB_STATE_FAULTED : final_state);
    spin_unlock_irqrestore(&mb->state_lock, flags);
    return error;
}

static enum hrtimer_restart rtctrl_watchdog_fn(struct hrtimer* timer) {
    struct rtctrl_mailbox_dev* mb = container_of(timer, struct rtctrl_mailbox_dev, watchdog);
    u64 now = ktime_get_ns();
    u64 expires;
    unsigned long flags;

    spin_lock_irqsave(&mb->state_lock, flags);
    if (atomic_read(&mb->state) != RTCTRL_MB_STATE_ARMED) {
        spin_unlock_irqrestore(&mb->state_lock, flags);
        return HRTIMER_NORESTART;
    }
    expires = min(mb->last_kick_ns + mb->watchdog_timeout_ns, mb->command_deadline_ns);
    if (now >= expires) {
        rtctrl_hw_disable_locked(mb);
        atomic_set(&mb->state, RTCTRL_MB_STATE_FAULTED);
        mb->staged_safe_command = false;
        atomic64_inc(&mb->watchdog_trips);
        spin_unlock_irqrestore(&mb->state_lock, flags);
        return HRTIMER_NORESTART;
    }
    hrtimer_set_expires(timer, ns_to_ktime(expires));
    spin_unlock_irqrestore(&mb->state_lock, flags);
    return HRTIMER_RESTART;
}

static irqreturn_t rtctrl_irq(int irq, void* data) {
    struct rtctrl_mailbox_dev* mb = data;
    u32 pending = readl(mb->regs + RTCTRL_REG_IRQ_STATUS);
    u32 status;
    unsigned long flags;
    int state;

    if (!(pending & (RTCTRL_IRQ_RX_READY | RTCTRL_IRQ_FAULT)))
        return IRQ_NONE;
    writel(pending, mb->regs + RTCTRL_REG_IRQ_ACK);
    atomic64_inc(&mb->irq_count);
    status = readl(mb->regs + RTCTRL_REG_STATUS);
    if (!(pending & RTCTRL_IRQ_FAULT) && !(status & RTCTRL_MB_STATUS_FAULT))
        return IRQ_HANDLED;
    spin_lock_irqsave(&mb->state_lock, flags);
    state = atomic_read(&mb->state);
    if (state != RTCTRL_MB_STATE_DEAD && state != RTCTRL_MB_STATE_STOPPING &&
        state != RTCTRL_MB_STATE_SUSPENDED) {
        rtctrl_hw_disable_locked(mb);
        atomic_set(&mb->state, RTCTRL_MB_STATE_FAULTED);
        mb->staged_safe_command = false;
    }
    spin_unlock_irqrestore(&mb->state_lock, flags);
    return IRQ_HANDLED;
}

static void rtctrl_reset_session_locked(struct rtctrl_mailbox_dev* mb) {
    u32 command_consumer = readl(mb->regs + RTCTRL_REG_TX_CONSUMER);
    u32 feedback_producer = READ_ONCE(mb->layout->feedback.header.producer);

    mb->command_producer_shadow = command_consumer;
    mb->feedback_consumer_shadow = feedback_producer;
    mb->last_command_sequence = 0;
    mb->last_feedback_sequence = 0;
    WRITE_ONCE(mb->layout->command.header.producer, command_consumer);
    WRITE_ONCE(mb->layout->command.header.consumer, command_consumer);
    WRITE_ONCE(mb->layout->feedback.header.consumer, feedback_producer);
    mb->staged_safe_command = false;
    mb->command_deadline_ns = 0;
    mb->session_epoch++;
    WRITE_ONCE(mb->layout->session_epoch, mb->session_epoch);
    dma_wmb();
}

static int rtctrl_open(struct inode* inode, struct file* file) {
    struct miscdevice* misc = file->private_data;
    struct rtctrl_mailbox_dev* mb = container_of(misc, struct rtctrl_mailbox_dev, misc);
    struct rtctrl_file_ctx* ctx;
    unsigned long flags;
    int error = 0;
    int state;

    if (!kref_get_unless_zero(&mb->refcount))
        return -ENODEV;
    ctx = kzalloc(sizeof(*ctx), GFP_KERNEL);
    if (!ctx) {
        error = -ENOMEM;
        goto put_ref;
    }
    mutex_init(&ctx->command_lock);
    mutex_init(&ctx->feedback_lock);
    if (atomic_cmpxchg(&mb->opened, 0, 1) != 0) {
        error = -EBUSY;
        goto free_ctx;
    }
    mutex_lock(&mb->transition_lock);
    state = atomic_read(&mb->state);
    if (state == RTCTRL_MB_STATE_DEAD || state == RTCTRL_MB_STATE_STOPPING ||
        state == RTCTRL_MB_STATE_SUSPENDED) {
        error = -ENODEV;
        atomic_set(&mb->opened, 0);
        goto unlock;
    }
    if (state != RTCTRL_MB_STATE_DISARMED)
        (void)rtctrl_stop_locked(mb, RTCTRL_MB_STATE_DISARMED);
    spin_lock_irqsave(&mb->state_lock, flags);
    state = atomic_read(&mb->state);
    if (state != RTCTRL_MB_STATE_DISARMED) {
        spin_unlock_irqrestore(&mb->state_lock, flags);
        error = -ENODEV;
        atomic_set(&mb->opened, 0);
        goto unlock;
    }
    rtctrl_reset_session_locked(mb);
    spin_unlock_irqrestore(&mb->state_lock, flags);
    ctx->mb = mb;
    file->private_data = ctx;
    mutex_unlock(&mb->transition_lock);
    return nonseekable_open(inode, file);

unlock:
    mutex_unlock(&mb->transition_lock);
free_ctx:
    kfree(ctx);
put_ref:
    kref_put(&mb->refcount, rtctrl_kref_release);
    return error;
}

static int rtctrl_release(struct inode* inode, struct file* file) {
    struct rtctrl_file_ctx* ctx = file->private_data;
    struct rtctrl_mailbox_dev* mb = ctx->mb;
    int state;

    mutex_lock(&mb->transition_lock);
    state = atomic_read(&mb->state);
    if (state != RTCTRL_MB_STATE_DEAD && state != RTCTRL_MB_STATE_SUSPENDED)
        (void)rtctrl_stop_locked(mb, RTCTRL_MB_STATE_DISARMED);
    atomic_set(&mb->opened, 0);
    mutex_unlock(&mb->transition_lock);
    kref_put(&mb->refcount, rtctrl_kref_release);
    kfree(ctx);
    return 0;
}

static bool rtctrl_float_finite(const float* value) {
    u32 bits;

    memcpy(&bits, value, sizeof(bits));
    return (bits & 0x7f800000U) != 0x7f800000U;
}

static bool rtctrl_float_zero(const float* value) {
    u32 bits;

    memcpy(&bits, value, sizeof(bits));
    return (bits & 0x7fffffffU) == 0U;
}

static bool rtctrl_safe_damping(const float* value) {
    u32 bits;

    memcpy(&bits, value, sizeof(bits));
    return (bits & 0x80000000U) == 0U && bits <= RTCTRL_SAFE_STOP_MAX_KD_BITS;
}

static bool rtctrl_command_valid(const struct rtctrl_mb_command_frame* frame, u32 expected_joints,
                                 u64 now, bool* safe_command) {
    u32 index;
    u32 joint_count = frame->joint_count;
    u32 flags = frame->flags;

    *safe_command = flags == RTCTRL_MB_COMMAND_FLAG_SAFE_STOP;
    if (frame->sequence == 0 || joint_count != expected_joints ||
        (flags != RTCTRL_MB_COMMAND_FLAG_POSITION && !*safe_command) ||
        frame->created_time_ns > now || frame->valid_until_ns <= now)
        return false;
    for (index = 0; index < joint_count; ++index) {
        const struct rtctrl_mb_joint_command* joint = &frame->joint[index];

        if (!rtctrl_float_finite(&joint->position) || !rtctrl_float_finite(&joint->velocity) ||
            !rtctrl_float_finite(&joint->effort) || !rtctrl_float_finite(&joint->kp) ||
            !rtctrl_float_finite(&joint->kd))
            return false;
        if (*safe_command &&
            (!rtctrl_float_zero(&joint->velocity) || !rtctrl_float_zero(&joint->effort) ||
             !rtctrl_float_zero(&joint->kp) || !rtctrl_safe_damping(&joint->kd)))
            return false;
    }
    return true;
}

static bool rtctrl_feedback_valid(const struct rtctrl_mb_feedback_frame* frame,
                                  u32 expected_joints) {
    u32 index;

    if (frame->sequence == 0 || frame->joint_count != expected_joints)
        return false;
    for (index = 0; index < frame->joint_count; ++index) {
        const struct rtctrl_mb_joint_feedback* joint = &frame->joint[index];

        if (!rtctrl_float_finite(&joint->position) || !rtctrl_float_finite(&joint->velocity) ||
            !rtctrl_float_finite(&joint->effort) || !rtctrl_float_finite(&joint->temperature_c))
            return false;
    }
    return true;
}

static long rtctrl_get_info(struct rtctrl_mailbox_dev* mb, void __user* user) {
    struct rtctrl_mb_info info;

    mutex_lock(&mb->transition_lock);
    if (atomic_read(&mb->state) == RTCTRL_MB_STATE_DEAD ||
        atomic_read(&mb->state) == RTCTRL_MB_STATE_SUSPENDED ||
        atomic_read(&mb->state) == RTCTRL_MB_STATE_STOPPING) {
        mutex_unlock(&mb->transition_lock);
        return -ENODEV;
    }
    info = (struct rtctrl_mb_info){
        .abi_version = RTCTRL_MB_UAPI_ABI_VERSION,
        .capabilities = RTCTRL_MB_CAP_IRQ | RTCTRL_MB_CAP_WATCHDOG | RTCTRL_MB_CAP_KERNEL_STAGED_IO,
        .max_joints = RTCTRL_MB_MAX_JOINTS,
        .ring_depth = RTCTRL_MB_RING_DEPTH,
        .watchdog_timeout_us = (u32)(mb->watchdog_timeout_ns / NSEC_PER_USEC),
        .session_epoch = mb->session_epoch,
        .state = (u32)atomic_read(&mb->state),
        .joint_count = mb->joint_count,
    };
    mutex_unlock(&mb->transition_lock);
    return copy_to_user(user, &info, sizeof(info)) ? -EFAULT : 0;
}

static long rtctrl_arm(struct rtctrl_mailbox_dev* mb) {
    u64 now;
    u64 expires;
    u32 status;
    unsigned long flags;
    long result = 0;

    if (!capable(CAP_SYS_RAWIO))
        return -EPERM;
    mutex_lock(&mb->transition_lock);
    now = ktime_get_ns();
    spin_lock_irqsave(&mb->state_lock, flags);
    if (atomic_read(&mb->state) != RTCTRL_MB_STATE_DISARMED) {
        result = -EALREADY;
        goto unlock_state;
    }
    status = readl(mb->regs + RTCTRL_REG_STATUS);
    if ((status & (RTCTRL_MB_STATUS_READY | RTCTRL_MB_STATUS_FAULT)) != RTCTRL_MB_STATUS_READY ||
        !mb->staged_safe_command || mb->command_deadline_ns <= now) {
        result = -EIO;
        goto unlock_state;
    }
    now = ktime_get_ns();
    if (mb->command_deadline_ns <= now ||
        mb->command_deadline_ns - now < RTCTRL_MB_MIN_REMAINING_LEASE_NS) {
        result = -ETIME;
        goto unlock_state;
    }
    mb->last_kick_ns = now;
    expires = min(now + mb->watchdog_timeout_ns, mb->command_deadline_ns);
    atomic_set(&mb->state, RTCTRL_MB_STATE_ARMED);
    hrtimer_start(&mb->watchdog, ns_to_ktime(expires), HRTIMER_MODE_ABS_PINNED);
    writel(RTCTRL_CONTROL_ENABLE, mb->regs + RTCTRL_REG_CONTROL);
    readl(mb->regs + RTCTRL_REG_CONTROL);

unlock_state:
    spin_unlock_irqrestore(&mb->state_lock, flags);
    mutex_unlock(&mb->transition_lock);
    return result;
}

static long rtctrl_disarm(struct rtctrl_mailbox_dev* mb) {
    unsigned long flags;
    int state;

    spin_lock_irqsave(&mb->state_lock, flags);
    state = atomic_read(&mb->state);
    if (state == RTCTRL_MB_STATE_DEAD || state == RTCTRL_MB_STATE_SUSPENDED) {
        spin_unlock_irqrestore(&mb->state_lock, flags);
        return -ENODEV;
    }
    rtctrl_hw_disable_locked(mb);
    atomic_set(&mb->state, RTCTRL_MB_STATE_STOPPING);
    mb->staged_safe_command = false;
    spin_unlock_irqrestore(&mb->state_lock, flags);
    mutex_lock(&mb->transition_lock);
    hrtimer_cancel(&mb->watchdog);
    state = rtctrl_wait_dma_quiesced(mb);
    spin_lock_irqsave(&mb->state_lock, flags);
    if (atomic_read(&mb->state) == RTCTRL_MB_STATE_STOPPING)
        atomic_set(&mb->state, state ? RTCTRL_MB_STATE_FAULTED : RTCTRL_MB_STATE_DISARMED);
    spin_unlock_irqrestore(&mb->state_lock, flags);
    mutex_unlock(&mb->transition_lock);
    return state;
}

static long rtctrl_submit_command(struct rtctrl_mailbox_dev* mb,
                                  const struct rtctrl_mb_command_frame* frame) {
    struct rtctrl_mb_command_frame* slot;
    u64 now;
    u64 expires;
    u32 consumer;
    u32 producer;
    unsigned long flags;
    bool safe_command;
    bool cancel_timer = false;
    int state;
    long result = 0;

    mutex_lock(&mb->transition_lock);
    now = ktime_get_ns();
    state = atomic_read(&mb->state);
    if (state != RTCTRL_MB_STATE_DISARMED && state != RTCTRL_MB_STATE_ARMED) {
        result = state == RTCTRL_MB_STATE_DEAD ? -ENODEV : -EPIPE;
        goto unlock;
    }
    if (!rtctrl_command_valid(frame, mb->joint_count, now, &safe_command) ||
        frame->sequence <= mb->last_command_sequence ||
        (state == RTCTRL_MB_STATE_DISARMED && !safe_command)) {
        atomic64_inc(&mb->invalid_ring_events);
        (void)rtctrl_stop_locked(mb, RTCTRL_MB_STATE_FAULTED);
        result = -EPROTO;
        goto unlock;
    }
    spin_lock_irqsave(&mb->state_lock, flags);
    state = atomic_read(&mb->state);
    if (state != RTCTRL_MB_STATE_DISARMED && state != RTCTRL_MB_STATE_ARMED) {
        result = -EPIPE;
        goto unlock_state;
    }
    now = ktime_get_ns();
    if (frame->valid_until_ns <= now ||
        frame->valid_until_ns - now < RTCTRL_MB_MIN_REMAINING_LEASE_NS) {
        rtctrl_hw_disable_locked(mb);
        atomic_set(&mb->state, RTCTRL_MB_STATE_FAULTED);
        mb->staged_safe_command = false;
        atomic64_inc(&mb->invalid_ring_events);
        cancel_timer = true;
        result = -ETIME;
        goto unlock_state;
    }
    consumer = readl(mb->regs + RTCTRL_REG_TX_CONSUMER);
    producer = mb->command_producer_shadow + 1U;
    if ((u32)(producer - consumer) > RTCTRL_MB_RING_DEPTH) {
        result = -EAGAIN;
        goto unlock_state;
    }
    slot = &mb->layout->command.slot[(producer - 1U) & RTCTRL_MB_RING_MASK];
    *slot = *frame;
    dma_wmb();
    WRITE_ONCE(mb->layout->command.header.producer, producer);
    mb->command_producer_shadow = producer;
    mb->last_command_sequence = frame->sequence;
    mb->command_deadline_ns = frame->valid_until_ns;
    mb->staged_safe_command = safe_command;
    if (state == RTCTRL_MB_STATE_ARMED) {
        mb->last_kick_ns = now;
        expires = min(now + mb->watchdog_timeout_ns, mb->command_deadline_ns);
        hrtimer_start(&mb->watchdog, ns_to_ktime(expires), HRTIMER_MODE_ABS_PINNED);
    }
    dma_wmb();
    writel(producer, mb->regs + RTCTRL_REG_TX_DOORBELL);
    atomic64_inc(&mb->submit_count);

unlock_state:
    spin_unlock_irqrestore(&mb->state_lock, flags);
    if (cancel_timer)
        hrtimer_cancel(&mb->watchdog);
unlock:
    mutex_unlock(&mb->transition_lock);
    return result;
}

static long rtctrl_read_feedback(struct rtctrl_mailbox_dev* mb,
                                 struct rtctrl_mb_feedback_frame* frame) {
    u32 producer;
    u32 pending;
    long result = 0;

    mutex_lock(&mb->transition_lock);
    if (atomic_read(&mb->state) == RTCTRL_MB_STATE_DEAD ||
        atomic_read(&mb->state) == RTCTRL_MB_STATE_SUSPENDED ||
        atomic_read(&mb->state) == RTCTRL_MB_STATE_STOPPING) {
        result = -ENODEV;
        goto unlock;
    }
    producer = READ_ONCE(mb->layout->feedback.header.producer);
    pending = producer - mb->feedback_consumer_shadow;
    if (pending == 0U) {
        result = -EAGAIN;
        goto unlock;
    }
    if (pending > RTCTRL_MB_RING_DEPTH) {
        atomic64_inc(&mb->invalid_ring_events);
        (void)rtctrl_stop_locked(mb, RTCTRL_MB_STATE_FAULTED);
        result = -EPROTO;
        goto unlock;
    }
    dma_rmb();
    *frame = mb->layout->feedback.slot[(producer - 1U) & RTCTRL_MB_RING_MASK];
    if (!rtctrl_feedback_valid(frame, mb->joint_count) ||
        frame->sequence <= mb->last_feedback_sequence) {
        atomic64_inc(&mb->invalid_ring_events);
        (void)rtctrl_stop_locked(mb, RTCTRL_MB_STATE_FAULTED);
        result = -EPROTO;
        goto unlock;
    }
    mb->feedback_consumer_shadow = producer;
    mb->last_feedback_sequence = frame->sequence;
    WRITE_ONCE(mb->layout->feedback.header.consumer, producer);
    dma_wmb();
    mutex_unlock(&mb->transition_lock);
    return 0;

unlock:
    mutex_unlock(&mb->transition_lock);
    return result;
}

static long rtctrl_get_stats(struct rtctrl_mailbox_dev* mb, void __user* user) {
    struct rtctrl_mb_stats stats;

    mutex_lock(&mb->transition_lock);
    if (atomic_read(&mb->state) == RTCTRL_MB_STATE_DEAD ||
        atomic_read(&mb->state) == RTCTRL_MB_STATE_SUSPENDED ||
        atomic_read(&mb->state) == RTCTRL_MB_STATE_STOPPING) {
        mutex_unlock(&mb->transition_lock);
        return -ENODEV;
    }
    stats = (struct rtctrl_mb_stats){
        .irq_count = atomic64_read(&mb->irq_count),
        .submit_count = atomic64_read(&mb->submit_count),
        .watchdog_trips = atomic64_read(&mb->watchdog_trips),
        .invalid_ring_events = atomic64_read(&mb->invalid_ring_events),
        .armed = atomic_read(&mb->state) == RTCTRL_MB_STATE_ARMED,
        .status = readl(mb->regs + RTCTRL_REG_STATUS),
        .command_producer = mb->command_producer_shadow,
        .command_consumer = readl(mb->regs + RTCTRL_REG_TX_CONSUMER),
        .feedback_producer = READ_ONCE(mb->layout->feedback.header.producer),
        .feedback_consumer = mb->feedback_consumer_shadow,
        .state = (u32)atomic_read(&mb->state),
        .session_epoch = mb->session_epoch,
    };
    mutex_unlock(&mb->transition_lock);
    return copy_to_user(user, &stats, sizeof(stats)) ? -EFAULT : 0;
}

static long rtctrl_ioctl(struct file* file, unsigned int command, unsigned long argument) {
    struct rtctrl_file_ctx* ctx = file->private_data;
    struct rtctrl_mailbox_dev* mb = ctx->mb;
    void __user* user = (void __user*)argument;
    long result;

    switch (command) {
        case RTCTRL_MB_IOC_GET_INFO:
            return rtctrl_get_info(mb, user);
        case RTCTRL_MB_IOC_ARM:
            return rtctrl_arm(mb);
        case RTCTRL_MB_IOC_DISARM:
            return rtctrl_disarm(mb);
        case RTCTRL_MB_IOC_SUBMIT_COMMAND:
            mutex_lock(&ctx->command_lock);
            if (copy_from_user(&ctx->command_staging, user, sizeof(ctx->command_staging))) {
                mutex_unlock(&ctx->command_lock);
                return -EFAULT;
            }
            result = rtctrl_submit_command(mb, &ctx->command_staging);
            mutex_unlock(&ctx->command_lock);
            return result;
        case RTCTRL_MB_IOC_READ_FEEDBACK:
            mutex_lock(&ctx->feedback_lock);
            result = rtctrl_read_feedback(mb, &ctx->feedback_staging);
            if (result) {
                mutex_unlock(&ctx->feedback_lock);
                return result;
            }
            result = copy_to_user(user, &ctx->feedback_staging, sizeof(ctx->feedback_staging))
                         ? -EFAULT
                         : 0;
            mutex_unlock(&ctx->feedback_lock);
            return result;
        case RTCTRL_MB_IOC_GET_STATS:
            return rtctrl_get_stats(mb, user);
        default:
            return -ENOTTY;
    }
}

static const struct file_operations rtctrl_fops = {
    .owner = THIS_MODULE,
    .open = rtctrl_open,
    .release = rtctrl_release,
    .unlocked_ioctl = rtctrl_ioctl,
    .compat_ioctl = compat_ptr_ioctl,
    .llseek = no_llseek,
};

static void rtctrl_init_layout(struct rtctrl_mailbox_dev* mb) {
    memset(mb->layout, 0, mb->dma_bytes);
    mb->layout->magic = RTCTRL_MB_LAYOUT_MAGIC;
    mb->layout->abi_version = RTCTRL_MB_HW_ABI_VERSION;
    mb->layout->layout_bytes = sizeof(*mb->layout);
    mb->layout->max_joints = RTCTRL_MB_MAX_JOINTS;
    mb->layout->joint_count = mb->joint_count;
    mb->layout->ring_depth = RTCTRL_MB_RING_DEPTH;
    dma_wmb();
}

/* transition_lock must be held; CONTROL is left disabled. */
static int rtctrl_wait_dma_quiesced(struct rtctrl_mailbox_dev* mb) {
    u32 status;

    return readl_poll_timeout(mb->regs + RTCTRL_REG_STATUS, status,
                              status & RTCTRL_MB_STATUS_DMA_QUIESCED, 1,
                              RTCTRL_DMA_QUIESCE_TIMEOUT_US);
}

static int rtctrl_reset_endpoint(struct rtctrl_mailbox_dev* mb) {
    u32 control;

    writel(RTCTRL_CONTROL_RESET, mb->regs + RTCTRL_REG_CONTROL);
    return readl_poll_timeout(mb->regs + RTCTRL_REG_CONTROL, control,
                              !(control & RTCTRL_CONTROL_RESET), 1,
                              RTCTRL_ENDPOINT_RESET_TIMEOUT_US);
}

static int rtctrl_program_hardware_locked(struct rtctrl_mailbox_dev* mb) {
    int error;

    rtctrl_hw_disable_locked(mb);
    error = rtctrl_wait_dma_quiesced(mb);
    if (error)
        return error;
    error = rtctrl_reset_endpoint(mb);
    if (error)
        return error;
    mb->session_epoch++;
    rtctrl_init_layout(mb);
    mb->layout->session_epoch = mb->session_epoch;
    mb->command_producer_shadow = 0;
    mb->feedback_consumer_shadow = 0;
    mb->last_command_sequence = 0;
    mb->last_feedback_sequence = 0;
    mb->command_deadline_ns = 0;
    mb->staged_safe_command = false;
    dma_wmb();
    writel(lower_32_bits(mb->dma_handle), mb->regs + RTCTRL_REG_DMA_ADDR_LO);
    writel(upper_32_bits(mb->dma_handle), mb->regs + RTCTRL_REG_DMA_ADDR_HI);
    writel((u32)mb->dma_bytes, mb->regs + RTCTRL_REG_DMA_BYTES);
    writel(RTCTRL_MB_HW_ABI_VERSION, mb->regs + RTCTRL_REG_ABI_VERSION);
    writel(~0U, mb->regs + RTCTRL_REG_IRQ_ACK);
    wmb();
    return 0;
}

static int rtctrl_probe(struct platform_device* pdev) {
    struct device* dev = &pdev->dev;
    struct rtctrl_mailbox_dev* mb;
    u32 watchdog_us = RTCTRL_DEFAULT_WATCHDOG_US;
    int error;

    BUILD_BUG_ON(!is_power_of_2(RTCTRL_MB_RING_DEPTH));
    BUILD_BUG_ON(sizeof(float) != sizeof(u32));
    BUILD_BUG_ON(sizeof(struct rtctrl_mb_layout) > U32_MAX);
    BUILD_BUG_ON(offsetof(struct rtctrl_mb_layout, command) % 8);
    BUILD_BUG_ON(offsetof(struct rtctrl_mb_layout, feedback) % 8);
    mb = kzalloc(sizeof(*mb), GFP_KERNEL);
    if (!mb)
        return -ENOMEM;
    kref_init(&mb->refcount);
    error = devm_add_action_or_reset(dev, rtctrl_put_device_ref, mb);
    if (error)
        return error;
    mb->dev = dev;
    mutex_init(&mb->transition_lock);
    spin_lock_init(&mb->state_lock);
    atomic_set(&mb->state, RTCTRL_MB_STATE_DISARMED);
    mb->regs = devm_platform_ioremap_resource(pdev, 0);
    if (IS_ERR(mb->regs))
        return PTR_ERR(mb->regs);
    mb->reset = devm_reset_control_get_exclusive(dev, "mailbox");
    if (IS_ERR(mb->reset))
        return dev_err_probe(dev, PTR_ERR(mb->reset), "mailbox reset is required\n");
    error = rtctrl_assert_reset(mb);
    if (error)
        return dev_err_probe(dev, error, "failed to assert mailbox reset\n");
    error = rtctrl_deassert_reset(mb);
    if (error)
        return dev_err_probe(dev, error, "failed to deassert mailbox reset\n");
    /* Fail-safe before the IRQ is requested or any DMA address is exposed. */
    writel(0, mb->regs + RTCTRL_REG_CONTROL);
    readl(mb->regs + RTCTRL_REG_CONTROL);
    mb->irq = platform_get_irq(pdev, 0);
    if (mb->irq < 0)
        return mb->irq;
    error = dma_set_mask_and_coherent(dev, DMA_BIT_MASK(64));
    if (error)
        return dev_err_probe(dev, error, "64-bit coherent DMA unavailable\n");
    mb->dma_bytes = PAGE_ALIGN(sizeof(struct rtctrl_mb_layout));
    mb->dma_cpu = dma_alloc_coherent(dev, mb->dma_bytes, &mb->dma_handle, GFP_KERNEL);
    if (!mb->dma_cpu)
        return -ENOMEM;
    error = devm_add_action_or_reset(dev, rtctrl_free_dma, mb);
    if (error)
        return error;
    mb->layout = mb->dma_cpu;
    if (device_property_read_u32(dev, "sx,joint-count", &mb->joint_count) || mb->joint_count == 0 ||
        mb->joint_count > RTCTRL_MB_MAX_JOINTS)
        return dev_err_probe(dev, -EINVAL, "missing or invalid sx,joint-count\n");
    rtctrl_init_layout(mb);
    device_property_read_u32(dev, "sx,watchdog-timeout-us", &watchdog_us);
    if (watchdog_us < RTCTRL_MIN_WATCHDOG_US || watchdog_us > RTCTRL_MAX_WATCHDOG_US)
        return dev_err_probe(dev, -EINVAL, "invalid watchdog timeout\n");
    mb->watchdog_timeout_ns = (u64)watchdog_us * NSEC_PER_USEC;
    hrtimer_init(&mb->watchdog, CLOCK_MONOTONIC, HRTIMER_MODE_ABS_PINNED);
    mb->watchdog.function = rtctrl_watchdog_fn;
    error = devm_request_irq(dev, mb->irq, rtctrl_irq, 0, dev_name(dev), mb);
    if (error)
        return dev_err_probe(dev, error, "failed to request mailbox IRQ\n");
    mutex_lock(&mb->transition_lock);
    error = rtctrl_program_hardware_locked(mb);
    if (error) {
        mutex_unlock(&mb->transition_lock);
        return dev_err_probe(dev, error, "endpoint DMA did not quiesce\n");
    }
    atomic_set(&mb->state, RTCTRL_MB_STATE_DISARMED);
    mutex_unlock(&mb->transition_lock);
    mb->misc.minor = MISC_DYNAMIC_MINOR;
    mb->misc.name = devm_kasprintf(dev, GFP_KERNEL, "rtctrl-mailbox-%s", dev_name(dev));
    if (!mb->misc.name)
        return -ENOMEM;
    mb->misc.fops = &rtctrl_fops;
    mb->misc.parent = dev;
    mb->misc.mode = 0600;
    error = misc_register(&mb->misc);
    if (error)
        return dev_err_probe(dev, error, "failed to register misc device\n");
    platform_set_drvdata(pdev, mb);
    dev_info(dev, "staged DMA mailbox ready: %zu bytes, watchdog %u us\n", mb->dma_bytes,
             watchdog_us);
    return 0;
}

static void rtctrl_remove_common(struct platform_device* pdev) {
    struct rtctrl_mailbox_dev* mb = platform_get_drvdata(pdev);
    unsigned long flags;
    bool was_in_reset = READ_ONCE(mb->reset_asserted);

    spin_lock_irqsave(&mb->state_lock, flags);
    if (!was_in_reset)
        rtctrl_hw_disable_locked(mb);
    atomic_set(&mb->state, RTCTRL_MB_STATE_DEAD);
    mb->staged_safe_command = false;
    spin_unlock_irqrestore(&mb->state_lock, flags);
    mutex_lock(&mb->transition_lock);
    hrtimer_cancel(&mb->watchdog);
    if (!was_in_reset && rtctrl_wait_dma_quiesced(mb) && rtctrl_assert_reset(mb)) {
        mb->preserve_dma = true;
        dev_crit(mb->dev, "DMA active and reset failed; preserving coherent memory\n");
    } else if (rtctrl_assert_reset(mb)) {
        dev_warn(mb->dev, "reset assert failed after DMA quiesced\n");
    }
    spin_lock_irqsave(&mb->state_lock, flags);
    atomic_set(&mb->state, RTCTRL_MB_STATE_DEAD);
    spin_unlock_irqrestore(&mb->state_lock, flags);
    mutex_unlock(&mb->transition_lock);
    misc_deregister(&mb->misc);
}

#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 6, 0)
static int rtctrl_remove(struct platform_device* pdev) {
    rtctrl_remove_common(pdev);
    return 0;
}
#else
static void rtctrl_remove(struct platform_device* pdev) {
    rtctrl_remove_common(pdev);
}
#endif

static void rtctrl_shutdown(struct platform_device* pdev) {
    struct rtctrl_mailbox_dev* mb = platform_get_drvdata(pdev);
    unsigned long flags;
    bool was_in_reset = READ_ONCE(mb->reset_asserted);

    spin_lock_irqsave(&mb->state_lock, flags);
    if (!was_in_reset)
        rtctrl_hw_disable_locked(mb);
    atomic_set(&mb->state, RTCTRL_MB_STATE_DEAD);
    mb->staged_safe_command = false;
    spin_unlock_irqrestore(&mb->state_lock, flags);
    mutex_lock(&mb->transition_lock);
    hrtimer_cancel(&mb->watchdog);
    if (!was_in_reset && rtctrl_wait_dma_quiesced(mb) && rtctrl_assert_reset(mb)) {
        mb->preserve_dma = true;
        dev_crit(mb->dev, "DMA active and reset failed during shutdown\n");
    } else if (rtctrl_assert_reset(mb)) {
        dev_warn(mb->dev, "reset assert failed after shutdown quiesce\n");
    }
    spin_lock_irqsave(&mb->state_lock, flags);
    atomic_set(&mb->state, RTCTRL_MB_STATE_DEAD);
    spin_unlock_irqrestore(&mb->state_lock, flags);
    mutex_unlock(&mb->transition_lock);
}

static int rtctrl_suspend(struct platform_device* pdev, pm_message_t state) {
    struct rtctrl_mailbox_dev* mb = platform_get_drvdata(pdev);
    unsigned long flags;

    spin_lock_irqsave(&mb->state_lock, flags);
    rtctrl_hw_disable_locked(mb);
    atomic_set(&mb->state, RTCTRL_MB_STATE_SUSPENDED);
    mb->staged_safe_command = false;
    spin_unlock_irqrestore(&mb->state_lock, flags);
    mutex_lock(&mb->transition_lock);
    hrtimer_cancel(&mb->watchdog);
    if (rtctrl_wait_dma_quiesced(mb) && rtctrl_assert_reset(mb)) {
        spin_lock_irqsave(&mb->state_lock, flags);
        atomic_set(&mb->state, RTCTRL_MB_STATE_FAULTED);
        spin_unlock_irqrestore(&mb->state_lock, flags);
        mutex_unlock(&mb->transition_lock);
        return -ETIMEDOUT;
    }
    if (rtctrl_assert_reset(mb)) {
        spin_lock_irqsave(&mb->state_lock, flags);
        atomic_set(&mb->state, RTCTRL_MB_STATE_FAULTED);
        spin_unlock_irqrestore(&mb->state_lock, flags);
        mutex_unlock(&mb->transition_lock);
        return -EIO;
    }
    spin_lock_irqsave(&mb->state_lock, flags);
    atomic_set(&mb->state, RTCTRL_MB_STATE_SUSPENDED);
    spin_unlock_irqrestore(&mb->state_lock, flags);
    mutex_unlock(&mb->transition_lock);
    return 0;
}

static int rtctrl_resume(struct platform_device* pdev) {
    struct rtctrl_mailbox_dev* mb = platform_get_drvdata(pdev);
    unsigned long flags;
    int error;

    mutex_lock(&mb->transition_lock);
    spin_lock_irqsave(&mb->state_lock, flags);
    if (atomic_read(&mb->state) != RTCTRL_MB_STATE_SUSPENDED) {
        spin_unlock_irqrestore(&mb->state_lock, flags);
        mutex_unlock(&mb->transition_lock);
        return -EINVAL;
    }
    spin_unlock_irqrestore(&mb->state_lock, flags);
    error = rtctrl_deassert_reset(mb);
    if (error) {
        mutex_unlock(&mb->transition_lock);
        return error;
    }
    error = rtctrl_program_hardware_locked(mb);
    if (error) {
        (void)rtctrl_assert_reset(mb);
        mutex_unlock(&mb->transition_lock);
        return error;
    }
    spin_lock_irqsave(&mb->state_lock, flags);
    if (atomic_read(&mb->state) == RTCTRL_MB_STATE_SUSPENDED) {
        atomic_set(&mb->state, RTCTRL_MB_STATE_DISARMED);
        error = 0;
    } else {
        error = -ENODEV;
    }
    spin_unlock_irqrestore(&mb->state_lock, flags);
    mutex_unlock(&mb->transition_lock);
    return error;
}

static const struct of_device_id rtctrl_of_match[] = {{.compatible = "sx,rtctrl-mailbox-v2"}, {}};
MODULE_DEVICE_TABLE(of, rtctrl_of_match);

static struct platform_driver rtctrl_driver = {
    .probe = rtctrl_probe,
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 6, 0)
    .remove = rtctrl_remove,
#elif LINUX_VERSION_CODE < KERNEL_VERSION(6, 12, 0)
    .remove_new = rtctrl_remove,
#else
    .remove = rtctrl_remove,
#endif
    .shutdown = rtctrl_shutdown,
    .suspend = rtctrl_suspend,
    .resume = rtctrl_resume,
    .driver =
        {
            .name = "rtctrl-mailbox",
            .of_match_table = rtctrl_of_match,
            .suppress_bind_attrs = true,
        },
};
module_platform_driver(rtctrl_driver);

MODULE_AUTHOR("Sun Xun <sx2728977548@163.com>");
MODULE_DESCRIPTION("Robot kernel-staged coherent-DMA mailbox with watchdog");
MODULE_LICENSE("GPL");
