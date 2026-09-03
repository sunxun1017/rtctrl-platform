/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef _UAPI_LINUX_RTCTRL_MAILBOX_H
#define _UAPI_LINUX_RTCTRL_MAILBOX_H

#include <linux/ioctl.h>
#include <linux/types.h>

#define RTCTRL_MB_UAPI_ABI_VERSION 2U
#define RTCTRL_MB_HW_ABI_VERSION 2U
#define RTCTRL_MB_MIN_REMAINING_LEASE_NS 1000000ULL
#define RTCTRL_MB_LAYOUT_MAGIC 0x4d425452U /* "RTBM" on little-endian hosts */
#define RTCTRL_MB_MAX_JOINTS 64U
#define RTCTRL_MB_RING_DEPTH 8U
#define RTCTRL_MB_RING_MASK (RTCTRL_MB_RING_DEPTH - 1U)

#define RTCTRL_MB_CAP_IRQ (1U << 0)
#define RTCTRL_MB_CAP_WATCHDOG (1U << 1)
#define RTCTRL_MB_CAP_KERNEL_STAGED_IO (1U << 2)

#define RTCTRL_MB_STATUS_READY (1U << 0)
#define RTCTRL_MB_STATUS_FAULT (1U << 1)
#define RTCTRL_MB_STATUS_DMA_QUIESCED (1U << 2)

#define RTCTRL_MB_STATE_DISARMED 0U
#define RTCTRL_MB_STATE_ARMED 1U
#define RTCTRL_MB_STATE_FAULTED 2U
#define RTCTRL_MB_STATE_DEAD 3U
#define RTCTRL_MB_STATE_STOPPING 4U
#define RTCTRL_MB_STATE_SUSPENDED 5U

#define RTCTRL_MB_COMMAND_FLAG_POSITION (1U << 0)
#define RTCTRL_MB_COMMAND_FLAG_SAFE_STOP (1U << 1)

struct rtctrl_mb_joint_command {
    float position;
    float velocity;
    float effort;
    float kp;
    float kd;
};

struct rtctrl_mb_joint_feedback {
    float position;
    float velocity;
    float effort;
    float temperature_c;
    __u32 error_flags;
};

struct rtctrl_mb_command_frame {
    __aligned_u64 sequence;
    __aligned_u64 created_time_ns;
    __aligned_u64 valid_until_ns;
    __u32 joint_count;
    __u32 flags;
    struct rtctrl_mb_joint_command joint[RTCTRL_MB_MAX_JOINTS];
};

struct rtctrl_mb_feedback_frame {
    __aligned_u64 sequence;
    __aligned_u64 sample_time_ns;
    __aligned_u64 device_cycle;
    __u32 joint_count;
    __u32 fault_bits;
    struct rtctrl_mb_joint_feedback joint[RTCTRL_MB_MAX_JOINTS];
};

struct rtctrl_mb_ring_header {
    __u32 producer;
    __u32 consumer;
    __u32 dropped;
    __u32 reserved;
};

struct rtctrl_mb_command_ring {
    struct rtctrl_mb_ring_header header;
    struct rtctrl_mb_command_frame slot[RTCTRL_MB_RING_DEPTH];
};

struct rtctrl_mb_feedback_ring {
    struct rtctrl_mb_ring_header header;
    struct rtctrl_mb_feedback_frame slot[RTCTRL_MB_RING_DEPTH];
};

struct rtctrl_mb_layout {
    __u32 magic;
    __u32 abi_version;
    __u32 layout_bytes;
    __u32 max_joints;
    __u32 joint_count;
    __u32 ring_depth;
    __u32 session_epoch;
    __u32 reserved[9];
    struct rtctrl_mb_command_ring command;
    struct rtctrl_mb_feedback_ring feedback;
};

struct rtctrl_mb_info {
    __u32 abi_version; /* userspace ioctl ABI, not the endpoint hardware ABI */
    __u32 capabilities;
    __u32 max_joints;
    __u32 ring_depth;
    __u32 watchdog_timeout_us;
    __u32 session_epoch;
    __u32 state;
    __u32 joint_count;
};

struct rtctrl_mb_stats {
    __aligned_u64 irq_count;
    __aligned_u64 submit_count;
    __aligned_u64 watchdog_trips;
    __aligned_u64 invalid_ring_events;
    __u32 armed;
    __u32 status;
    __u32 command_producer;
    __u32 command_consumer;
    __u32 feedback_producer;
    __u32 feedback_consumer;
    __u32 state;
    __u32 session_epoch;
};

#define RTCTRL_MB_IOC_MAGIC 0xb7
#define RTCTRL_MB_IOC_GET_INFO _IOR(RTCTRL_MB_IOC_MAGIC, 0x00, struct rtctrl_mb_info)
#define RTCTRL_MB_IOC_ARM _IO(RTCTRL_MB_IOC_MAGIC, 0x01)
#define RTCTRL_MB_IOC_DISARM _IO(RTCTRL_MB_IOC_MAGIC, 0x02)
#define RTCTRL_MB_IOC_SUBMIT_COMMAND _IOW(RTCTRL_MB_IOC_MAGIC, 0x03, struct rtctrl_mb_command_frame)
#define RTCTRL_MB_IOC_READ_FEEDBACK _IOR(RTCTRL_MB_IOC_MAGIC, 0x04, struct rtctrl_mb_feedback_frame)
#define RTCTRL_MB_IOC_GET_STATS _IOR(RTCTRL_MB_IOC_MAGIC, 0x05, struct rtctrl_mb_stats)

#endif /* _UAPI_LINUX_RTCTRL_MAILBOX_H */
